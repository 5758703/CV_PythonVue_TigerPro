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


def _parse_court_points(raw, w, h):
    """解析球场四角 [[x,y]×4]，支持 0–1 归一化或像素坐标。"""
    if not raw:
        raise ValueError("请标注球场四个角点（左上→右上→右下→左下）")
    pts = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(pts, list) or len(pts) != 4:
        raise ValueError("球场角点须为 4 个点")
    out = []
    for p in pts:
        x, y = float(p[0]), float(p[1])
        if 0 <= x <= 1 and 0 <= y <= 1:
            x, y = x * w, y * h
        out.append([x, y])
    return np.float32(out)


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


def _draw_court(frame, img_pts):
    pts = img_pts.astype(np.int32).reshape((-1, 1, 2))
    cv2.polylines(frame, [pts], True, (0, 220, 0), 2, cv2.LINE_AA)
    labels = ["TL", "TR", "BR", "BL"]
    for i, (x, y) in enumerate(img_pts):
        cv2.circle(frame, (int(x), int(y)), 5, (0, 255, 0), -1, cv2.LINE_AA)
        cv2.putText(frame, labels[i], (int(x) + 6, int(y) - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)


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


def _assign_player_slots(tracks, last_court_pos):
    """按球场纵向坐标排序：Y 小=上场(远端)，Y 大=下场(近端)。"""
    items = [(tid, last_court_pos[tid][1]) for tid in tracks if tid in last_court_pos]
    items.sort(key=lambda x: x[1])
    return {tid: i for i, (tid, _) in enumerate(items[:2])}


def _avg_speed(dist_m, frame_cnt, fps):
    if frame_cnt <= 0 or fps <= 0:
        return 0.0
    return dist_m / (frame_cnt / fps)


def _slot_color(slot):
    return _SLOT_COLORS_BGR[slot % len(_SLOT_COLORS_BGR)]


class _SmoothTrail:
    """轨迹平滑器：EMA + 帧间密插值，主画面圆点尾迹 / 鹰眼折线共用。"""

    __slots__ = ("alpha", "max_hist", "max_jump", "min_step", "pos", "hist", "integer_coords")

    def __init__(self, alpha=0.38, max_hist=36, max_jump=90.0, min_step=1.2, integer_coords=True):
        self.alpha = alpha
        self.max_hist = max_hist
        self.max_jump = max_jump
        self.min_step = min_step
        self.integer_coords = integer_coords
        self.pos = None
        self.hist = []

    def reset(self):
        self.pos = None
        self.hist = []

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

        # 密插值：慢速时圆点几乎相连，快速时仍保持弧线
        steps = max(2, min(14, int(jump / max(self.min_step * 0.22, 0.15)) + 1))
        for i in range(1, steps + 1):
            t = i / steps
            tx = ox + (x - ox) * t
            ty = oy + (y - oy) * t
            a = self.alpha
            self.pos = (self.pos[0] * (1 - a) + tx * a, self.pos[1] * (1 - a) + ty * a)
            self._commit(*self.pos, force=(i < steps))
        return self.hist[-1]


def _blend_color_bgr(color, factor):
    return tuple(int(c * factor) for c in color)


def _draw_player_foot_trail(frame, history, color, frame_scale=1.0):
    """主画面球员：纯渐变圆点尾迹（无连线），近大远小、近亮远暗。"""
    if not history:
        return
    n = len(history)
    dot_max = max(5, int(8 * frame_scale))
    for i, pt in enumerate(history):
        px, py = int(round(pt[0])), int(round(pt[1]))
        age = (i + 1) / n
        radius = max(2, int(2 + (dot_max - 2) * (age ** 0.55)))
        bright = 0.08 + 0.92 * (age ** 2.2)
        cv2.circle(frame, (px, py), radius, _blend_color_bgr(color, bright), -1, cv2.LINE_AA)
    px, py = int(round(history[-1][0])), int(round(history[-1][1]))
    cv2.circle(frame, (px, py), dot_max + 1, color, -1, cv2.LINE_AA)
    cv2.circle(frame, (px, py), dot_max + 3, _blend_color_bgr(color, 0.45), 1, cv2.LINE_AA)


def _draw_shuttle_flight_trail(frame, history, frame_scale=1.0):
    """主画面羽毛球：密集小黄点，单次飞行弧迹，由 reset 控制长度。"""
    if not history:
        return
    color = (0, 255, 255)
    n = len(history)
    dot_max = max(2, int(3 * frame_scale))
    for i, pt in enumerate(history):
        px, py = int(round(pt[0])), int(round(pt[1]))
        age = (i + 1) / n
        radius = max(1, int(1 + dot_max * (age ** 0.7)))
        bright = 0.15 + 0.85 * (age ** 1.6)
        cv2.circle(frame, (px, py), radius, _blend_color_bgr(color, bright), -1, cv2.LINE_AA)
    px, py = int(round(history[-1][0])), int(round(history[-1][1]))
    cv2.circle(frame, (px, py), dot_max + 1, color, -1, cv2.LINE_AA)


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
    for tid, trail in smooth_trails.items():
        hist = trail.hist
        if not hist:
            continue
        if slot_map and tid in slot_map:
            color = _slot_color(slot_map[tid])
        else:
            color = _PLAYER_COLORS[tid % len(_PLAYER_COLORS)]
        _draw_player_foot_trail(frame, hist, color, frame_scale=frame_scale)


def _draw_shuttle_trail(frame, shuttle_trail, frame_scale=1.0):
    _draw_shuttle_flight_trail(frame, shuttle_trail.hist, frame_scale=frame_scale)


def _draw_hawkeye_minimap(frame, court_smooth_trails, shuttle_court=None, shuttle_trail_hist=None,
                          margin=10, lang="zh"):
    """右上角鹰眼俯视图：标题栏 + 球场线 + 球员/羽毛球轨迹。"""
    fh, fw = frame.shape[:2]
    header_h = 24
    panel_w = max(128, int(fw * 0.12))
    court_h = int(panel_w * COURT_L_M / COURT_W_M)
    court_h = min(court_h, fh - margin * 2 - header_h)
    panel_w = int(court_h * COURT_W_M / COURT_L_M)
    total_h = court_h + header_h
    x0 = fw - panel_w - margin
    y0 = margin
    x1, y1 = x0 + panel_w - 1, y0 + total_h - 1

    accent = (255, 200, 0)  # BGR cyan
    dim = (55, 62, 72)
    bg = (12, 16, 24)

    cv2.rectangle(frame, (x0, y0), (x1, y1), bg, -1, cv2.LINE_AA)
    cv2.rectangle(frame, (x0, y0), (x1, y0 + header_h), (22, 28, 38), -1, cv2.LINE_AA)
    cv2.line(frame, (x0, y0 + header_h), (x1, y0 + header_h), accent, 1, cv2.LINE_AA)
    cv2.rectangle(frame, (x0, y0), (x1, y1), accent, 1, cv2.LINE_AA)

    br = 8
    for (cx, cy, dx, dy) in (
        (x0, y0, br, br), (x1, y0, -br, br), (x0, y1, br, -br), (x1, y1, -br, -br),
    ):
        cv2.line(frame, (cx, cy), (cx + dx, cy), accent, 1, cv2.LINE_AA)
        cv2.line(frame, (cx, cy), (cx, cy + dy), accent, 1, cv2.LINE_AA)

    pad = 5
    ix0, iy0 = x0 + pad, y0 + header_h + pad
    ix1, iy1 = x1 - pad, y1 - pad
    cv2.rectangle(frame, (ix0, iy0), (ix1, iy1), (35, 42, 52), 1, cv2.LINE_AA)
    mid_y = (iy0 + iy1) // 2
    cv2.line(frame, (ix0, mid_y), (ix1, mid_y), dim, 1, cv2.LINE_AA)
    service_y1 = iy0 + (iy1 - iy0) // 4
    service_y2 = iy1 - (iy1 - iy0) // 4
    cv2.line(frame, (ix0, service_y1), (ix1, service_y1), (40, 46, 56), 1, cv2.LINE_AA)
    cv2.line(frame, (ix0, service_y2), (ix1, service_y2), (40, 46, 56), 1, cv2.LINE_AA)
    cv2.line(frame, (ix0 + (ix1 - ix0) // 2, iy0), (ix0 + (ix1 - ix0) // 2, iy1), (40, 46, 56), 1, cv2.LINE_AA)

    inner_w, inner_h = ix1 - ix0, iy1 - iy0

    def _court_to_panel(cx_m, cy_m):
        px = ix0 + int(float(cx_m) / COURT_W_M * inner_w)
        py = iy0 + int(float(cy_m) / COURT_L_M * inner_h)
        return max(ix0, min(ix1, px)), max(iy0, min(iy1, py))

    for slot in sorted(court_smooth_trails.keys()):
        trail = court_smooth_trails[slot]
        hist = trail.hist
        if not hist:
            continue
        color = _slot_color(slot)
        pts = [_court_to_panel(cx, cy) for cx, cy in hist]
        _draw_hawkeye_line_trail(frame, pts, color)
        lx, ly = pts[-1]
        cv2.circle(frame, (lx, ly), 3, color, -1, cv2.LINE_AA)
        cv2.circle(frame, (lx, ly), 5, color, 1, cv2.LINE_AA)

    if shuttle_court is not None:
        if shuttle_trail_hist and len(shuttle_trail_hist) > 1:
            spts = [_court_to_panel(cx, cy) for cx, cy in shuttle_trail_hist]
            for i in range(1, len(spts)):
                t = i / len(spts)
                c = _blend_color_bgr((0, 255, 255), 0.2 + 0.8 * t)
                cv2.line(frame, spts[i - 1], spts[i], c, 1, cv2.LINE_AA)
        sx, sy = _court_to_panel(shuttle_court[0], shuttle_court[1])
        cv2.circle(frame, (sx, sy), 4, (0, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, (sx, sy), 6, (255, 255, 255), 1, cv2.LINE_AA)

    from PIL import Image, ImageDraw
    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    font_title = _get_overlay_font(max(11, panel_w // 12))
    font_sub = _get_overlay_font(9)
    title = _hud_palette(lang)["hawkeye"]
    draw.text((x0 + 8, y0 + 5), title, font=font_title, fill=(0, 210, 255))
    draw.text((x1 - 8, y0 + 7), "TOP", font=font_sub, fill=(100, 120, 140), anchor="ra")
    frame[:] = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def _hud_palette(lang):
    """HUD 文案与配色 token。"""
    if lang == "zh":
        return {
            "far_title": "上场球员",
            "near_title": "下场球员",
            "rally_label": "当前回合",
            "section_rally": "本回合",
            "section_match": "全场",
            "lbl_speed": "当前速度",
            "lbl_dist": "移动距离",
            "lbl_avg": "平均速度",
            "lbl_max": "最大速度",
            "lbl_total_dist": "总距离",
            "unit_speed": "m/s",
            "unit_dist": "m",
            "hawkeye": "HAWK-EYE",
        }
    return {
        "far_title": "FAR COURT",
        "near_title": "NEAR COURT",
        "rally_label": "RALLY",
        "section_rally": "RALLY",
        "section_match": "MATCH",
        "lbl_speed": "Speed",
        "lbl_dist": "Distance",
        "lbl_avg": "Avg Speed",
        "lbl_max": "Max Speed",
        "lbl_total_dist": "Total Dist",
        "unit_speed": "m/s",
        "unit_dist": "m",
        "hawkeye": "HAWK-EYE",
    }


def _hud_player_rows(st, lang):
    """返回 (section, label, value) 行；section 为 None 表示普通 KV 行。"""
    t = _hud_palette(lang)
    u, um = t["unit_speed"], t["unit_dist"]
    return [
        (None, t["lbl_speed"], f"{st['current_speed']:.2f} {u}"),
        ("rally", t["lbl_dist"], f"{st['rally_dist']:.2f} {um}"),
        ("rally", t["lbl_avg"], f"{st['rally_avg']:.2f} {u}"),
        ("rally", t["lbl_max"], f"{st['max_speed_rally']:.2f} {u}"),
        ("match", t["lbl_total_dist"], f"{st['total_dist']:.2f} {um}"),
        ("match", t["lbl_avg"], f"{st['total_avg']:.2f} {u}"),
        ("match", t["lbl_max"], f"{st['max_speed_total']:.2f} {u}"),
    ]


def _hud_section_title(section, lang):
    t = _hud_palette(lang)
    if section == "rally":
        return t["section_rally"]
    if section == "match":
        return t["section_match"]
    return None


def _draw_hud_player_block(draw, panel_w, start_y, slot, player, lang, fonts):
    """绘制单个球员统计块（固定标签宽）。"""
    t = _hud_palette(lang)
    font_title, font_label, font_value, font_section = fonts
    title = t["far_title"] if slot == 0 else t["near_title"]
    accent = (255, 220, 80) if slot == 0 else (255, 120, 200)

    bar_h = 28
    draw.rectangle((0, start_y, 3, start_y + bar_h), fill=accent)
    draw.text((14, start_y + 4), title, font=font_title, fill=accent)

    rows = _hud_player_rows(player, lang)
    value_x = panel_w - 14
    y = start_y + bar_h + 6
    last_section = None
    for section, label, value in rows:
        if section != last_section and section is not None:
            sec = _hud_section_title(section, lang)
            draw.text((16, y), sec, font=font_section, fill=(90, 160, 200))
            y += 20
            last_section = section
        draw.text((16, y), label, font=font_label, fill=(130, 145, 170))
        draw.text((value_x, y), value, font=font_value, fill=(235, 245, 255), anchor="ra")
        lb = draw.textbbox((16, y), label, font=font_label)
        vb = draw.textbbox((value_x, y), value, font=font_value, anchor="ra")
        y = max(lb[3], vb[3]) + 4
    return y + 10


def _overlay_match_hud(frame, hud, court_smooth_trails, shuttle_court=None, shuttle_trail_hist=None, lang="zh"):
    """左侧球员统计 HUD + 右上鹰眼（标签固定、数值右对齐）。"""
    from PIL import Image, ImageDraw
    fh, fw = frame.shape[:2]
    panel_w = max(268, min(310, int(fw * 0.24)))

    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
    layer = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    draw_bg = ImageDraw.Draw(layer)
    draw_bg.rectangle((0, 0, panel_w, fh), fill=(6, 10, 18, 210))
    draw_bg.rectangle((0, 0, 3, fh), fill=(0, 200, 255, 255))
    pil = Image.alpha_composite(pil, layer)
    draw = ImageDraw.Draw(pil)

    font_title = _get_overlay_font(16)
    font_label = _get_overlay_font(13)
    font_value = _get_overlay_font(13)
    font_section = _get_overlay_font(12)
    font_rally_l = _get_overlay_font(13)
    font_rally_v = _get_overlay_font(28)
    fonts = (font_title, font_label, font_value, font_section)

    t = _hud_palette(lang)
    players_by_slot = {p["slot"]: p for p in hud.get("players", [])}

    y_top = 12
    if 0 in players_by_slot:
        y_top = _draw_hud_player_block(draw, panel_w, y_top, 0, players_by_slot[0], lang, fonts)

    rally_mid = fh // 2
    draw.line((12, rally_mid - 28, panel_w - 12, rally_mid - 28), fill=(40, 55, 75), width=1)
    draw.text((16, rally_mid - 22), t["rally_label"], font=font_rally_l, fill=(130, 145, 170))
    rally_val = str(hud.get("rally", 0))
    draw.text((panel_w - 14, rally_mid - 8), rally_val, font=font_rally_v,
              fill=(255, 210, 60), anchor="ra")
    draw.line((12, rally_mid + 28, panel_w - 12, rally_mid + 28), fill=(40, 55, 75), width=1)

    y_bot = rally_mid + 36
    if 1 in players_by_slot:
        _draw_hud_player_block(draw, panel_w, y_bot, 1, players_by_slot[1], lang, fonts)

    frame[:] = cv2.cvtColor(np.asarray(pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    _draw_hawkeye_minimap(frame, court_smooth_trails, shuttle_court=shuttle_court,
                          shuttle_trail_hist=shuttle_trail_hist, lang=lang)


def _make_heatmap(court_positions, out_path, size=(260, 670)):
    """球员球场坐标热力图（无 matplotlib 依赖）。"""
    heat = np.zeros(size, dtype=np.float32)
    for x, y in court_positions:
        ix = int(x / COURT_W_M * (size[0] - 1))
        iy = int(y / COURT_L_M * (size[1] - 1))
        if 0 <= ix < size[0] and 0 <= iy < size[1]:
            cv2.circle(heat, (ix, iy), 8, 1.0, -1)
    if heat.max() > 0:
        heat = cv2.GaussianBlur(heat, (0, 0), 12)
        heat = heat / (heat.max() + 1e-6)
    colored = cv2.applyColorMap((heat * 255).astype(np.uint8), cv2.COLORMAP_JET)
    cv2.rectangle(colored, (0, 0), (size[0] - 1, size[1] - 1), (200, 200, 200), 1)
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


def _infer_pose_rtmo(rtmo_model, frame, conf, court_poly):
    """rtmlib RTMO -> (persons_kp, centroids)。"""
    from inference import infer_pose_rtmo
    persons = []
    centroids = []
    for kp in infer_pose_rtmo(frame, rtmo_model, conf=conf):
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
    pose_library="ultralytics",
    model_key="",
    show_skeleton=True,
    show_trajectories=True,
    show_shuttle=True,
    show_stats=True,
    show_court=True,
    language="zh",
    progress_cb=None,
):
    """羽毛球视频逐帧分析。

    Returns:
        dict: stats + output files relative names
    """
    from inference import _get_model, _get_rtmo_model, _open_h264, _write_bgr

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    lib = (pose_library or "ultralytics").lower()
    pose_rtmo = None
    pose_model = None
    if lib == "rtmlib":
        pose_rtmo = _get_rtmo_model(pose_model_path, model_key or "rtmo-s")
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
    H = _court_homography(img_pts)
    court_poly = img_pts.reshape((-1, 1, 2))

    out_video = out_dir / "analyze_output.mp4"
    jsonl_path = out_dir / "detections.jsonl"
    meta_path = out_dir / "metadata.json"
    heatmap_path = out_dir / "heatmap.png"
    scatter_path = out_dir / "scatter.png"

    writer, ew, eh = _open_h264(str(out_video), fps, w, h)
    frame_scale = max(w, h) / 1280.0
    jump_px = max(55, int(75 * frame_scale))
    court_jump_m = max(1.2, 2.0 * frame_scale)
    player_trail_cap = min(240, int(fps * 3.8 * 3.2))
    shuttle_trail_cap = min(200, int(fps * 1.4 * 4.0))
    hawkeye_trail_cap = min(140, int(fps * 2.8))

    tracks = {}
    img_smooth = {}
    court_smooth = {}
    player_states = defaultdict(_default_player_state)
    court_positions = []
    shuttle_smooth = _SmoothTrail(
        alpha=0.55, max_hist=shuttle_trail_cap, max_jump=jump_px * 2.0, min_step=0.18)
    shuttle_court_smooth = _SmoothTrail(
        alpha=0.55, max_hist=shuttle_trail_cap, max_jump=court_jump_m * 3.0,
        min_step=0.008, integer_coords=False)
    shuttle_frames = 0
    rally_id = 0
    rally_active = False
    no_shuttle_streak = 0
    player_speeds = defaultdict(float)
    player_dist = defaultdict(float)
    last_court_pos = {}
    slot_map = {}
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
                persons, centroids = _infer_pose_rtmo(pose_rtmo, frame, conf, court_poly)
            else:
                persons, centroids = _infer_pose_yolo(pose_model, frame, conf, court_poly)

            total_persons += len(persons)
            tracks = _match_tracks(centroids, tracks)
            frame_players = []

            for tid, (cx, cy) in tracks.items():
                if tid not in img_smooth:
                    img_smooth[tid] = _SmoothTrail(
                        alpha=0.34, max_hist=player_trail_cap, max_jump=jump_px,
                        min_step=0.18 * frame_scale)
                if tid not in court_smooth:
                    court_smooth[tid] = _SmoothTrail(
                        alpha=0.34, max_hist=hawkeye_trail_cap, max_jump=court_jump_m,
                        min_step=0.008, integer_coords=False)

                img_smooth[tid].push(cx, cy)
                cx_m, cy_m = _to_court_xy(cx, cy, H)
                court_smooth[tid].push(cx_m, cy_m)
                court_positions.append((cx_m, cy_m))
                frame_players.append({
                    "id": tid,
                    "image": [round(cx, 1), round(cy, 1)],
                    "court": [round(cx_m, 3), round(cy_m, 3)],
                })
                st = player_states[tid]
                st["active_frames"] += 1
                if rally_active:
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

            slot_map = _assign_player_slots(tracks, last_court_pos)

            # 羽毛球
            shuttle_xy = None
            shuttle_court_pos = None
            if ball_model is not None:
                br = ball_model.predict(frame, conf=conf, verbose=False)[0]
                if br.boxes is not None and len(br.boxes):
                    best = None
                    best_conf = 0
                    for box in br.boxes:
                        c = float(box.conf[0])
                        if c > best_conf:
                            xy = box.xyxy[0].cpu().tolist()
                            cx = (xy[0] + xy[2]) / 2
                            cy = (xy[1] + xy[3]) / 2
                            if _in_court_polygon(cx, cy, court_poly):
                                best_conf = c
                                best = (cx, cy)
                    if best:
                        shuttle_xy = best
                        shuttle_frames += 1
                        shuttle_smooth.push(best[0], best[1])
                        scx, scy = _to_court_xy(best[0], best[1], H)
                        shuttle_court_smooth.push(scx, scy)
                        shuttle_court_pos = shuttle_court_smooth.pos

            if shuttle_xy:
                no_shuttle_streak = 0
                if not rally_active:
                    rally_id += 1
                    rally_active = True
            else:
                no_shuttle_streak += 1
                # 羽毛球：失检短暂后清空尾迹（单次飞行弧迹，对齐 GIF）
                if no_shuttle_streak > max(2, int(fps * 0.22)):
                    shuttle_smooth.reset()
                    shuttle_court_smooth.reset()
                if rally_active and no_shuttle_streak > int(fps * 1.5):
                    rally_active = False
                    for st in player_states.values():
                        st["rally_dist"] = 0.0
                        st["max_speed_rally"] = 0.0
                        st["rally_frames"] = 0

            # 绘制
            if show_court:
                _draw_court(vis, img_pts)
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
            if show_stats:
                hud_players = []
                for tid, slot in sorted(slot_map.items(), key=lambda x: x[1]):
                    st = player_states[tid]
                    hud_players.append({
                        "slot": slot,
                        "tid": tid,
                        "current_speed": st["current_speed"],
                        "rally_dist": st["rally_dist"],
                        "rally_avg": _avg_speed(st["rally_dist"], st["rally_frames"], fps),
                        "max_speed_rally": st["max_speed_rally"],
                        "total_dist": st["total_dist"],
                        "total_avg": _avg_speed(st["total_dist"], st["active_frames"], fps),
                        "max_speed_total": st["max_speed_total"],
                    })
                court_smooth_by_slot = {
                    slot: court_smooth[tid]
                    for tid, slot in slot_map.items() if tid in court_smooth
                }
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

    _make_heatmap(court_positions, str(heatmap_path))
    _make_scatter(court_positions, str(scatter_path))

    meta = {
        "createdAt": datetime.utcnow().isoformat() + "Z",
        "source": os.path.basename(src_path),
        "frames": frames,
        "fps": round(float(fps), 2),
        "width": w,
        "height": h,
        "courtPoints": court_points if isinstance(court_points, list) else json.loads(court_points),
        "totalPersons": total_persons,
        "shuttleDetections": shuttle_frames,
        "rallyCount": rally_id,
        "playerDistances": {str(k): round(float(v), 2) for k, v in player_dist.items()},
        "playerMaxSpeed": {str(k): round(float(v), 2) for k, v in player_speeds.items()},
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
        "outputVideo": out_video.name,
        "heatmap": heatmap_path.name,
        "scatter": scatter_path.name,
        "detections": jsonl_path.name,
        "metadata": meta_path.name,
    }
