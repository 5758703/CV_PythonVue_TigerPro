"""文档表格识别接口 /api/ai/table。

POST /api/ai/table/recognize
  form-data:
    file       : 图片（必填）
    detectId   : YOLO 表格检测模型 ID（必填，library=ultralytics）
    detId      : RapidOCR 检测模型 ID（必填）
    recId      : RapidOCR 识别模型 ID（必填）
    tableId    : SLANet_plus 结构模型 ID（必填，library=rapidtable）
    conf       : 表格检测置信度（可选，默认 0.25）

Response:
  { code:0, data: { tables, tableCount, detections, imageBase64, width, height, ... } }
"""
from flask import Blueprint, request, jsonify, current_app
import os

from models import AiModel
from security import permission_required

table_recog_bp = Blueprint("table_recog", __name__, url_prefix="/api/ai/table")


def _abs_weight_file(m):
    """单文件权重（YOLO / rapidtable onnx）。"""
    if m is None or not m.file_path:
        return None
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    if os.path.isfile(p):
        return p
    if os.path.isdir(p):
        for root, _dirs, files in os.walk(p):
            for f in files:
                low = f.lower()
                if low.endswith((".pt", ".onnx")):
                    return os.path.join(root, f)
    return None


def _abs_model_dir(m):
    if m is None or not m.file_path:
        return None
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    return p if os.path.exists(p) else None


@table_recog_bp.post("/recognize")
@permission_required("ai:table:list")
def recognize():
    """YOLO 检表 → RapidOCR → SLANet_plus → HTML/CSV。"""
    file = request.files.get("file") or request.files.get("image")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片文件（field: file）"), 400

    def _int(name):
        try:
            return int(request.form.get(name, 0))
        except (TypeError, ValueError):
            return 0

    detect_id = _int("detectId")
    det_id = _int("detId")
    rec_id = _int("recId")
    table_id = _int("tableId")
    if not all([detect_id, det_id, rec_id, table_id]):
        return jsonify(code=400, message="请选择检测模型、OCR 检测/识别模型与表格结构模型"), 400

    try:
        conf = float(request.form.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25
    conf = max(0.05, min(0.95, conf))

    detect_m = AiModel.query.get(detect_id)
    det_m = AiModel.query.get(det_id)
    rec_m = AiModel.query.get(rec_id)
    table_m = AiModel.query.get(table_id)
    if not all([detect_m, det_m, rec_m, table_m]):
        return jsonify(code=400, message="模型不存在，请检查各模型 ID"), 400

    if (detect_m.library or "").lower() != "ultralytics" or detect_m.task != "object-detection":
        return jsonify(code=400, message="表格检测模型需为 library=ultralytics 且 task=object-detection"), 400
    if (det_m.library or "").lower() != "rapidocr" or (rec_m.library or "").lower() != "rapidocr":
        return jsonify(code=400, message="请选择 library=rapidocr 的文本检测与识别模型"), 400
    if (table_m.library or "").lower() != "rapidtable" or table_m.task != "table-structure":
        return jsonify(code=400, message="结构模型需为 library=rapidtable 且 task=table-structure"), 400

    detect_path = _abs_weight_file(detect_m)
    det_dir = _abs_model_dir(det_m)
    rec_dir = _abs_model_dir(rec_m)
    table_path = _abs_weight_file(table_m)
    if detect_path is None:
        return jsonify(code=400, message="表格检测模型暂无本地权重，请先在模型管理页拉取"), 400
    if det_dir is None or rec_dir is None:
        return jsonify(code=400, message="RapidOCR 检测/识别模型暂无本地权重，请先拉取"), 400
    if table_path is None:
        return jsonify(code=400, message="表格结构模型暂无本地权重，请先拉取 SLANet_plus"), 400

    image_bytes = file.read()
    try:
        from inference import detect_image, paddle_ocr, table_structure
        from services.table_recog import recognize_tables

        def detect_fn(img_bytes):
            return detect_image(detect_path, img_bytes, conf=conf, draw=False)

        def ocr_fn(img_bytes):
            return paddle_ocr(det_dir, rec_dir, img_bytes)

        def table_fn(crop_bgr, lines):
            return table_structure(
                table_path,
                crop_bgr,
                lines,
                model_key=table_m.model_key,
            )

        data = recognize_tables(
            image_bytes,
            detect_fn=detect_fn,
            ocr_fn=ocr_fn,
            table_fn=table_fn,
            conf=conf,
            whole_image_fallback=True,
        )
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"表格识别失败：{e}"), 500

    return jsonify(code=0, message="识别完成", data=data)
