"""OpenCV Zoo EfficientSAM-Ti：交互式分割（点/框），cv2.dnn ONNX。

资产目录（uploads/models/efficient-sam/）：
  - image_segmentation_efficientsam_ti_2025april.onnx      （推荐，多点/框）
  - image_segmentation_efficientsam_ti_2025april_int8.onnx （可选）
参考：https://huggingface.co/opencv/image_segmentation_efficientsam
"""
from __future__ import annotations

import os
import threading
import time

import cv2
import numpy as np

_lock = threading.Lock()
_net_cache = {}  # (path, mtime) -> net

INPUT_SIZE = 1024
MAX_POINTS = 6

ONNX_FP32 = "image_segmentation_efficientsam_ti_2025april.onnx"
ONNX_INT8 = "image_segmentation_efficientsam_ti_2025april_int8.onnx"
ONNX_LEGACY = "image_segmentation_efficientsam_ti_2024may.onnx"

ASSET_URLS = {
    ONNX_FP32: [
        "https://huggingface.co/opencv/image_segmentation_efficientsam/resolve/main/"
        "image_segmentation_efficientsam_ti_2025april.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/image_segmentation_efficientsam/"
        "image_segmentation_efficientsam_ti_2025april.onnx",
    ],
    ONNX_INT8: [
        "https://huggingface.co/opencv/image_segmentation_efficientsam/resolve/main/"
        "image_segmentation_efficientsam_ti_2025april_int8.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/image_segmentation_efficientsam/"
        "image_segmentation_efficientsam_ti_2025april_int8.onnx",
    ],
}

INPUT_NAMES = ["batched_images", "batched_point_coords", "batched_point_labels"]
OUTPUT_NAMES = ["output_masks", "iou_predictions"]


def resolve_model_dir(path: str) -> str:
    if os.path.isdir(path):
        return path
    if os.path.isfile(path):
        return os.path.dirname(path)
    raise FileNotFoundError(f"模型路径不存在：{path}")


def resolve_onnx(path: str, precision: str = "fp32") -> str:
    """path 可为目录或 .onnx 文件。"""
    if os.path.isfile(path) and path.lower().endswith(".onnx"):
        return path
    d = resolve_model_dir(path)
    prefer = [ONNX_INT8, ONNX_FP32] if (precision or "").lower() == "int8" else [ONNX_FP32, ONNX_INT8, ONNX_LEGACY]
    for name in prefer:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.path.getsize(p) > 100_000:
            return p
    raise FileNotFoundError(f"目录中未找到 EfficientSAM ONNX：{d}")


def assets_ready(model_dir: str) -> bool:
    try:
        resolve_onnx(model_dir, "fp32")
        return True
    except Exception:  # noqa: BLE001
        return False


def _download_one(urls, dest: str, timeout: int = 600, min_bytes: int = 100_000) -> int:
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
    total += _download_one(ASSET_URLS[ONNX_FP32], os.path.join(model_dir, ONNX_FP32), timeout=timeout)
    try:
        total += _download_one(ASSET_URLS[ONNX_INT8], os.path.join(model_dir, ONNX_INT8),
                               timeout=timeout, min_bytes=50_000)
    except Exception:
        pass  # int8 可选
    if not assets_ready(model_dir):
        raise ValueError("EfficientSAM 资产不完整，请重试拉取")
    return model_dir, total


def _get_net(onnx_path: str):
    mtime = os.path.getmtime(onnx_path)
    key = (onnx_path, mtime)
    with _lock:
        hit = _net_cache.get(key)
        if hit is not None:
            return hit
        net = cv2.dnn.readNet(onnx_path)
        try:
            net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        except Exception:  # noqa: BLE001
            pass
        _net_cache[key] = net
        return net


def _build_prompts(points, point_labels, box, orig_w: int, orig_h: int):
    """组装最多 6 个点；框转为 label=2/3 的对角点。坐标为原图像素。

    输出 blob 形状与 OpenCV Zoo efficientSAM.py 一致：
      points (1,1,6,2)，labels (1,1,6,1)
    """
    pts = []
    lbls = []
    bg_pts = []

    if points:
        for i, p in enumerate(points):
            x, y = float(p[0]), float(p[1])
            lab = int(point_labels[i]) if point_labels and i < len(point_labels) else 1
            pts.append([x, y])
            lbls.append(float(lab))
            if lab == 0:
                bg_pts.append((int(round(x)), int(round(y))))

    if box is not None and len(box) >= 4:
        x1, y1, x2, y2 = [float(v) for v in box[:4]]
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        while len(pts) > MAX_POINTS - 2:
            dropped = int(lbls.pop())
            px, py = pts.pop()
            if dropped == 0:
                t = (int(px), int(py))
                if t in bg_pts:
                    bg_pts.remove(t)
        pts.append([x1, y1])
        lbls.append(2.0)
        pts.append([x2, y2])
        lbls.append(3.0)

    if not pts:
        raise ValueError("EfficientSAM 需要至少 1 个前景点或框选")

    if len(pts) > MAX_POINTS:
        keep, keep_lbl = [], []
        for p, lab in zip(pts, lbls):
            if int(lab) in (1, 2, 3) and len(keep) < MAX_POINTS:
                keep.append(p)
                keep_lbl.append(lab)
        for p, lab in zip(pts, lbls):
            if len(keep) >= MAX_POINTS:
                break
            if int(lab) == 0:
                keep.append(p)
                keep_lbl.append(lab)
        pts, lbls = keep[:MAX_POINTS], keep_lbl[:MAX_POINTS]
        bg_pts = [(int(p[0]), int(p[1])) for p, lab in zip(pts, lbls) if int(lab) == 0]

    sx = INPUT_SIZE / float(orig_w)
    sy = INPUT_SIZE / float(orig_h)
    scaled = np.array([[p[0] * sx, p[1] * sy] for p in pts], dtype=np.float32)
    labels_col = np.array(lbls, dtype=np.float32).reshape(-1, 1)

    pad = MAX_POINTS - scaled.shape[0]
    if pad > 0:
        scaled = np.vstack([scaled, np.zeros((pad, 2), dtype=np.float32)])
        labels_col = np.vstack([labels_col, np.full((pad, 1), -1.0, dtype=np.float32)])

    # Zoo: np.array([[points_6x2]]) -> (1,1,6,2); np.array([[labels_6x1]]) -> (1,1,6,1)
    points_blob = np.array([[scaled]], dtype=np.float32)
    labels_blob = np.array([[labels_col]], dtype=np.float32)
    return points_blob, labels_blob, bg_pts


def _preprocess_image(bgr: np.ndarray) -> np.ndarray:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (INPUT_SIZE, INPUT_SIZE))
    resized = resized.astype(np.float32) / 255.0
    return cv2.dnn.blobFromImage(resized)


def _select_mask(masks_u8, ious, bg_pts, orig_size_wh):
    """masks: (3,H,W)；按 IoU 排序，剔除覆盖背景点的候选。"""
    order = np.argsort(ious)[::-1]
    ow, oh = orig_size_wh
    for idx in order:
        m = masks_u8[idx]
        if m.dtype != np.uint8:
            m = (m.astype(np.uint8) * 255) if m.max() <= 1 else m.astype(np.uint8)
        resized = cv2.resize(m, (ow, oh), interpolation=cv2.INTER_NEAREST)
        if bg_pts:
            hit_bg = False
            for x, y in bg_pts:
                if 0 <= x < ow and 0 <= y < oh and resized[y, x] > 0:
                    hit_bg = True
                    break
            if hit_bg:
                continue
        return resized, float(ious[idx])
    best = int(order[0])
    m = masks_u8[best]
    if m.dtype != np.uint8:
        m = (m.astype(np.uint8) * 255) if m.max() <= 1 else m.astype(np.uint8)
    return cv2.resize(m, (ow, oh), interpolation=cv2.INTER_NEAREST), float(ious[best])


def _forward_opencv(net, image_blob, points_blob, labels_blob):
    # 缓存的 cv2.dnn.Net 非线程安全：setInput/forward 必须与缓存同锁串行
    with _lock:
        net.setInput(image_blob, INPUT_NAMES[0])
        net.setInput(points_blob, INPUT_NAMES[1])
        net.setInput(labels_blob, INPUT_NAMES[2])
        try:
            return net.forward(OUTPUT_NAMES)
        except Exception:
            outs = net.forward()
            return outs if isinstance(outs, (list, tuple)) else [outs]


def _forward_ort(onnx_path, image_blob, points_blob, labels_blob):
    import onnxruntime as ort

    mtime = os.path.getmtime(onnx_path)
    key = (onnx_path, mtime, "ort")
    feeds = {}
    with _lock:
        sess = _net_cache.get(key)
        if sess is None:
            sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
            _net_cache[key] = sess
        for inp in sess.get_inputs():
            name = inp.name
            if "image" in name:
                feeds[name] = image_blob.astype(np.float32)
            elif "coord" in name:
                feeds[name] = points_blob.astype(np.float32)
            elif "label" in name:
                feeds[name] = labels_blob.astype(np.float32)
            else:
                if len(feeds) == 0:
                    feeds[name] = image_blob.astype(np.float32)
                elif len(feeds) == 1:
                    feeds[name] = points_blob.astype(np.float32)
                else:
                    feeds[name] = labels_blob.astype(np.float32)
        return sess.run(None, feeds)


def infer_mask(model_path: str, image_bgr: np.ndarray, points=None, point_labels=None,
               box=None, precision: str = "fp32"):
    """返回 (mask_bool HxW, score, meta)。优先 OpenCV DNN，失败回退 ONNX Runtime。"""
    onnx = resolve_onnx(model_path, precision=precision)
    h, w = image_bgr.shape[:2]
    image_blob = _preprocess_image(image_bgr)
    points_blob, labels_blob, bg_pts = _build_prompts(points, point_labels, box, w, h)

    t0 = time.perf_counter()
    backend = "opencv"
    try:
        net = _get_net(onnx)
        outs = _forward_opencv(net, image_blob, points_blob, labels_blob)
    except Exception as e_cv:  # noqa: BLE001
        try:
            outs = _forward_ort(onnx, image_blob, points_blob, labels_blob)
            backend = "ort"
        except Exception as e_ort:  # noqa: BLE001
            raise RuntimeError(f"EfficientSAM 推理失败（opencv: {e_cv}; ort: {e_ort})") from e_ort
    latency = (time.perf_counter() - t0) * 1000.0

    if len(outs) >= 2:
        mask_blob, iou_blob = outs[0], outs[1]
    else:
        mask_blob, iou_blob = outs[0], np.ones((1, 1, 3), dtype=np.float32)

    masks = np.asarray(mask_blob)
    while masks.ndim > 3:
        masks = masks[0]
    if masks.ndim == 2:
        masks = masks[None, ...]
    ious = np.asarray(iou_blob).reshape(-1)
    if ious.size < masks.shape[0]:
        ious = np.ones(masks.shape[0], dtype=np.float32)

    # Zoo: masks >= 0 （logits/概率阈值）
    masks_bin = masks >= 0
    mask_u8, score = _select_mask(masks_bin, ious, bg_pts, (w, h))
    mask_bool = mask_u8 > 0
    meta = {
        "latencyMs": round(latency, 2),
        "onnx": os.path.basename(onnx),
        "backend": f"efficient-sam-{backend}",
        "maxPoints": MAX_POINTS,
        "pointsBlob": list(points_blob.shape),
        "labelsBlob": list(labels_blob.shape),
    }
    return mask_bool, score, meta
