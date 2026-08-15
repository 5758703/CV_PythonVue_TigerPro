"""手势识别：MediaPipe 0–9 数字 + 中国手语 YOLO11s /api/ai/handpose。

支持同时启用多个识别引擎：recognizer=mediapipe,csl-yolo11s
支持本地视频异步识别：POST /estimate-video
"""
import os
import threading
import time
import uuid

import cv2
import numpy as np
from flask import Blueprint, current_app, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from security import permission_required

handpose_bp = Blueprint("handpose", __name__, url_prefix="/api/ai/handpose")

MEDIAPIPE_REL_DIR = os.path.join("models", "opencv-handpose-mediapipe")
CSL_REL_DIR = os.path.join("models", "chinese-sign-language-tigerhhzz-yolo11s")

_CSL_ALIASES = frozenset({"csl-yolo11s", "csl", "sign-language", "chinese-sign-language"})
_MP_ALIASES = frozenset({"mediapipe", "digit", "digits", "number", "numbers"})

_video_jobs: dict = {}
_video_jobs_lock = threading.Lock()


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


def _parse_recognizers() -> list[str]:
    """解析表单 recognizer：支持单值、逗号分隔、重复字段。"""
    raw_list = request.form.getlist("recognizer")
    if not raw_list:
        raw = (request.form.get("recognizers") or "mediapipe").strip()
        raw_list = [raw] if raw else ["mediapipe"]
    selected: list[str] = []
    for item in raw_list:
        for part in str(item or "").replace(";", ",").split(","):
            key = part.strip().lower()
            if not key:
                continue
            if key in _CSL_ALIASES:
                rid = "csl-yolo11s"
            elif key in _MP_ALIASES or key == "mediapipe":
                rid = "mediapipe"
            else:
                rid = key
            if rid not in selected:
                selected.append(rid)
    if not selected:
        selected = ["mediapipe"]
    return selected


@handpose_bp.get("/models")
@permission_required("ai:handpose:list")
def list_models():
    """可选识别引擎：MediaPipe 数字 / 中国手语 YOLO11s（可多选）。"""
    from services.sign_language import list_recognizers

    recognizers = list_recognizers()
    for r in recognizers:
        if r.get("id") == "csl-yolo11s":
            from services.sign_language import load_class_names_list
            try:
                r["classes"] = load_class_names_list(_csl_dir())
            except Exception:  # noqa: BLE001
                r["classes"] = r.get("classes") or []
    return jsonify(code=0, message="ok", data={"recognizers": recognizers, "multiSelect": True})


@handpose_bp.post("/estimate")
@permission_required("ai:handpose:list")
def estimate():
    """单帧/单图手势识别（可同时启用数字 + 手语）。"""
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400
    arr = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify(code=400, message="无法解析图片"), 400

    selected = _parse_recognizers()
    draw = (request.form.get("draw") or "0") in ("1", "true", "True")
    use_mp = "mediapipe" in selected
    use_csl = "csl-yolo11s" in selected

    if not use_mp and not use_csl:
        return jsonify(code=400, message="请至少选择一种识别模型"), 400

    mp_data = None
    csl_data = None
    errors = []

    if use_mp:
        try:
            mp_data = _run_mediapipe(img)
        except FileNotFoundError as e:
            errors.append(str(e))
        except Exception as e:  # noqa: BLE001
            errors.append(f"数字手势失败：{e}")

    if use_csl:
        try:
            csl_data = _run_csl(img)
        except FileNotFoundError as e:
            errors.append(str(e))
        except Exception as e:  # noqa: BLE001
            errors.append(f"手语检测失败：{e}")

    if mp_data is None and csl_data is None:
        msg = "；".join(errors) if errors else "识别失败"
        return jsonify(code=500, message=msg), 500

    data = _merge_results(img, selected, mp_data, csl_data, draw=draw)
    if errors:
        data["warnings"] = errors
    return jsonify(code=0, message="ok", data=data)


def _video_worker(job_id, src_path, out_path, out_name, selected, params):
    from services.handpose_video import process_handpose_video

    def cb(processed, total):
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j["processed"] = processed
                j["total"] = total

    try:
        stats = process_handpose_video(
            src_path, out_path,
            selected=selected,
            mediapipe_dir=params["mediapipe_dir"],
            csl_dir=params["csl_dir"],
            palm_score=params["palm_score"],
            hand_conf=params["hand_conf"],
            max_hands=params["max_hands"],
            det_conf=params["det_conf"],
            frame_stride=params["frame_stride"],
            stable_n=params["stable_n"],
            progress_cb=cb,
        )
        stats["output"] = out_name
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j.update(
                    status="done",
                    stats=stats,
                    processed=stats.get("frames", 0),
                    total=stats.get("frames", 0),
                )
    except Exception as e:  # noqa: BLE001
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j.update(status="error", error=str(e))
    finally:
        if os.path.isfile(src_path):
            try:
                os.remove(src_path)
            except OSError:
                pass


@handpose_bp.post("/estimate-video")
@permission_required("ai:handpose:list")
def estimate_video():
    """本地视频手势识别（异步）。

    表单：file 视频；recognizer（可多选）；handConf/maxHands/conf/frameStride。
    返回 jobId，轮询 /video-progress/<jobId>。
    """
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到视频"), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的视频格式"), 400

    selected = _parse_recognizers()
    if not selected:
        return jsonify(code=400, message="请至少选择一种识别模型"), 400

    video_folder = current_app.config["VIDEO_FOLDER"]
    out_folder = current_app.config["OUTPUT_FOLDER"]
    os.makedirs(video_folder, exist_ok=True)
    os.makedirs(out_folder, exist_ok=True)

    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "handpose"
    src_path = os.path.join(video_folder, f"{base}_{ts}{ext}")
    out_name = f"{base}_{ts}_handpose.mp4"
    out_path = os.path.join(out_folder, out_name)
    file.save(src_path)

    try:
        frame_stride = int(_parse_float("frameStride", 2))
    except (TypeError, ValueError):
        frame_stride = 2
    frame_stride = max(1, min(frame_stride, 10))

    params = {
        "mediapipe_dir": _mediapipe_dir(),
        "csl_dir": _csl_dir(),
        "palm_score": _parse_float("palmScore", 0.5),
        "hand_conf": _parse_float("handConf", 0.8),
        "max_hands": int(_parse_float("maxHands", 2)),
        "det_conf": _parse_float("conf", 0.25),
        "frame_stride": frame_stride,
        "stable_n": int(_parse_float("stableN", 2)),
    }

    job_id = uuid.uuid4().hex
    with _video_jobs_lock:
        _video_jobs[job_id] = {
            "status": "running", "processed": 0, "total": 0, "stats": None, "error": None,
        }
    threading.Thread(
        target=_video_worker,
        args=(job_id, src_path, out_path, out_name, selected, params),
        daemon=True,
    ).start()
    return jsonify(code=0, message="任务已启动", data={"jobId": job_id})


@handpose_bp.get("/video-progress/<job_id>")
@permission_required("ai:handpose:list")
def video_progress(job_id):
    with _video_jobs_lock:
        j = _video_jobs.get(job_id)
        if j is None:
            return jsonify(code=404, message="任务不存在或已过期"), 404
        data = dict(j)
    if data["status"] == "error":
        return jsonify(code=0, message=data.get("error") or "视频处理失败", data=data)
    return jsonify(code=0, data=data)


@handpose_bp.get("/output/<path:name>")
@permission_required("ai:handpose:list")
def output_video(name):
    if not name.endswith("_handpose.mp4"):
        return jsonify(code=400, message="非法文件名"), 400
    safe_name = secure_filename(name)
    if not safe_name or safe_name != name:
        return jsonify(code=400, message="非法文件名"), 400
    folder = current_app.config["OUTPUT_FOLDER"]
    path = os.path.join(folder, safe_name)
    if not os.path.isfile(path):
        return jsonify(code=404, message="文件不存在"), 404
    return send_from_directory(folder, safe_name, as_attachment=False)


def _merge_results(img, selected, mp_data, csl_data, *, draw: bool) -> dict:
    from services.handpose_multi import merge_estimate_results
    return merge_estimate_results(img, selected, mp_data, csl_data, draw=draw)


def _run_csl(img) -> dict:
    from services.sign_language import detect_sign_language

    conf = _parse_float("conf", 0.25)
    return detect_sign_language(
        img, _csl_dir(), conf=conf, draw=False, mediapipe_dir=_mediapipe_dir(),
    )


def _run_mediapipe(img) -> dict:
    from services.handpose import detect_hands, format_display_digits, primary_digit, resolve_handedness

    palm_score = _parse_float("palmScore", 0.5)
    hand_conf = _parse_float("handConf", 0.8)
    max_hands = int(_parse_float("maxHands", 2))

    hands = detect_hands(
        img, _mediapipe_dir(),
        palm_score=palm_score, hand_conf=hand_conf, max_hands=max_hands,
    )
    hands = resolve_handedness(hands, swap_labels=True)
    disp = format_display_digits(hands)
    dig = primary_digit(hands)
    return {
        "recognizer": "mediapipe",
        "hands": hands,
        **disp,
        "primaryDigit": dig,
        "totalCount": int(dig) if dig is not None else 0,
        "extendedTotal": int(sum(h["count"] for h in hands)),
        "width": img.shape[1],
        "height": img.shape[0],
    }
