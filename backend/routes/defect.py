"""Defect diagnosis API /api/ai/defect — YOLO gate + box-guided SAM + Qwen-VL."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from models import AiModel
from security import permission_required
from services import defect_diagnosis as engine

defect_bp = Blueprint("defect", __name__, url_prefix="/api/ai/defect")


def _form_float(name, default):
    try:
        return float(request.form.get(name, default))
    except (TypeError, ValueError):
        return default


def _form_int(name, default=0):
    try:
        return int(request.form.get(name, default))
    except (TypeError, ValueError):
        return default


@defect_bp.get("/status")
@permission_required("ai:defect:list")
def status():
    return jsonify(code=0, data=engine.engine_status())


@defect_bp.post("/diagnose")
@permission_required("ai:defect:list")
def diagnose():
    """Dual-engine defect diagnosis on one image.

    Form:
      file — image
      modelId — detector AiModel id (required)
      segModelId — optional interactive/instance segmentation model
      conf — YOLO conf (default 0.25)
      suspiciousConf — gate into VLM queue (default from config)
      scenario — general | pcb | injection
      draw — return overlay base64 (default 1)
    """
    from routes.ai_model import _detect_lib, _detect_model_path, _resolve_detect_runtime

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400

    mid = _form_int("modelId", 0)
    if not mid:
        return jsonify(code=400, message="缺少 modelId（检测模型）"), 400
    m = AiModel.query.get(mid)
    if m is None:
        return jsonify(code=404, message="检测模型不存在"), 404

    try:
        lib, abs_path = _resolve_detect_runtime(m)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400
    if abs_path is None:
        abs_path = _detect_model_path(m)
    if abs_path is None:
        return jsonify(code=400, message="检测模型暂无本地权重，请先上传或拉取"), 400

    seg_path = None
    seg_lib = None
    seg_mid = _form_int("segModelId", 0)
    if seg_mid:
        sm = AiModel.query.get(seg_mid)
        if sm is None:
            return jsonify(code=404, message="分割模型不存在"), 404
        task = (sm.task or "").lower()
        if task not in ("instance-segmentation", "interactive-segmentation"):
            return jsonify(code=400, message="分割模型任务须为 instance/interactive-segmentation"), 400
        seg_lib = _detect_lib(sm)
        seg_path = _detect_model_path(sm)
        if seg_path is None:
            return jsonify(code=400, message="分割模型暂无本地权重"), 400

    conf = _form_float("conf", 0.25)
    raw_sus = request.form.get("suspiciousConf")
    suspicious_conf = _form_float("suspiciousConf", 0.45) if raw_sus is not None else None
    scenario = (request.form.get("scenario") or "general").strip().lower()
    draw = (request.form.get("draw") or "1") in ("1", "true", "True")

    try:
        image_bytes = file.read()
        result = engine.run_pipeline(
            image_bytes,
            det_path=abs_path,
            seg_path=seg_path,
            seg_lib=seg_lib,
            conf=conf,
            suspicious_conf=suspicious_conf,
            scenario=scenario,
            draw=draw,
            model_key=m.model_key,
        )
    except FileNotFoundError as e:
        return jsonify(code=400, message=str(e)), 400
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"缺陷诊断失败：{e}"), 500

    result["detector"] = {
        "modelId": m.id,
        "modelKey": m.model_key,
        "modelName": m.model_name,
        "library": lib,
    }
    if seg_mid:
        result["segmentor"] = {
            "modelId": seg_mid,
            "library": seg_lib,
        }
    return jsonify(code=0, message="诊断完成", data=result)
