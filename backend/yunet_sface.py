"""OpenCV Zoo YuNet 检测 + SFace 识别（与 InsightFace 并列的人脸后端）。

资产目录约定（uploads/models/opencv-yunet-sface/）：
  - face_detection_yunet_2023mar.onnx
  - face_recognition_sface_2021dec.onnx
"""
from __future__ import annotations

import os
import threading
import time

import cv2
import numpy as np

_lock = threading.Lock()
_detector_cache = {}   # (path, mtime) -> FaceDetectorYN
_recognizer_cache = {} # (path, mtime) -> FaceRecognizerSF

YUNET_NAME = "face_detection_yunet_2023mar.onnx"
SFACE_NAME = "face_recognition_sface_2021dec.onnx"

ASSET_URLS = {
    YUNET_NAME: [
        "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ],
    SFACE_NAME: [
        "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ],
}


def resolve_model_dir(path: str) -> str:
    if os.path.isdir(path):
        return path
    if os.path.isfile(path):
        return os.path.dirname(path)
    raise FileNotFoundError(f"模型路径不存在：{path}")


def list_assets(model_dir: str) -> dict:
    d = resolve_model_dir(model_dir)
    yunet = os.path.join(d, YUNET_NAME)
    sface = os.path.join(d, SFACE_NAME)
    return {
        "dir": d,
        "yunet": yunet,
        "sface": sface,
        "yunet_ok": os.path.isfile(yunet) and os.path.getsize(yunet) > 10_000,
        "sface_ok": os.path.isfile(sface) and os.path.getsize(sface) > 1_000_000,
    }


def assets_ready(model_dir: str) -> bool:
    a = list_assets(model_dir)
    return a["yunet_ok"] and a["sface_ok"]


def _download_one(urls, dest: str, timeout: int = 600, min_bytes: int = 1000) -> int:
    import requests

    if os.path.isfile(dest) and os.path.getsize(dest) > min_bytes:
        return os.path.getsize(dest)
    last_err = None
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    for url in urls:
        tmp = dest + ".part"
        try:
            resp = requests.get(url, stream=True, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
            if not os.path.isfile(tmp) or os.path.getsize(tmp) < min_bytes:
                raise ValueError(f"文件过小：{url}")
            os.replace(tmp, dest)
            return os.path.getsize(dest)
        except Exception as e:  # noqa: BLE001
            last_err = e
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            continue
    raise RuntimeError(f"下载失败 {os.path.basename(dest)}：{last_err}")


def download_assets(model_dir: str, timeout: int = 600) -> tuple[str, int]:
    os.makedirs(model_dir, exist_ok=True)
    total = 0
    total += _download_one(ASSET_URLS[YUNET_NAME], os.path.join(model_dir, YUNET_NAME),
                           timeout=timeout, min_bytes=50_000)
    total += _download_one(ASSET_URLS[SFACE_NAME], os.path.join(model_dir, SFACE_NAME),
                           timeout=timeout, min_bytes=1_000_000)
    if not assets_ready(model_dir):
        raise ValueError("YuNet/SFace 资产不完整，请重试拉取")
    return model_dir, total


def _get_detector(yunet_path: str, input_size: tuple[int, int], score_thresh: float):
    """FaceDetectorYN 按路径缓存；每次调用 setInputSize。"""
    mtime = os.path.getmtime(yunet_path)
    key = (yunet_path, mtime)
    with _lock:
        det = _detector_cache.get(key)
        if det is None:
            det = cv2.FaceDetectorYN.create(
                yunet_path,
                "",
                input_size,
                score_threshold=float(score_thresh),
                nms_threshold=0.3,
                top_k=5000,
            )
            _detector_cache[key] = det
        else:
            try:
                det.setScoreThreshold(float(score_thresh))
            except Exception:  # noqa: BLE001
                pass
        det.setInputSize(tuple(input_size))
        return det


def _get_recognizer(sface_path: str):
    mtime = os.path.getmtime(sface_path)
    key = (sface_path, mtime)
    with _lock:
        rec = _recognizer_cache.get(key)
        if rec is not None:
            return rec
        rec = cv2.FaceRecognizerSF.create(sface_path, "")
        _recognizer_cache[key] = rec
        return rec


def extract_embeddings(model_dir: str, image_bgr: np.ndarray, det_thresh: float = 0.6):
    """YuNet 检测 + SFace alignCrop/feature，返回 [{embedding,bbox,detScore,landmarks}]。"""
    from services.face_gallery import l2_normalize

    assets = list_assets(model_dir)
    if not assets["yunet_ok"] or not assets["sface_ok"]:
        raise FileNotFoundError("YuNet/SFace ONNX 未就绪，请先拉取权重")

    h, w = image_bgr.shape[:2]
    if h < 16 or w < 16:
        return []

    t0 = time.perf_counter()
    detector = _get_detector(assets["yunet"], (w, h), det_thresh)
    _retval, faces = detector.detect(image_bgr)
    det_ms = (time.perf_counter() - t0) * 1000.0

    if faces is None or len(faces) == 0:
        return [], {"detMs": round(det_ms, 2), "featMs": 0.0, "backend": "opencv-yunet-sface"}

    recognizer = _get_recognizer(assets["sface"])
    out = []
    t1 = time.perf_counter()
    for row in faces:
        score = float(row[-1])
        if score < float(det_thresh):
            continue
        # row: x,y,w,h, 5 landmarks (x,y)*5, score
        x, y, bw, bh = float(row[0]), float(row[1]), float(row[2]), float(row[3])
        bbox = [x, y, x + bw, y + bh]
        try:
            aligned = recognizer.alignCrop(image_bgr, row)
            feat = recognizer.feature(aligned)
            emb = l2_normalize(np.asarray(feat, dtype=np.float32).reshape(-1))
        except Exception:  # noqa: BLE001
            continue
        out.append({
            "embedding": emb,
            "bbox": bbox,
            "detScore": round(score, 4),
            "landmarks": [float(v) for v in row[4:14].tolist()],
        })
    feat_ms = (time.perf_counter() - t1) * 1000.0
    meta = {
        "detMs": round(det_ms, 2),
        "featMs": round(feat_ms, 2),
        "backend": "opencv-yunet-sface",
        "dim": int(out[0]["embedding"].size) if out else 0,
    }
    return out, meta
