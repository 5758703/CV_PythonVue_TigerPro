"""RADAR abdominal CT API /api/ai/radar."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from security import permission_required
from services import radar as engine

radar_bp = Blueprint("radar", __name__, url_prefix="/api/ai/radar")


def _form_float(name: str, default: float | None = None) -> float | None:
    raw = request.form.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@radar_bp.get("/status")
@permission_required("ai:model:query")
def status():
    return jsonify(code=0, message="ok", data=engine.status())


@radar_bp.post("/infer")
@permission_required("ai:model:query")
def infer():
    """Run RADAR findings inference (mock by default).

    Form:
      file — NIfTI (.nii / .nii.gz) required for real engine; optional under mock
             (JPG/PNG also accepted under mock).
      threshold — positive score cutoff (default from config)
      engine — optional override: auto | mock | real
    """
    upload = request.files.get("file")
    filename = upload.filename if upload and upload.filename else None
    data = upload.read() if upload and upload.filename else None
    threshold = _form_float("threshold")
    forced = (request.form.get("engine") or "").strip() or None

    try:
        result = engine.infer(
            filename=filename,
            data=data,
            threshold=threshold,
            engine=forced,
        )
    except engine.RadarError as exc:
        code = 503 if "权重" in str(exc) or "真推理" in str(exc) else 400
        return jsonify(code=code, message=str(exc), data=None), code
    except Exception as exc:  # noqa: BLE001
        return jsonify(code=500, message=f"推理失败: {exc}", data=None), 500
    return jsonify(code=0, message="ok", data=result)


@radar_bp.post("/report")
@permission_required("ai:model:query")
def report():
    """Generate assistive Chinese report from findings JSON."""
    body = request.get_json(silent=True) or {}
    findings = body.get("findings")
    if not isinstance(findings, list) or not findings:
        return jsonify(code=400, message="缺少 findings 数组"), 400
    threshold = body.get("threshold")
    try:
        thr = float(threshold) if threshold is not None else None
    except (TypeError, ValueError):
        thr = None
    image_name = body.get("imageName") or body.get("filename")
    try:
        result = engine.build_assistive_report(
            findings,
            threshold=thr,
            image_name=image_name,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify(code=502, message=f"报告生成失败: {exc}", data=None), 502
    return jsonify(code=0, message="ok", data=result)
