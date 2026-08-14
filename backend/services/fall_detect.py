"""跌倒检测辅助：COCO-17 关键点指标计算、person 检测框合成、轻量跨帧跟踪。

判定阈值不在本模块，全部由 services/alert_engine._eval_fall_detection 从
AlertRule.config_json 读取。本模块只负责与规则无关的几何量与 trackId 分配。
"""
from __future__ import annotations

import math
import threading

# COCO-17 关键点索引
KP_NOSE = 0
KP_L_SHOULDER, KP_R_SHOULDER = 5, 6
KP_L_HIP, KP_R_HIP = 11, 12
KP_L_ANKLE, KP_R_ANKLE = 15, 16


def _coerce_row(row):
    """解析单行 [x, y, conf]；格式不合法或转换失败返回 None。"""
    try:
        row = list(row)
        if len(row) < 3:
            return None
        x, y, c = float(row[0]), float(row[1]), float(row[2])
        return (x, y, c)
    except (TypeError, ValueError):
        return None


def _point(kp, idx: int, min_conf: float):
    """取单个关键点像素坐标；置信度不足或索引越界返回 None。"""
    if kp is None or idx >= len(kp):
        return None
    parsed = _coerce_row(kp[idx])
    if parsed is None:
        return None
    x, y, c = parsed
    return (x, y) if c >= min_conf else None


def _mid(a, b):
    """两点中点；只有一点可用时退化为该点，都不可用返回 None。"""
    if a and b:
        return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    return a or b


def keypoint_metrics(kp, width=None, height=None, kp_min_conf: float = 0.3) -> dict:
    """从 COCO-17 关键点提取跌倒判定所需的几何量（像素坐标系）。"""
    nose = _point(kp, KP_NOSE, kp_min_conf)
    shoulder = _mid(_point(kp, KP_L_SHOULDER, kp_min_conf),
                    _point(kp, KP_R_SHOULDER, kp_min_conf))
    hip = _mid(_point(kp, KP_L_HIP, kp_min_conf), _point(kp, KP_R_HIP, kp_min_conf))
    ankle = _mid(_point(kp, KP_L_ANKLE, kp_min_conf), _point(kp, KP_R_ANKLE, kp_min_conf))

    trunk_angle = None
    if shoulder and hip:
        dx = shoulder[0] - hip[0]
        dy = shoulder[1] - hip[1]
        trunk_angle = abs(math.degrees(math.atan2(dx, -dy)))

    body_height = abs(shoulder[1] - ankle[1]) if (shoulder and ankle) else None

    return {
        "trunkAngle": trunk_angle,
        "hipY": hip[1] if hip else None,
        "shoulderY": shoulder[1] if shoulder else None,
        "ankleY": ankle[1] if ankle else None,
        "noseY": nose[1] if nose else None,
        "bodyHeight": body_height,
        "valid": {
            "trunk": trunk_angle is not None,
            "hip": hip is not None,
            "ankle": ankle is not None,
            "nose": nose is not None,
        },
    }


def build_person_detections(persons, width, height, kp_min_conf: float = 0.3) -> list[dict]:
    """姿态结果 persons -> 告警引擎可用的 person 检测框（带 keypoints 透传）。

    bbox 取可用关键点包围盒并外扩 5%，钳制在画面内；confidence 取可用点平均分。
    """
    out = []
    fw = float(width or 0) or None
    fh = float(height or 0) or None
    for p in persons or []:
        kp = (p or {}).get("keypoints") or []
        pts = []
        for row in kp:
            parsed = _coerce_row(row)
            if parsed is None:
                continue
            x, y, c = parsed
            if c >= kp_min_conf:
                pts.append((x, y, c))
        if not pts:
            continue
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        pad_x = (max(xs) - min(xs)) * 0.05
        pad_y = (max(ys) - min(ys)) * 0.05
        x1 = max(0.0, min(xs) - pad_x)
        y1 = max(0.0, min(ys) - pad_y)
        x2 = max(xs) + pad_x
        y2 = max(ys) + pad_y
        if fw:
            x2 = min(fw, x2)
        if fh:
            y2 = min(fh, y2)
        out.append({
            "className": "person",
            "confidence": round(sum(q[2] for q in pts) / len(pts), 4),
            "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
            "keypoints": kp,
        })
    return out


# ---------------------------------------------------------------- 轻量跨帧跟踪
# source_key -> {"next_id": int, "tracks": {tid: {"anchor": (x,y), "bbox": [...], "miss": int}}}
_trackers: dict[str, dict] = {}
_tracker_lock = threading.Lock()

_MATCH_MIN_IOU = 0.2
_MATCH_DIST_FACTOR = 0.6  # 允许位移上限 = 该框长边 * 系数


def _iou(a, b) -> float:
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.0
    ax1, ay1, ax2, ay2 = (float(v) for v in a[:4])
    bx1, by1, bx2, by2 = (float(v) for v in b[:4])
    iw = min(ax2, bx2) - max(ax1, bx1)
    ih = min(ay2, by2) - max(ay1, by1)
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def _track_anchor(det: dict):
    """跟踪锚点：优先髋部中点（匹配阶段不设置信度门限），退化为 bbox 中心。"""
    kp = det.get("keypoints") or []
    hip = _mid(_point(kp, KP_L_HIP, 0.0), _point(kp, KP_R_HIP, 0.0))
    if hip:
        return hip
    bbox = det.get("bbox") or []
    if len(bbox) >= 4:
        return ((float(bbox[0]) + float(bbox[2])) / 2.0,
                (float(bbox[1]) + float(bbox[3])) / 2.0)
    return (0.0, 0.0)


def _bbox_long_side(bbox) -> float:
    if not bbox or len(bbox) < 4:
        return 1.0
    return max(abs(float(bbox[2]) - float(bbox[0])),
               abs(float(bbox[3]) - float(bbox[1])), 1.0)


def assign_track_ids(detections, source_key: str = "default", max_age: int = 15):
    """按髋部质心最近邻 + IoU 双条件匹配上一帧，原地写入 trackId。"""
    dets = detections or []
    try:
        max_age = int(max_age)
    except (TypeError, ValueError):
        max_age = 15

    with _tracker_lock:
        st = _trackers.setdefault(source_key or "default", {"next_id": 1, "tracks": {}})
        tracks: dict = st["tracks"]

        pairs = []
        for i, d in enumerate(dets):
            anchor = _track_anchor(d)
            limit = _bbox_long_side(d.get("bbox")) * _MATCH_DIST_FACTOR
            for tid, tr in tracks.items():
                dist = math.dist(anchor, tr["anchor"])
                if dist > limit:
                    continue
                if _iou(d.get("bbox"), tr["bbox"]) < _MATCH_MIN_IOU:
                    continue
                pairs.append((dist, i, tid))
        pairs.sort()

        matched_det, matched_tid = {}, set()
        for _dist, i, tid in pairs:
            if i in matched_det or tid in matched_tid:
                continue
            matched_det[i] = tid
            matched_tid.add(tid)

        live = set()
        for i, d in enumerate(dets):
            tid = matched_det.get(i)
            if tid is None:
                tid = st["next_id"]
                st["next_id"] += 1
            tracks[tid] = {
                "anchor": _track_anchor(d),
                "bbox": list(d.get("bbox") or []),
                "miss": 0,
            }
            d["trackId"] = tid
            live.add(tid)

        for tid in list(tracks):
            if tid in live:
                continue
            tracks[tid]["miss"] += 1
            if tracks[tid]["miss"] > max_age:
                del tracks[tid]

    return dets


def reset_tracker(source_key: str | None = None):
    """清跟踪器状态；source_key 为 None 时全清（含 ID 计数器）。"""
    with _tracker_lock:
        if source_key is None:
            _trackers.clear()
            return
        _trackers.pop(source_key, None)
