"""TrackZone 区域过滤 + 进出双向计数 + 越界报警。

实现思路：
- 用 Ultralytics TrackZone 语义维护监控多边形（凸包）
- 全帧 ByteTrack 保持跨边界 ID 连续
- 以检测框∩区域面积 / 框面积 ≥ 30% 判定「有效进入」（擦边不计）
- 稳态帧 + 确认帧 + 空间去重，抑制 ID 切换误计
- 按类别分组统计人 / 车
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# COCO 常见类别
PERSON_CLASS_IDS = {0}
VEHICLE_CLASS_IDS = {1, 2, 3, 5, 7}  # bicycle, car, motorcycle, bus, truck

PERSON_NAMES = {"person", "people", "human", "pedestrian", "人", "行人"}
VEHICLE_NAMES = {
    "bicycle", "car", "motorcycle", "bus", "truck", "vehicle",
    "自行车", "汽车", "摩托车", "公交车", "卡车", "车辆",
}

CLASS_PRESETS = {
    "all": None,
    "person": sorted(PERSON_CLASS_IDS),
    "vehicle": sorted(VEHICLE_CLASS_IDS),
    "person_vehicle": sorted(PERSON_CLASS_IDS | VEHICLE_CLASS_IDS),
}


def resolve_classes(preset: str | None = None, classes: list[int] | None = None) -> list[int] | None:
    """解析类别过滤：显式 classes 优先，否则按预设。"""
    if classes is not None:
        try:
            return [int(c) for c in classes]
        except (TypeError, ValueError):
            return None
    if not preset:
        return None
    key = str(preset).strip().lower().replace("-", "_").replace("+", "_")
    aliases = {
        "person": "person",
        "people": "person",
        "human": "person",
        "人": "person",
        "vehicle": "vehicle",
        "car": "vehicle",
        "车": "vehicle",
        "person_vehicle": "person_vehicle",
        "personvehicle": "person_vehicle",
        "both": "person_vehicle",
        "人车": "person_vehicle",
        "all": "all",
        "全部": "all",
    }
    mapped = aliases.get(key, key)
    return CLASS_PRESETS.get(mapped)


def class_group(class_id: int | None, class_name: str | None) -> str:
    """将检测归入 person / vehicle / other。"""
    name = (class_name or "").strip().lower()
    if class_id is not None:
        try:
            cid = int(class_id)
        except (TypeError, ValueError):
            cid = None
        else:
            if cid in PERSON_CLASS_IDS:
                return "person"
            if cid in VEHICLE_CLASS_IDS:
                return "vehicle"
    if name in PERSON_NAMES:
        return "person"
    if name in VEHICLE_NAMES:
        return "vehicle"
    return "other"


def parse_region(raw) -> list[list[float]] | None:
    """解析归一化多边形 [[x,y], ...]，至少 3 个顶点，坐标裁剪到 [0,1]。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    pts = []
    for p in raw:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return None
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError):
            return None
        pts.append([max(0.0, min(1.0, x)), max(0.0, min(1.0, y))])
    return pts if len(pts) >= 3 else None


def region_to_pixels(region_norm: list[list[float]], width: int, height: int) -> np.ndarray:
    """归一化区域 -> 像素坐标多边形（与 TrackZone 一致做凸包）。"""
    pts = np.array(
        [[int(round(p[0] * width)), int(round(p[1] * height))] for p in region_norm],
        dtype=np.int32,
    )
    if len(pts) < 3:
        return pts
    hull = cv2.convexHull(pts)
    return hull.reshape(-1, 2) if hull is not None else pts


def point_in_polygon(pt: tuple[float, float], polygon: np.ndarray) -> bool:
    """判断点是否在多边形内（含边界）。"""
    if polygon is None or len(polygon) < 3:
        return False
    return cv2.pointPolygonTest(polygon.astype(np.float32), (float(pt[0]), float(pt[1])), False) >= 0


# 默认：检测框与区域重叠面积占比 ≥ 该阈值才算「有效进入」；低于则视为擦边/未进入
DEFAULT_AREA_RATIO = 0.30


def bbox_zone_overlap_ratio(bbox: list | tuple | None, polygon: np.ndarray) -> float:
    """计算检测框与多边形的面积重叠比 = 交集面积 / 检测框面积。

    返回 [0, 1]；无有效框或区域时返回 0。
    """
    if bbox is None or len(bbox) < 4 or polygon is None or len(polygon) < 3:
        return 0.0
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    except (TypeError, ValueError):
        return 0.0
    if x2 <= x1 or y2 <= y1:
        return 0.0
    box_area = (x2 - x1) * (y2 - y1)
    if box_area <= 1e-6:
        return 0.0

    # 裁剪到框周围，缩小运算
    bx1, by1 = int(np.floor(x1)), int(np.floor(y1))
    bx2, by2 = int(np.ceil(x2)), int(np.ceil(y2))
    bw, bh = max(1, bx2 - bx1), max(1, by2 - by1)

    # 框掩膜（局部坐标）
    box_mask = np.ones((bh, bw), dtype=np.uint8) * 255
    # 多边形平移到局部
    poly_local = polygon.astype(np.float32).copy()
    poly_local[:, 0] -= bx1
    poly_local[:, 1] -= by1
    zone_mask = np.zeros((bh, bw), dtype=np.uint8)
    cv2.fillPoly(zone_mask, [poly_local.astype(np.int32)], 255)
    inter = cv2.bitwise_and(box_mask, zone_mask)
    inter_area = float(cv2.countNonZero(inter))
    # countNonZero 按像素；与浮点框面积对齐用像素框面积
    pixel_box_area = float(bw * bh)
    if pixel_box_area <= 0:
        return 0.0
    return max(0.0, min(1.0, inter_area / pixel_box_area))


def is_effectively_inside(
    bbox: list | tuple | None,
    polygon: np.ndarray,
    *,
    center: tuple[float, float] | None = None,
    area_ratio: float = DEFAULT_AREA_RATIO,
    class_id: int | None = None,
    class_name: str | None = None,
) -> bool:
    """是否「有效进入」区域：重叠面积占比 ≥ area_ratio。

    无 bbox 时回退到锚点是否在多边形内（兼容旧路径）。
    """
    if bbox is not None and len(bbox) >= 4:
        return bbox_zone_overlap_ratio(bbox, polygon) >= float(area_ratio)
    if center is not None:
        pt = anchor_point(center, bbox, class_id=class_id, class_name=class_name)
        return point_in_polygon(pt, polygon)
    return False


def zone_cross_direction(
    prev: tuple[float, float],
    curr: tuple[float, float],
    polygon: np.ndarray,
) -> int:
    """根据中心点内外状态判断穿越方向（兼容告警引擎旧逻辑）。

    返回：+1 进入（外→内），-1 离开（内→外），0 未穿越。
    """
    prev_in = point_in_polygon(prev, polygon)
    curr_in = point_in_polygon(curr, polygon)
    if (not prev_in) and curr_in:
        return 1
    if prev_in and (not curr_in):
        return -1
    return 0


def zone_cross_by_area(
    prev_inside: bool,
    curr_inside: bool,
) -> int:
    """基于有效进入状态的方向：+1 进 / -1 出 / 0 无。"""
    if (not prev_inside) and curr_inside:
        return 1
    if prev_inside and (not curr_inside):
        return -1
    return 0


def anchor_point(
    center: tuple[float, float],
    bbox: list | None = None,
    *,
    class_id: int | None = None,
    class_name: str | None = None,
) -> tuple[float, float]:
    """车辆用地平面更稳的底边中心；人/其他用框中心。"""
    if bbox is not None and len(bbox) >= 4 and class_group(class_id, class_name) == "vehicle":
        try:
            x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
            return ((x1 + x2) / 2.0, y2)
        except (TypeError, ValueError):
            pass
    return (float(center[0]), float(center[1]))


class ZoneFlowCounter:
    """区域进出计数（面积阈值 + 抗 ID 切换 / 边界抖动）。

    判定规则：
    - 检测框与多边形重叠面积 / 框面积 ≥ area_ratio（默认 30%）才算有效进入
    - 擦边（<30%）不计进出
    - 另有：稳态帧、确认帧、空间去重、区内丢检补 EXIT
    """

    def __init__(
        self,
        *,
        stable_frames: int = 2,
        confirm_frames: int = 2,
        dedupe_dist: float = 90.0,
        dedupe_frames: int = 60,
        miss_exit_frames: int = 20,
        area_ratio: float = DEFAULT_AREA_RATIO,
    ):
        self.stable_frames = max(1, int(stable_frames))
        self.confirm_frames = max(1, int(confirm_frames))
        self.dedupe_dist = float(dedupe_dist)
        self.dedupe_frames = max(1, int(dedupe_frames))
        self.miss_exit_frames = max(1, int(miss_exit_frames))
        self.area_ratio = float(area_ratio)

        self._frame = 0
        # tid -> 运行时状态
        self._states: dict[int, dict[str, Any]] = {}
        self.counted: set[tuple[int, int]] = set()  # (tid, direction) 兼容旧字段
        self._recent_events: list[dict] = []  # 空间去重用

        self.enter_count = 0
        self.exit_count = 0
        self.by_group = {
            "person": {"in": 0, "out": 0},
            "vehicle": {"in": 0, "out": 0},
            "other": {"in": 0, "out": 0},
        }
        self.alarms: list[dict] = []
        self._alarm_log: list[str] = []
        # 兼容旧代码读取 id_history
        self.id_history: dict[int, tuple[float, float]] = {}

    def reset(self):
        self.__init__(
            stable_frames=self.stable_frames,
            confirm_frames=self.confirm_frames,
            dedupe_dist=self.dedupe_dist,
            dedupe_frames=self.dedupe_frames,
            miss_exit_frames=self.miss_exit_frames,
            area_ratio=self.area_ratio,
        )

    def _is_duplicate(self, direction: int, group: str, pt: tuple[float, float]) -> bool:
        for ev in self._recent_events:
            if ev["direction"] != direction or ev["group"] != group:
                continue
            if self._frame - ev["frame"] > self.dedupe_frames:
                continue
            dx = pt[0] - ev["x"]
            dy = pt[1] - ev["y"]
            if (dx * dx + dy * dy) ** 0.5 <= self.dedupe_dist:
                return True
        return False

    def _commit(
        self,
        tid: int,
        direction: int,
        pt: tuple[float, float],
        *,
        class_id: int | None,
        class_name: str | None,
        bbox: list | None,
        overlap: float | None = None,
    ) -> dict | None:
        mark = (tid, direction)
        group = class_group(class_id, class_name)

        # 同 ID 同方向尚未经历反向时不重复计
        if mark in self.counted:
            return None

        if self._is_duplicate(direction, group, pt):
            # ID 切换导致的重复穿越：吞掉，并标记该 tid 方向，避免反复尝试
            self.counted.add(mark)
            logger.info(
                "ZONE dedupe skip %s tid=%s group=%s at (%.0f,%.0f)",
                "ENTER" if direction > 0 else "EXIT", tid, group, pt[0], pt[1],
            )
            return None

        # 记下本次方向；清掉反向标记，使离开后再进入可再次计数
        self.counted.add(mark)
        self.counted.discard((tid, -direction))

        event = "ENTER" if direction > 0 else "EXIT"
        if direction > 0:
            self.enter_count += 1
            self.by_group[group]["in"] += 1
        else:
            self.exit_count += 1
            self.by_group[group]["out"] += 1

        self._recent_events.append({
            "frame": self._frame,
            "direction": direction,
            "group": group,
            "x": pt[0],
            "y": pt[1],
        })
        self._recent_events = [
            e for e in self._recent_events
            if self._frame - e["frame"] <= self.dedupe_frames
        ]

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ratio_txt = f" ratio={overlap:.0%}" if overlap is not None else ""
        line = f"[{ts}] ALARM: {event} | TrackID={tid} | class={class_name or group}{ratio_txt}"
        self._alarm_log.append(line)
        logger.info(line)

        alarm = {
            "event": event,
            "direction": "in" if direction > 0 else "out",
            "trackId": int(tid),
            "className": class_name,
            "classId": class_id,
            "group": group,
            "bbox": bbox,
            "overlapRatio": round(float(overlap), 4) if overlap is not None else None,
            "time": ts,
        }
        self.alarms.append(alarm)
        return alarm

    def update(
        self,
        tid: int,
        center: tuple[float, float],
        polygon: np.ndarray,
        *,
        class_id: int | None = None,
        class_name: str | None = None,
        bbox: list | None = None,
    ) -> dict | None:
        """更新单个目标；确认有效进出后返回 alarm，否则 None。

        有效进入：bbox∩zone 面积 / bbox 面积 ≥ area_ratio（默认 30%）。
        """
        tid = int(tid)
        pt = anchor_point(center, bbox, class_id=class_id, class_name=class_name)
        overlap = bbox_zone_overlap_ratio(bbox, polygon) if bbox is not None else (
            1.0 if point_in_polygon(pt, polygon) else 0.0
        )
        inside = overlap >= self.area_ratio
        self.id_history[tid] = pt

        st = self._states.get(tid)
        if st is None:
            self._states[tid] = {
                "inside": inside,
                "overlap": overlap,
                "side_streak": 1,
                "pending_dir": None,
                "pending_streak": 0,
                "miss": 0,
                "class_id": class_id,
                "class_name": class_name,
                "bbox": bbox,
                "pt": pt,
            }
            return None

        st["miss"] = 0
        st["class_id"] = class_id if class_id is not None else st.get("class_id")
        st["class_name"] = class_name if class_name is not None else st.get("class_name")
        st["bbox"] = bbox if bbox is not None else st.get("bbox")
        st["pt"] = pt
        st["overlap"] = overlap
        alarm = None

        if inside == st["inside"]:
            st["side_streak"] += 1
            if st["pending_dir"] is not None:
                # pending ENTER 要求当前有效在区内；EXIT 要求未达阈值
                want_inside = st["pending_dir"] > 0
                if inside == want_inside:
                    st["pending_streak"] += 1
                    if st["pending_streak"] >= self.confirm_frames:
                        alarm = self._commit(
                            tid, st["pending_dir"], pt,
                            class_id=st.get("class_id"),
                            class_name=st.get("class_name"),
                            bbox=st.get("bbox"),
                            overlap=overlap,
                        )
                        st["pending_dir"] = None
                        st["pending_streak"] = 0
                else:
                    # 确认期内又抖回原侧 → 取消
                    st["pending_dir"] = None
                    st["pending_streak"] = 0
        else:
            # 侧切换：仅当旧侧已稳定才启动 pending
            if st["side_streak"] >= self.stable_frames:
                direction = 1 if (not st["inside"] and inside) else -1
                st["pending_dir"] = direction
                st["pending_streak"] = 1
                if self.confirm_frames <= 1:
                    alarm = self._commit(
                        tid, direction, pt,
                        class_id=st.get("class_id"),
                        class_name=st.get("class_name"),
                        bbox=st.get("bbox"),
                        overlap=overlap,
                    )
                    st["pending_dir"] = None
                    st["pending_streak"] = 0
            else:
                # 旧侧不稳，视为抖动，不计数
                st["pending_dir"] = None
                st["pending_streak"] = 0
            st["inside"] = inside
            st["side_streak"] = 1

        return alarm

    def end_frame(self, active_ids: set[int] | list[int] | None = None) -> list[dict]:
        """每帧结束调用：推进帧号，并对「区内消失」的目标补记 EXIT。"""
        self._frame += 1
        active = set(int(x) for x in (active_ids or []))
        alarms = []
        for tid, st in list(self._states.items()):
            if tid in active:
                continue
            st["miss"] = int(st.get("miss") or 0) + 1
            if not st.get("inside"):
                continue
            if st["miss"] < self.miss_exit_frames:
                continue
            if (tid, -1) in self.counted:
                continue
            # 视为离开区域
            alarm = self._commit(
                tid, -1, st.get("pt") or (0.0, 0.0),
                class_id=st.get("class_id"),
                class_name=st.get("class_name"),
                bbox=st.get("bbox"),
            )
            st["inside"] = False
            st["pending_dir"] = None
            st["pending_streak"] = 0
            if alarm:
                alarms.append(alarm)
        return alarms

    def snapshot(self) -> dict:
        person = self.by_group["person"]
        vehicle = self.by_group["vehicle"]
        return {
            "in": self.enter_count,
            "out": self.exit_count,
            "total": self.enter_count + self.exit_count,
            "net": self.enter_count - self.exit_count,
            "person": {
                "in": person["in"],
                "out": person["out"],
                "net": person["in"] - person["out"],
            },
            "vehicle": {
                "in": vehicle["in"],
                "out": vehicle["out"],
                "net": vehicle["in"] - vehicle["out"],
            },
            "alarmCount": len(self.alarms),
            "recentAlarms": self.alarms[-20:],
        }


def parse_css_color(raw, default_bgr=(255, 0, 0), default_alpha: float = 1.0):
    """解析 #RGB / #RRGGBB / #RRGGBBAA / rgb() / rgba() / [r,g,b(,a)] → (BGR, alpha)。"""
    if raw is None:
        return default_bgr, float(default_alpha)
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            r, g, b = int(raw[0]), int(raw[1]), int(raw[2])
            a = float(raw[3]) if len(raw) >= 4 else float(default_alpha)
            if a > 1.0:
                a = a / 255.0
            return (max(0, min(255, b)), max(0, min(255, g)), max(0, min(255, r))), max(0.0, min(1.0, a))
        except (TypeError, ValueError):
            return default_bgr, float(default_alpha)
    s = str(raw).strip()
    if not s:
        return default_bgr, float(default_alpha)
    lower = s.lower()
    if lower.startswith("rgba(") or lower.startswith("rgb("):
        try:
            inner = lower[lower.index("(") + 1: lower.rindex(")")]
            parts = [p.strip() for p in inner.split(",")]
            r, g, b = int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
            a = float(parts[3]) if len(parts) >= 4 else float(default_alpha)
            if a > 1.0:
                a = a / 255.0
            return (max(0, min(255, b)), max(0, min(255, g)), max(0, min(255, r))), max(0.0, min(1.0, a))
        except (ValueError, IndexError):
            return default_bgr, float(default_alpha)
    if s.startswith("#"):
        h = s[1:]
        try:
            if len(h) == 3:
                r, g, b = (int(c * 2, 16) for c in h)
                return (b, g, r), float(default_alpha)
            if len(h) == 6:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                return (b, g, r), float(default_alpha)
            if len(h) == 8:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                a = int(h[6:8], 16) / 255.0
                return (b, g, r), max(0.0, min(1.0, a))
        except ValueError:
            return default_bgr, float(default_alpha)
    return default_bgr, float(default_alpha)


def draw_zone_overlay(
    frame: np.ndarray,
    polygon: np.ndarray,
    counter: ZoneFlowCounter | None = None,
    alarms_this_frame: list[dict] | None = None,
    occupancy: dict | None = None,
    border_color=None,
    fill_color=None,
    fill_alpha: float | None = None,
    border_width: int | float | None = None,
) -> np.ndarray:
    """绘制监控区域、框内人车计数、角标 HUD、越界红框。

    occupancy: 当前帧有效在区内数量 {"person": n, "vehicle": m}；为 0 的项不绘制。
    border_color / fill_color: CSS 色或 [r,g,b(,a)]；fill_alpha 可覆盖填充透明度。
    border_width: 边框线宽（像素），默认 2，范围 1–20。
    """
    out = frame
    if polygon is not None and len(polygon) >= 3:
        border_bgr, _ = parse_css_color(border_color, default_bgr=(255, 0, 0), default_alpha=1.0)
        fill_bgr, fill_a = parse_css_color(
            fill_color, default_bgr=border_bgr, default_alpha=0.12,
        )
        if fill_alpha is not None:
            try:
                fill_a = max(0.0, min(1.0, float(fill_alpha)))
            except (TypeError, ValueError):
                pass
        thickness = 2
        if border_width is not None:
            try:
                thickness = max(1, min(20, int(round(float(border_width)))))
            except (TypeError, ValueError):
                thickness = 2
        cv2.polylines(out, [polygon.astype(np.int32)], True, border_bgr, thickness)
        if fill_a > 0:
            overlay = out.copy()
            cv2.fillPoly(overlay, [polygon.astype(np.int32)], fill_bgr)
            cv2.addWeighted(overlay, fill_a, out, 1.0 - fill_a, 0, out)
        out = _draw_zone_occupancy_label(out, polygon, occupancy)

    if alarms_this_frame:
        for a in alarms_this_frame:
            box = a.get("bbox")
            if not box or len(box) < 4:
                continue
            x1, y1, x2, y2 = map(int, box[:4])
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 255), 3)
            label = f"ALARM:{a.get('event', '')}"
            cv2.putText(
                out, label, (x1, max(20, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA,
            )

    if counter is not None:
        snap = counter.snapshot()
        lines = [
            f"In:{snap['in']} Out:{snap['out']} Net:{snap['net']}",
            f"Person In:{snap['person']['in']} Out:{snap['person']['out']}",
            f"Vehicle In:{snap['vehicle']['in']} Out:{snap['vehicle']['out']}",
        ]
        y0 = 32
        for i, text in enumerate(lines):
            cv2.putText(
                out, text, (16, y0 + i * 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2, cv2.LINE_AA,
            )
    return out


_zone_font_cache: dict[tuple[int, bool], Any] = {}


def _zone_font(size: int = 22, bold: bool = False):
    """加载支持中文的字体（OpenCV putText 无法画中文）。"""
    key = (int(size), bool(bold))
    if key in _zone_font_cache:
        return _zone_font_cache[key]
    import os
    from PIL import ImageFont
    win = os.environ.get("WINDIR", r"C:\Windows")
    bold_candidates = [
        os.path.join(win, "Fonts", "msyhbd.ttc"),
        os.path.join(win, "Fonts", "simhei.ttf"),
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ]
    regular_candidates = [
        os.path.join(win, "Fonts", "msyh.ttc"),
        os.path.join(win, "Fonts", "msyhbd.ttc"),
        os.path.join(win, "Fonts", "simhei.ttf"),
        os.path.join(win, "Fonts", "simsun.ttc"),
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    candidates = bold_candidates + regular_candidates if bold else regular_candidates
    font = None
    for path in candidates:
        if os.path.isfile(path):
            try:
                font = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default()
    _zone_font_cache[key] = font
    return font


# 视频计数文案相对自适应字号的放大倍数（加粗绘制；相对曾用的 5 倍再缩小 2 倍）
_ZONE_LABEL_SCALE = 2.5


def _polygon_centroid(polygon: np.ndarray) -> tuple[int, int]:
    pts = polygon.reshape(-1, 2).astype(np.float64)
    return int(round(float(pts[:, 0].mean()))), int(round(float(pts[:, 1].mean())))


def _polygon_area(polygon: np.ndarray) -> float:
    """多边形面积（鞋带公式，像素²）。"""
    pts = polygon.reshape(-1, 2).astype(np.float64)
    x, y = pts[:, 0], pts[:, 1]
    return float(abs(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)))


def _polygon_bbox_size(polygon: np.ndarray) -> tuple[float, float]:
    pts = polygon.reshape(-1, 2).astype(np.float64)
    return float(pts[:, 0].max() - pts[:, 0].min()), float(pts[:, 1].max() - pts[:, 1].min())


def format_zone_occupancy_lines(occupancy: dict | None) -> list[str]:
    """生成框内人车累计统计文案；计数为 0 的项省略。

    occupancy 可用当前在区数，或累计进入数（车/人键）。
    """
    if not occupancy:
        return []
    lines = []
    vehicle = int(occupancy.get("vehicle") or 0)
    person = int(occupancy.get("person") or 0)
    if vehicle > 0:
        lines.append(f"车：{vehicle}")
    if person > 0:
        lines.append(f"人：{person}")
    return lines


def occupancy_from_counter(counter: ZoneFlowCounter | None) -> dict:
    """从进出计数器取人/车累计进入数（自动累加）。"""
    if counter is None:
        return {"person": 0, "vehicle": 0}
    snap = counter.snapshot()
    return {
        "person": int(snap["person"]["in"]),
        "vehicle": int(snap["vehicle"]["in"]),
    }


def _measure_label_block(draw, lines: list[str], font, gap: int = 6) -> tuple[int, int, list[int], list[int]]:
    """测量多行标签块宽高及各行尺寸。"""
    sizes = [draw.textbbox((0, 0), t, font=font) for t in lines]
    widths = [b[2] - b[0] for b in sizes]
    heights = [b[3] - b[1] for b in sizes]
    total_h = sum(heights) + gap * max(0, len(lines) - 1)
    max_w = max(widths) if widths else 0
    return max_w, total_h, widths, heights


def _fit_zone_label_font_size(
    draw,
    lines: list[str],
    polygon: np.ndarray,
    *,
    area_ratio: float = 0.06,
) -> int:
    """按多边形面积比例自适应字号，使文字块约占区域 area_ratio（默认约 1/16）。"""
    poly_area = max(_polygon_area(polygon), 1.0)
    target = poly_area * area_ratio
    bw, bh = _polygon_bbox_size(polygon)
    # 字号上限：约外接矩形短边的 22%，避免过大遮挡
    max_size = max(18, int(min(bw, bh) * 0.22))
    min_size = 14
    best = min_size
    lo, hi = min_size, max_size
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _zone_font(mid)
        tw, th, _, _ = _measure_label_block(draw, lines, font)
        area = max(tw, 1) * max(th, 1)
        if area <= target:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _draw_zone_occupancy_label(
    frame: np.ndarray,
    polygon: np.ndarray,
    occupancy: dict | None,
) -> np.ndarray:
    """在多边形中心绘制「车：n / 人：m」（仅非零）。

    基准字号按区域自适应后放大 _ZONE_LABEL_SCALE 倍并加粗；透明背景 + 描边白字。
    """
    lines = format_zone_occupancy_lines(occupancy)
    if not lines or polygon is None or len(polygon) < 3:
        return frame
    from PIL import Image, ImageDraw

    cx, cy = _polygon_centroid(polygon)
    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)

    base = _fit_zone_label_font_size(draw, lines, polygon, area_ratio=0.06)
    bw, bh = _polygon_bbox_size(polygon)
    # 放大 5 倍；上限约外接矩形短边，避免完全溢出
    font_size = min(int(base * _ZONE_LABEL_SCALE), max(18, int(min(bw, bh) * 0.95)))
    font = _zone_font(font_size, bold=True)
    gap = max(4, font_size // 8)
    _, total_h, widths, heights = _measure_label_block(draw, lines, font, gap=gap)
    outline = max(2, font_size // 18)
    ty = cy - total_h // 2
    for text, tw, th in zip(lines, widths, heights):
        tx = cx - tw // 2
        # 透明背景：加粗黑描边 + 白字
        for ox in range(-outline, outline + 1):
            for oy in range(-outline, outline + 1):
                if ox == 0 and oy == 0:
                    continue
                draw.text((tx + ox, ty + oy), text, font=font, fill=(0, 0, 0))
        draw.text((tx, ty), text, font=font, fill=(255, 255, 255))
        ty += th + gap
    return cv2.cvtColor(np.asarray(pil.convert("RGB")), cv2.COLOR_RGB2BGR)


# ---------- 实时会话：复用 TrackZone / 计数器 ----------
_tz_lock = threading.Lock()
_tz_sessions: dict[str, dict[str, Any]] = {}


def _session_key(model_path: str, session_id: str | None) -> str:
    return f"{model_path}::{session_id or 'default'}"


def reset_zone_session(model_path: str | None = None, session_id: str | None = None):
    """重置/清理 TrackZone 会话。"""
    with _tz_lock:
        if model_path is None and session_id is None:
            _tz_sessions.clear()
            return
        if model_path is not None:
            key = _session_key(model_path, session_id)
            _tz_sessions.pop(key, None)
            return
        # 仅按 session_id 清理
        dead = [k for k in _tz_sessions if k.endswith(f"::{session_id}")]
        for k in dead:
            _tz_sessions.pop(k, None)


def get_or_create_zone_counter(model_path: str, session_id: str | None = None, reset: bool = False) -> ZoneFlowCounter:
    key = _session_key(model_path, session_id)
    with _tz_lock:
        slot = _tz_sessions.get(key)
        if slot is None or reset:
            counter = ZoneFlowCounter()
            _tz_sessions[key] = {"counter": counter}
            return counter
        return slot["counter"]


def create_trackzone(
    model_path: str,
    region_px: np.ndarray,
    *,
    classes: list[int] | None = None,
    conf: float = 0.25,
    imgsz: int = 640,
):
    """创建 Ultralytics TrackZone（区域凸包由解决方案内部处理）。"""
    from ultralytics import solutions

    region_list = [tuple(map(int, p)) for p in region_px.reshape(-1, 2)]
    kwargs = dict(
        model=model_path,
        region=region_list,
        classes=classes,
        conf=conf,
        imgsz=imgsz,
        tracker="bytetrack.yaml",
        show=False,
        verbose=False,
        device="cpu",
    )
    return solutions.TrackZone(**kwargs)
