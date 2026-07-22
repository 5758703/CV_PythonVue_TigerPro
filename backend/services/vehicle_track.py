"""道路车辆追踪服务：ByteTrack + 可选车牌检测 + RapidOCR + 标定测速 + 拥堵统计 + 越线计数。"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import cv2
import numpy as np

from inference import _crosses, detect_image

# COCO: bicycle, car, motorcycle, bus, truck
DEFAULT_VEHICLE_CLASSES = [1, 2, 3, 5, 7]

_CN_PROVINCES = "京沪津渝冀晋蒙辽吉黑苏浙皖闽赣鲁豫鄂湘粤桂琼川贵云藏陕甘青宁新港澳"
_PLATE_ALNUM = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"
_PLATE_FULL_RE = re.compile(
    rf"^[{_CN_PROVINCES}][{_PLATE_ALNUM}]{{5,7}}$"
)
_PLATE_PREFIX_RE = re.compile(rf"^[{_CN_PROVINCES}][{_PLATE_ALNUM}]")

_sessions_lock = threading.Lock()
_sessions: dict[str, "VehicleSession"] = {}


@dataclass
class VehicleSession:
    """单路视频流/摄像头的追踪会话状态。"""
    track_history: dict[int, list[tuple[float, float, float]]] = field(default_factory=dict)
    plates: dict[int, dict[str, Any]] = field(default_factory=dict)
    plate_votes: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    last_ocr_at: dict[int, float] = field(default_factory=dict)
    crossing: dict[str, int] = field(default_factory=lambda: {"in": 0, "out": 0, "total": 0})
    counted: set[tuple[int, int]] = field(default_factory=set)
    records: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


def get_session(session_id: str, reset: bool = False) -> VehicleSession:
    with _sessions_lock:
        if reset or session_id not in _sessions:
            _sessions[session_id] = VehicleSession()
        return _sessions[session_id]


def clear_session(session_id: str) -> None:
    with _sessions_lock:
        _sessions.pop(session_id, None)


def congestion_level(count: int, *, light: int = 3, moderate: int = 8, heavy: int = 15) -> dict:
    """根据画面车辆数估算拥堵等级。"""
    if count <= light:
        level, label = "smooth", "畅通"
    elif count <= moderate:
        level, label = "moderate", "缓行"
    elif count <= heavy:
        level, label = "busy", "拥堵"
    else:
        level, label = "severe", "严重拥堵"
    return {
        "level": level,
        "label": label,
        "vehicleCount": count,
        "thresholds": {"light": light, "moderate": moderate, "heavy": heavy},
    }


def _clip_bbox(bbox, w, h, pad=2):
    x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    x1 = max(0, int(x1) - pad)
    y1 = max(0, int(y1) - pad)
    x2 = min(w, int(x2) + pad)
    y2 = min(h, int(y2) + pad)
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    ub = max(0, bx2 - bx1) * max(0, by2 - by1)
    denom = ua + ub - inter
    return inter / denom if denom > 0 else 0.0


def _plate_roi_heuristic(vehicle_bbox, img_h, img_w):
    """无专用车牌模型时：取车身框中下部作为车牌候选区。"""
    x1, y1, x2, y2 = [int(v) for v in vehicle_bbox[:4]]
    h = y2 - y1
    # 以前只取下半部，对一些倾角/遮挡场景偏小；这里适当抬高起点并稍微放大
    py1 = y1 + int(h * 0.45)
    py2 = min(img_h, y2 + int(h * 0.08))
    return _clip_bbox([x1, py1, x2, py2], img_w, img_h, pad=4)


def _detect_plate_boxes(plate_model_path: str, img_bgr, conf: float = 0.25) -> list[dict]:
    ok, buf = cv2.imencode(".jpg", img_bgr)
    if not ok:
        return []
    try:
        res = detect_image(plate_model_path, buf.tobytes(), conf=conf, draw=False)
        return res.get("detections") or []
    except Exception:  # noqa: BLE001
        return []


def _expand_bbox(bbox, w: int, h: int, *, pad_ratio: float = 0.25, pad_px: int = 6, min_size: tuple[int, int] = (50, 18)):
    """
    将 bbox 做“足够大的 OCR 裁剪”：
    - 车牌检测出来的框有时会很小（比如 10~20px 高），直接送 OCR 容易为空；
    - 这里用相对+绝对 padding 扩张，并确保最小宽高。
    """
    x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)

    extra_w = bw * pad_ratio
    extra_h = bh * pad_ratio
    x1 -= extra_w
    x2 += extra_w
    y1 -= extra_h
    y2 += extra_h

    # 最小尺寸保障（OCR 至少要有足够像素）
    min_w, min_h = min_size
    if (x2 - x1) < min_w:
        grow = (min_w - (x2 - x1)) / 2.0
        x1 -= grow
        x2 += grow
    if (y2 - y1) < min_h:
        grow = (min_h - (y2 - y1)) / 2.0
        y1 -= grow
        y2 += grow

    x1 = max(0, int(round(x1 - pad_px)))
    y1 = max(0, int(round(y1 - pad_px)))
    x2 = min(w, int(round(x2 + pad_px)))
    y2 = min(h, int(round(y2 + pad_px)))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _plate_candidates(vehicle_bbox, img_bgr, plate_model_path: str | None, plate_conf: float):
    h, w = img_bgr.shape[:2]
    if plate_model_path:
        # 车身 bbox 可能偏小/偏紧：这里把车身 ROI 稍微放大一点，避免把车牌裁掉
        crop = _clip_bbox(vehicle_bbox, w, h, pad=16)
        if crop:
            x1, y1, x2, y2 = crop
            roi = img_bgr[y1:y2, x1:x2]
            plates = _detect_plate_boxes(plate_model_path, roi, conf=plate_conf)
            # 取前几个候选，交给 OCR 再做“最终选择”
            plates = sorted(plates, key=lambda d: float(d.get("confidence") or 0), reverse=True)[:3]
            for p in plates:
                pb = p.get("bbox") or []
                if len(pb) >= 4:
                    bbox = [pb[0] + x1, pb[1] + y1, pb[2] + x1, pb[3] + y1]
                    if not _plate_in_vehicle_zone(bbox, vehicle_bbox):
                        continue
                    exp = _expand_bbox(bbox, w, h, pad_ratio=0.12, pad_px=4, min_size=(72, 24))
                    if exp:
                        yield exp, "model"

    # 模型未检出时再用启发式候选
    if plate_model_path:
        return
    roi_box = _plate_roi_heuristic(vehicle_bbox, h, w)
    if roi_box:
        exp = _expand_bbox(list(roi_box), w, h, pad_ratio=0.35, pad_px=5, min_size=(60, 20))
        if exp:
            yield exp, "heuristic"


def _pick_plate_bbox(vehicle_bbox, img_bgr, plate_model_path: str | None, plate_conf: float):
    """兼容旧接口：返回“首个候选框”。主流程会改用多候选 OCR。"""
    for pb, src in _plate_candidates(vehicle_bbox, img_bgr, plate_model_path, plate_conf):
        return pb, src
    return None, None


def _normalize_plate_text(text: str) -> str:
    t = re.sub(r"\s+", "", (text or "").upper())
    t = re.sub(r"[^0-9A-Z\u4e00-\u9fff]", "", t)
    return t


def _fix_plate_ocr_chars(text: str) -> str:
    """修正常见 OCR 混淆（仅作用于号牌主体，保留首字省份）。"""
    if len(text) < 3:
        return text
    head, tail = text[0], list(text[1:])
    province_fix = {"画": "粤", "奥": "粤", "粤": "粤", "專": "粤", "尊": "粤"}
    head = province_fix.get(head, head)
    fixes = {"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "B": "8", "S": "5", "Z": "2"}
    for i, ch in enumerate(tail):
        if i >= 1 and ch in fixes:
            tail[i] = fixes[ch]
    return head + "".join(tail)


def _vote_plate_text(votes: list[dict[str, Any]], *, max_votes: int = 10) -> tuple[str, float]:
    """同 track 多帧投票，按 rank 加权取最优号牌。"""
    if not votes:
        return "", 0.0
    recent = votes[-max_votes:]
    weighted: dict[str, float] = {}
    for v in recent:
        text = (v.get("text") or "").strip()
        if not text:
            continue
        rank = float(v.get("rank") or 0.0)
        fmt = _plate_format_score(text)
        weighted[text] = weighted.get(text, 0.0) + rank + fmt * 0.15
    if not weighted:
        return "", 0.0
    best = max(weighted, key=weighted.get)
    return best, weighted[best] / max(1.0, len(recent))


def _plate_format_score(text: str) -> float:
    """按中国号牌格式给文本打分（0~1）。"""
    t = _normalize_plate_text(text)
    if not t:
        return 0.0
    if _PLATE_FULL_RE.match(t):
        return 1.0
    if _PLATE_PREFIX_RE.match(t) and len(t) >= 4:
        return 0.55 + min(0.35, (len(t) - 2) * 0.08)
    if any(c in _CN_PROVINCES for c in t[:1]):
        return 0.35
    if re.fullmatch(rf"[{_PLATE_ALNUM}]{{4,8}}", t):
        return 0.25
    return 0.05


def _plate_in_vehicle_zone(plate_bbox, vehicle_bbox, *, bottom_ratio: float = 0.32) -> bool:
    """车牌应落在车身中下部，过滤引擎盖/背景误检。"""
    vx1, vy1, vx2, vy2 = [float(v) for v in vehicle_bbox[:4]]
    pb = plate_bbox
    if len(pb) < 4:
        return False
    vh = max(1.0, vy2 - vy1)
    zone_y1 = vy1 + vh * bottom_ratio
    cx = (pb[0] + pb[2]) / 2.0
    cy = (pb[1] + pb[3]) / 2.0
    return (zone_y1 <= cy <= vy2 + vh * 0.06) and (vx1 - 8 <= cx <= vx2 + 8)


def _merge_ocr_lines(lines: list[dict]) -> tuple[str, float]:
    """按从左到右拼接多段 OCR 文本。"""
    if not lines:
        return "", 0.0
    ordered = []
    for ln in lines:
        box = ln.get("box") or []
        if not box:
            continue
        xs = [p[0] for p in box if isinstance(p, (list, tuple)) and len(p) >= 2]
        cx = sum(xs) / len(xs) if xs else 0.0
        ordered.append((cx, ln))
    if not ordered:
        best = max(lines, key=lambda ln: float(ln.get("score") or 0))
        return _normalize_plate_text(best.get("text") or ""), float(best.get("score") or 0)
    ordered.sort(key=lambda x: x[0])
    text = "".join(_normalize_plate_text(ln.get("text") or "") for _, ln in ordered)
    scores = [float(ln.get("score") or 0) for _, ln in ordered if ln.get("text")]
    score = sum(scores) / len(scores) if scores else 0.0
    return text, score


def _ocr_plate(ocr_fn: Callable[[bytes], dict] | None, img_bgr, bbox) -> dict:
    if ocr_fn is None or bbox is None:
        return {"text": "", "score": 0.0, "lines": []}
    h, w = img_bgr.shape[:2]
    clipped = _clip_bbox(bbox, w, h, pad=4)
    if not clipped:
        return {"text": "", "score": 0.0, "lines": []}
    x1, y1, x2, y2 = clipped
    crop = img_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return {"text": "", "score": 0.0, "lines": []}

    # 车牌往往很小：强制放大后再喂 OCR，提高命中率
    ch = crop.shape[0]
    cw = crop.shape[1]
    min_h = 95
    min_w = 210
    scale_h = max(1.0, min_h / max(1, ch))
    scale_w = max(1.0, min_w / max(1, cw))
    scale = max(scale_h, scale_w)
    if scale > 1.01:
        crop = cv2.resize(crop, (int(round(cw * scale)), int(round(ch * scale))), interpolation=cv2.INTER_CUBIC)

    # 去掉上下边框的一小部分区域，减少蓝底/反光边缘对 OCR 的干扰
    hc, wc = crop.shape[:2]
    m = int(max(6, hc * 0.08))
    if hc > 80 and m < hc // 3:
        crop = crop[m:hc - m, :, :]
        hc, wc = crop.shape[:2]

    # v1：对比度增强；v2：自适应阈值；v3：HSV 亮字符掩膜；v4：去蓝底白底黑字
    v1 = cv2.convertScaleAbs(crop, alpha=1.35, beta=0)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    th = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        31, 5,
    )
    if th.mean() < 120:
        th = 255 - th
    v2 = cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    lower = (0, 0, 90)
    upper = (180, 90, 255)
    mask = cv2.inRange(hsv, lower, upper)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    masked = cv2.bitwise_and(crop, crop, mask=mask)
    g = cv2.cvtColor(masked, cv2.COLOR_BGR2GRAY)
    g = cv2.convertScaleAbs(g, alpha=1.6, beta=0)
    v3 = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)

    blue_mask = cv2.inRange(hsv, (95, 70, 40), (135, 255, 255))
    fg = cv2.bitwise_and(crop, crop, mask=cv2.bitwise_not(blue_mask))
    fg_gray = cv2.cvtColor(fg, cv2.COLOR_BGR2GRAY)
    fg_gray = cv2.convertScaleAbs(fg_gray, alpha=2.0, beta=10)
    _, fg_bin = cv2.threshold(fg_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if fg_bin.mean() < 127:
        fg_bin = 255 - fg_bin
    v4 = cv2.cvtColor(fg_bin, cv2.COLOR_GRAY2BGR)

    variants = [v1, v2, v3, v4]
    best_out = {"text": "", "score": 0.0, "lines": [], "rank": -1.0}

    for img_variant in variants:
        ok, buf = cv2.imencode(".jpg", img_variant)
        if not ok:
            continue
        try:
            res = ocr_fn(buf.tobytes()) or {}
            lines = res.get("lines") or []
            if not lines:
                continue
            text, score = _merge_ocr_lines(lines)
            text = _fix_plate_ocr_chars(_normalize_plate_text(text))
            fmt = _plate_format_score(text)
            rank = fmt * 0.65 + min(1.0, score) * 0.35
            if text and rank >= float(best_out.get("rank") or -1):
                best_out = {"text": text, "score": score, "lines": lines, "rank": rank}
        except Exception:  # noqa: BLE001
            continue

    return {k: best_out[k] for k in ("text", "score", "lines")}


def _calc_speed_kmh(history: list[tuple[float, float, float]], meters_per_pixel: float | None) -> float | None:
    if not meters_per_pixel or meters_per_pixel <= 0 or len(history) < 2:
        return None
    x0, y0, t0 = history[0]
    x1, y1, t1 = history[-1]
    dt = t1 - t0
    if dt <= 0:
        return None
    dist_m = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 * meters_per_pixel
    return round(dist_m / dt * 3.6, 1)


def enrich_vehicle_frame(
    img_bgr: np.ndarray,
    detections: list[dict],
    session: VehicleSession,
    *,
    plate_model_path: str | None = None,
    ocr_fn: Callable[[bytes], dict] | None = None,
    enable_ocr: bool = True,
    enable_speed: bool = True,
    meters_per_pixel: float | None = None,
    line_px: list[float] | None = None,
    plate_conf: float = 0.2,
    ocr_cooldown_sec: float = 0.6,
    history_len: int = 12,
    congestion_thresholds: dict | None = None,
) -> dict:
    """在追踪结果上叠加车牌、速度、越线与会话记录。"""
    h, w = img_bgr.shape[:2]
    now = time.time()
    enriched = []
    thr = congestion_thresholds or {}

    for d in detections:
        tid = d.get("trackId")
        bbox = d.get("bbox") or []
        item = dict(d)
        item["plate"] = None
        item["plateBbox"] = None
        item["plateSource"] = None
        item["speedKmh"] = None

        if tid is None or len(bbox) < 4:
            enriched.append(item)
            continue

        cx = (bbox[0] + bbox[2]) / 2.0
        cy = (bbox[1] + bbox[3]) / 2.0
        hist = session.track_history.setdefault(int(tid), [])
        hist.append((cx, cy, now))
        if len(hist) > history_len:
            del hist[:-history_len]

        if line_px and len(line_px) == 4:
            prev = hist[-2] if len(hist) >= 2 else None
            if prev:
                direction = _crosses((prev[0], prev[1]), (cx, cy), line_px)
                key = (int(tid), direction)
                if direction != 0 and key not in session.counted:
                    session.counted.add(key)
                    if direction > 0:
                        session.crossing["in"] += 1
                    else:
                        session.crossing["out"] += 1
                    session.crossing["total"] = session.crossing["in"] + session.crossing["out"]

        if enable_speed:
            item["speedKmh"] = _calc_speed_kmh(hist, meters_per_pixel)

        plate_info = session.plates.get(int(tid))
        need_ocr = enable_ocr and ocr_fn is not None
        last_ocr = session.last_ocr_at.get(int(tid), 0)

        # 行驶场景：近距/大框车辆缩短 OCR 冷却，便于多帧投票
        bw = max(1.0, float(bbox[2]) - float(bbox[0]))
        bh = max(1.0, float(bbox[3]) - float(bbox[1]))
        area_ratio = (bw * bh) / max(1.0, float(w * h))
        cooldown = float(ocr_cooldown_sec)
        if not plate_info or not plate_info.get("text"):
            cooldown = min(cooldown, 0.45)
        elif area_ratio >= 0.08:
            cooldown = min(cooldown, 0.7)

        # 车牌识别初次可能失败/读错：在冷却周期内允许“重新 OCR + 比较分数”，以提升准确率
        if need_ocr and (now - last_ocr) >= cooldown:
            best_text = None
            best_rank = -1.0
            best_score = 0.0
            best_pb = None
            best_src = None
            for pb, psrc in _plate_candidates(bbox, img_bgr, plate_model_path, plate_conf):
                ocr_res = _ocr_plate(ocr_fn, img_bgr, pb)
                text = (ocr_res.get("text") or "").strip()
                score = float(ocr_res.get("score") or 0.0)
                rank = _plate_format_score(text) * 0.65 + min(1.0, score) * 0.35
                if text and rank >= best_rank:
                    best_text = text
                    best_rank = rank
                    best_score = score
                    best_pb = pb
                    best_src = psrc

            session.last_ocr_at[int(tid)] = now

            if best_text and best_rank >= 0.28:
                votes = session.plate_votes.setdefault(int(tid), [])
                votes.append({"text": best_text, "rank": best_rank, "score": best_score, "time": now})
                if len(votes) > 12:
                    del votes[:-12]
                voted_text, voted_weight = _vote_plate_text(votes)
                display_text = voted_text or best_text
                display_rank = _plate_format_score(display_text) * 0.65 + min(1.0, best_score) * 0.35
                if voted_weight > 0:
                    display_rank = max(display_rank, voted_weight * 0.5)

                prev_rank = _plate_format_score(plate_info.get("text") if plate_info else "") * 0.65
                if plate_info:
                    prev_rank += min(1.0, float(plate_info.get("score") or 0)) * 0.35
                update = (not plate_info) or display_rank > prev_rank or display_text != plate_info.get("text")
                if update:
                    plate_info = {
                        "text": display_text,
                        "score": best_score,
                        "rank": display_rank,
                        "updatedAt": now,
                        "source": best_src,
                        "voteCount": len(votes),
                    }
                    session.plates[int(tid)] = plate_info
                    item["plateBbox"] = best_pb
                    item["plateSource"] = best_src
                    session.records.append({
                        "time": now,
                        "trackId": int(tid),
                        "className": d.get("className"),
                        "plate": display_text,
                        "plateScore": best_score,
                        "speedKmh": item.get("speedKmh"),
                        "confidence": d.get("confidence"),
                    })

        if plate_info:
            item["plate"] = plate_info.get("text")
            item["plateScore"] = plate_info.get("score")
            item["plateSource"] = plate_info.get("source")

        enriched.append(item)

    congestion = congestion_level(
        len(enriched),
        light=int(thr.get("light", 3)),
        moderate=int(thr.get("moderate", 8)),
        heavy=int(thr.get("heavy", 15)),
    )
    return {
        "detections": enriched,
        "width": w,
        "height": h,
        "crossing": dict(session.crossing),
        "congestion": congestion,
        "recordCount": len(session.records),
        "recentRecords": session.records[-20:],
    }


_hud_font_cache: dict[int, Any] = {}


def _hud_font(size: int = 18):
    if size in _hud_font_cache:
        return _hud_font_cache[size]
    from PIL import ImageFont
    win = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        os.path.join(win, "Fonts", "msyh.ttc"),
        os.path.join(win, "Fonts", "msyhbd.ttc"),
        os.path.join(win, "Fonts", "simhei.ttf"),
        os.path.join(win, "Fonts", "simsun.ttc"),
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
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
    _hud_font_cache[size] = font
    return font


def _draw_label_bgr(img_bgr, text: str, origin, *, color=(0, 200, 80), font_size=18):
    """在 BGR 图上绘制支持中文的标签（号牌等）。"""
    if not text:
        return img_bgr
    from PIL import Image, ImageDraw
    font = _hud_font(font_size)
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    x, y = int(origin[0]), int(origin[1])
    bbox = draw.textbbox((x, y), text, font=font)
    pad = 3
    fill = (max(0, color[2] - 40), max(0, color[1] - 40), max(0, color[0] - 40))
    draw.rectangle(
        [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
        fill=fill,
    )
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def draw_vehicle_hud(img_bgr, result: dict, *, line_px=None) -> np.ndarray:
    """在 BGR 图上绘制车辆框、ID、号牌、速度（供视频导出 / 图片识别）。"""
    vis = img_bgr.copy()
    for d in result.get("detections") or []:
        bbox = d.get("bbox") or []
        if len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        color = (0, 200, 80)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
        parts = []
        if d.get("trackId") is not None:
            parts.append(f"ID{d['trackId']}")
        parts.append(str(d.get("className") or "vehicle"))
        if d.get("plate"):
            parts.append(str(d["plate"]))
        if d.get("speedKmh"):
            parts.append(f"{d['speedKmh']}km/h")
        label = " ".join(parts)
        vis = _draw_label_bgr(vis, label, (x1, max(4, y1 - 22)), color=color, font_size=17)
        pb = d.get("plateBbox")
        if pb and len(pb) >= 4:
            cv2.rectangle(vis, (int(pb[0]), int(pb[1])), (int(pb[2]), int(pb[3])), (0, 255, 255), 2)

    cong = result.get("congestion") or {}
    if cong.get("label"):
        vis = _draw_label_bgr(
            vis, f"拥堵: {cong.get('label', '-')}", (10, 8),
            color=(0, 165, 255), font_size=18,
        )
    crossing = result.get("crossing") or {}
    if line_px and len(line_px) == 4:
        p1 = (int(line_px[0]), int(line_px[1]))
        p2 = (int(line_px[2]), int(line_px[3]))
        cv2.line(vis, p1, p2, (0, 0, 255), 2)
        vis = _draw_label_bgr(
            vis, f"进:{crossing.get('in', 0)} 出:{crossing.get('out', 0)}",
            (10, 36), color=(0, 0, 255), font_size=18,
        )
    return vis


def analyze_vehicle_image(
    img_bgr: np.ndarray,
    detections: list[dict],
    *,
    plate_model_path: str | None = None,
    ocr_fn: Callable[[bytes], dict] | None = None,
    enable_ocr: bool = True,
    plate_conf: float = 0.2,
) -> dict:
    """单张图片：车辆检测结果 + 车牌定位/OCR（无追踪会话）。"""
    # 为 enrich 分配临时 ID；关闭测速/越线
    dets = []
    for i, d in enumerate(detections or [], start=1):
        item = dict(d)
        if item.get("trackId") is None:
            item["trackId"] = i
        dets.append(item)
    session = VehicleSession()
    return enrich_vehicle_frame(
        img_bgr,
        dets,
        session,
        plate_model_path=plate_model_path,
        ocr_fn=ocr_fn if enable_ocr else None,
        enable_ocr=enable_ocr and ocr_fn is not None,
        enable_speed=False,
        meters_per_pixel=None,
        line_px=None,
        plate_conf=plate_conf,
        ocr_cooldown_sec=0.0,
    )
