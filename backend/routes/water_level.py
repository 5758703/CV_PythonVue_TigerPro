"""水位检测接口 /api/ai/water-level。

POST /api/ai/water-level/detect
  form-data:
    image       : 图片文件（必填）
    detId       : RapidOCR 检测模型 ID（必填）
    recId       : RapidOCR 识别模型 ID（必填）
    waterYRatio : float 0–1，手动水面线（可选，不传则自动检测）

Response:
  { code:0, data: { level, waterY, waterYRatio, surfaceConfidence,
                    method, note, marks, markCount, imageBase64, width, height } }
"""
from flask import Blueprint, request, jsonify

from models import AiModel
from security import permission_required

water_level_bp = Blueprint("water_level", __name__, url_prefix="/api/ai/water-level")


def _get_model_path(mid):
    import os
    from flask import current_app
    m = AiModel.query.get(mid)
    if m is None or not m.file_path:
        return None
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    return p if os.path.exists(p) else None


@water_level_bp.post("/detect")
@permission_required("ai:water:list")
def detect():
    """水位检测：上传水位尺图片 + RapidOCR 模型 -> 水位值 + 标注图。"""
    file = request.files.get("image")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片文件（field name: image）"), 400

    try:
        det_id = int(request.form.get("detId", 0))
        rec_id = int(request.form.get("recId", 0))
    except (TypeError, ValueError):
        return jsonify(code=400, message="detId / recId 参数无效"), 400

    if det_id == 0 or rec_id == 0:
        return jsonify(code=400, message="请选择检测模型（detId）和识别模型（recId）"), 400

    det_m = AiModel.query.get(det_id)
    rec_m = AiModel.query.get(rec_id)
    if det_m is None or rec_m is None:
        return jsonify(code=400, message="模型不存在，请检查 detId / recId"), 400
    if (det_m.library or "").lower() != "rapidocr" or (rec_m.library or "").lower() != "rapidocr":
        return jsonify(code=400, message="请选择 library=rapidocr 的检测和识别模型"), 400

    det_dir = _get_model_path(det_id)
    rec_dir = _get_model_path(rec_id)
    if det_dir is None or rec_dir is None:
        return jsonify(code=400, message="检测/识别模型暂无本地权重，请先在模型管理页拉取"), 400

    water_y_ratio = None
    raw_wy = (request.form.get("waterYRatio") or "").strip()
    if raw_wy:
        try:
            v = float(raw_wy)
            if 0.0 < v < 1.0:
                water_y_ratio = v
        except ValueError:
            pass

    image_bytes = file.read()

    try:
        from inference import paddle_ocr
        from services.water_level import detect_water_level

        def ocr_fn(img_bytes):
            return paddle_ocr(det_dir, rec_dir, img_bytes).get("lines", [])

        data = detect_water_level(ocr_fn, image_bytes, water_y_ratio)
    except Exception as e:      # noqa: BLE001
        return jsonify(code=500, message=f"水位检测失败：{e}"), 500

    return jsonify(code=0, message="检测完成", data=data)
