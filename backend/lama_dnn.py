"""OpenCV Zoo LaMa 图像修复（inpainting）：cv2.dnn ONNX 优先，失败回退 ONNX Runtime。

资产目录（uploads/models/inpainting-lama/）：
  - inpainting_lama_2025jan.onnx
参考：https://huggingface.co/opencv/inpainting_lama
"""
from __future__ import annotations

import os
import threading
import time

import cv2
import numpy as np

_lock = threading.Lock()
_net_cache = {}  # (path, mtime, backend) -> net_or_session

INPUT_SIZE = 512
ONNX_NAME = "inpainting_lama_2025jan.onnx"

ASSET_URLS = {
    ONNX_NAME: [
        "https://huggingface.co/opencv/inpainting_lama/resolve/main/inpainting_lama_2025jan.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/inpainting_lama/inpainting_lama_2025jan.onnx",
        "https://hf-mirror.com/opencv/inpainting_lama/resolve/main/inpainting_lama_2025jan.onnx",
    ],
}


def resolve_model_dir(path: str) -> str:
    if os.path.isdir(path):
        return path
    if os.path.isfile(path):
        return os.path.dirname(path)
    raise FileNotFoundError(f"模型路径不存在：{path}")


def resolve_onnx(path: str) -> str:
    if os.path.isfile(path) and path.lower().endswith(".onnx"):
        return path
    d = resolve_model_dir(path)
    p = os.path.join(d, ONNX_NAME)
    if os.path.isfile(p) and os.path.getsize(p) > 1_000_000:
        return p
    # 目录内任意较大 onnx 兜底
    if os.path.isdir(d):
        for name in os.listdir(d):
            if name.lower().endswith(".onnx"):
                fp = os.path.join(d, name)
                if os.path.isfile(fp) and os.path.getsize(fp) > 1_000_000:
                    return fp
    raise FileNotFoundError(f"目录中未找到 LaMa ONNX：{d}")


def assets_ready(model_dir: str) -> bool:
    try:
        resolve_onnx(model_dir)
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


def download_assets(model_dir: str, timeout: int = 900) -> tuple[str, int]:
    os.makedirs(model_dir, exist_ok=True)
    total = _download_one(ASSET_URLS[ONNX_NAME], os.path.join(model_dir, ONNX_NAME), timeout=timeout)
    if not assets_ready(model_dir):
        raise ValueError("LaMa 资产不完整，请重试拉取")
    return model_dir, total


def _get_opencv_net(onnx_path: str):
    mtime = os.path.getmtime(onnx_path)
    key = (onnx_path, mtime, "opencv")
    with _lock:
        hit = _net_cache.get(key)
        if hit is not None:
            return hit
        net = cv2.dnn.readNetFromONNX(onnx_path)
        try:
            net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        except Exception:  # noqa: BLE001
            pass
        _net_cache[key] = net
        return net


def _prepare_blobs(image_bgr: np.ndarray, mask_u8: np.ndarray):
    """与 OpenCV Zoo lama.py 一致：image 0.00392→512，mask 二值 float。"""
    if mask_u8.ndim == 3:
        mask_u8 = cv2.cvtColor(mask_u8, cv2.COLOR_BGR2GRAY)
    if mask_u8.shape[:2] != image_bgr.shape[:2]:
        mask_u8 = cv2.resize(mask_u8, (image_bgr.shape[1], image_bgr.shape[0]),
                             interpolation=cv2.INTER_NEAREST)
    image_blob = cv2.dnn.blobFromImage(
        image_bgr, 0.00392, (INPUT_SIZE, INPUT_SIZE), (0, 0, 0), swapRB=False, crop=False)
    mask_blob = cv2.dnn.blobFromImage(
        mask_u8, scalefactor=1.0, size=(INPUT_SIZE, INPUT_SIZE), mean=(0,),
        swapRB=False, crop=False)
    mask_blob = (mask_blob > 0).astype(np.float32)
    return image_blob, mask_blob


def _postprocess(output, orig_h: int, orig_w: int) -> np.ndarray:
    """CHW → HWC uint8，再缩放到原图尺寸（产品展示用；Zoo demo 仅按宽高比缩放）。"""
    arr = np.asarray(output)
    while arr.ndim > 3:
        arr = arr[0]
    if arr.ndim == 3 and arr.shape[0] in (1, 3, 4):
        hwc = np.transpose(arr, (1, 2, 0))
    elif arr.ndim == 3:
        hwc = arr
    else:
        raise ValueError(f"意外的 LaMa 输出形状：{getattr(output, 'shape', None)}")
    if hwc.shape[2] > 3:
        hwc = hwc[:, :, :3]
    if hwc.dtype != np.uint8:
        mx = float(np.nanmax(hwc)) if hwc.size else 0.0
        if mx <= 1.5:
            hwc = (np.clip(hwc, 0, 1) * 255.0).astype(np.uint8)
        else:
            hwc = np.clip(hwc, 0, 255).astype(np.uint8)
    if hwc.shape[0] != orig_h or hwc.shape[1] != orig_w:
        hwc = cv2.resize(hwc, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
    return hwc


def _forward_opencv(net, image_blob, mask_blob):
    with _lock:
        net.setInput(image_blob, "image")
        net.setInput(mask_blob, "mask")
        return net.forward()


def _forward_ort(onnx_path, image_blob, mask_blob):
    import onnxruntime as ort

    mtime = os.path.getmtime(onnx_path)
    key = (onnx_path, mtime, "ort")
    with _lock:
        sess = _net_cache.get(key)
        if sess is None:
            sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
            _net_cache[key] = sess
        feeds = {}
        for inp in sess.get_inputs():
            name = (inp.name or "").lower()
            if "mask" in name:
                feeds[inp.name] = mask_blob.astype(np.float32)
            else:
                feeds[inp.name] = image_blob.astype(np.float32)
        outs = sess.run(None, feeds)
        return outs[0] if len(outs) == 1 else outs


def expand_mask(mask_u8: np.ndarray, dilate_px: int) -> np.ndarray:
    """形态学外扩遮罩（椭圆核），便于罩住毛发/软边缘。dilate_px<=0 则原样返回。"""
    if mask_u8 is None or mask_u8.size == 0:
        return mask_u8
    px = int(dilate_px or 0)
    if px <= 0:
        return mask_u8
    if mask_u8.ndim == 3:
        gray = cv2.cvtColor(mask_u8, cv2.COLOR_BGR2GRAY)
    else:
        gray = mask_u8
    binary = (gray > 0).astype(np.uint8) * 255
    # 核边长约 2*r+1，使「外扩半径」接近 dilate_px
    k = max(3, int(px) * 2 + 1)
    if k % 2 == 0:
        k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    return cv2.dilate(binary, kernel, iterations=1)


def inpaint(model_path: str, image_bgr: np.ndarray, mask_u8: np.ndarray, dilate_px: int = 0):
    """返回 (result_bgr HxWx3, meta)。mask 非零区域为待修复。

    dilate_px>0 时先对外扩遮罩再推理，减轻毛发/软边残留。
    """
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("无效图片")
    if mask_u8 is None or mask_u8.size == 0:
        raise ValueError("请提供修复遮罩（涂抹待修复区域）")
    if mask_u8.ndim == 3:
        mask_u8 = cv2.cvtColor(mask_u8, cv2.COLOR_BGR2GRAY)
    mask_before = int(np.count_nonzero(mask_u8 > 0))
    if mask_before <= 0:
        raise ValueError("遮罩为空：请先涂抹需要修复的区域")

    dilate_px = max(0, min(int(dilate_px or 0), 128))
    mask_use = expand_mask(mask_u8, dilate_px) if dilate_px > 0 else mask_u8

    onnx = resolve_onnx(model_path)
    h, w = image_bgr.shape[:2]
    image_blob, mask_blob = _prepare_blobs(image_bgr, mask_use)

    t0 = time.perf_counter()
    backend = "opencv"
    try:
        net = _get_opencv_net(onnx)
        out = _forward_opencv(net, image_blob, mask_blob)
    except Exception as e_cv:  # noqa: BLE001
        try:
            out = _forward_ort(onnx, image_blob, mask_blob)
            backend = "ort"
        except Exception as e_ort:  # noqa: BLE001
            raise RuntimeError(f"LaMa 推理失败（opencv: {e_cv}; ort: {e_ort})") from e_ort
    latency = (time.perf_counter() - t0) * 1000.0

    if isinstance(out, (list, tuple)):
        out = out[0]
    result = _postprocess(out, h, w)
    meta = {
        "latencyMs": round(latency, 2),
        "onnx": os.path.basename(onnx),
        "backend": f"lama-{backend}",
        "inputSize": INPUT_SIZE,
        "width": w,
        "height": h,
        "maskPixels": int(np.count_nonzero(mask_use > 0)),
        "maskPixelsBefore": mask_before,
        "dilatePx": dilate_px,
        "expandedMask": mask_use,  # 调用方可选用；序列化前需弹出
    }
    return result, meta
