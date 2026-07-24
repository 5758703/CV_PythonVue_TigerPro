"""开放 API 能力适配：复用控制台同一套 inference / services，不透传内部路由。"""
from __future__ import annotations

import os

from flask import current_app
from models import AiModel


def _abs_model_path(m: AiModel):
    if m is None or not m.file_path:
        return None
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    return p if os.path.exists(p) else None


def resolve_detect_runtime(m: AiModel):
    """复用控制台检测运行时解析。"""
    from routes.ai_model import _resolve_detect_runtime
    return _resolve_detect_runtime(m)


def run_vision_detect(*, model_id: int, image_bytes: bytes, conf: float = 0.25, draw: bool = True):
    m = AiModel.query.get(model_id)
    if m is None:
        raise ValueError("模型不存在")
    lib, abs_path = resolve_detect_runtime(m)
    if lib == "transformers":
        from inference import detect_image_hf
        return detect_image_hf(
            abs_path, image_bytes, conf=conf, draw=draw, task=m.task or "object-detection"
        )
    if lib == "rfdetr":
        from inference import detect_image_rfdetr
        return detect_image_rfdetr(
            abs_path, image_bytes, conf=conf, draw=draw, model_key=m.model_key or "rf-detr-medium"
        )
    from inference import detect_image
    return detect_image(abs_path, image_bytes, conf=conf, draw=draw)


def run_vision_ocr(*, det_id: int, rec_id: int, image_bytes: bytes):
    det_m = AiModel.query.get(det_id)
    rec_m = AiModel.query.get(rec_id)
    if det_m is None or rec_m is None:
        raise ValueError("detId / recId 模型不存在")
    det_dir = _abs_model_path(det_m)
    rec_dir = _abs_model_path(rec_m)
    if det_dir is None or rec_dir is None:
        raise ValueError("OCR 模型缺少本地权重，请先在控制台拉取")
    from inference import paddle_ocr
    return paddle_ocr(det_dir, rec_dir, image_bytes)


def run_face_recognize(*, model_id: int, image_bytes: bytes,
                       threshold: float = 0.4, det_thresh: float = 0.5, draw: bool = False):
    from routes.face import _resolve_face_model
    from inference import recognize_faces

    resolved, err = _resolve_face_model(model_id)
    if err:
        raise ValueError(err)
    m, root, pack = resolved
    return recognize_faces(
        root, pack, m.model_key, image_bytes,
        threshold=threshold, det_thresh=det_thresh, draw=draw,
    )


def run_water_read(*, det_id: int, rec_id: int, image_bytes: bytes, water_y_ratio: float | None = None):
    det_m = AiModel.query.get(det_id)
    rec_m = AiModel.query.get(rec_id)
    if det_m is None or rec_m is None:
        raise ValueError("detId / recId 模型不存在")
    if (det_m.library or "").lower() != "rapidocr" or (rec_m.library or "").lower() != "rapidocr":
        raise ValueError("请选择 library=rapidocr 的检测和识别模型")
    det_dir = _abs_model_path(det_m)
    rec_dir = _abs_model_path(rec_m)
    if det_dir is None or rec_dir is None:
        raise ValueError("水位 OCR 模型缺少本地权重")
    from inference import paddle_ocr
    from services.water_level import detect_water_level

    def ocr_fn(img_bytes):
        return paddle_ocr(det_dir, rec_dir, img_bytes).get("lines", [])

    return detect_water_level(ocr_fn, image_bytes, water_y_ratio)
