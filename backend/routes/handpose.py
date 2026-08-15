"""手势识别：MediaPipe 0–9 数字 + 中国手语 YOLO11s /api/ai/handpose。"""
import base64
import os

import cv2
import numpy as np
from flask import Blueprint, current_app, jsonify, request

from security import permission_required

handpose_bp = Blueprint("handpose", __name__, url_prefix="/api/ai/handpose")

MEDIAPIPE_REL_DIR = os.path.join("models", "opencv-handpose-mediapipe")
CSL_REL_DIR = os.path.join("models", "chinese-sign-language-tigerhhzz-yolo11s")


def _upload_root():
    return current_app.config["UPLOAD_FOLDER"]


def _mediapipe_dir():
    return os.path.join(_upload_root(), MEDIAPIPE_REL_DIR)


def _csl_dir():
    return os.path.join(_upload_root(), CSL_REL_DIR)


def _parse_float(name, default):
    try:
        return float(request.form.get(name, default))
    except (TypeError, ValueError):
        return default


@handpose_bp.get("/models")
@permission_required("ai:handpose:list")
def list_models():
    """可选识别引擎：MediaPipe 数字 / 中国手语 YOLO11s。"""
    from services.sign_language import list_recognizers

    recognizers = list_recognizers()
    # 填充 CSL 类别（需本地权重目录）
    for r in recognizers:
        if r.get("id") == "csl-yolo11s":
            from services.sign_language import load_class_names_list
            try:
                r["classes"] = load_class_names_list(_csl_dir())
            except Exception:  # noqa: BLE001
                r["classes"] = r.get("classes") or []
    return jsonify(code=0, message="ok", data={"recognizers": recognizers})


@handpose_bp.post("/estimate")
@permission_required("ai:handpose:list")
def estimate():
    """单帧/单图手势识别。

    表单：
      recognizer  mediapipe（默认）| csl-yolo11s
      file        图片
      mediapipe：palmScore, handConf, maxHands
      csl-yolo11s：conf 检测阈值(默认0.25)
      draw=1      返回标注图 base64
    """
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400
    arr = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify(code=400, message="无法解析图片"), 400

    recognizer = (request.form.get("recognizer") or "mediapipe").strip().lower()
    draw = (request.form.get("draw") or "0") in ("1", "true", "True")

    if recognizer in ("csl-yolo11s", "csl", "sign-language", "chinese-sign-language"):
        return _estimate_csl(img, draw=draw)
    return _estimate_mediapipe(img, draw=draw)


def _estimate_csl(img, *, draw: bool):
    from services.sign_language import detect_sign_language

    conf = _parse_float("conf", 0.5)
    try:
        data = detect_sign_language(
            img, _csl_dir(), conf=conf, draw=draw, mediapipe_dir=_mediapipe_dir(),
        )
    except FileNotFoundError as e:
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"手语检测失败：{e}"), 500
    return jsonify(code=0, message="ok", data=data)


def _estimate_mediapipe(img, *, draw: bool):
    from services.handpose import detect_hands, draw_hands, format_display_digits, primary_digit, resolve_handedness

    palm_score = _parse_float("palmScore", 0.5)
    hand_conf = _parse_float("handConf", 0.8)
    max_hands = int(_parse_float("maxHands", 2))

    try:
        hands = detect_hands(
            img, _mediapipe_dir(),
            palm_score=palm_score, hand_conf=hand_conf, max_hands=max_hands,
        )
    except FileNotFoundError as e:
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"手部关键点推理失败：{e}"), 500

    hands = resolve_handedness(hands, swap_labels=True)
    disp = format_display_digits(hands)
    dig = primary_digit(hands)
    data = {
        "recognizer": "mediapipe",
        "hands": hands,
        **disp,
        "primaryDigit": dig,
        "totalCount": int(dig) if dig is not None else 0,
        "extendedTotal": int(sum(h["count"] for h in hands)),
        "width": img.shape[1],
        "height": img.shape[0],
    }
    if draw:
        vis = draw_hands(img, hands)
        ok, buf = cv2.imencode(".jpg", vis)
        data["imageBase64"] = base64.b64encode(buf.tobytes()).decode() if ok else None
    return jsonify(code=0, message="ok", data=data)
