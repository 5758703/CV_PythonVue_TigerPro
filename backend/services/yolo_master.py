"""Tencent YOLO-Master 推理封装（检测 / 分割 / 姿态 / OBB / 分类）。

YOLO-Master 基于 Ultralytics 分叉，MoE 权重需其代码库。设置环境变量 YOLO_MASTER_ROOT
指向 clone 后的仓库根目录（含 ultralytics/），或在其中执行 pip install -e .

与标准 ultralytics 共存：仅在 library=yolo-master 时临时 prepend 路径并重载 ultralytics 模块（全局锁）。
"""
from __future__ import annotations

import base64
import contextlib
import os
import threading
from pathlib import Path

import cv2
import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ROOT = _BACKEND_ROOT / "uploads" / "models" / "third_party" / "YOLO-Master"
_RELEASE_BASE = (
    "https://github.com/Tencent/YOLO-Master/releases/download/YOLO-Master-v26.02"
)

_runtime_lock = threading.RLock()
_model_cache: dict[tuple, object] = {}

# 预置模型元数据（seed 与文档共用）
YOLO_MASTER_MODELS = [
    {
        "key": "yolo-master-esmoe-n",
        "name": "YOLO-Master EsMoE-N 检测",
        "task": "object-detection",
        "version": "esmoe-n",
        "file": "YOLO-Master-EsMoE-N.pt",
        "desc": "Tencent YOLO-Master Efficient Sparse MoE Nano，COCO 42.4% mAP，实时检测首选。",
    },
    {
        "key": "yolo-master-esmoe-s",
        "name": "YOLO-Master EsMoE-S 检测",
        "task": "object-detection",
        "version": "esmoe-s",
        "file": "YOLO-Master-EsMoE-S.pt",
        "desc": "YOLO-Master EsMoE Small，精度与速度均衡。",
    },
    {
        "key": "yolo-master-v01-n",
        "name": "YOLO-Master v0.1-N 检测",
        "task": "object-detection",
        "version": "v0.1-n",
        "file": "YOLO-Master-v0.1-N.pt",
        "desc": "YOLO-Master v0.1 Nano 检测权重。",
    },
    {
        "key": "yolo-master-seg-n",
        "name": "YOLO-Master Seg-N 实例分割",
        "task": "instance-segmentation",
        "version": "seg-n",
        "file": "YOLO-Master-v0.1-seg-N.pt",
        "desc": "YOLO-Master 实例分割 Nano（mask + box）。",
    },
    {
        "key": "yolo-master-cls-n",
        "name": "YOLO-Master Cls-N 图像分类",
        "task": "image-classification",
        "version": "cls-n",
        "file": "YOLO-Master-v0.1-cls-N.pt",
        "desc": "YOLO-Master 图像分类 Nano（ImageNet Top-1 76.6%）。",
    },
    {
        "key": "yolo-master-pose-n",
        "name": "YOLO-Master Pose-N 姿态估计",
        "task": "pose-estimation",
        "version": "pose-n",
        "file": "yolo11n-pose.pt",
        "source_url": (
            "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-pose.pt"
        ),
        "desc": (
            "YOLO-Master 官方 Release 暂无 pose 权重，暂用 Ultralytics YOLO11n-pose "
            "（与 YOLO-Master 推理栈兼容）。"
        ),
    },
    {
        "key": "yolo-master-obb-n",
        "name": "YOLO-Master OBB-N 旋转框检测",
        "task": "obb",
        "version": "obb-n",
        "file": "yolo11n-obb.pt",
        "source_url": (
            "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-obb.pt"
        ),
        "desc": (
            "YOLO-Master 官方 Release 暂无 obb 权重，暂用 Ultralytics YOLO11n-obb "
            "（与 YOLO-Master 推理栈兼容）。"
        ),
    },
]


def release_url(filename: str) -> str:
    return f"{_RELEASE_BASE}/{filename}"


def get_yolo_master_root() -> str | None:
    env = (os.getenv("YOLO_MASTER_ROOT") or "").strip()
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    if _DEFAULT_ROOT.is_dir():
        return str(_DEFAULT_ROOT)
    return None


def _moe_module_path(root: str | None = None) -> str | None:
    base = root or get_yolo_master_root()
    if not base:
        return None
    path = os.path.join(base, "ultralytics", "nn", "modules", "moe")
    return path if os.path.isdir(path) else None


def is_yolo_master_available() -> bool:
    if _moe_module_path():
        return True
    try:
        import importlib

        importlib.import_module("ultralytics.nn.modules.moe")
        return True
    except ImportError:
        return False


def install_hint() -> str:
    root = get_yolo_master_root()
    if root:
        return (
            f"已检测到 YOLO_MASTER_ROOT={root}，请在该目录执行 "
            f"`pip install -e .`（或运行 `python scripts/setup_yolo_master.py`），"
            f"然后重启后端。"
        )
    return (
        "EsMoE 等 MoE 权重需 Tencent YOLO-Master 代码库。"
        "请运行 `python scripts/setup_yolo_master.py`，"
        "或 clone https://github.com/Tencent/YOLO-Master 到 "
        "backend/uploads/models/third_party/YOLO-Master 并 pip install -e .，"
        "然后重启后端。"
    )


def ensure_yolo_master_runtime() -> None:
    if is_yolo_master_available():
        return
    raise RuntimeError(install_hint())


@contextlib.contextmanager
def _yolo_master_import():
    """在 YOLO-Master 代码路径下临时导入 ultralytics.YOLO（含 MoE 模块）。"""
    root = get_yolo_master_root()
    saved_path = list(__import__("sys").path)
    saved_modules = {}
    sys = __import__("sys")
    try:
        if root:
            sys.path.insert(0, root)
            for name in list(sys.modules):
                if name == "ultralytics" or name.startswith("ultralytics."):
                    saved_modules[name] = sys.modules.pop(name)
        from ultralytics import YOLO  # noqa: WPS433
        import importlib

        importlib.import_module("ultralytics.nn.modules.moe")
        yield YOLO
    except ImportError as e:
        raise RuntimeError(
            f"YOLO-Master MoE 模块不可用：{e}。{install_hint()}"
        ) from e
    finally:
        for name, mod in saved_modules.items():
            sys.modules[name] = mod
        sys.path[:] = saved_path


def _predict_kwargs(conf=0.25, imgsz=None, **extra):
    from inference import _yolo_predict_kwargs

    return _yolo_predict_kwargs(conf=conf, imgsz=imgsz, **extra)


def _safe_class_name(names, cls_id: int) -> str:
    from inference import _safe_class_name as _scn

    return _scn(names, cls_id)


def _safe_plot(result, fallback_frame=None):
    from inference import _safe_plot as _sp

    return _sp(result, fallback_frame=fallback_frame)


def _patch_loaded_moe_modules(model) -> None:
    """旧版 .pt 反序列化后可能缺少新版 MoE/Router 字段，补齐默认值。

    注意：checkpoint 反序列化的模块与当前 import 的类对象不同，不能用 isinstance。
    """
    root = getattr(model, "model", model)
    router_names = {"EfficientSpatialRouter", "AdaptiveRoutingLayer", "LocalRoutingLayer"}
    for mod in root.modules():
        name = type(mod).__name__
        if name in router_names and not hasattr(mod, "capacity_factor"):
            mod.capacity_factor = None
        if name != "OptimizedMOEImproved":
            continue
        if not hasattr(mod, "_training_step"):
            mod._training_step = 0
        if not hasattr(mod, "_current_top_k"):
            mod._current_top_k = getattr(mod, "top_k", getattr(mod, "num_experts", 2))
        if not hasattr(mod, "warmup_steps"):
            mod.warmup_steps = 5000
        if not hasattr(mod, "progressive_sparsity"):
            mod.progressive_sparsity = False
        if not hasattr(mod, "detach_routing"):
            mod.detach_routing = False
        if not hasattr(mod, "add_residual"):
            mod.add_residual = True
        if not hasattr(mod, "expert_dropout_rate"):
            mod.expert_dropout_rate = 0.15
        if not hasattr(mod, "dropout_interval"):
            mod.dropout_interval = 100
        mod.eval()


def _finalize_yolo_master_model(model):
    _patch_loaded_moe_modules(model)
    inner = getattr(model, "model", None)
    if inner is not None and hasattr(inner, "eval"):
        inner.eval()
    if hasattr(model, "eval"):
        model.eval()


def get_model(abs_path: str, task: str | None = None):
    """加载并缓存 YOLO-Master 模型实例。"""
    ensure_yolo_master_runtime()
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"权重不存在：{abs_path}")
    mtime = os.path.getmtime(abs_path)
    cache_key = (abs_path, task or "", mtime)
    with _runtime_lock:
        cached = _model_cache.get(cache_key)
        if cached is not None:
            _finalize_yolo_master_model(cached)
            return cached
        with _yolo_master_import() as YOLO:
            try:
                if task and str(abs_path).lower().endswith((".yaml", ".yml")):
                    model = YOLO(abs_path, task=task)
                elif str(abs_path).lower().endswith(".onnx"):
                    model = YOLO(abs_path, task=task or "detect")
                else:
                    model = YOLO(abs_path)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(
                    f"YOLO-Master 加载失败：{e}。{install_hint()}"
                ) from e
        _finalize_yolo_master_model(model)
        _model_cache[cache_key] = model
        return model


def detect_image(abs_path, image_bytes, conf=0.25, draw=True, model_key=None):
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    h, w = img.shape[:2]

    from inference import _yolo_imgsz_for_model

    model = get_model(abs_path, task="detect")
    results = model.predict(img, **_predict_kwargs(conf=conf, imgsz=_yolo_imgsz_for_model(model_key)))
    r = results[0]
    names = getattr(r, "names", None) or getattr(model, "names", None) or {}

    detections = []
    if r.boxes is not None:
        for b in r.boxes:
            cls_id = int(b.cls[0])
            detections.append({
                "className": _safe_class_name(names, cls_id),
                "classId": cls_id,
                "confidence": round(float(b.conf[0]), 4),
                "bbox": [round(float(v), 1) for v in b.xyxy[0].tolist()],
            })

    image_b64 = None
    if draw:
        plotted = _safe_plot(r, img)
        ok, buf = cv2.imencode(".jpg", plotted)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    return {
        "detections": detections,
        "count": len(detections),
        "imageBase64": image_b64,
        "width": w,
        "height": h,
        "engine": "yolo-master",
    }


def detect_obb(abs_path, image_bytes, conf=0.25, draw=True, model_key=None):
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    h, w = img.shape[:2]

    from inference import _yolo_imgsz_for_model

    model = get_model(abs_path, task="obb")
    r = model.predict(img, **_predict_kwargs(conf=conf, imgsz=_yolo_imgsz_for_model(model_key)))[0]
    names = getattr(r, "names", None) or getattr(model, "names", None) or {}

    detections = []
    if getattr(r, "obb", None) is not None and r.obb is not None:
        xyxy = r.obb.xyxy.cpu().numpy() if r.obb.xyxy is not None else []
        xyxyxyxy = r.obb.xyxyxyxy.cpu().numpy() if r.obb.xyxyxyxy is not None else []
        confs = r.obb.conf.cpu().numpy() if r.obb.conf is not None else None
        clss = r.obb.cls.cpu().numpy() if r.obb.cls is not None else None
        n = len(xyxyxyxy) if len(xyxyxyxy) else len(xyxy)
        for i in range(n):
            score = float(confs[i]) if confs is not None else 0.0
            if score < float(conf or 0):
                continue
            cid = int(clss[i]) if clss is not None else 0
            item = {
                "className": _safe_class_name(names, cid),
                "classId": cid,
                "confidence": round(score, 4),
                "bbox": [round(float(v), 1) for v in xyxy[i].tolist()] if len(xyxy) > i else [],
            }
            if len(xyxyxyxy) > i:
                quad = [[round(float(v), 1) for v in pt] for pt in xyxyxyxy[i].tolist()]
                item["quad"] = quad
            detections.append(item)

    image_b64 = None
    if draw:
        plotted = _safe_plot(r, img)
        ok, buf = cv2.imencode(".jpg", plotted)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    return {
        "detections": detections,
        "count": len(detections),
        "imageBase64": image_b64,
        "width": w,
        "height": h,
        "engine": "yolo-master",
    }


def estimate_pose(abs_path, image_bytes, conf=0.25, draw=True):
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    h, w = img.shape[:2]

    model = get_model(abs_path, task="pose")
    r = model.predict(img, **_predict_kwargs(conf=conf))[0]

    persons = []
    if r.keypoints is not None and r.keypoints.data is not None:
        for kp in r.keypoints.data.cpu().tolist():
            pts = [[round(float(x), 1), round(float(y), 1), round(float(c), 4)]
                   for x, y, c in kp]
            persons.append({"keypoints": pts})

    image_b64 = None
    if draw:
        plotted = r.plot()
        ok, buf = cv2.imencode(".jpg", plotted)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    return {
        "count": len(persons),
        "persons": persons,
        "imageBase64": image_b64,
        "width": w,
        "height": h,
        "engine": "yolo-master",
    }


def segment_image(abs_path, image_bytes, conf=0.25, draw=True):
    from inference import _ultralytics_boxes_to_detections, _ultralytics_masks_to_items

    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    h, w = img.shape[:2]

    model = get_model(abs_path, task="segment")
    r = model.predict(img, **_predict_kwargs(conf=conf))[0]
    detections = _ultralytics_boxes_to_detections(r, model)
    _ultralytics_masks_to_items(r, detections, h, w, include_mask=True)

    image_b64 = None
    if draw:
        plotted = _safe_plot(r, fallback_frame=img)
        ok, buf = cv2.imencode(".jpg", plotted)
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    return {
        "detections": detections,
        "count": len(detections),
        "imageBase64": image_b64,
        "width": w,
        "height": h,
        "engine": "yolo-master",
    }


def classify_image(abs_path, image_bytes, top_k=5, conf=0.25):
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")

    model = get_model(abs_path, task="classify")
    r = model.predict(img, **_predict_kwargs(conf=conf))[0]
    names = getattr(r, "names", None) or getattr(model, "names", None) or {}

    results = []
    if getattr(r, "probs", None) is not None:
        data = getattr(r.probs, "data", None)
        if data is not None:
            if hasattr(data, "detach"):
                data = data.detach().cpu().numpy()
            elif hasattr(data, "cpu"):
                data = data.cpu().numpy()
            data = np.asarray(data, dtype=np.float32).reshape(-1)
            idxs = data.argsort()[::-1][: max(1, int(top_k))]
            for idx in idxs:
                c = float(data[int(idx)])
                if c < float(conf or 0):
                    continue
                results.append({
                    "label": _safe_class_name(names, int(idx)),
                    "score": round(c, 4),
                })

    return {
        "results": results,
        "top": results[0] if results else None,
        "engine": "yolo-master",
        "backend": "yolo-master",
    }


def detect_video(abs_path, src_path, dst_path, conf=0.25, progress_cb=None, model_key=None, **alert_kw):
    from inference import (
        _open_h264,
        _write_bgr,
        _video_alert_ctx,
        _apply_frame_video_alerts,
        _video_alert_stats,
        _yolo_imgsz_for_model,
    )

    model = get_model(abs_path, task="detect")
    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    writer, ew, eh = _open_h264(dst_path, fps, w, h)

    class_counts = {}
    total_det = 0
    frames = 0
    alert_ctx = _video_alert_ctx(
        alert_kw.get("alert_rules"),
        alert_kw.get("alert_source_key"),
    )
    yolo_imgsz = _yolo_imgsz_for_model(model_key)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            r = model.predict(frame, **_predict_kwargs(conf=conf, imgsz=yolo_imgsz))[0]
            frame_dets = []
            if r.boxes is not None:
                names = r.names
                for b in r.boxes:
                    cid = int(b.cls[0])
                    name = _safe_class_name(names, cid)
                    conf_i = float(b.conf[0]) if getattr(b, "conf", None) is not None else 0.0
                    xyxy = [round(float(v), 1) for v in b.xyxy[0].tolist()]
                    class_counts[name] = class_counts.get(name, 0) + 1
                    total_det += 1
                    frame_dets.append({
                        "className": name,
                        "classId": cid,
                        "confidence": round(conf_i, 4),
                        "bbox": xyxy,
                    })
            plotted = _safe_plot(r, frame)
            plotted = _apply_frame_video_alerts(plotted, frame_dets, alert_ctx, frames, fps)
            _write_bgr(writer, plotted, ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        cap.release()
        writer.close()

    result = {
        "frames": frames,
        "totalFrames": total,
        "totalDetections": total_det,
        "classCounts": class_counts,
        "fps": round(float(fps), 2),
        "width": ew,
        "height": eh,
        "engine": "yolo-master",
    }
    result.update(_video_alert_stats(alert_ctx))
    return result


def segment_video(abs_path, src_path, dst_path, conf=0.25, progress_cb=None):
    from inference import _open_h264, _write_bgr, _ultralytics_boxes_to_detections, _safe_plot

    model = get_model(abs_path, task="segment")
    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    writer, ew, eh = _open_h264(dst_path, fps, w, h)
    class_counts, total_det, frames = {}, 0, 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            r = model.predict(frame, **_predict_kwargs(conf=conf))[0]
            dets = _ultralytics_boxes_to_detections(r, model)
            for d in dets:
                class_counts[d["className"]] = class_counts.get(d["className"], 0) + 1
                total_det += 1
            plotted = _safe_plot(r, fallback_frame=frame)
            _write_bgr(writer, plotted, ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        cap.release()
        writer.close()
    return {
        "frames": frames,
        "totalFrames": total,
        "totalDetections": total_det,
        "classCounts": class_counts,
        "fps": round(float(fps), 2),
        "width": ew,
        "height": eh,
        "engine": "yolo-master",
    }


def pose_video(abs_path, src_path, dst_path, conf=0.25, progress_cb=None):
    from inference import _open_h264, _write_bgr

    model = get_model(abs_path, task="pose")
    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    writer, ew, eh = _open_h264(dst_path, fps, w, h)
    total_persons = 0
    frames = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            r = model.predict(frame, **_predict_kwargs(conf=conf))[0]
            if r.keypoints is not None and r.keypoints.data is not None:
                total_persons += len(r.keypoints.data)
            _write_bgr(writer, r.plot(), ew, eh)
            frames += 1
            if progress_cb:
                progress_cb(frames, total)
    finally:
        cap.release()
        writer.close()

    return {
        "frames": frames,
        "totalFrames": total,
        "totalPersons": total_persons,
        "fps": round(float(fps), 2),
        "width": ew,
        "height": eh,
        "engine": "yolo-master",
    }
