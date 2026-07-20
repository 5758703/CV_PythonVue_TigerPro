"""羽毛球比赛视频分析（参考 Good-Badminton 思路，复用平台 YOLO 推理）。

功能：球场四角映射、球员姿态、羽毛球检测、轨迹统计、热力图/散点图、标注视频输出。
"""
import json
import math
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

# 标准羽毛球场尺寸（米，单打）
COURT_W_M = 5.18
COURT_L_M = 13.4

# COCO-17 骨架连线
_POSE_SKELETON = [
    (0, 1), (0, 2), (1, 3), (2, 4), (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
]

_PLAYER_COLORS = [
    (0, 200, 255), (0, 255, 120), (255, 180, 0), (255, 80, 200),
]

# 上场(远端) / 下场(近端) — 对齐参考 GIF 亮黄 / 亮粉
_SLOT_COLORS_BGR = [
    (0, 255, 255),   # 亮黄
    (255, 45, 230),  # 亮粉紫
]

_overlay_font_cache = {}


def _get_overlay_font(size=18):
    """加载支持中文的 TrueType 字体（OpenCV putText 无法渲染中文）。"""
    if size in _overlay_font_cache:
        return _overlay_font_cache[size]
    from PIL import ImageFont
    win = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        os.path.join(win, "Fonts", "msyh.ttc"),
        os.path.join(win, "Fonts", "msyhbd.ttc"),
        os.path.join(win, "Fonts", "simhei.ttf"),
        os.path.join(win, "Fonts", "simsun.ttc"),
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                font = ImageFont.truetype(path, size)
                _overlay_font_cache[size] = font
                return font
            except OSError:
                continue
    font = ImageFont.load_default()
    _overlay_font_cache[size] = font
    return font


def _draw_text_lines_bgr(frame, lines, origin=(12, 10), font_size=18, line_gap=6):
    """在 BGR 图像上绘制多行文字（PIL，支持中文）。"""
    if not lines:
        return frame
    from PIL import Image, ImageDraw
    font = _get_overlay_font(font_size)
    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    x, y = origin
    for text in lines:
        draw.text((x + 1, y + 1), text, font=font, fill=(30, 30, 30))
        draw.text((x, y), text, font=font, fill=(255, 255, 255))
        bbox = draw.textbbox((x, y), text, font=font)
        y = bbox[3] + line_gap
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def _parse_xy_points(raw, w, h, expect_n=None, label="点"):
    """解析 [[x,y]…]，支持 0–1 归一化或像素坐标。"""
    if raw is None or raw == "" or raw == []:
        return None
    pts = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(pts, list):
        raise ValueError(f"{label}须为数组")
    if expect_n is not None and len(pts) != expect_n:
        raise ValueError(f"{label}须为 {expect_n} 个点")
    out = []
    for p in pts:
        x, y = float(p[0]), float(p[1])
        if 0 <= x <= 1 and 0 <= y <= 1:
            x, y = x * w, y * h
        out.append([x, y])
    return np.float32(out)


def _parse_court_points(raw, w, h):
    """解析球场四角 [[x,y]×4]，支持 0–1 归一化或像素坐标。"""
    if not raw:
        raise ValueError("请标注球场四个角点（左上→右上→右下→左下）")
    out = _parse_xy_points(raw, w, h, expect_n=4, label="球场角点")
    if out is None:
        raise ValueError("请标注球场四个角点（左上→右上→右下→左下）")
    return out


def _default_net_from_corners(img_pts):
    """四角 → 默认网线端点 (左中, 右中)。"""
    tl, tr, br, bl = img_pts[:4]
    left = ((float(tl[0]) + float(bl[0])) * 0.5, (float(tl[1]) + float(bl[1])) * 0.5)
    right = ((float(tr[0]) + float(br[0])) * 0.5, (float(tr[1]) + float(br[1])) * 0.5)
    return np.float32([left, right])


def _parse_net_points(raw, w, h, img_pts):
    """解析网线两端点；缺省时由四角中点推导。"""
    parsed = _parse_xy_points(raw, w, h, expect_n=2, label="网线端点") if raw not in (None, "", []) else None
    if parsed is not None and len(parsed) == 2:
        return parsed
    return _default_net_from_corners(img_pts)


def _court_homography(img_pts):
    """图像四角 → 标准球场坐标（米）。"""
    dst = np.float32([
        [0, 0], [COURT_W_M, 0], [COURT_W_M, COURT_L_M], [0, COURT_L_M],
    ])
    return cv2.getPerspectiveTransform(img_pts, dst)


def _to_court_xy(px, py, H):
    pt = cv2.perspectiveTransform(np.float32([[[px, py]]]), H)[0][0]
    return float(pt[0]), float(pt[1])


def _in_court_polygon(px, py, poly):
    return cv2.pointPolygonTest(poly, (float(px), float(py)), False) >= 0


def _expand_court_poly(poly, margin_ratio=0.08):
    """球场多边形外扩，减少边线/底线附近球被误滤。"""
    pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
    if len(pts) < 3:
        return poly
    c = pts.mean(axis=0)
    expanded = c + (pts - c) * (1.0 + float(margin_ratio))
    return expanded.reshape((-1, 1, 2)).astype(np.float32)


def _detect_shuttlecock(
    ball_model,
    frame,
    court_poly,
    conf=0.15,
    prev_xy=None,
    max_jump=None,
    imgsz=960,
):
    """羽毛球专用检测：偏低阈值、偏好小框、球场扩边、时序邻近优先。

    Returns:
        (cx, cy, score) | None
    """
    if ball_model is None:
        return None
    h, w = frame.shape[:2]
    frame_area = float(max(1, h * w))
    ball_conf = float(conf)
    if ball_conf <= 0:
        ball_conf = 0.12
    # 小球易低分：相对姿态 conf 再放宽一点，但不低于 0.08
    ball_conf = max(0.08, min(ball_conf, 0.35))
    poly = _expand_court_poly(court_poly, 0.08)

    try:
        pr = ball_model.predict(
            frame,
            conf=ball_conf,
            imgsz=int(imgsz) if imgsz else 960,
            verbose=False,
            max_det=30,
            iou=0.45,
        )[0]
    except Exception:  # noqa: BLE001
        return None
    if pr.boxes is None or len(pr.boxes) == 0:
        return None

    names = getattr(pr, "names", None) or getattr(ball_model, "names", None) or {}
    cands = []
    for box in pr.boxes:
        score = float(box.conf[0]) if getattr(box, "conf", None) is not None else 0.0
        xy = box.xyxy[0].tolist()
        x1, y1, x2, y2 = [float(v) for v in xy]
        cx, cy = (x1 + x2) * 0.5, (y1 + y2) * 0.5
        bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
        area_ratio = (bw * bh) / frame_area
        # 过滤明显过大的框（人/拍），羽毛球通常 << 1.5% 画面
        if area_ratio > 0.02:
            continue
        if not _in_court_polygon(cx, cy, poly):
            continue
        # 类名启发（若为多类模型）
        cls_id = int(box.cls[0]) if getattr(box, "cls", None) is not None else -1
        cname = str(names.get(cls_id, "") if isinstance(names, dict) else "").lower()
        name_bonus = 0.0
        if any(k in cname for k in ("shuttle", "badminton", "ball", "cock")):
            name_bonus = 0.08
        # 偏好更小的框
        size_bonus = max(0.0, 0.12 * (1.0 - min(1.0, area_ratio / 0.005)))
        temporal = 0.0
        if prev_xy is not None:
            dist = math.hypot(cx - prev_xy[0], cy - prev_xy[1])
            limit = float(max_jump or (0.35 * max(w, h)))
            if dist > limit:
                continue
            temporal = 0.15 * (1.0 - min(1.0, dist / max(limit, 1.0)))
        cands.append((score + name_bonus + size_bonus + temporal, cx, cy, score))

    if not cands:
        return None
    cands.sort(key=lambda t: t[0], reverse=True)
    _, cx, cy, raw = cands[0]
    return cx, cy, raw


def _draw_shuttle_marker(frame, xy, frame_scale=1.0):
    """当前帧羽毛球位置高亮。"""
    if not xy:
        return
    r = max(4, int(6 * frame_scale))
    x, y = int(xy[0]), int(xy[1])
    cv2.circle(frame, (x, y), r + 2, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.circle(frame, (x, y), r, (0, 255, 255), -1, cv2.LINE_AA)
    cv2.circle(frame, (x, y), max(1, r // 3), (255, 255, 255), -1, cv2.LINE_AA)


def _person_bbox_from_keypoints(kp):
    """从关键点估计人体框中心。"""
    xs = [p[0] for p in kp if len(p) >= 3 and p[2] > 0.3]
    ys = [p[1] for p in kp if len(p) >= 3 and p[2] > 0.3]
    if not xs:
        return None
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _foot_position_from_keypoints(kp):
    """脚底锚点：踝部中心，否则取关键点最下端（对齐 GIF 脚下圆点）。"""
    ankles = []
    for idx in (15, 16):
        if idx < len(kp) and len(kp[idx]) >= 3 and kp[idx][2] > 0.3:
            ankles.append((kp[idx][0], kp[idx][1]))
    if ankles:
        return sum(p[0] for p in ankles) / len(ankles), sum(p[1] for p in ankles) / len(ankles)
    vis = [(p[0], p[1]) for p in kp if len(p) >= 3 and p[2] > 0.3]
    if not vis:
        return None
    return sum(p[0] for p in vis) / len(vis), max(p[1] for p in vis)


def _match_tracks(centroids, tracks, max_dist=80):
    """简单最近邻追踪，返回 {track_id: (cx,cy)}。"""
    used = set()
    new_tracks = {}
    next_id = max(tracks.keys(), default=0) + 1
    for cx, cy in centroids:
        best_id, best_d = None, max_dist
        for tid, (tx, ty) in tracks.items():
            if tid in used:
                continue
            d = math.hypot(cx - tx, cy - ty)
            if d < best_d:
                best_d, best_id = d, tid
        if best_id is not None:
            used.add(best_id)
            new_tracks[best_id] = (cx, cy)
        else:
            new_tracks[next_id] = (cx, cy)
            next_id += 1
    return new_tracks


def _draw_court(frame, img_pts, net_pts=None):
    pts = img_pts.astype(np.int32).reshape((-1, 1, 2))
    cv2.polylines(frame, [pts], True, (0, 220, 0), 2, cv2.LINE_AA)
    labels = ["TL", "TR", "BR", "BL"]
    for i, (x, y) in enumerate(img_pts):
        cv2.circle(frame, (int(x), int(y)), 5, (0, 255, 0), -1, cv2.LINE_AA)
        cv2.putText(frame, labels[i], (int(x) + 6, int(y) - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)
    # 网线：优先用户/管理员标注，否则四角中点
    if net_pts is not None and len(net_pts) >= 2:
        left = (float(net_pts[0][0]), float(net_pts[0][1]))
        right = (float(net_pts[1][0]), float(net_pts[1][1]))
    elif len(img_pts) >= 4:
        tl, tr, br, bl = img_pts[:4]
        left = ((float(tl[0]) + float(bl[0])) * 0.5, (float(tl[1]) + float(bl[1])) * 0.5)
        right = ((float(tr[0]) + float(br[0])) * 0.5, (float(tr[1]) + float(br[1])) * 0.5)
    else:
        return
    cv2.line(frame, (int(left[0]), int(left[1])), (int(right[0]), int(right[1])),
             (0, 200, 255), 2, cv2.LINE_AA)
    cv2.circle(frame, (int(left[0]), int(left[1])), 4, (0, 200, 255), -1, cv2.LINE_AA)
    cv2.circle(frame, (int(right[0]), int(right[1])), 4, (0, 200, 255), -1, cv2.LINE_AA)


def _draw_skeleton(frame, kp, color):
    for i, j in _POSE_SKELETON:
        if i >= len(kp) or j >= len(kp):
            continue
        if kp[i][2] < 0.3 or kp[j][2] < 0.3:
            continue
        p1 = (int(kp[i][0]), int(kp[i][1]))
        p2 = (int(kp[j][0]), int(kp[j][1]))
        cv2.line(frame, p1, p2, color, 2, cv2.LINE_AA)
    for p in kp:
        if len(p) >= 3 and p[2] > 0.3:
            cv2.circle(frame, (int(p[0]), int(p[1])), 3, color, -1, cv2.LINE_AA)


def _default_player_state():
    return {
        "total_dist": 0.0,
        "rally_dist": 0.0,
        "current_speed": 0.0,
        "max_speed_total": 0.0,
        "max_speed_rally": 0.0,
        "active_frames": 0,
        "rally_frames": 0,
    }


def _assign_player_slots(tracks, last_court_pos, net_y_m=None, prev_slot_map=None):
    """按半场分配 slot：Y < 网线 → 上场(0)，Y ≥ 网线 → 下场(1)。

    同侧多人时取离网更远者；无人时不占该 slot（HUD 仍会固定显示空面板）。
    """
    half = float(net_y_m) if net_y_m is not None else (COURT_L_M * 0.5)
    by_side = {0: [], 1: []}
    for tid in tracks:
        if tid not in last_court_pos:
            continue
        y = float(last_court_pos[tid][1])
        side = 0 if y < half else 1
        by_side[side].append((tid, abs(y - half)))
    result = {}
    for side, items in by_side.items():
        if not items:
            continue
        # 优先沿用上一帧同侧 tid，减少抖动
        if prev_slot_map:
            sticky = [tid for tid, s in prev_slot_map.items() if s == side and any(t == tid for t, _ in items)]
            if sticky:
                result[sticky[0]] = side
                continue
        items.sort(key=lambda x: x[1], reverse=True)
        result[items[0][0]] = side
    return result


class _RallyTracker:
    """正式比赛语义的回合判定：发球/开球 → 持续对打 → 球落地或长时失检结束。

    旧逻辑用「约 1.5s 检不到球」就结束回合，连续对打中遮挡/出画会造成虚假多回合。
    新逻辑：
      - 失检约 3.5s 才判回合结束（对齐捡球/死球间隔，容忍对打中短暂丢检）；
      - 持续不足约 0.8s 的闪检不计入回合；
      - HUD 显示当前正式回合序号。
    """

    __slots__ = (
        "end_gap", "min_len", "trail_clear",
        "completed", "active", "confirmed", "cur_frames", "no_ball", "lengths",
    )

    def __init__(self, fps: float):
        fps = float(fps or 25.0)
        self.end_gap = max(60, int(fps * 3.5))       # ~3.5s 无球 → 死球
        self.min_len = max(16, int(fps * 0.8))        # 最短有效回合
        self.trail_clear = max(3, int(fps * 0.22))    # 仅清球尾迹，不结束回合
        self.completed = 0
        self.active = False
        self.confirmed = False
        self.cur_frames = 0
        self.no_ball = 0
        self.lengths = []

    @property
    def display_id(self) -> int:
        if self.active:
            return self.completed if self.confirmed else (self.completed + 1)
        return self.completed

    @property
    def rally_count(self) -> int:
        return self.completed

    def on_ball(self):
        self.no_ball = 0
        if not self.active:
            self.active = True
            self.confirmed = False
            self.cur_frames = 0
        self.cur_frames += 1
        if not self.confirmed and self.cur_frames >= self.min_len:
            self.confirmed = True
            self.completed += 1

    def on_miss(self):
        """返回 (clear_shuttle_trail, rally_just_ended)。"""
        self.no_ball += 1
        clear_trail = self.no_ball > self.trail_clear
        ended = False
        if self.active and self.no_ball > self.end_gap:
            if self.confirmed:
                self.lengths.append(self.cur_frames)
            self.active = False
            self.confirmed = False
            self.cur_frames = 0
            ended = True
        return clear_trail, ended

    def finalize(self):
        if self.active and self.confirmed:
            self.lengths.append(self.cur_frames)
        self.active = False
        self.confirmed = False
        self.cur_frames = 0


def _empty_hud_player(slot):
    return {
        "slot": slot,
        "tid": None,
        "current_speed": 0.0,
        "rally_dist": 0.0,
        "rally_avg": 0.0,
        "max_speed_rally": 0.0,
        "total_dist": 0.0,
        "total_avg": 0.0,
        "max_speed_total": 0.0,
        "speed_hist": [],
    }


def _avg_speed(dist_m, frame_cnt, fps):
    if frame_cnt <= 0 or fps <= 0:
        return 0.0
    return dist_m / (frame_cnt / fps)


def _slot_color(slot):
    return _SLOT_COLORS_BGR[slot % len(_SLOT_COLORS_BGR)]


class _SmoothTrail:
    """轨迹平滑器：EMA + 可选帧间密插值。

    densify=True 适合羽毛球飞行弧；球员脚印用 densify=False，避免圆点叠成墨迹。
    """

    __slots__ = (
        "alpha", "max_hist", "max_jump", "min_step", "pos", "hist",
        "integer_coords", "densify", "miss",
    )

    def __init__(self, alpha=0.38, max_hist=36, max_jump=90.0, min_step=1.2,
                 integer_coords=True, densify=True):
        self.alpha = alpha
        self.max_hist = max_hist
        self.max_jump = max_jump
        self.min_step = min_step
        self.integer_coords = integer_coords
        self.densify = densify
        self.pos = None
        self.hist = []
        self.miss = 0

    def reset(self):
        self.pos = None
        self.hist = []
        self.miss = 0

    def decay(self, drop=None):
        """从尾迹头部丢弃旧点（失检淡出 / 回合结束加速清除）。"""
        if not self.hist:
            self.pos = None
            return
        n = len(self.hist)
        if drop is None:
            drop = max(2, n // 5)
        drop = min(n, max(1, int(drop)))
        self.hist = self.hist[drop:]
        if self.hist:
            self.pos = (float(self.hist[-1][0]), float(self.hist[-1][1]))
        else:
            self.pos = None

    def _store_point(self, sx, sy):
        if self.integer_coords:
            return int(round(sx)), int(round(sy))
        return float(sx), float(sy)

    def _commit(self, sx, sy, force=False):
        pt = self._store_point(sx, sy)
        if not self.hist:
            self.hist.append(pt)
        else:
            lx, ly = self.hist[-1]
            if force or math.hypot(pt[0] - lx, pt[1] - ly) >= self.min_step:
                self.hist.append(pt)
        if len(self.hist) > self.max_hist:
            self.hist = self.hist[-self.max_hist:]

    def push(self, x, y):
        x, y = float(x), float(y)
        self.miss = 0
        if self.pos is None:
            self.pos = (x, y)
            self._commit(x, y, force=True)
            return self.hist[-1]

        ox, oy = self.pos
        jump = math.hypot(x - ox, y - oy)
        if jump > self.max_jump:
            self.hist.clear()
            self.pos = (x, y)
            self._commit(x, y, force=True)
            return self.hist[-1]

        if not self.densify:
            a = self.alpha
            self.pos = (ox * (1 - a) + x * a, oy * (1 - a) + y * a)
            self._commit(*self.pos, force=False)
            # 每帧最多追加 1 点后，仍裁剪超长历史
            if len(self.hist) > self.max_hist:
                self.hist = self.hist[-self.max_hist:]
            return self.hist[-1]

        # 密插值：慢速时点几乎相连，快速时保持弧线（羽毛球用）
        steps = max(2, min(14, int(jump / max(self.min_step * 0.22, 0.15)) + 1))
        for i in range(1, steps + 1):
            t = i / steps
            tx = ox + (x - ox) * t
            ty = oy + (y - oy) * t
            a = self.alpha
            self.pos = (self.pos[0] * (1 - a) + tx * a, self.pos[1] * (1 - a) + ty * a)
            self._commit(*self.pos, force=(i < steps))
        return self.hist[-1]


def _prune_player_trails(img_smooth, court_smooth, active_tids, max_miss=8):
    """活跃 ID 保留；失检轨迹快速头部衰减，超时删除，避免旧 track 永久涂抹画面。"""
    active = set(active_tids or ())
    for tid in list(img_smooth.keys()):
        trail = img_smooth[tid]
        if tid in active:
            trail.miss = 0
            continue
        trail.miss = getattr(trail, "miss", 0) + 1
        # 失检后每帧砍掉一段旧点，形成实时淡出
        trail.decay(drop=max(3, len(trail.hist) // 4) if trail.hist else 1)
        ct = court_smooth.get(tid)
        if ct is not None:
            ct.miss = getattr(ct, "miss", 0) + 1
            ct.decay(drop=max(2, len(ct.hist) // 5) if ct.hist else 1)
        if trail.miss > max_miss or not trail.hist:
            img_smooth.pop(tid, None)
            court_smooth.pop(tid, None)


def _blend_color_bgr(color, factor):
    return tuple(int(c * factor) for c in color)


def _decimate_trail_pts(history, max_pts=36):
    """抽稀过密点列，绘制更干净。"""
    if not history:
        return []
    n = len(history)
    if n <= max_pts:
        return list(history)
    step = max(1, n / float(max_pts))
    out = []
    i = 0.0
    while int(i) < n:
        out.append(history[int(i)])
        i += step
    if out[-1] != history[-1]:
        out.append(history[-1])
    return out


def _draw_player_foot_trail(frame, history, color, frame_scale=1.0):
    """主画面球员尾迹：短时淡出折线 + 轻柔头部光点（广播级 comet，非实心墨点）。"""
    if not history:
        return
    pts = _decimate_trail_pts(history, max_pts=40)
    n = len(pts)
    ip = [(int(round(p[0])), int(round(p[1]))) for p in pts]

    # 在副本上画线再柔化合成，尾部更通透、不糊死场地
    overlay = frame.copy()
    if n == 1:
        r = max(3, int(4 * frame_scale))
        cv2.circle(overlay, ip[0], r, color, -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
        return

    for i in range(1, n):
        t = i / (n - 1)
        # 尾端几乎看不见，近端渐亮渐粗
        bright = 0.08 + 0.92 * (t ** 2.4)
        thick = max(1, int(round(0.8 + 2.4 * t * frame_scale)))
        cv2.line(overlay, ip[i - 1], ip[i], _blend_color_bgr(color, bright), thick, cv2.LINE_AA)

    # 头部彗星核
    hx, hy = ip[-1]
    core = max(3, int(4 * frame_scale))
    cv2.circle(overlay, (hx, hy), core + 3, _blend_color_bgr(color, 0.28), -1, cv2.LINE_AA)
    cv2.circle(overlay, (hx, hy), core, color, -1, cv2.LINE_AA)
    cv2.circle(overlay, (hx, hy), core + 1, (255, 255, 255), 1, cv2.LINE_AA)

    cv2.addWeighted(overlay, 0.62, frame, 0.38, 0, frame)


def _draw_shuttle_flight_trail(frame, history, frame_scale=1.0):
    """主画面羽毛球：稀疏淡出小点，单次飞行弧迹。"""
    if not history:
        return
    color = (0, 255, 255)
    pts = _decimate_trail_pts(history, max_pts=48)
    n = len(pts)
    overlay = frame.copy()
    dot_max = max(2, int(3 * frame_scale))
    for i, pt in enumerate(pts):
        px, py = int(round(pt[0])), int(round(pt[1]))
        age = (i + 1) / n
        radius = max(1, int(1 + dot_max * (age ** 0.85)))
        bright = 0.12 + 0.88 * (age ** 1.8)
        cv2.circle(overlay, (px, py), radius, _blend_color_bgr(color, bright), -1, cv2.LINE_AA)
    px, py = int(round(pts[-1][0])), int(round(pts[-1][1]))
    cv2.circle(overlay, (px, py), dot_max + 1, color, -1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)


def _draw_hawkeye_line_trail(frame, pts, color):
    """鹰眼球员：细实线轨迹 + 当前位置圆点（参考 GIF 非点状）。"""
    if not pts:
        return
    if len(pts) == 1:
        cv2.circle(frame, pts[0], 4, color, -1, cv2.LINE_AA)
        return
    total = len(pts)
    for i in range(1, total):
        t = i / total
        seg_color = _blend_color_bgr(color, 0.18 + 0.82 * t)
        cv2.line(frame, pts[i - 1], pts[i], seg_color, 2, cv2.LINE_AA)
    cv2.circle(frame, pts[-1], 4, color, -1, cv2.LINE_AA)
    cv2.circle(frame, pts[-1], 5, _blend_color_bgr(color, 0.35), 1, cv2.LINE_AA)


def _draw_trajectories(frame, smooth_trails, slot_map=None, frame_scale=1.0):
    """仅绘制已分半场的球员尾迹，避免未分配 track 的杂色涂抹。"""
    for tid, trail in smooth_trails.items():
        hist = trail.hist
        if not hist:
            continue
        if not slot_map or tid not in slot_map:
            continue
        color = _slot_color(slot_map[tid])
        _draw_player_foot_trail(frame, hist, color, frame_scale=frame_scale)


def _draw_shuttle_trail(frame, shuttle_trail, frame_scale=1.0):
    _draw_shuttle_flight_trail(frame, shuttle_trail.hist, frame_scale=frame_scale)


def _draw_hawkeye_minimap(frame, court_smooth_trails, shuttle_court=None, shuttle_trail_hist=None,
                          margin=16, lang="zh", rally_no=0):
    """右侧「MOVEMENT / 移动鹰眼」：约 18% 屏宽、偏高卡片，对齐截图样式。"""
    from PIL import Image, ImageDraw
    fh, fw = frame.shape[:2]
    # 截图比例：右侧约 18% 宽，总高约 72% 屏高
    panel_w = max(200, min(280, int(fw * 0.185)))
    header_h = max(52, int(fh * 0.07))
    legend_h = 22
    panel_h = max(int(fh * 0.68), int(panel_w * COURT_L_M / COURT_W_M * 0.92) + header_h + legend_h)
    panel_h = min(panel_h, fh - margin * 2)
    court_h = panel_h - header_h - legend_h
    ideal_w = int(court_h * COURT_W_M / COURT_L_M)
    court_inner_w = min(panel_w - 20, max(ideal_w, int(panel_w * 0.72)))

    x0 = fw - panel_w - margin
    y0 = margin
    x1, y1 = x0 + panel_w - 1, y0 + panel_h - 1

    line_c = (78, 88, 102)
    bg = (11, 16, 28)
    header_bg = (14, 20, 34)

    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (x1, y1), bg, -1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.90, frame, 0.10, 0, frame)
    cv2.rectangle(frame, (x0, y0), (x1, y0 + header_h), header_bg, -1, cv2.LINE_AA)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (40, 48, 62), 1, cv2.LINE_AA)

    cx0 = x0 + (panel_w - court_inner_w) // 2
    cy0 = y0 + header_h + 8
    cx1 = cx0 + court_inner_w - 1
    cy1 = cy0 + court_h - 16
    cv2.rectangle(frame, (cx0, cy0), (cx1, cy1), line_c, 1, cv2.LINE_AA)
    mid_y = (cy0 + cy1) // 2
    cv2.line(frame, (cx0, mid_y), (cx1, mid_y), (70, 80, 95), 1, cv2.LINE_AA)
    svc1 = cy0 + (cy1 - cy0) // 4
    svc2 = cy1 - (cy1 - cy0) // 4
    cv2.line(frame, (cx0, svc1), (cx1, svc1), line_c, 1, cv2.LINE_AA)
    cv2.line(frame, (cx0, svc2), (cx1, svc2), line_c, 1, cv2.LINE_AA)
    mid_x = (cx0 + cx1) // 2
    cv2.line(frame, (mid_x, cy0), (mid_x, cy1), line_c, 1, cv2.LINE_AA)

    inner_w, inner_h = max(1, cx1 - cx0), max(1, cy1 - cy0)

    def _court_to_panel(cx_m, cy_m):
        px = cx0 + int(float(cx_m) / COURT_W_M * inner_w)
        py = cy0 + int(float(cy_m) / COURT_L_M * inner_h)
        return max(cx0, min(cx1, px)), max(cy0, min(cy1, py))

    for slot in sorted(court_smooth_trails.keys()):
        trail = court_smooth_trails[slot]
        hist = trail.hist
        if not hist:
            continue
        color = _slot_color(slot)
        pts = [_court_to_panel(cx, cy) for cx, cy in hist]
        if len(pts) >= 2:
            for i in range(1, len(pts)):
                t = i / (len(pts) - 1)
                c = _blend_color_bgr(color, 0.25 + 0.75 * t)
                thick = max(2, int(2 + 2.2 * t))
                cv2.line(frame, pts[i - 1], pts[i], _blend_color_bgr(color, 0.22), thick + 3, cv2.LINE_AA)
                cv2.line(frame, pts[i - 1], pts[i], c, thick, cv2.LINE_AA)
        lx, ly = pts[-1]
        cv2.circle(frame, (lx, ly), 7, color, -1, cv2.LINE_AA)
        cv2.circle(frame, (lx, ly), 4, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, (lx, ly), 8, color, 1, cv2.LINE_AA)

    if shuttle_court is not None:
        if shuttle_trail_hist and len(shuttle_trail_hist) > 1:
            spts = [_court_to_panel(cx, cy) for cx, cy in shuttle_trail_hist]
            for i in range(1, len(spts)):
                t = i / len(spts)
                c = _blend_color_bgr((0, 255, 255), 0.25 + 0.75 * t)
                cv2.line(frame, spts[i - 1], spts[i], c, 1, cv2.LINE_AA)
        sx, sy = _court_to_panel(shuttle_court[0], shuttle_court[1])
        cv2.circle(frame, (sx, sy), 4, (0, 255, 255), -1, cv2.LINE_AA)

    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
    draw = ImageDraw.Draw(pil)
    font_en = _get_overlay_font(max(11, panel_w // 16))
    font_zh = _get_overlay_font(max(15, panel_w // 12))
    font_sub = _get_overlay_font(10)
    font_pill = _get_overlay_font(9)
    t = _hud_palette(lang)

    draw.text((x0 + 14, y0 + 8), "MOVEMENT", font=font_en, fill=(255, 220, 60))
    draw.text((x0 + 14, y0 + 26), t["hawkeye_zh"], font=font_zh, fill=(245, 248, 252))
    draw.text((x1 - 14, y0 + 18), "TOP VIEW", font=font_sub, fill=(200, 210, 220), anchor="ra")
    draw.line((x0 + 12, y0 + header_h - 2, x1 - 12, y0 + header_h - 2), fill=(45, 55, 70, 200), width=1)

    rally_txt = f"RALLY {int(rally_no or 0):02d}"
    rx, ry = cx0 + 6, cy0 + 6
    tw = max(58, len(rally_txt) * 7)
    draw.rounded_rectangle((rx, ry, rx + tw, ry + 16), radius=8, fill=(28, 34, 48, 220))
    draw.text((rx + 8, ry + 2), rally_txt, font=font_pill, fill=(170, 180, 195))

    ly = y1 - legend_h + 4
    c0 = tuple(reversed(_SLOT_COLORS_BGR[0]))
    c1 = tuple(reversed(_SLOT_COLORS_BGR[1]))
    draw.ellipse((x0 + 14, ly, x0 + 22, ly + 8), fill=c0)
    draw.text((x0 + 26, ly - 1), "P1", font=font_sub, fill=(210, 218, 228))
    draw.ellipse((x0 + 56, ly, x0 + 64, ly + 8), fill=c1)
    draw.text((x0 + 68, ly - 1), "P2", font=font_sub, fill=(210, 218, 228))

    frame[:] = cv2.cvtColor(np.asarray(pil.convert("RGB")), cv2.COLOR_RGB2BGR)


def _hud_palette(lang):
    """HUD 文案与配色 token（对齐截图）。"""
    if lang == "zh":
        return {
            "far_title": "上场 P1",
            "near_title": "下场 P2",
            "rally_label": "当前回合",
            "section_rally": "本回合",
            "lbl_speed_live": "实时速度",
            "lbl_dist": "移动距离",
            "lbl_avg": "平均速度",
            "lbl_max": "峰值速度",
            "unit_speed": "m/s",
            "unit_dist": "m",
            "hawkeye": "HAWK-EYE",
            "hawkeye_zh": "移动鹰眼",
            "live": "LIVE",
        }
    return {
        "far_title": "FAR P1",
        "near_title": "NEAR P2",
        "rally_label": "RALLY",
        "section_rally": "RALLY",
        "lbl_speed_live": "SPEED",
        "lbl_dist": "Distance",
        "lbl_avg": "Avg Speed",
        "lbl_max": "Peak Speed",
        "unit_speed": "m/s",
        "unit_dist": "m",
        "hawkeye": "HAWK-EYE",
        "hawkeye_zh": "Hawk-Eye",
        "live": "LIVE",
    }


def _clamp_hud_speed(v, lo=0.0, hi=12.0):
    """显示用速度钳制，抑制追踪跳变产生的离谱峰值。"""
    try:
        x = float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(lo, min(hi, x))


def _rounded_rect(draw, box, fill, radius=8, outline=None, width=1):
    """简易圆角矩形（PIL）。"""
    r = max(1, int(radius))
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def _draw_speed_sparkline(draw, box, values, color, max_v=12.0):
    """右侧迷你柱状速度历史（截图中的 sparkline）。"""
    x0, y0, x1, y1 = box
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)
    bars = list(values or [])[-12:]
    if not bars:
        bars = [0.0] * 8
    while len(bars) < 8:
        bars.insert(0, 0.0)
    n = len(bars)
    gap = 2
    bw = max(2, (w - gap * (n - 1)) // n)
    for i, v in enumerate(bars):
        t = min(1.0, float(v) / max_v) if max_v > 0 else 0
        bh = max(2, int(h * (0.12 + 0.88 * t)))
        bx = x0 + i * (bw + gap)
        by = y1 - bh
        alpha = int(90 + 140 * t)
        draw.rectangle((bx, by, bx + bw - 1, y1), fill=(*color[:3], alpha))


def _draw_hud_player_block(draw, panel_w, start_y, slot, player, lang, fonts, margin=10):
    """截图样式球员卡：圆点标题 + LIVE + 大号实时速度 + sparkline + 本回合三行。"""
    t = _hud_palette(lang)
    font_title, font_label, font_value, font_section, font_unit, font_speed = fonts
    title = t["far_title"] if slot == 0 else t["near_title"]
    accent = (255, 214, 64) if slot == 0 else (255, 70, 200)
    card_bg = (14, 18, 28, 210)
    x0, x1 = margin, panel_w - margin

    header_h = 28
    speed_block_h = 52
    rally_header_h = 22
    row_h = 20
    pad_bot = 12
    content_h = header_h + speed_block_h + rally_header_h + row_h * 3 + pad_bot

    y0 = start_y
    y1 = start_y + content_h
    _rounded_rect(draw, (x0, y0, x1, y1), fill=card_bg, radius=16,
                  outline=(48, 56, 72, 120), width=1)
    draw.rectangle((x0, y0 + 14, x0 + 3, y1 - 14), fill=accent)

    draw.ellipse((x0 + 12, y0 + 10, x0 + 20, y0 + 18), fill=accent)
    draw.text((x0 + 26, y0 + 6), title, font=font_title, fill=(245, 248, 252))
    live_x = x1 - 12
    draw.text((live_x, y0 + 8), t["live"], font=font_section, fill=(130, 145, 165), anchor="ra")
    draw.ellipse((live_x - 42, y0 + 11, live_x - 36, y0 + 17), outline=(120, 135, 155), width=1)
    draw.ellipse((live_x - 40, y0 + 13, live_x - 38, y0 + 15), fill=accent)
    draw.line((x0 + 12, y0 + header_h - 2, x1 - 12, y0 + header_h - 2), fill=(42, 50, 64, 180), width=1)

    spd = _clamp_hud_speed(player.get("current_speed"))
    sy = y0 + header_h + 4
    draw.text((x0 + 12, sy), t["lbl_speed_live"], font=font_section, fill=(120, 135, 155))
    draw.text((x0 + 12, sy + 14), f"{spd:.2f}", font=font_speed, fill=(250, 252, 255))
    num_bbox = draw.textbbox((x0 + 12, sy + 14), f"{spd:.2f}", font=font_speed)
    draw.text((num_bbox[2] + 6, sy + 26), t["unit_speed"], font=font_unit, fill=(150, 160, 175))
    spark_w = max(48, int((x1 - x0) * 0.28))
    _draw_speed_sparkline(
        draw,
        (x1 - 12 - spark_w, sy + 12, x1 - 12, sy + 44),
        player.get("speed_hist") or [],
        accent,
    )

    ry = y0 + header_h + speed_block_h
    draw.line((x0 + 12, ry - 2, x1 - 12, ry - 2), fill=(42, 50, 64, 160), width=1)
    draw.ellipse((x0 + 12, ry + 4, x0 + 20, ry + 12), outline=accent, width=1)
    draw.text((x0 + 26, ry + 1), t["section_rally"], font=font_section, fill=(200, 210, 220))

    rows = [
        (t["lbl_dist"], f"{float(player.get('rally_dist') or 0):.2f}", t["unit_dist"]),
        (t["lbl_avg"], f"{_clamp_hud_speed(player.get('rally_avg')):.2f}", t["unit_speed"]),
        (t["lbl_max"], f"{_clamp_hud_speed(player.get('max_speed_rally')):.2f}", t["unit_speed"]),
    ]
    y = ry + rally_header_h
    for label, value, unit in rows:
        draw.text((x0 + 12, y), label, font=font_label, fill=(145, 158, 172))
        draw.text((x1 - 12, y), f"{value} {unit}", font=font_value, fill=(240, 246, 252), anchor="ra")
        y += row_h
    return y1 + 10


def _draw_rally_badge(draw, panel_w, y, rally_no, lang, fonts, margin=10):
    """当前回合条：左文案 + 右侧大号两位序号。"""
    t = _hud_palette(lang)
    font_section = fonts[3]
    font_big = _get_overlay_font(26)
    x0, x1 = margin, panel_w - margin
    badge_h = 40
    _rounded_rect(draw, (x0, y, x1, y + badge_h), fill=(14, 18, 28, 215), radius=14,
                  outline=(48, 56, 72, 120), width=1)
    draw.text((x0 + 14, y + 11), t["rally_label"], font=font_section, fill=(150, 162, 178))
    draw.text((x1 - 14, y + 4), f"{int(rally_no or 0):02d}", font=font_big,
              fill=(250, 252, 255), anchor="ra")
    return y + badge_h + 10


def _overlay_match_hud(frame, hud, court_smooth_trails, shuttle_court=None, shuttle_trail_hist=None, lang="zh"):
    """左侧约 15% 宽统计卡片栈 + 右侧约 18% 宽移动鹰眼（对齐截图比例与样式）。"""
    from PIL import Image, ImageDraw
    fh, fw = frame.shape[:2]
    panel_w = max(210, min(268, int(fw * 0.155)))
    margin = max(10, int(fw * 0.01))

    scale = max(0.85, min(1.2, fw / 1280.0))
    font_title = _get_overlay_font(int(14 * scale))
    font_label = _get_overlay_font(int(11 * scale))
    font_value = _get_overlay_font(int(12 * scale))
    font_section = _get_overlay_font(int(11 * scale))
    font_unit = _get_overlay_font(int(10 * scale))
    font_speed = _get_overlay_font(int(28 * scale))
    fonts = (font_title, font_label, font_value, font_section, font_unit, font_speed)

    players_by_slot = {p["slot"]: p for p in hud.get("players", []) if "slot" in p}

    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
    layer = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    y = max(12, int(fh * 0.02))
    y = _draw_hud_player_block(
        draw, panel_w, y, 0,
        players_by_slot.get(0) or _empty_hud_player(0),
        lang, fonts, margin=margin,
    )
    y = _draw_rally_badge(draw, panel_w, y, hud.get("rally", 0), lang, fonts, margin=margin)
    _draw_hud_player_block(
        draw, panel_w, y, 1,
        players_by_slot.get(1) or _empty_hud_player(1),
        lang, fonts, margin=margin,
    )

    pil = Image.alpha_composite(pil, layer)
    frame[:] = cv2.cvtColor(np.asarray(pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    _draw_hawkeye_minimap(
        frame, court_smooth_trails,
        shuttle_court=shuttle_court,
        shuttle_trail_hist=shuttle_trail_hist,
        lang=lang,
        rally_no=hud.get("rally", 0),
        margin=margin,
    )



def _make_heatmap(court_positions, out_path, size=(260, 670)):
    """球员球场坐标热力图（无 matplotlib 依赖）。

    size=(宽W, 高H)，与散点图一致；NumPy/OpenCV 画布为 (H, W)。
    """
    w, h = int(size[0]), int(size[1])
    heat = np.zeros((h, w), dtype=np.float32)
    for x, y in court_positions:
        ix = int(x / COURT_W_M * (w - 1))
        iy = int(y / COURT_L_M * (h - 1))
        if 0 <= ix < w and 0 <= iy < h:
            cv2.circle(heat, (ix, iy), 8, 1.0, -1)
    if heat.max() > 0:
        heat = cv2.GaussianBlur(heat, (0, 0), 12)
        heat = heat / (heat.max() + 1e-6)
    colored = cv2.applyColorMap((heat * 255).astype(np.uint8), cv2.COLORMAP_JET)
    cv2.rectangle(colored, (0, 0), (w - 1, h - 1), (200, 200, 200), 1)
    cv2.imwrite(out_path, colored)


def _make_scatter(court_positions, out_path, size=(260, 670)):
    canvas = np.full((size[1], size[0], 3), 245, dtype=np.uint8)
    cv2.rectangle(canvas, (0, 0), (size[0] - 1, size[1] - 1), (180, 180, 180), 1)
    for x, y in court_positions:
        ix = int(x / COURT_W_M * (size[0] - 1))
        iy = int(y / COURT_L_M * (size[1] - 1))
        cv2.circle(canvas, (ix, iy), 2, (50, 100, 220), -1, cv2.LINE_AA)
    cv2.imwrite(out_path, canvas)


def extract_video_frame(video_path, frame_index=0, auto_detect_court=False):
    """提取视频指定帧为 JPEG base64；可选自动球场四角检测。"""
    import base64
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频")
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise ValueError("无法读取视频帧")
    h, w = frame.shape[:2]
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise ValueError("帧编码失败")
    result = {
        "imageBase64": base64.b64encode(buf.tobytes()).decode(),
        "width": int(w),
        "height": int(h),
    }
    if auto_detect_court:
        from services.court_detector import detect_court_from_frame
        result.update(detect_court_from_frame(frame))
    return result


def _infer_pose_yolo(pose_model, frame, conf, court_poly):
    """Ultralytics YOLO Pose -> (persons_kp, centroids)。"""
    persons = []
    centroids = []
    pr = pose_model.predict(frame, conf=conf, verbose=False)[0]
    if pr.keypoints is not None and pr.keypoints.data is not None:
        for kp_t in pr.keypoints.data.cpu().tolist():
            kp = [[float(x), float(y), float(c)] for x, y, c in kp_t]
            cxy = _foot_position_from_keypoints(kp)
            if cxy is None:
                cxy = _person_bbox_from_keypoints(kp)
            if cxy is None:
                continue
            if not _in_court_polygon(cxy[0], cxy[1], court_poly):
                continue
            persons.append(kp)
            centroids.append(cxy)
    return persons, centroids


def _infer_pose_rtmlib(rtmlib_model, frame, conf, court_poly, model_key):
    """rtmlib（RTMO/RTMPose/DWPose）-> (persons_kp, centroids)，取 COCO-17 body。"""
    from inference import infer_pose_rtmlib_frame
    persons = []
    centroids = []
    for kp in infer_pose_rtmlib_frame(frame, rtmlib_model, model_key, conf=conf):
        cxy = _foot_position_from_keypoints(kp)
        if cxy is None:
            cxy = _person_bbox_from_keypoints(kp)
        if cxy is None:
            continue
        if not _in_court_polygon(cxy[0], cxy[1], court_poly):
            continue
        persons.append(kp)
        centroids.append(cxy)
    return persons, centroids


def analyze_badminton_video(
    pose_model_path,
    src_path,
    out_dir,
    court_points,
    ball_model_path=None,
    conf=0.25,
    ball_conf=None,
    pose_library="ultralytics",
    model_key="",
    show_skeleton=True,
    show_trajectories=True,
    show_shuttle=True,
    show_stats=True,
    show_court=True,
    language="zh",
    net_points=None,
    progress_cb=None,
):
    """羽毛球视频逐帧分析。

    Returns:
        dict: stats + output files relative names
    """
    from inference import _get_model, _get_rtmlib_solver, _open_h264, _write_bgr

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    lib = (pose_library or "ultralytics").lower()
    pose_solver = None
    pose_model = None
    if lib == "rtmlib":
        pose_solver = _get_rtmlib_solver(model_key or "rtmo-s", pose_model_path)
    else:
        pose_model = _get_model(pose_model_path)
    ball_model = _get_model(ball_model_path) if ball_model_path else None

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    img_pts = _parse_court_points(court_points, w, h)
    net_pts = _parse_net_points(net_points, w, h, img_pts)
    H = _court_homography(img_pts)
    court_poly = img_pts.reshape((-1, 1, 2))
    # 网线球场纵向坐标（用于半场 slot 分配）
    _net_court = [_to_court_xy(float(p[0]), float(p[1]), H) for p in net_pts]
    net_y_m = (
        sum(p[1] for p in _net_court) / len(_net_court)
        if _net_court else (COURT_L_M * 0.5)
    )

    out_video = out_dir / "analyze_output.mp4"
    jsonl_path = out_dir / "detections.jsonl"
    meta_path = out_dir / "metadata.json"
    heatmap_path = out_dir / "heatmap.png"
    scatter_path = out_dir / "scatter.png"

    writer, ew, eh = _open_h264(str(out_video), fps, w, h)
    frame_scale = max(w, h) / 1280.0
    jump_px = max(55, int(75 * frame_scale))
    court_jump_m = max(1.2, 2.0 * frame_scale)
    # 主画面短彗星尾（约 0.9s）；鹰眼可稍长；羽毛球单次飞行约 1.2s
    player_trail_cap = min(36, max(20, int(fps * 0.9)))
    shuttle_trail_cap = min(56, max(24, int(fps * 1.2)))
    hawkeye_trail_cap = min(160, max(60, int(fps * 4.5)))
    trail_miss_limit = max(6, int(fps * 0.25))

    tracks = {}
    img_smooth = {}
    court_smooth = {}
    player_states = defaultdict(_default_player_state)
    court_positions = []
    court_pos_by_tid = defaultdict(list)
    shuttle_court_list = []
    shuttle_track = []
    rally_lengths = []
    current_rally_frames = 0
    shuttle_smooth = _SmoothTrail(
        alpha=0.55, max_hist=shuttle_trail_cap, max_jump=jump_px * 2.0, min_step=0.18)
    shuttle_court_smooth = _SmoothTrail(
        alpha=0.55, max_hist=shuttle_trail_cap, max_jump=court_jump_m * 3.0,
        min_step=0.008, integer_coords=False)
    shuttle_frames = 0
    rally = _RallyTracker(fps)
    player_speeds = defaultdict(float)
    player_dist = defaultdict(float)
    last_court_pos = {}
    slot_map = {}
    slot_hud_cache = {0: _empty_hud_player(0), 1: _empty_hud_player(1)}
    slot_owner = {0: None, 1: None}
    slot_speed_hist = {0: [], 1: []}
    frames = 0
    total_persons = 0

    jl_f = open(jsonl_path, "w", encoding="utf-8")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames += 1
            vis = frame.copy()

            # 姿态
            if lib == "rtmlib":
                persons, centroids = _infer_pose_rtmlib(
                    pose_solver, frame, conf, court_poly, model_key or "rtmo-s")
            else:
                persons, centroids = _infer_pose_yolo(pose_model, frame, conf, court_poly)

            total_persons += len(persons)
            tracks = _match_tracks(centroids, tracks)
            # 每帧瞬时速度先清零，有位移再写入（避免缺帧残留）
            for st in player_states.values():
                st["current_speed"] = 0.0
            frame_players = []

            for tid, (cx, cy) in tracks.items():
                if tid not in img_smooth:
                    img_smooth[tid] = _SmoothTrail(
                        alpha=0.48, max_hist=player_trail_cap, max_jump=jump_px,
                        min_step=max(2.2, 2.8 * frame_scale), densify=False)
                if tid not in court_smooth:
                    court_smooth[tid] = _SmoothTrail(
                        alpha=0.42, max_hist=hawkeye_trail_cap, max_jump=court_jump_m,
                        min_step=0.012, integer_coords=False, densify=False)

                img_smooth[tid].push(cx, cy)
                cx_m, cy_m = _to_court_xy(cx, cy, H)
                court_smooth[tid].push(cx_m, cy_m)
                court_positions.append((cx_m, cy_m))
                court_pos_by_tid[tid].append((cx_m, cy_m))
                frame_players.append({
                    "id": tid,
                    "image": [round(cx, 1), round(cy, 1)],
                    "court": [round(cx_m, 3), round(cy_m, 3)],
                })
                st = player_states[tid]
                st["active_frames"] += 1
                if rally.active:
                    st["rally_frames"] += 1
                if tid in last_court_pos and fps > 0:
                    lx, ly = last_court_pos[tid]
                    dist = math.hypot(cx_m - lx, cy_m - ly)
                    if dist > 0.01:
                        speed = dist * fps
                        st["current_speed"] = speed
                        st["total_dist"] += dist
                        st["rally_dist"] += dist
                        st["max_speed_total"] = max(st["max_speed_total"], speed)
                        st["max_speed_rally"] = max(st["max_speed_rally"], speed)
                        player_dist[tid] += dist
                        player_speeds[tid] = max(player_speeds[tid], speed)
                last_court_pos[tid] = (cx_m, cy_m)

            slot_map = _assign_player_slots(
                tracks, last_court_pos, net_y_m=net_y_m, prev_slot_map=slot_map)
            # 失检 / 换 ID：主画面与鹰眼尾迹实时衰减清除，避免永久涂抹
            _prune_player_trails(img_smooth, court_smooth, tracks.keys(), max_miss=trail_miss_limit)

            # 羽毛球（专用检测：小目标阈值、扩边球场、时序关联）
            shuttle_xy = None
            shuttle_court_pos = None
            if ball_model is not None:
                bc = ball_conf if ball_conf is not None else max(0.12, min(0.25, float(conf) * 0.7))
                prev = shuttle_smooth.pos
                hit = _detect_shuttlecock(
                    ball_model,
                    frame,
                    court_poly,
                    conf=bc,
                    prev_xy=prev,
                    max_jump=max(80.0, jump_px * 3.5),
                    imgsz=960,
                )
                if hit is not None:
                    shuttle_xy = (hit[0], hit[1])
                    shuttle_frames += 1
                    shuttle_smooth.push(hit[0], hit[1])
                    scx, scy = _to_court_xy(hit[0], hit[1], H)
                    shuttle_court_smooth.push(scx, scy)
                    shuttle_court_pos = shuttle_court_smooth.pos
                    shuttle_court_list.append((scx, scy))
                    shuttle_track.append({
                        "frame": frames,
                        "ix": float(hit[0]),
                        "iy": float(hit[1]),
                        "x": float(scx),
                        "y": float(scy),
                    })

            if shuttle_xy:
                rally.on_ball()
                current_rally_frames = rally.cur_frames
            else:
                clear_trail, rally_ended = rally.on_miss()
                # 羽毛球：失检短暂后清空尾迹（单次飞行弧迹）；回合结束用更长死球阈值
                if clear_trail:
                    shuttle_smooth.reset()
                    shuttle_court_smooth.reset()
                if rally_ended:
                    current_rally_frames = 0
                    for st in player_states.values():
                        st["rally_dist"] = 0.0
                        st["max_speed_rally"] = 0.0
                        st["rally_frames"] = 0
                    # 回合结束：主画面脚印尾迹清空，鹰眼保留短历史供下一拍衔接
                    for tr in img_smooth.values():
                        tr.reset()
                    for tr in court_smooth.values():
                        tr.decay(drop=max(4, len(tr.hist) // 2) if tr.hist else 1)
                else:
                    current_rally_frames = rally.cur_frames if rally.active else 0

            rally_id = rally.display_id
            rally_active = rally.active

            # 绘制
            if show_court:
                _draw_court(vis, img_pts, net_pts=net_pts)
            if show_skeleton:
                for i, kp in enumerate(persons):
                    fxy = _foot_position_from_keypoints(kp) or _person_bbox_from_keypoints(kp)
                    color = _PLAYER_COLORS[i % len(_PLAYER_COLORS)]
                    if fxy:
                        best_tid, best_d = None, 50.0
                        for t, (tx, ty) in tracks.items():
                            d = math.hypot(fxy[0] - tx, fxy[1] - ty)
                            if d < best_d:
                                best_d, best_tid = d, t
                        if best_tid is not None and best_tid in slot_map:
                            color = _slot_color(slot_map[best_tid])
                    _draw_skeleton(vis, kp, color)
            if show_trajectories:
                _draw_trajectories(vis, img_smooth, slot_map=slot_map, frame_scale=frame_scale)
            if show_shuttle and shuttle_smooth.hist:
                _draw_shuttle_trail(vis, shuttle_smooth, frame_scale=frame_scale)
            if show_shuttle and shuttle_xy:
                _draw_shuttle_marker(vis, shuttle_xy, frame_scale=frame_scale)
            if show_stats:
                # 按半场更新 HUD 缓存：标签固定，数值随帧变化；缺检时速度归零、累计保留
                active_slots = set()
                for tid, slot in slot_map.items():
                    if slot not in (0, 1):
                        continue
                    st = player_states[tid]
                    slot_owner[slot] = tid
                    active_slots.add(slot)
                    slot_hud_cache[slot] = {
                        "slot": slot,
                        "tid": tid,
                        "current_speed": st["current_speed"],
                        "rally_dist": st["rally_dist"],
                        "rally_avg": _avg_speed(st["rally_dist"], st["rally_frames"], fps),
                        "max_speed_rally": st["max_speed_rally"],
                        "total_dist": st["total_dist"],
                        "total_avg": _avg_speed(st["total_dist"], st["active_frames"], fps),
                        "max_speed_total": st["max_speed_total"],
                        "speed_hist": list(slot_speed_hist[slot]),
                    }
                for slot in (0, 1):
                    # 每帧更新 sparkline（缺检写 0）
                    if slot in active_slots:
                        spd_now = float(slot_hud_cache[slot].get("current_speed") or 0.0)
                    else:
                        spd_now = 0.0
                        tid = slot_owner[slot]
                        if tid is not None and tid in player_states:
                            st = player_states[tid]
                            slot_hud_cache[slot] = {
                                "slot": slot,
                                "tid": tid,
                                "current_speed": 0.0,
                                "rally_dist": st["rally_dist"],
                                "rally_avg": _avg_speed(st["rally_dist"], st["rally_frames"], fps),
                                "max_speed_rally": st["max_speed_rally"],
                                "total_dist": st["total_dist"],
                                "total_avg": _avg_speed(st["total_dist"], st["active_frames"], fps),
                                "max_speed_total": st["max_speed_total"],
                                "speed_hist": [],
                            }
                        else:
                            slot_hud_cache[slot]["current_speed"] = 0.0
                    hist = slot_speed_hist[slot]
                    hist.append(_clamp_hud_speed(spd_now))
                    if len(hist) > 24:
                        del hist[:-24]
                    slot_hud_cache[slot]["speed_hist"] = list(hist)

                hud_players = [slot_hud_cache[0], slot_hud_cache[1]]
                court_smooth_by_slot = {
                    slot: court_smooth[tid]
                    for tid, slot in slot_map.items() if tid in court_smooth and slot in (0, 1)
                }
                # 缺检半场仍保留上次鹰眼轨迹（若有 owner）
                for slot in (0, 1):
                    if slot in court_smooth_by_slot:
                        continue
                    tid = slot_owner[slot]
                    if tid is not None and tid in court_smooth:
                        court_smooth_by_slot[slot] = court_smooth[tid]

                _overlay_match_hud(vis, {"rally": rally_id, "players": hud_players},
                                   court_smooth_by_slot,
                                   shuttle_court=shuttle_court_pos,
                                   shuttle_trail_hist=shuttle_court_smooth.hist if shuttle_court_pos else None,
                                   lang=language)

            _write_bgr(writer, vis, ew, eh)

            rec = {
                "frame": frames,
                "rally": rally_id,
                "players": frame_players,
                "shuttle": {"image": [float(shuttle_xy[0]), float(shuttle_xy[1])]} if shuttle_xy else None,
            }
            jl_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            if progress_cb:
                progress_cb(frames, total)
    finally:
        cap.release()
        writer.close()
        jl_f.close()

    rally.finalize()
    rally_lengths = list(rally.lengths)
    rally_id = rally.rally_count

    _make_heatmap(court_positions, str(heatmap_path))
    _make_scatter(court_positions, str(scatter_path))

    from services.badminton_report import build_match_report
    report = build_match_report(
        frames=frames,
        fps=float(fps),
        rally_count=rally_id,
        shuttle_frames=shuttle_frames,
        total_persons=total_persons,
        player_distances={k: float(v) for k, v in player_dist.items()},
        player_max_speed={k: float(v) for k, v in player_speeds.items()},
        player_states=player_states,
        court_pos_by_tid=dict(court_pos_by_tid),
        shuttle_court_list=shuttle_court_list,
        shuttle_track=shuttle_track,
        court_img_pts=img_pts.tolist() if hasattr(img_pts, "tolist") else img_pts,
        net_img_pts=net_pts.tolist() if hasattr(net_pts, "tolist") else net_pts,
        rally_lengths=rally_lengths,
        final_slot_map=dict(slot_map),
        source_name=os.path.basename(src_path),
        model_key=model_key or pose_library or "",
    )

    meta = {
        "createdAt": datetime.utcnow().isoformat() + "Z",
        "source": os.path.basename(src_path),
        "frames": frames,
        "fps": round(float(fps), 2),
        "width": w,
        "height": h,
        "courtPoints": court_points if isinstance(court_points, list) else json.loads(court_points),
        "netPoints": (
            [[round(float(p[0]) / w, 4), round(float(p[1]) / h, 4)] for p in net_pts]
            if w > 0 and h > 0 else None
        ),
        "totalPersons": total_persons,
        "shuttleDetections": shuttle_frames,
        "rallyCount": rally_id,
        "playerDistances": {str(k): round(float(v), 2) for k, v in player_dist.items()},
        "playerMaxSpeed": {str(k): round(float(v), 2) for k, v in player_speeds.items()},
        "report": report,
        "outputs": {
            "video": out_video.name,
            "detections": jsonl_path.name,
            "heatmap": heatmap_path.name,
            "scatter": scatter_path.name,
        },
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "frames": frames,
        "totalFrames": total,
        "fps": round(float(fps), 2),
        "width": ew,
        "height": eh,
        "rallyCount": rally_id,
        "shuttleDetections": shuttle_frames,
        "totalPersons": total_persons,
        "playerDistances": meta["playerDistances"],
        "playerMaxSpeed": meta["playerMaxSpeed"],
        "report": report,
        "outputVideo": out_video.name,
        "heatmap": heatmap_path.name,
        "scatter": scatter_path.name,
        "detections": jsonl_path.name,
        "metadata": meta_path.name,
    }
