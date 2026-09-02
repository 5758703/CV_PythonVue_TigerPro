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
    shape = list(inp.shape)  # NCHW
    if len(shape) != 4:
        raise ValueError(f"expected NCHW input, got {shape!r}")
    try:
        h, w = int(shape[2]), int(shape[3])
    except (TypeError, ValueError) as e:
        raise ValueError(f"ONNX input has dynamic spatial dimensions: {shape!r}") from e
    if h <= 0 or w <= 0:
        raise ValueError(f"ONNX input has invalid spatial dimensions: {shape!r}")
    blob = _preprocess(image_bgr, w, h)
    out = sess.run([sess.get_outputs()[0].name], {inp.name: blob})[0]
    feat = np.asarray(out, dtype=np.float32).reshape(-1)
    if feat.size == 0:
        raise ValueError("ONNX model returned an empty embedding")
    return feat


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
        meta = dict(meta or {})
        meta.setdefault("modelVersion", meta.get("onnx"))
        return _l2(feat), meta
    except Exception as e:  # noqa: BLE001
        return None, {"youtuError": str(e)}


def extract_strong(strong_root: str | None, image_bgr: np.ndarray) -> tuple[np.ndarray | None, dict]:
    onnx = resolve_strong_onnx(strong_root)
    if not onnx:
        return None, {"strong": False}
    try:
        feat = _infer_onnx(onnx, image_bgr)
        return _l2(feat), {
            "strong": True,
            "onnx": os.path.basename(onnx),
            "modelKey": _strong_model_key(onnx),
            "modelVersion": os.path.basename(onnx),
            "dim": int(feat.size),
        }
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


def _strong_model_key(onnx_path: str) -> str:
    """Return the stable gallery/model-space key for a strong ONNX asset."""
    name = os.path.basename(onnx_path).lower()
    if "clip" in name:
        return "clip-reid-person"
    if "fastreid" in name:
        return "fastreid-osnet"
    if "osnet" in name:
        return "osnet-x1-0"
    return f"strong-onnx:{name}"


def _backend_status(meta: dict, error_key: str) -> dict:
    error = meta.get(error_key)
    if error:
        return {"ready": False, "error": str(error)}
    return {"ready": False}


def extract_person_embeddings(
    image_bgr: np.ndarray,
    *,
    youtu_root: str | None = None,
    strong_root: str | None = None,
) -> tuple[dict[str, np.ndarray], dict]:
    """Extract independent embeddings keyed by their stable model spaces."""
    strong, strong_meta = extract_strong(strong_root, image_bgr)
    youtu, youtu_meta = extract_youtu(youtu_root, image_bgr)
    spaces: dict[str, np.ndarray] = {}
    backends = {
        "strong": _backend_status(strong_meta, "strongError"),
        "youtu": _backend_status(youtu_meta, "youtuError"),
    }

    if strong is not None:
        key = str(strong_meta.get("modelKey") or _strong_model_key(strong_meta.get("onnx") or "unknown.onnx"))
        spaces[key] = _l2(strong)
        backends["strong"] = {"ready": True, "modelKey": key, "modelVersion": strong_meta.get("modelVersion"), "dim": int(spaces[key].size)}
    if youtu is not None:
        key = "opencv-person-reid-youtu"
        spaces[key] = _l2(youtu)
        backends["youtu"] = {
            "ready": True,
            "modelKey": key,
            "modelVersion": youtu_meta.get("modelVersion"),
            "dim": int(spaces[key].size),
        }

    best_key = next(iter(spaces), None)
    versions_by_space = {
        key: (strong_meta.get("modelVersion") if key != "opencv-person-reid-youtu" else youtu_meta.get("modelVersion"))
        for key in spaces
    }
    return spaces, {
        **youtu_meta,
        **strong_meta,
        "backends": backends,
        "availableModelSpaces": list(spaces),
        "modelVersionsBySpace": versions_by_space,
        "bestModelKey": best_key,
        "associationModelKey": best_key,
        "activeBackend": "strong" if strong is not None else ("youtu" if youtu is not None else None),
        "backend": "strong" if strong is not None else ("youtu" if youtu is not None else None),
        "dim": int(spaces[best_key].size) if best_key else 0,
    }


def fuse_similarity_scores(scores, weights) -> float | None:
    """Fuse calibrated per-space scores while renormalizing available weights."""
    weighted_scores: list[tuple[float, float]] = []
    weight_map = dict(weights or {})
    for key, score in dict(scores or {}).items():
        if score is None:
            continue
        try:
            score_f, weight_f = float(score), float(weight_map.get(key))
        except (TypeError, ValueError):
            continue
        if not np.isfinite(score_f) or not np.isfinite(weight_f) or weight_f <= 0:
            continue
        weighted_scores.append((score_f, weight_f))
    if not weighted_scores:
        return None
    total_weight = sum(weight for _, weight in weighted_scores)
    return sum(score * weight for score, weight in weighted_scores) / total_weight


def extract_person_embedding(
    image_bgr: np.ndarray,
    *,
    youtu_root: str | None = None,
    strong_root: str | None = None,
    fuse_weight_strong: float = 0.65,
) -> tuple[np.ndarray, dict]:
    """Compatibility wrapper returning the best single, unmodified space."""
    del fuse_weight_strong
    spaces, meta = extract_person_embeddings(
        image_bgr, youtu_root=youtu_root, strong_root=strong_root,
    )
    key = meta.get("bestModelKey")
    if key is not None:
        return spaces[key], {**meta, "modelKey": key}
    raise RuntimeError("无可用行人 ReID 后端（强模型与 Youtu 均不可用）")


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    x, y = _l2(a), _l2(b)
    if x.size != y.size:
        raise ValueError("cannot compare embeddings from different dimensions/model spaces")
    return float(np.dot(x, y))
