"""车辆视觉 ReID（TransReID / CLIP-ReID / ViT 风格 ONNX）+ 车牌融合打分。

身份键：plate|visual_key（有牌优先；无牌仅视觉；两者融合生成稳定 identity_key）。
"""
from __future__ import annotations

import hashlib
import os
import threading
from typing import Any

import cv2
import numpy as np

_lock = threading.Lock()
_sess_cache: dict[tuple, Any] = {}

DEFAULT_IN_W, DEFAULT_IN_H = 256, 256
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)

VEHICLE_ONNX_NAMES = (
    "transreid.onnx",
    "clip_vehicle_reid.onnx",
    "vehicle_vit_clip_reid.onnx",
    "vehicle_vit_reid.onnx",
    "veri_reid.onnx",
    "vehicle_reid.onnx",
)


def resolve_vehicle_onnx(model_path: str | None) -> str | None:
    if not model_path:
        return None
    if os.path.isfile(model_path) and model_path.lower().endswith(".onnx"):
        return model_path if os.path.getsize(model_path) > 100_000 else None
    if not os.path.isdir(model_path):
        return None
    for name in VEHICLE_ONNX_NAMES:
        p = os.path.join(model_path, name)
        if os.path.isfile(p) and os.path.getsize(p) > 100_000:
            return p
    for name in sorted(os.listdir(model_path)):
        if name.lower().endswith(".onnx"):
            fp = os.path.join(model_path, name)
            if os.path.isfile(fp) and os.path.getsize(fp) > 100_000:
                return fp
    return None


def assets_ready(model_path: str | None) -> bool:
    return resolve_vehicle_onnx(model_path) is not None


def _l2(v: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(a))
    return a if n < eps else a / n


def _get_ort(onnx_path: str):
    import onnxruntime as ort

    mtime = os.path.getmtime(onnx_path)
    key = (onnx_path, mtime)
    with _lock:
        sess = _sess_cache.get(key)
        if sess is not None:
            return sess
        sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        _sess_cache[key] = sess
        return sess


def _input_spatial(sess) -> tuple[int, int]:
    """从 ONNX 首输入解析 (width, height)，默认 256×256。"""
    shape = sess.get_inputs()[0].shape
    if len(shape) < 4:
        return DEFAULT_IN_W, DEFAULT_IN_H
    h, w = shape[2], shape[3]
    if not isinstance(h, int) or h <= 0:
        h = DEFAULT_IN_H
    if not isinstance(w, int) or w <= 0:
        w = DEFAULT_IN_W
    return w, h


def _preprocess(image_bgr: np.ndarray, width: int, height: int) -> np.ndarray:
    img = cv2.resize(image_bgr, (width, height), interpolation=cv2.INTER_LINEAR)
    rgb = img[:, :, ::-1].astype(np.float32) / 255.0
    rgb = (rgb - np.asarray(MEAN, dtype=np.float32)) / np.asarray(STD, dtype=np.float32)
    return np.transpose(rgb, (2, 0, 1))[None, ...].astype(np.float32)


def _build_feed(sess, blob: np.ndarray) -> dict[str, np.ndarray]:
    """构造 ONNX 输入；额外 int 输入（cam/view）填零。"""
    feed: dict[str, np.ndarray] = {}
    for inp in sess.get_inputs():
        if inp.name == sess.get_inputs()[0].name:
            feed[inp.name] = blob
        elif "int" in inp.type:
            feed[inp.name] = np.zeros((1,), dtype=np.int64)
        else:
            feed[inp.name] = np.zeros((1,), dtype=np.float32)
    return feed


def _color_hist_embedding(image_bgr: np.ndarray, bins: int = 16) -> np.ndarray:
    """无专用 ONNX 时的轻量外观兜底：HSV 直方图 + 边缘统计。"""
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    feats = []
    for i, ch in enumerate(cv2.split(hsv)):
        hist = cv2.calcHist([ch], [0], None, [bins], [0, 256 if i else 180])
        feats.append(hist.reshape(-1))
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 160)
    feats.append(np.array([float(edges.mean()), float(gray.mean()), float(gray.std())], dtype=np.float32))
    return _l2(np.concatenate(feats).astype(np.float32))


def extract_vehicle_embedding(model_path: str | None, image_bgr: np.ndarray) -> tuple[np.ndarray, dict]:
    onnx = resolve_vehicle_onnx(model_path)
    if onnx:
        try:
            sess = _get_ort(onnx)
            in_w, in_h = _input_spatial(sess)
            blob = _preprocess(image_bgr, in_w, in_h)
            out = sess.run([sess.get_outputs()[0].name], _build_feed(sess, blob))[0]
            feat = _l2(np.asarray(out, dtype=np.float32).reshape(-1))
            return feat, {
                "backend": "vehicle-onnx",
                "onnx": os.path.basename(onnx),
                "dim": int(feat.size),
                "inputSize": f"{in_w}x{in_h}",
            }
        except Exception as e:  # noqa: BLE001
            feat = _color_hist_embedding(image_bgr)
            return feat, {"backend": "hist-fallback", "onnxError": str(e), "dim": int(feat.size)}
    feat = _color_hist_embedding(image_bgr)
    return feat, {"backend": "hist-fallback", "dim": int(feat.size)}


def visual_key_from_embedding(emb: np.ndarray, prefix: str = "V") -> str:
    """将 embedding 量化为短视觉键（稳定聚类代理）。

    使用 float32 字节哈希，避免 int8 粗量化导致相似外观（如直方图兜底）碰撞同一键。
    """
    e = _l2(emb)
    digest = hashlib.sha1(e.astype(np.float32).tobytes()).hexdigest()[:12]
    return f"{prefix}{digest}"


_VEHICLE_LARGE = frozenset({"truck", "bus"})
_VEHICLE_CAR = frozenset({"car"})
_VEHICLE_MOTOR = frozenset({"motorcycle", "motorbike"})


def vehicle_class_bucket(class_name: str | None) -> str:
    """YOLO 细类 → 粗桶（large/car/motor/unknown），用于跨镜类别门控。"""
    n = (class_name or "").strip().lower()
    if n in _VEHICLE_LARGE:
        return "large"
    if n in _VEHICLE_CAR:
        return "car"
    if n in _VEHICLE_MOTOR:
        return "motor"
    return "unknown"


def vehicle_class_conflict(a: str | None, b: str | None) -> bool:
    """双方类别均可判定时，truck/bus 与 car 等互斥。"""
    ba, bb = vehicle_class_bucket(a), vehicle_class_bucket(b)
    if ba == "unknown" or bb == "unknown":
        return False
    return ba != bb


def infer_vehicle_class(
    class_name: str | None,
    bbox: list | tuple | None = None,
    *,
    frame_h: int = 0,
    frame_w: int = 0,
) -> str | None:
    """检测类 + 框面积启发式，缓解 YOLO 将货车误标为 car。"""
    n = (class_name or "").strip().lower()
    bucket = vehicle_class_bucket(n)
    area_ratio = 0.0
    if bbox is not None and len(bbox) >= 4 and frame_h > 0 and frame_w > 0:
        x1, y1, x2, y2 = (float(bbox[i]) for i in range(4))
        area_ratio = max(0.0, x2 - x1) * max(0.0, y2 - y1) / float(frame_h * frame_w)
    if area_ratio >= 0.10 and bucket != "large":
        return "truck"
    if bucket != "unknown":
        return n
    if area_ratio >= 0.035:
        return "car"
    return n or None


def plate_reliable(plate: str | None, score: float | None = None) -> bool:
    """车牌 OCR 是否可信：低分或过短视为噪声，不参与硬冲突/身份键。"""
    p = (plate or "").strip().upper()
    if not p or p in ("UNKNOWN", "NONE", "NULL"):
        return False
    if score is not None and float(score) < 0.55:
        return False
    if len(p) < 6:
        return False
    return any(c.isalnum() for c in p)


def fuse_plate_visual(
    *,
    plate: str | None,
    plate_score: float = 0.0,
    emb_a: np.ndarray | None = None,
    emb_b: np.ndarray | None = None,
    plate_weight: float = 0.7,
    visual_weight: float = 0.3,
) -> dict:
    """车牌优先 + 视觉相似度融合打分，生成 identity_key。

    注意：embedding 缺失时不再返回共享键 UNKNOWN|U（会导致全车撞同一个 Global ID），
    改为 None，由关联器走新建 ID。
    """
    plate_text = (plate or "").strip().upper() or None
    visual_sim = 0.0
    if emb_a is not None and emb_b is not None:
        a, b = _l2(emb_a), _l2(emb_b)
        dim = max(a.size, b.size)
        if a.size != dim:
            aa = np.zeros(dim, dtype=np.float32)
            aa[: a.size] = a
            a = aa
        if b.size != dim:
            bb = np.zeros(dim, dtype=np.float32)
            bb[: b.size] = b
            b = bb
        visual_sim = float(np.dot(a, b))

    plate_ok = plate_reliable(plate_text, plate_score)
    pw = float(plate_weight) if plate_ok else 0.0
    vw = float(visual_weight) if emb_a is not None else 0.0
    if pw + vw <= 1e-6:
        fuse = 0.0
    else:
        fuse = (pw * float(plate_score) + vw * max(0.0, visual_sim)) / (pw + vw)

    vkey = visual_key_from_embedding(emb_a) if emb_a is not None else None
    if plate_ok and vkey:
        identity = f"{plate_text}|{vkey}"
    elif plate_ok:
        identity = plate_text
    elif vkey:
        identity = f"NOPLATE|{vkey}"
    else:
        identity = None

    return {
        "plate": plate_text,
        "plateScore": round(float(plate_score or 0), 4),
        "visualScore": round(float(visual_sim), 4),
        "fuseScore": round(float(fuse), 4),
        "visualKey": vkey,
        "identityKey": identity,
        "plateOk": plate_ok,
    }


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    x, y = _l2(a), _l2(b)
    dim = max(x.size, y.size)
    xa = np.zeros(dim, dtype=np.float32)
    ya = np.zeros(dim, dtype=np.float32)
    xa[: x.size] = x
    ya[: y.size] = y
    return float(np.dot(xa, ya))
