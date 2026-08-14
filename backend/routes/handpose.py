"""手势识别（手部 21 关键点 + 0-9 手势，含中式 6-9）/api/ai/handpose。"""
import base64
import os

import cv2
import numpy as np
from flask import Blueprint, current_app, jsonify, request

from security import permission_required

handpose_bp = Blueprint("handpose", __name__, url_prefix="/api/ai/handpose")

MODEL_REL_DIR = os.path.join("models", "opencv-handpose-mediapipe")


def _model_dir():
    return os.path.join(current_app.config["UPLOAD_FOLDER"], MODEL_REL_DIR)


def _parse_float(name, default):
    try:
        return float(request.form.get(name, default))
    except (TypeError, ValueError):
        return default


@handpose_bp.post("/estimate")
@permission_required("ai:handpose:list")
def estimate():
    """单帧/单图手部关键点估计与 0-9 手势分类。

    表单：file 图片；palmScore 手掌检测阈值(默认0.5)；handConf 关键点置信阈值(默认0.8)；
    maxHands 最大手数(默认2)；draw=1 返回标注图 base64。
    返回：hands[{..., fingers, count, gesture, gestureZh, digit}],
    displayText（单手「2」/ 双手「1.2」）, leftDigit, rightDigit,
    primaryDigit（兼容）, totalCount, extendedTotal。
    """
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400
    arr = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify(code=400, message="无法解析图片"), 400

    palm_score = _parse_float("palmScore", 0.5)
    hand_conf = _parse_float("handConf", 0.8)
    max_hands = int(_parse_float("maxHands", 2))
    draw = (request.form.get("draw") or "0") in ("1", "true", "True")

    from services.handpose import detect_hands, draw_hands, format_display_digits, primary_digit, resolve_handedness

    try:
        hands = detect_hands(
            img, _model_dir(),
            palm_score=palm_score, hand_conf=hand_conf, max_hands=max_hands,
        )
    except FileNotFoundError as e:
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"手部关键点推理失败：{e}"), 500

    # 摄像头帧通常非镜像，而 MediaPipe 按镜像假设输出左右；校正后再组合左.右
    hands = resolve_handedness(hands, swap_labels=True)
    disp = format_display_digits(hands)
    dig = primary_digit(hands)
    data = {
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
