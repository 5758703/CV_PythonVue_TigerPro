"""MobileNet V2 ImageNet-1000 分类：OpenCV DNN 优先，INT8 失败时回退 ONNX Runtime。

资产目录约定（uploads/models/mobilenet-v2/）：
  - mobilenetv2-12.onnx          FP32
  - mobilenetv2-12-int8.onnx     INT8
  - imagenet_classes.txt         1000 类英文标签（PyTorch Hub，保留）
  - imagenet_classes_zh.txt      1000 类中文标签（展示用，与英文一一对应）
"""
from __future__ import annotations

import os
import shutil
import threading
import time

import cv2
import numpy as np

_lock = threading.Lock()
_net_cache = {}      # (onnx_path, mtime, backend) -> net_or_session
_labels_cache = {}   # labels_path -> list[str]

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
INPUT_SIZE = 224

FP32_NAME = "mobilenetv2-12.onnx"
INT8_NAME = "mobilenetv2-12-int8.onnx"
LABELS_NAME = "imagenet_classes.txt"
LABELS_ZH_NAME = "imagenet_classes_zh.txt"

# 随仓库分发的中文标签（Chinese-CLIP ImageNet-1K label_cn.txt）
_BUNDLED_ZH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", LABELS_ZH_NAME)

# 多镜像：GitHub raw / media / jsDelivr（国内偶发重置时轮询）
ASSET_URLS = {
    FP32_NAME: [
        "https://media.githubusercontent.com/media/onnx/models/main/validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx",
        "https://cdn.jsdelivr.net/gh/onnx/models@main/validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx",
        "https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx",
    ],
    INT8_NAME: [
        "https://media.githubusercontent.com/media/onnx/models/main/validated/vision/classification/mobilenet/model/mobilenetv2-12-int8.onnx",
        "https://cdn.jsdelivr.net/gh/onnx/models@main/validated/vision/classification/mobilenet/model/mobilenetv2-12-int8.onnx",
        "https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-12-int8.onnx",
    ],
    LABELS_NAME: [
        "https://cdn.jsdelivr.net/gh/pytorch/hub@master/imagenet_classes.txt",
        "https://raw.githubusercontent.com/pytorch/hub/master/imagenet_classes.txt",
    ],
    LABELS_ZH_NAME: [
        "https://cdn.jsdelivr.net/gh/OFA-Sys/Chinese-CLIP@master/datasets/ImageNet-1K/label_cn.txt",
        "https://raw.githubusercontent.com/OFA-Sys/Chinese-CLIP/master/datasets/ImageNet-1K/label_cn.txt",
    ],
}


def resolve_model_dir(path: str) -> str:
    """file_path 可为目录或其中某个 .onnx；统一解析到含双模型的目录。"""
    if os.path.isdir(path):
        return path
    if os.path.isfile(path):
        return os.path.dirname(path)
    raise FileNotFoundError(f"模型路径不存在：{path}")


def list_assets(model_dir: str) -> dict:
    d = resolve_model_dir(model_dir)
    return {
        "dir": d,
        "fp32": os.path.join(d, FP32_NAME),
        "int8": os.path.join(d, INT8_NAME),
        "labels": os.path.join(d, LABELS_NAME),
        "labels_zh": os.path.join(d, LABELS_ZH_NAME),
        "fp32_ok": os.path.isfile(os.path.join(d, FP32_NAME)),
        "int8_ok": os.path.isfile(os.path.join(d, INT8_NAME)),
        "labels_ok": os.path.isfile(os.path.join(d, LABELS_NAME)),
        "labels_zh_ok": os.path.isfile(os.path.join(d, LABELS_ZH_NAME)),
    }


def assets_ready(model_dir: str) -> bool:
    a = list_assets(model_dir)
    return a["fp32_ok"] and a["int8_ok"] and a["labels_ok"]


def _ensure_zh_labels(model_dir: str, timeout: int = 600) -> int:
    """确保模型目录有中文标签：优先仓库内 assets，其次下载，最后英文占位。"""
    dest = os.path.join(model_dir, LABELS_ZH_NAME)
    if os.path.isfile(dest) and os.path.getsize(dest) > 2000:
        return os.path.getsize(dest)
    if os.path.isfile(_BUNDLED_ZH) and os.path.getsize(_BUNDLED_ZH) > 2000:
        shutil.copyfile(_BUNDLED_ZH, dest)
        return os.path.getsize(dest)
    try:
        return _download_one(ASSET_URLS[LABELS_ZH_NAME], dest, timeout=timeout, min_bytes=2000)
    except Exception:
        # 最后兜底：用英文标签复制一份，避免推理中断
        en = os.path.join(model_dir, LABELS_NAME)
        if os.path.isfile(en):
            shutil.copyfile(en, dest)
            return os.path.getsize(dest)
        raise


def _download_one(urls, dest: str, timeout: int = 600, min_bytes: int = 100) -> int:
    import requests

    if os.path.isfile(dest) and os.path.getsize(dest) > min_bytes:
        return os.path.getsize(dest)
    last_err = None
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


def _export_int8_from_fp32(fp32_path: str, int8_path: str) -> int:
    """Zoo INT8 不可达时，用 ORT 动态量化从 FP32 生成 INT8 兜底。"""
    from onnxruntime.quantization import QuantType, quantize_dynamic

    tmp = int8_path + ".part"
    if os.path.isfile(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
    quantize_dynamic(fp32_path, tmp, weight_type=QuantType.QUInt8)
    if not os.path.isfile(tmp) or os.path.getsize(tmp) < 1024:
        raise RuntimeError("ORT 动态量化生成 INT8 失败")
    os.replace(tmp, int8_path)
    return os.path.getsize(int8_path)


def _export_fp32_from_torchvision(fp32_path: str) -> int:
    """网络不可达时，从 torchvision MobileNet_V2 导出 ONNX（ImageNet 预训练）。"""
    import torch
    from torchvision.models import MobileNet_V2_Weights, mobilenet_v2

    weights = MobileNet_V2_Weights.IMAGENET1K_V1
    model = mobilenet_v2(weights=weights)
    model.eval()
    dummy = torch.randn(1, 3, INPUT_SIZE, INPUT_SIZE)
    tmp = fp32_path + ".part"
    torch.onnx.export(
        model,
        dummy,
        tmp,
        input_names=["input"],
        output_names=["output"],
        opset_version=12,
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
    )
    if not os.path.isfile(tmp) or os.path.getsize(tmp) < 1024 * 100:
        raise RuntimeError("torchvision 导出 MobileNet V2 ONNX 失败")
    os.replace(tmp, fp32_path)
    return os.path.getsize(fp32_path)


def _write_labels_from_torchvision(labels_path: str) -> int:
    from torchvision.models import MobileNet_V2_Weights

    cats = MobileNet_V2_Weights.IMAGENET1K_V1.meta["categories"]
    with open(labels_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cats) + "\n")
    return os.path.getsize(labels_path)


def download_assets(model_dir: str, timeout: int = 600) -> tuple[str, int]:
    """下载 fp32/int8 ONNX + labels；失败时 torchvision 导出 / ORT 量化兜底。"""
    os.makedirs(model_dir, exist_ok=True)
    total = 0

    fp32 = os.path.join(model_dir, FP32_NAME)
    if not (os.path.isfile(fp32) and os.path.getsize(fp32) > 1024 * 100):
        try:
            total += _download_one(ASSET_URLS[FP32_NAME], fp32, timeout=timeout, min_bytes=1024 * 100)
        except Exception:
            total += _export_fp32_from_torchvision(fp32)
    else:
        total += os.path.getsize(fp32)

    labels = os.path.join(model_dir, LABELS_NAME)
    if not (os.path.isfile(labels) and os.path.getsize(labels) > 2000):
        try:
            total += _download_one(ASSET_URLS[LABELS_NAME], labels, timeout=timeout, min_bytes=2000)
        except Exception:
            total += _write_labels_from_torchvision(labels)
    else:
        total += os.path.getsize(labels)

    int8 = os.path.join(model_dir, INT8_NAME)
    if not (os.path.isfile(int8) and os.path.getsize(int8) > 1024):
        try:
            total += _download_one(ASSET_URLS[INT8_NAME], int8, timeout=timeout, min_bytes=1024 * 50)
        except Exception:
            total += _export_int8_from_fp32(fp32, int8)
    else:
        total += os.path.getsize(int8)

    total += _ensure_zh_labels(model_dir, timeout=timeout)

    if not assets_ready(model_dir):
        raise ValueError("MobileNet 资产不完整，请重试拉取")
    return model_dir, total


def _load_labels(labels_path: str) -> list[str]:
    with _lock:
        cached = _labels_cache.get(labels_path)
        if cached is not None:
            return cached
        with open(labels_path, "r", encoding="utf-8") as f:
            labels = [ln.strip() for ln in f if ln.strip()]
        if len(labels) < 1000:
            raise ValueError(f"标签文件异常（期望 ≥1000 行）：{labels_path}")
        _labels_cache[labels_path] = labels
        return labels


def _load_label_pair(model_dir: str) -> tuple[list[str], list[str]]:
    """返回 (中文标签, 英文标签)；中文优先用于展示。"""
    assets = list_assets(model_dir)
    labels_en = _load_labels(assets["labels"])
    if not assets["labels_zh_ok"]:
        try:
            _ensure_zh_labels(assets["dir"])
        except Exception:  # noqa: BLE001
            return labels_en, labels_en
    try:
        labels_zh = _load_labels(os.path.join(assets["dir"], LABELS_ZH_NAME))
    except Exception:  # noqa: BLE001
        return labels_en, labels_en
    n = min(len(labels_zh), len(labels_en))
    return labels_zh[:n], labels_en[:n]


def _preprocess(bgr: np.ndarray) -> np.ndarray:
    """ImageNet 归一化 → NCHW float32 blob。"""
    blob = cv2.dnn.blobFromImage(
        bgr,
        scalefactor=1.0 / 255.0,
        size=(INPUT_SIZE, INPUT_SIZE),
        mean=IMAGENET_MEAN,
        swapRB=True,
        crop=False,
    )
    std = np.array(IMAGENET_STD, dtype=np.float32).reshape(1, 3, 1, 1)
    blob /= std
    return blob


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.float32).reshape(-1)
    x = x - np.max(x)
    e = np.exp(x)
    return e / np.sum(e)


def _get_opencv_net(onnx_path: str):
    mtime = os.path.getmtime(onnx_path)
    key = (onnx_path, mtime, "opencv")
    with _lock:
        hit = _net_cache.get(key)
        if hit is not None:
            return hit
        net = cv2.dnn.readNetFromONNX(onnx_path)
        # CPU 默认；若编译了 OpenCL/CUDA 可再扩展
        try:
            net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        except Exception:  # noqa: BLE001
            pass
        _net_cache[key] = net
        return net


def _get_ort_session(onnx_path: str):
    import onnxruntime as ort

    mtime = os.path.getmtime(onnx_path)
    key = (onnx_path, mtime, "ort")
    with _lock:
        hit = _net_cache.get(key)
        if hit is not None:
            return hit
        sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        _net_cache[key] = sess
        return sess


def _infer_opencv(onnx_path: str, blob: np.ndarray) -> np.ndarray:
    net = _get_opencv_net(onnx_path)
    net.setInput(blob)
    out = net.forward()
    return np.asarray(out).reshape(-1)


def _infer_ort(onnx_path: str, blob: np.ndarray) -> np.ndarray:
    sess = _get_ort_session(onnx_path)
    inp = sess.get_inputs()[0]
    name = inp.name
    # 部分量化模型要求 NHWC；Zoo MobileNet 一般为 NCHW
    feed = {name: blob.astype(np.float32)}
    outs = sess.run(None, feed)
    return np.asarray(outs[0]).reshape(-1)


def _pick_onnx(assets: dict, precision: str) -> tuple[str, str]:
    precision = (precision or "int8").strip().lower()
    if precision not in ("fp32", "int8"):
        precision = "int8"
    if precision == "fp32":
        if not assets["fp32_ok"]:
            raise FileNotFoundError(f"缺少 FP32 模型：{assets['fp32']}")
        return assets["fp32"], "fp32"
    if assets["int8_ok"]:
        return assets["int8"], "int8"
    if assets["fp32_ok"]:
        return assets["fp32"], "fp32"
    raise FileNotFoundError("缺少 MobileNet ONNX 权重")


def classify_mobilenet(
    model_dir: str,
    image_bytes: bytes,
    *,
    top_k: int = 3,
    precision: str = "int8",
    prefer_backend: str = "auto",
) -> dict:
    """返回 results / top / latencyMs / precision / backend。

    results[].label 为中文；labelEn 为英文（保留对照）。
    """
    assets = list_assets(model_dir)
    if not assets["labels_ok"]:
        raise FileNotFoundError(f"缺少标签文件：{assets['labels']}")
    labels_zh, labels_en = _load_label_pair(model_dir)
    onnx_path, used_precision = _pick_onnx(assets, precision)

    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    blob = _preprocess(img)

    prefer = (prefer_backend or "auto").strip().lower()
    backends_try = []
    if prefer == "ort":
        backends_try = ["ort"]
    elif prefer == "opencv":
        backends_try = ["opencv"]
    else:
        # auto：fp32 优先 OpenCV；int8 先 OpenCV，失败再 ORT
        backends_try = ["opencv", "ort"] if used_precision == "int8" else ["opencv", "ort"]

    last_err = None
    logits = None
    backend_used = None
    t0 = time.perf_counter()
    for be in backends_try:
        try:
            if be == "opencv":
                logits = _infer_opencv(onnx_path, blob)
            else:
                logits = _infer_ort(onnx_path, blob)
            backend_used = be
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    if logits is None:
        raise RuntimeError(f"MobileNet 推理失败：{last_err}")

    # Zoo 模型末尾多为 Softmax；若已是概率分布则跳过
    s = float(np.sum(logits))
    probs = logits if (0.99 <= s <= 1.01 and np.all(logits >= 0)) else _softmax(logits)

    n_cls = min(len(probs), len(labels_zh), len(labels_en))
    k = max(1, min(int(top_k or 3), n_cls))
    idxs = np.argsort(probs)[::-1][:k]
    results = []
    for i in idxs:
        ii = int(i)
        zh = labels_zh[ii] if ii < len(labels_zh) else f"类别_{ii}"
        en = labels_en[ii] if ii < len(labels_en) else f"class_{ii}"
        results.append({
            "label": zh,
            "labelEn": en,
            "score": round(float(probs[ii]), 4),
            "classId": ii,
        })

    return {
        "results": results,
        "top": results[0] if results else None,
        "latencyMs": latency_ms,
        "precision": used_precision,
        "backend": backend_used or "unknown",
        "inputSize": INPUT_SIZE,
        "labelLang": "zh",
    }
