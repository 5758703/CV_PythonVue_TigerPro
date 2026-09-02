"""OpenCV Zoo Youtu Person ReID：cv2.dnn ONNX 优先，失败回退 ONNX Runtime。

资产目录（uploads/models/opencv-person-reid-youtu/）：
  - person_reid_youtu_2021nov.onnx          FP（优先）
  - person_reid_youtu_2021nov_int8bq.onnx   INT8 block-quant（可选）
参考：https://huggingface.co/opencv/person_reid_youtureid
"""
from __future__ import annotations

import os
import threading
import time

import cv2
import numpy as np

_lock = threading.Lock()
_net_cache = {}  # (path, mtime, backend) -> net_or_session

INPUT_W, INPUT_H = 128, 256
OUTPUT_DIM = 768
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)

FP32_NAME = "person_reid_youtu_2021nov.onnx"
INT8BQ_NAME = "person_reid_youtu_2021nov_int8bq.onnx"
INT8_NAME = "person_reid_youtu_2021nov_int8.onnx"

ASSET_URLS = {
    FP32_NAME: [
        "https://huggingface.co/opencv/person_reid_youtureid/resolve/main/person_reid_youtu_2021nov.onnx",
        "https://hf-mirror.com/opencv/person_reid_youtureid/resolve/main/person_reid_youtu_2021nov.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/person_reid_youtureid/person_reid_youtu_2021nov.onnx",
    ],
    INT8BQ_NAME: [
        "https://huggingface.co/opencv/person_reid_youtureid/resolve/main/person_reid_youtu_2021nov_int8bq.onnx",
        "https://hf-mirror.com/opencv/person_reid_youtureid/resolve/main/person_reid_youtu_2021nov_int8bq.onnx",
    ],
}


def resolve_model_dir(path: str) -> str:
    if os.path.isdir(path):
        return path
    if os.path.isfile(path):
        return os.path.dirname(path)
    raise FileNotFoundError(f"模型路径不存在：{path}")


def resolve_onnx(path: str, prefer: str = "fp32") -> str:
    """prefer: fp32 | int8bq | auto（有 fp32 用 fp32，否则 int8bq）。"""
    if os.path.isfile(path) and path.lower().endswith(".onnx"):
        return path
    d = resolve_model_dir(path)
    candidates = []
    if prefer == "int8bq":
        candidates = [INT8BQ_NAME, INT8_NAME, FP32_NAME]
    elif prefer == "auto":
        candidates = [FP32_NAME, INT8BQ_NAME, INT8_NAME]
    else:
        candidates = [FP32_NAME, INT8BQ_NAME, INT8_NAME]
    for name in candidates:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.path.getsize(p) > 1_000_000:
            return p
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.lower().endswith(".onnx"):
                fp = os.path.join(d, name)
                if os.path.isfile(fp) and os.path.getsize(fp) > 1_000_000:
                    return fp
    raise FileNotFoundError(f"目录中未找到 Youtu ReID ONNX：{d}")


def assets_ready(model_dir: str) -> bool:
    try:
        resolve_onnx(model_dir, prefer="auto")
        return True
    except Exception:  # noqa: BLE001
        return False


def _download_one(urls, dest: str, timeout: int = 900, min_bytes: int = 1_000_000) -> int:
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


def download_assets(model_dir: str, timeout: int = 900, with_int8: bool = True) -> tuple[str, int]:
    os.makedirs(model_dir, exist_ok=True)
    total = 0
    total += _download_one(
        ASSET_URLS[FP32_NAME],
        os.path.join(model_dir, FP32_NAME),
        timeout=timeout,
        min_bytes=10_000_000,
    )
    if with_int8:
        try:
            total += _download_one(
                ASSET_URLS[INT8BQ_NAME],
                os.path.join(model_dir, INT8BQ_NAME),
                timeout=timeout,
                min_bytes=5_000_000,
            )
        except Exception:  # noqa: BLE001
            pass
    if not assets_ready(model_dir):
        raise ValueError("Youtu ReID 资产不完整，请重试拉取")
    return model_dir, total


def _get_opencv_net(onnx_path: str):
    mtime = os.path.getmtime(onnx_path)
    key = (onnx_path, mtime, "opencv")
    with _lock:
        net = _net_cache.get(key)
        if net is not None:
            return net
        net = cv2.dnn.readNetFromONNX(onnx_path)
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        _net_cache[key] = net
        return net


def _get_ort_session(onnx_path: str):
    import onnxruntime as ort

    mtime = os.path.getmtime(onnx_path)
    key = (onnx_path, mtime, "ort")
    with _lock:
        sess = _net_cache.get(key)
        if sess is not None:
            return sess
        sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        _net_cache[key] = sess
        return sess


def preprocess_crop(image_bgr: np.ndarray) -> np.ndarray:
    """行人裁剪 → NCHW float32 blob（RGB + ImageNet normalize）。"""
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("空裁剪图")
    img = cv2.resize(image_bgr, (INPUT_W, INPUT_H), interpolation=cv2.INTER_LINEAR)
    rgb = img[:, :, ::-1].astype(np.float32) / 255.0
    rgb = (rgb - np.asarray(MEAN, dtype=np.float32)) / np.asarray(STD, dtype=np.float32)
    # HWC → NCHW
    blob = np.transpose(rgb, (2, 0, 1))[None, ...].astype(np.float32)
    return blob


def _forward_opencv(net, blob: np.ndarray) -> np.ndarray:
    with _lock:
        net.setInput(blob)
        out = net.forward()
    return np.asarray(out, dtype=np.float32)


def _forward_ort(onnx_path: str, blob: np.ndarray) -> np.ndarray:
    sess = _get_ort_session(onnx_path)
    inp = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name
    out = sess.run([out_name], {inp: blob})[0]
    return np.asarray(out, dtype=np.float32)


def extract_feature(model_path: str, image_bgr: np.ndarray, prefer: str = "fp32"):
    """返回 (embedding float32 [D], meta)。"""
    onnx = resolve_onnx(model_path, prefer=prefer)
    blob = preprocess_crop(image_bgr)
    t0 = time.perf_counter()
    backend = "opencv"
    try:
        net = _get_opencv_net(onnx)
        out = _forward_opencv(net, blob)
    except Exception as e_cv:  # noqa: BLE001
        try:
            out = _forward_ort(onnx, blob)
            backend = "ort"
        except Exception as e_ort:  # noqa: BLE001
            raise RuntimeError(f"Youtu ReID 推理失败（opencv: {e_cv}; ort: {e_ort})") from e_ort
    latency = (time.perf_counter() - t0) * 1000.0
    feat = np.asarray(out, dtype=np.float32).reshape(-1)
    if feat.size == 0:
        raise RuntimeError("ReID 输出为空")
    meta = {
        "latencyMs": round(latency, 2),
        "onnx": os.path.basename(onnx),
        "backend": f"youtu-reid-{backend}",
        "provider": "opencv-dnn-cpu" if backend == "opencv" else "onnxruntime-cpu",
        "dim": int(feat.size),
        "inputSize": [INPUT_W, INPUT_H],
    }
    return feat, meta
