"""中国手语（CSL）YOLO11s 检测识别服务。

权重目录：uploads/models/chinese-sign-language-tigerhhzz-yolo11s/
  - weights.onnx
  - class_names.txt / environment.json（30 类：A–Z、CH、NG、SH、ZH）
"""
from __future__ import annotations

import json
import os
from typing import Any

import cv2
import numpy as np

MODEL_KEY = "chinese-sign-language-tigerhhzz-yolo11s"
MODEL_REL_DIR = os.path.join("models", MODEL_KEY)
WEIGHT_FILE = "weights.onnx"

RECOGNIZER_MEDIAPIPE = "mediapipe"
RECOGNIZER_CSL = "csl-yolo11s"

# 手语字母常见中文读法（用于展示，非权威语言学标注）
_CSL_LABEL_ZH = {
    "A": "A（啊）", "B": "B（波）", "C": "C（次）", "CH": "CH（吃）",
    "D": "D（的）", "E": "E（鹅）", "F": "F（佛）", "G": "G（哥）",
    "H": "H（喝）", "I": "I（衣）", "J": "J（基）", "K": "K（科）",
    "L": "L（勒）", "M": "M（摸）", "N": "N（讷）", "NG": "NG（嗯）",
    "O": "O（喔）", "P": "P（坡）", "Q": "Q（七）", "R": "R（日）",
    "S": "S（思）", "SH": "SH（诗）", "T": "T（特）", "U": "U（乌）",
    "V": "V（微）", "W": "W（屋）", "X": "X（西）", "Y": "Y（衣）",
    "Z": "Z（资）", "ZH": "ZH（知）",
}


def list_recognizers() -> list[dict[str, Any]]:
    """手势识别页可选引擎列表。"""
    return [
        {
            "id": RECOGNIZER_MEDIAPIPE,
            "name": "数字手势（MediaPipe 0–9）",
            "description": "21 关键点 + 角度法识别 0–9，含中式单手 6–9；支持双手「右 左」组合。",
            "kind": "keypoint",
        },
        {
            "id": RECOGNIZER_CSL,
            "name": "中国手语（YOLO11s）",
            "description": "YOLO11s 检测 30 类手语字母/声母手势（A–Z、CH、NG、SH、ZH）。",
            "kind": "detection",
            "modelKey": MODEL_KEY,
        },
    ]


def _model_folder(model_dir: str) -> str:
    return os.path.abspath(model_dir)


def resolve_weight_path(model_dir: str) -> str:
    folder = _model_folder(model_dir)
    for name in (WEIGHT_FILE, "best.pt", "weights.pt"):
        p = os.path.join(folder, name)
        if os.path.isfile(p):
            return p
    for f in os.listdir(folder) if os.path.isdir(folder) else []:
        if f.lower().endswith((".onnx", ".pt")):
            return os.path.join(folder, f)
    raise FileNotFoundError(f"未找到手语检测权重：{folder}")


def load_class_names_dict(model_dir: str) -> dict[int, str]:
    """从 environment.json 或 class_names.txt 读取类别映射。"""
    if not model_dir:
        # 无目录时读默认相对路径（单测/文档用）
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", MODEL_REL_DIR.replace("/", os.sep))
        folder = base if os.path.isdir(base) else ""
    else:
        folder = _model_folder(model_dir)

    env_path = os.path.join(folder, "environment.json")
    if os.path.isfile(env_path):
        try:
            with open(env_path, encoding="utf-8") as f:
                data = json.load(f)
            cm = data.get("CLASS_MAP") or {}
            return {int(k): str(v) for k, v in sorted(cm.items(), key=lambda x: int(x[0]))}
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            pass

    txt_path = os.path.join(folder, "class_names.txt")
    if os.path.isfile(txt_path):
        try:
            with open(txt_path, encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            return {i: name for i, name in enumerate(lines)}
        except OSError:
            pass
    return {}


def load_class_names_list(model_dir: str) -> list[str]:
    d = load_class_names_dict(model_dir)
    if not d:
        return []
    return [d[i] for i in sorted(d.keys())]


def _class_name(names: dict[int, str], cls_id: int, fallback: str = "unknown") -> str:
    if cls_id in names:
        return names[cls_id]
    return fallback


def _label_zh(class_name: str) -> str:
    return _CSL_LABEL_ZH.get(class_name, f"手语 {class_name}")


DEFAULT_CONF = 0.25
# 推理内部下限：YOLO 侧先用低阈值出框，再用用户 conf 做后过滤。
# 若把用户 conf（常 0.5）直接传给 predict，0.25~0.45 的真实手势会被 NMS 直接丢掉。
_PREDICT_CONF_FLOOR = 0.15
# 手语字母多为近景手部；整帧误检常见为细长背景条（如家具立柱）
_MIN_AREA_RATIO = 0.008
_MAX_AREA_RATIO = 0.65
_MIN_ASPECT = 0.2
_MAX_ASPECT = 4.0
_PALM_CROP_PAD = 0.4  # 相对手框边长外扩，避免裁掉指尖
_SQUARE_CROP_SCALE = 1.4  # 方形特写裁剪边长 = max(w,h) * scale（贴近训练构图）


def _box_wh(bbox) -> tuple[float, float]:
    x1, y1, x2, y2 = (float(v) for v in bbox[:4])
    return max(0.0, x2 - x1), max(0.0, y2 - y1)


def is_plausible_hand_box(bbox, img_w: int, img_h: int) -> bool:
    """过滤过小、过大、细长条等不像手部的框。"""
    w, h = _box_wh(bbox)
    if w < 12 or h < 12:
        return False
    area = w * h
    img_area = max(1, int(img_w) * int(img_h))
    if area < _MIN_AREA_RATIO * img_area or area > _MAX_AREA_RATIO * img_area:
        return False
    ar = w / max(h, 1e-6)
    return _MIN_ASPECT <= ar <= _MAX_ASPECT


def expand_bbox(bbox, img_w: int, img_h: int, pad: float = _PALM_CROP_PAD) -> list[int]:
    x1, y1, x2, y2 = (float(v) for v in bbox[:4])
    bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
    px, py = bw * pad, bh * pad
    nx1 = int(max(0, x1 - px))
    ny1 = int(max(0, y1 - py))
    nx2 = int(min(img_w, x2 + px))
    ny2 = int(min(img_h, y2 + py))
    if nx2 <= nx1 or ny2 <= ny1:
        return [int(x1), int(y1), int(x2), int(y2)]
    return [nx1, ny1, nx2, ny2]


def square_crop_bbox(bbox, img_w: int, img_h: int, scale: float = _SQUARE_CROP_SCALE) -> list[int]:
    """以手框中心做方形特写裁剪（YOLO11s 训练多为近景方图）。"""
    x1, y1, x2, y2 = (float(v) for v in bbox[:4])
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    side = max(x2 - x1, y2 - y1, 32.0) * float(scale)
    half = side / 2.0
    nx1 = int(max(0, cx - half))
    ny1 = int(max(0, cy - half))
    nx2 = int(min(img_w, cx + half))
    ny2 = int(min(img_h, cy + half))
    if nx2 <= nx1 or ny2 <= ny1:
        return expand_bbox(bbox, img_w, img_h)
    return [nx1, ny1, nx2, ny2]


def bbox_iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = (float(v) for v in a[:4])
    bx1, by1, bx2, by2 = (float(v) for v in b[:4])
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1) + max(0.0, bx2 - bx1) * max(0.0, by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def filter_by_hand_regions(detections: list[dict[str, Any]], hand_boxes: list, *, min_iou: float = 0.08):
    """仅保留与手部区域有重叠的检测，去掉背景误检。"""
    if not hand_boxes:
        return detections
    kept = []
    for d in detections:
        bb = d.get("bbox") or []
        if len(bb) < 4:
            continue
        if any(bbox_iou(bb, hb) >= min_iou for hb in hand_boxes):
            kept.append(d)
    return kept


def format_csl_display(detections: list[dict[str, Any]]) -> dict[str, Any]:
    if not detections:
        return {
            "displayText": None,
            "primaryLabel": None,
            "labelZh": None,
            "confidence": None,
        }
    best = max(detections, key=lambda d: float(d.get("confidence") or 0))
    label = str(best.get("className") or "")
    conf = float(best.get("confidence") or 0)
    return {
        "displayText": label,
        "primaryLabel": label,
        "labelZh": _label_zh(label),
        "confidence": round(conf, 4),
    }


def _resolve_class_name(cls_id: int, names_map: dict[int, str], model_names) -> str:
    if cls_id in names_map:
        return names_map[cls_id]
    if isinstance(model_names, dict) and cls_id in model_names:
        return str(model_names[cls_id])
    if isinstance(model_names, (list, tuple)) and 0 <= cls_id < len(model_names):
        return str(model_names[cls_id])
    return str(cls_id)


def _boxes_to_detections(result, names_map: dict[int, str], *, ox=0, oy=0) -> list[dict[str, Any]]:
    model_names = names_map or getattr(result, "names", None) or {}
    detections: list[dict[str, Any]] = []
    if result.boxes is None:
        return detections
    for b in result.boxes:
        cls_id = int(b.cls[0])
        cname = _resolve_class_name(cls_id, names_map, model_names)
        xyxy = [round(float(v), 1) for v in b.xyxy[0].tolist()]
        xyxy[0] += ox
        xyxy[1] += oy
        xyxy[2] += ox
        xyxy[3] += oy
        detections.append({
            "className": cname,
            "classId": cls_id,
            "confidence": round(float(b.conf[0]), 4),
            "bbox": xyxy,
            "labelZh": _label_zh(cname),
        })
    return detections


def _locate_hands(img_bgr: np.ndarray, mediapipe_dir: str | None) -> list[list[float]]:
    """用 MediaPipe 手掌/关键点给出手部框；失败则空列表。"""
    if not mediapipe_dir or not os.path.isdir(mediapipe_dir):
        return []
    try:
        from services.handpose import detect_hands
        hands = detect_hands(img_bgr, mediapipe_dir, palm_score=0.4, hand_conf=0.55, max_hands=2)
        return [h["bbox"] for h in hands if h.get("bbox") and len(h["bbox"]) >= 4]
    except Exception:  # noqa: BLE001
        return []


def _predict_on_crop(
    model,
    img_bgr: np.ndarray,
    names_map: dict[int, str],
    region: list[int],
    predict_kw: dict,
) -> list[dict[str, Any]]:
    x1, y1, x2, y2 = region
    crop = img_bgr[y1:y2, x1:x2]
    if crop.size == 0 or crop.shape[0] < 16 or crop.shape[1] < 16:
        return []
    r = model.predict(crop, **predict_kw)[0]
    dets = _boxes_to_detections(r, names_map, ox=x1, oy=y1)
    if dets:
        return dets
    # 裁剪内无框但有分类概率时，用手框区域作为检测
    probs = getattr(r, "probs", None)
    data = getattr(probs, "data", None) if probs is not None else None
    if data is None:
        return []
    arr = data.detach().cpu().numpy() if hasattr(data, "detach") else np.asarray(data)
    arr = np.asarray(arr, dtype=np.float32).reshape(-1)
    if not arr.size:
        return []
    idx = int(arr.argmax())
    score = float(arr[idx])
    cname = _resolve_class_name(idx, names_map, names_map)
    return [{
        "className": cname,
        "classId": idx,
        "confidence": round(score, 4),
        "bbox": [float(x1), float(y1), float(x2), float(y2)],
        "labelZh": _label_zh(cname),
    }]


def detect_sign_language(
    img_bgr: np.ndarray,
    model_dir: str,
    *,
    conf: float = DEFAULT_CONF,
    draw: bool = False,
    mediapipe_dir: str | None = None,
) -> dict[str, Any]:
    """中国手语检测：先定位手部再 YOLO 分类，避免整帧背景误检。

    手部裁剪优先方形特写（贴近训练构图），矩形外扩为回退；裁剪无结果时再
    整帧推理。YOLO predict 使用低置信度下限，用户 conf 仅作后过滤。
    """
    weight_path = resolve_weight_path(model_dir)
    names_map = load_class_names_dict(model_dir)
    h, w = img_bgr.shape[:2]
    conf = float(conf if conf is not None else DEFAULT_CONF)

    from inference import _get_model, _yolo_predict_kwargs

    model = _get_model(weight_path)
    predict_kw = _yolo_predict_kwargs(conf=_PREDICT_CONF_FLOOR)

    hand_boxes = _locate_hands(img_bgr, mediapipe_dir)
    detections: list[dict[str, Any]] = []

    if hand_boxes:
        for hb in hand_boxes:
            # 1) 方形特写  2) 矩形外扩
            for region in (
                square_crop_bbox(hb, w, h),
                expand_bbox(hb, w, h),
            ):
                crop_dets = _predict_on_crop(model, img_bgr, names_map, region, predict_kw)
                crop_dets = [d for d in crop_dets if d["confidence"] >= conf]
                if crop_dets:
                    detections.extend(crop_dets)
                    break
        # 手已定位但裁剪仍无达标结果：整帧兜底（部分构图手框偏大/偏小）
        if not detections:
            r = model.predict(img_bgr, **predict_kw)[0]
            detections = _boxes_to_detections(r, names_map)
    else:
        r = model.predict(img_bgr, **predict_kw)[0]
        detections = _boxes_to_detections(r, names_map)

    detections = [d for d in detections if d["confidence"] >= conf]
    detections = [d for d in detections if is_plausible_hand_box(d["bbox"], w, h)]
    if hand_boxes:
        regions = [square_crop_bbox(hb, w, h) for hb in hand_boxes] + [
            expand_bbox(hb, w, h) for hb in hand_boxes
        ]
        detections = filter_by_hand_regions(detections, regions, min_iou=0.05)

    detections.sort(key=lambda d: d["confidence"], reverse=True)
    # 每只手只保留最高置信度一类
    if hand_boxes and detections:
        assigned: list[dict[str, Any]] = []
        used = set()
        for hb in hand_boxes:
            region = square_crop_bbox(hb, w, h)
            cands = [
                (i, d) for i, d in enumerate(detections)
                if i not in used and bbox_iou(d["bbox"], region) >= 0.05
            ]
            if not cands:
                region = expand_bbox(hb, w, h)
                cands = [
                    (i, d) for i, d in enumerate(detections)
                    if i not in used and bbox_iou(d["bbox"], region) >= 0.05
                ]
            if not cands:
                continue
            i, best = max(cands, key=lambda t: t[1]["confidence"])
            used.add(i)
            assigned.append(best)
        detections = assigned or detections[:2]

    disp = format_csl_display(detections)

    image_b64 = None
    if draw:
        vis = img_bgr.copy()
        for d in detections:
            x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"{d['className']} {d['confidence']:.2f}"
            cv2.putText(vis, label, (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.65, (0, 255, 0), 2, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", vis)
        if ok:
            import base64
            image_b64 = base64.b64encode(buf.tobytes()).decode()

    return {
        "recognizer": RECOGNIZER_CSL,
        "detections": detections,
        "count": len(detections),
        "classes": load_class_names_list(model_dir),
        "width": w,
        "height": h,
        "imageBase64": image_b64,
        **disp,
    }
