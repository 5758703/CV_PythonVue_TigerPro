"""强行人 ReID：OSNet / CLIP-ReID 风格 ONNX + 并联 Youtu。

优先使用本地强模型 ONNX；不可用时回退 Youtu；两者皆可用时加权融合。
"""
from __future__ import annotations

import os
import threading
from typing import Any

import cv2
import numpy as np

_lock = threading.Lock()
_sess_cache: dict[tuple, Any] = {}

# OSNet / CLIP-ReID 常见输入
OSNET_W, OSNET_H = 128, 256
CLIP_W, CLIP_H = 224, 224
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)

STRONG_NAMES = (
    "osnet_x1_0.onnx",
    "osnet_x1_0_market.onnx",
    "osnet_ain_x1_0.onnx",
    "clip_reid.onnx",
    "clip_reid_person.onnx",
    "person_vit_clip_reid.onnx",
    "fastreid_osnet.onnx",
    "person_reid_strong.onnx",
)


def resolve_strong_onnx(model_path: str | None) -> str | None:
    if not model_path:
        return None
    if os.path.isfile(model_path) and model_path.lower().endswith(".onnx"):
        return model_path if os.path.getsize(model_path) > 100_000 else None
    if not os.path.isdir(model_path):
        return None
    for name in STRONG_NAMES:
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
    return resolve_strong_onnx(model_path) is not None


def _get_ort(onnx_path: str):
    import onnxruntime as ort

    mtime = os.path.getmtime(onnx_path)
    key = (onnx_path, mtime, "ort")
    with _lock:
        sess = _sess_cache.get(key)
        if sess is not None:
            return sess
        sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        _sess_cache[key] = sess
        return sess


def _preprocess(image_bgr: np.ndarray, w: int, h: int) -> np.ndarray:
    img = cv2.resize(image_bgr, (w, h), interpolation=cv2.INTER_LINEAR)
    rgb = img[:, :, ::-1].astype(np.float32) / 255.0
    rgb = (rgb - np.asarray(MEAN, dtype=np.float32)) / np.asarray(STD, dtype=np.float32)
    return np.transpose(rgb, (2, 0, 1))[None, ...].astype(np.float32)


def _infer_onnx(onnx_path: str, image_bgr: np.ndarray) -> np.ndarray:
    sess = _get_ort(onnx_path)
    inp = sess.get_inputs()[0]
    shape = inp.shape  # NCHW
    # 兼容 OSNet(128x256) 与 CLIP(224x224)
    try:
        h = int(shape[2]) if isinstance(shape[2], int) else OSNET_H
        w = int(shape[3]) if isinstance(shape[3], int) else OSNET_W
    except Exception:  # noqa: BLE001
        h, w = OSNET_H, OSNET_W
    if max(h, w) >= 200:
        h, w = CLIP_H, CLIP_W
    else:
        h, w = OSNET_H, OSNET_W
    blob = _preprocess(image_bgr, w, h)
    out = sess.run([sess.get_outputs()[0].name], {inp.name: blob})[0]
    return np.asarray(out, dtype=np.float32).reshape(-1)


def _l2(v: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(a))
    if n < eps:
        return a
    return a / n


def _pad_or_trim(v: np.ndarray, dim: int) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32).reshape(-1)
    if a.size == dim:
        return a
    if a.size > dim:
        return a[:dim]
    out = np.zeros(dim, dtype=np.float32)
    out[: a.size] = a
    return out


def extract_youtu(youtu_root: str | None, image_bgr: np.ndarray) -> tuple[np.ndarray | None, dict]:
    if not youtu_root:
        return None, {}
    try:
        from person_reid_dnn import extract_feature
        feat, meta = extract_feature(youtu_root, image_bgr)
        return _l2(feat), dict(meta or {})
    except Exception as e:  # noqa: BLE001
        return None, {"youtuError": str(e)}


def extract_strong(strong_root: str | None, image_bgr: np.ndarray) -> tuple[np.ndarray | None, dict]:
    onnx = resolve_strong_onnx(strong_root)
    if not onnx:
        return None, {"strong": False}
    try:
        feat = _infer_onnx(onnx, image_bgr)
        return _l2(feat), {"strong": True, "onnx": os.path.basename(onnx), "dim": int(feat.size)}
    except Exception as e:  # noqa: BLE001
        return None, {"strong": False, "strongError": str(e)}


def color_signature(image_bgr: np.ndarray | None) -> np.ndarray | None:
    """HSV 颜色直方图签名（行人跨镜弱外观时的软线索）。"""
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        return None
    import cv2

    h, w = image_bgr.shape[:2]
    if h < 8 or w < 8:
        return None
    # 取中部躯干区域，减轻背景干扰
    y0, y1 = int(h * 0.15), int(h * 0.75)
    x0, x1 = int(w * 0.2), int(w * 0.8)
    roi = image_bgr[y0:y1, x0:x1]
    if roi.size == 0:
        roi = image_bgr
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hist_h = cv2.calcHist([hsv], [0], None, [16], [0, 180]).reshape(-1)
    hist_s = cv2.calcHist([hsv], [1], None, [8], [0, 256]).reshape(-1)
    hist_v = cv2.calcHist([hsv], [2], None, [8], [0, 256]).reshape(-1)
    sig = np.concatenate([hist_h, hist_s, hist_v]).astype(np.float32)
    n = float(np.linalg.norm(sig))
    return sig / n if n > 1e-6 else sig


def color_sig_cosine(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return -1.0
    return float(np.dot(_l2(a), _l2(b)))


def extract_person_embedding(
    image_bgr: np.ndarray,
    *,
    youtu_root: str | None = None,
    strong_root: str | None = None,
    fuse_weight_strong: float = 0.65,
) -> tuple[np.ndarray, dict]:
    """并联强 ReID 与 Youtu：均可用则加权融合到统一维度；否则取可用者。"""
    strong, sm = extract_strong(strong_root, image_bgr)
    youtu, ym = extract_youtu(youtu_root, image_bgr)
    meta = {**ym, **sm}

    if strong is not None and youtu is not None:
        dim = max(int(strong.size), int(youtu.size))
        s = _pad_or_trim(strong, dim)
        y = _pad_or_trim(youtu, dim)
        w = float(np.clip(fuse_weight_strong, 0.0, 1.0))
        fused = _l2(w * s + (1.0 - w) * y)
        meta.update({"backend": "strong+youtu", "dim": int(fused.size), "fuseWeightStrong": w})
        return fused, meta
    if strong is not None:
        meta.update({"backend": "strong", "dim": int(strong.size)})
        return strong, meta
    if youtu is not None:
        meta.update({"backend": "youtu", "dim": int(youtu.size)})
        return youtu, meta
    raise RuntimeError("无可用行人 ReID 后端（强模型与 Youtu 均不可用）")


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    x, y = _l2(a), _l2(b)
    dim = max(x.size, y.size)
    return float(np.dot(_pad_or_trim(x, dim), _pad_or_trim(y, dim)))
