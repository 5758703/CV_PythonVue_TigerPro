"""车辆视觉 ReID（TransReID / CLIP-ReID / ViT 风格 ONNX）+ 车牌融合打分。

身份键只采用可靠车牌；视觉哈希仅用于诊断，不参与跨帧身份键。
"""
from __future__ import annotations

import hashlib
import os
import re
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
    """将 embedding 量化为短视觉诊断键。

    该值只用于排障展示；浮点字节哈希不具备跨帧身份稳定性。
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
    """硬冲突仅限 large(truck/bus) ↔ car/motor。

    motorcycle↔car 不冲突：YOLO 常把轿车/SUV 误标摩托，硬拦会阻断跨镜合并。
    """
    ba, bb = vehicle_class_bucket(a), vehicle_class_bucket(b)
    if ba == "unknown" or bb == "unknown":
        return False
    if ba == bb:
        return False
    # 仅货车/客车与小车/摩托互斥
    if {ba, bb} == {"large", "car"} or {ba, bb} == {"large", "motor"}:
        return True
    return False


def infer_vehicle_class(
    class_name: str | None,
    bbox: list | tuple | None = None,
    *,
    frame_h: int = 0,
    frame_w: int = 0,
) -> str | None:
    """检测类 + 框面积启发式，缓解 YOLO 将货车误标为 car / 轿车误标摩托。"""
    n = (class_name or "").strip().lower()
    bucket = vehicle_class_bucket(n)
    area_ratio = 0.0
    if bbox is not None and len(bbox) >= 4 and frame_h > 0 and frame_w > 0:
        x1, y1, x2, y2 = (float(bbox[i]) for i in range(4))
        area_ratio = max(0.0, x2 - x1) * max(0.0, y2 - y1) / float(frame_h * frame_w)
    # 大框摩托多为误检（轿车/SUV），升为 car
    if bucket == "motor" and area_ratio >= 0.04:
        return "car"
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


def normalize_vehicle_plate_text(text: str | None) -> str:
    """Normalize OCR punctuation and common alphanumeric confusions per plate."""
    plate = re.sub(r"\s+", "", (text or "").upper())
    plate = re.sub(r"[^0-9A-Z\u4e00-\u9fff]", "", plate)
    if len(plate) <= 2:
        return plate
    # Preserve the province and following letter; OCR confusions are only
    # unambiguous in the serial portion of a Chinese vehicle plate.
    return plate[:2] + plate[2:].translate(str.maketrans({
        "O": "0", "D": "0", "Q": "0", "I": "1", "L": "1",
        "B": "8", "S": "5", "Z": "2",
    }))


def aggregate_vehicle_plate_votes(observations) -> tuple[str | None, float]:
    """Return the highest-confidence normalized multi-observation plate vote."""
    votes: dict[str, list[float]] = {}
    for observation in observations or ():
        if isinstance(observation, dict):
            text, score = observation.get("text"), observation.get("score")
        else:
            text, score = observation
        plate = normalize_vehicle_plate_text(text)
        if plate:
            votes.setdefault(plate, []).append(max(0.0, float(score or 0.0)))
    if not votes:
        return None, 0.0
    plate, scores = max(votes.items(), key=lambda item: (sum(item[1]), len(item[1]), item[0]))
    return plate, sum(scores) / len(scores)


def fuse_plate_visual(
    *,
    plate: str | None,
    plate_score: float = 0.0,
    emb_a: np.ndarray | None = None,
    emb_b: np.ndarray | None = None,
    plate_weight: float = 0.7,
    visual_weight: float = 0.3,
    model_space_a: tuple[str, int, str | None] | None = None,
    model_space_b: tuple[str, int, str | None] | None = None,
) -> dict:
    """车牌优先 + 视觉相似度融合打分，生成 identity_key。

    注意：embedding 缺失时不再返回共享键 UNKNOWN|U（会导致全车撞同一个 Global ID），
    改为 None，由关联器走新建 ID。
    """
    plate_text = (plate or "").strip().upper() or None
    visual_sim = 0.0
    comparable_visual = False
    if emb_a is not None and emb_b is not None:
        a, b = _l2(emb_a), _l2(emb_b)
        spaces_match = (
            model_space_a == model_space_b
            if model_space_a is not None or model_space_b is not None
            else True
        )
        declared_dims_match = (
            (model_space_a is None or int(model_space_a[1]) == int(a.size))
            and (model_space_b is None or int(model_space_b[1]) == int(b.size))
        )
        if spaces_match and declared_dims_match and a.size == b.size:
            visual_sim = float(np.dot(a, b))
            comparable_visual = True

    plate_ok = plate_reliable(plate_text, plate_score)
    pw = float(plate_weight) if plate_ok else 0.0
    vw = float(visual_weight) if comparable_visual else 0.0
    if pw + vw <= 1e-6:
        fuse = 0.0
    else:
        fuse = (pw * float(plate_score) + vw * max(0.0, visual_sim)) / (pw + vw)

    vkey = visual_key_from_embedding(emb_a) if emb_a is not None else None
    identity = plate_text if plate_ok else None

    return {
        "plate": plate_text,
        "plateScore": round(float(plate_score or 0), 4),
        "visualScore": round(float(visual_sim), 4),
        "fuseScore": round(float(fuse), 4),
        "visualKey": vkey,
        "identityKey": identity,
        "plateOk": plate_ok,
    }


def cosine(a: np.ndarray, b: np.ndarray) -> float | None:
    x, y = _l2(a), _l2(b)
    if x.size != y.size:
        return None
    return float(np.dot(x, y))


def vehicle_candidate_score(
    tracklet_embedding: np.ndarray,
    candidate_prototype: np.ndarray,
    *,
    model_space_a: tuple[str, int, str | None] | None = None,
    model_space_b: tuple[str, int, str | None] | None = None,
) -> float | None:
    """Visual evidence is a tracklet-to-candidate comparison, never self-score."""
    if model_space_a is not None or model_space_b is not None:
        if model_space_a != model_space_b:
            return None
        if model_space_a is None:
            return None
        if (
            int(np.asarray(tracklet_embedding).size) != int(model_space_a[1])
            or int(np.asarray(candidate_prototype).size) != int(model_space_a[1])
        ):
            return None
    return cosine(tracklet_embedding, candidate_prototype)
