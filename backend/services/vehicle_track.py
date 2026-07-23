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
    """扩张 bbox，保证 OCR 最小像素。"""
    x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    extra_w = bw * pad_ratio
    extra_h = bh * pad_ratio
    x1 -= extra_w
    x2 += extra_w
    y1 -= extra_h
    y2 += extra_h
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


def _order_quad_points(pts: np.ndarray) -> np.ndarray:
    """四点排序为 TL, TR, BR, BL。"""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.float32([tl, tr, br, bl])


def _bbox_to_quad(bbox) -> np.ndarray:
    x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    return np.float32([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])


def _warp_plate(img_bgr, quad, out_w: int = 240, out_h: int = 80) -> np.ndarray | None:
    try:
        src = _order_quad_points(quad)
        dst = np.float32([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]])
        m = cv2.getPerspectiveTransform(src, dst)
        return cv2.warpPerspective(img_bgr, m, (out_w, out_h))
    except Exception:  # noqa: BLE001
        return None


def _locate_plates_in_roi(plate_model_path: str, roi_bgr, conf: float = 0.25) -> list[dict]:
    """在车辆 ROI 内定位车牌，返回 [{bbox, quad, confidence, source}]。

    优先 pose 4 角点 → OBB → detect bbox。
    """
    from inference import _get_model, _yolo_predict_kwargs

    out: list[dict] = []
    try:
        model = _get_model(plate_model_path)
        r = model.predict(roi_bgr, **_yolo_predict_kwargs(conf=conf))[0]
    except Exception:  # noqa: BLE001
        return out

    # Pose：keypoints 4 点
    if getattr(r, "keypoints", None) is not None and r.keypoints is not None and r.keypoints.xy is not None:
        try:
            kps = r.keypoints.xy.cpu().numpy()
            confs = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None else None
            boxes = r.boxes.xyxy.cpu().numpy() if r.boxes is not None else None
            box_confs = r.boxes.conf.cpu().numpy() if r.boxes is not None else None
            for i, kp in enumerate(kps):
                if kp is None or len(kp) < 4:
                    continue
                quad = np.asarray(kp[:4], dtype=np.float32)
                if confs is not None and float(np.mean(confs[i][:4])) < 0.15:
                    continue
                xs, ys = quad[:, 0], quad[:, 1]
                bbox = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
                score = float(box_confs[i]) if box_confs is not None and i < len(box_confs) else 0.5
                if boxes is not None and i < len(boxes):
                    bbox = [float(v) for v in boxes[i][:4]]
                out.append({"bbox": bbox, "quad": quad, "confidence": score, "source": "pose"})
        except Exception:  # noqa: BLE001
            pass

    # OBB
    if not out and getattr(r, "obb", None) is not None and r.obb is not None:
        try:
            xyxyxyxy = r.obb.xyxyxyxy.cpu().numpy()
            confs = r.obb.conf.cpu().numpy() if r.obb.conf is not None else None
            for i, poly in enumerate(xyxyxyxy):
                quad = np.asarray(poly, dtype=np.float32).reshape(4, 2)
                xs, ys = quad[:, 0], quad[:, 1]
                bbox = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
                score = float(confs[i]) if confs is not None else 0.5
                out.append({"bbox": bbox, "quad": quad, "confidence": score, "source": "obb"})
        except Exception:  # noqa: BLE001
            pass

    # Detect boxes
    if not out and r.boxes is not None:
        try:
            for b in r.boxes:
                xyxy = [float(v) for v in b.xyxy[0].tolist()]
                score = float(b.conf[0])
                out.append({
                    "bbox": xyxy,
                    "quad": _bbox_to_quad(xyxy),
                    "confidence": score,
                    "source": "detect",
                })
        except Exception:  # noqa: BLE001
            pass

    out.sort(key=lambda d: float(d.get("confidence") or 0), reverse=True)
    return out[:3]


def _plate_candidates(vehicle_bbox, img_bgr, plate_model_path: str | None, plate_conf: float):
    """生成车牌候选：yield (bbox_abs, source, quad_abs|None, warped_bgr|None)。"""
    h, w = img_bgr.shape[:2]
    if plate_model_path:
        crop = _clip_bbox(vehicle_bbox, w, h, pad=16)
        if crop:
            x1, y1, x2, y2 = crop
            roi = img_bgr[y1:y2, x1:x2]
            plates = _locate_plates_in_roi(plate_model_path, roi, conf=plate_conf)
            for p in plates:
                pb = p.get("bbox") or []
                if len(pb) < 4:
                    continue
                bbox = [pb[0] + x1, pb[1] + y1, pb[2] + x1, pb[3] + y1]
                if not _plate_in_vehicle_zone(bbox, vehicle_bbox):
                    continue
                quad = p.get("quad")
                quad_abs = None
                warped = None
                if quad is not None:
                    q = np.asarray(quad, dtype=np.float32).reshape(4, 2)
                    q[:, 0] += x1
                    q[:, 1] += y1
                    quad_abs = q
                    warped = _warp_plate(img_bgr, q)
                exp = _expand_bbox(bbox, w, h, pad_ratio=0.08, pad_px=3, min_size=(72, 24))
                if exp:
                    if warped is None:
                        warped = _warp_plate(img_bgr, _bbox_to_quad(exp))
                        if quad_abs is None:
                            quad_abs = _bbox_to_quad(exp)
                    yield exp, p.get("source") or "model", quad_abs, warped

    if plate_model_path:
        return
    roi_box = _plate_roi_heuristic(vehicle_bbox, h, w)
    if roi_box:
        exp = _expand_bbox(list(roi_box), w, h, pad_ratio=0.35, pad_px=5, min_size=(60, 20))
        if exp:
            quad = _bbox_to_quad(exp)
            yield exp, "heuristic", quad, _warp_plate(img_bgr, quad)


def _pick_plate_bbox(vehicle_bbox, img_bgr, plate_model_path: str | None, plate_conf: float):
    """兼容旧接口：返回“首个候选框”。主流程会改用多候选 OCR。"""
    for pb, src, _quad, _warp in _plate_candidates(vehicle_bbox, img_bgr, plate_model_path, plate_conf):
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


def _ocr_plate(ocr_fn: Callable[[bytes], dict] | None, img_bgr, bbox, warped: np.ndarray | None = None) -> dict:
    """对透视矫正牌面或 bbox 裁剪做 OCR（优先 warped + rec-only）。"""
    if ocr_fn is None:
        return {"text": "", "score": 0.0, "lines": []}

    crops = []
    if warped is not None and getattr(warped, "size", 0):
        crops.append(warped)
    if bbox is not None:
        h, w = img_bgr.shape[:2]
        clipped = _clip_bbox(bbox, w, h, pad=4)
        if clipped:
            x1, y1, x2, y2 = clipped
            crop = img_bgr[y1:y2, x1:x2]
            if crop.size:
                ch, cw = crop.shape[:2]
                scale = max(1.0, 95 / max(1, ch), 210 / max(1, cw))
                if scale > 1.01:
                    crop = cv2.resize(crop, (int(round(cw * scale)), int(round(ch * scale))), interpolation=cv2.INTER_CUBIC)
                crops.append(cv2.convertScaleAbs(crop, alpha=1.25, beta=0))

    best_out = {"text": "", "score": 0.0, "lines": [], "rank": -1.0}
    for crop in crops:
        ok, buf = cv2.imencode(".jpg", crop)
        if not ok:
            continue
        try:
            try:
                res = ocr_fn(buf.tobytes(), rec_only=True) or {}
            except TypeError:
                res = ocr_fn(buf.tobytes()) or {}
            lines = res.get("lines") or []
            text = _fix_plate_ocr_chars(_normalize_plate_text(res.get("text") or ""))
            score = 0.0
            if lines:
                text2, score = _merge_ocr_lines(lines)
                text = _fix_plate_ocr_chars(_normalize_plate_text(text2 or text))
            elif text:
                score = float(res.get("score") or 0.4)
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
            for pb, psrc, _quad, warped in _plate_candidates(bbox, img_bgr, plate_model_path, plate_conf):
                ocr_res = _ocr_plate(ocr_fn, img_bgr, pb, warped=warped)
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
