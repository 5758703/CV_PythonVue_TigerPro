"""羽毛球比赛视频分析 /api/ai/badminton

POST /extract-frame   上传视频提取首帧（球场标注用，可选 autoDetect=1）
POST /detect-court    上传视频，提取首帧并自动检测球场四角
POST /analyze         启动异步分析任务
GET  /progress/<jobId> 查询进度与结果
GET  /artifact/<jobId>/<name> 下载产物（视频/图片/json）
"""
import json
import os
import threading
import time
import uuid

import numpy as np
from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from models import AiModel
from security import permission_required

badminton_bp = Blueprint("badminton", __name__, url_prefix="/api/ai/badminton")

_jobs = {}
_jobs_lock = threading.Lock()

_POSE_LIBS = frozenset({"ultralytics", "rtmlib"})


def _json_safe(obj):
    """将 numpy 标量/数组转为 JSON 可序列化的 Python 原生类型。"""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def _ensure_dir(p):
    os.makedirs(p, exist_ok=True)


def _abs_model_path(m):
    if not m or not m.file_path:
        return None
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    return p if os.path.exists(p) else None


def _job_dir(job_id):
    return os.path.join(current_app.config["BADMINTON_FOLDER"], job_id)


def _flag(name, default=True):
    v = (request.form.get(name) or str(default)).lower()
    return v not in ("0", "false", "no")


def _save_temp_video(file):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        raise ValueError("不支持的视频格式")
    video_folder = current_app.config["VIDEO_FOLDER"]
    _ensure_dir(video_folder)
    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "video"
    src_path = os.path.join(video_folder, f"bdm_frame_{base}_{ts}{ext}")
    file.save(src_path)
    return src_path


def _worker(job_id, pose_path, ball_path, src_path, out_dir, court_points, opts,
            pose_library, model_key):
    def cb(processed, total):
        with _jobs_lock:
            j = _jobs.get(job_id)
            if j:
                j["processed"] = processed
                j["total"] = total

    try:
        from services.badminton import analyze_badminton_video
        stats = analyze_badminton_video(
            pose_path, src_path, out_dir,
            court_points=court_points,
            ball_model_path=ball_path,
            pose_library=pose_library,
            model_key=model_key,
            progress_cb=cb,
            **opts,
        )
        with _jobs_lock:
            _jobs[job_id].update(status="done", stats=stats,
                                processed=stats["frames"], total=stats["frames"])
    except Exception as e:  # noqa: BLE001
        with _jobs_lock:
            _jobs[job_id].update(status="error", error=str(e))
    finally:
        if os.path.isfile(src_path):
            try:
                os.remove(src_path)
            except OSError:
                pass


@badminton_bp.post("/extract-frame")
@permission_required("ai:badminton:list")
def extract_frame():
    """提取视频首帧，用于球场四角标注。form: autoDetect=1 时尝试自动检测四角。"""
    file = request.files.get("video")
    if file is None or not file.filename:
        return jsonify(code=400, message="请上传视频（field: video）"), 400
    auto_detect = _flag("autoDetect", False)
    src_path = None
    try:
        src_path = _save_temp_video(file)
        from services.badminton import extract_video_frame
        data = extract_video_frame(src_path, 0, auto_detect_court=auto_detect)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"提取帧失败：{e}"), 500
    finally:
        if src_path and os.path.isfile(src_path):
            try:
                os.remove(src_path)
            except OSError:
                pass
    return jsonify(code=0, message="ok", data=_json_safe(data))


@badminton_bp.post("/detect-court")
@permission_required("ai:badminton:list")
def detect_court():
    """提取首帧并自动检测球场四角（0-1 归一化），失败时 courtPoints 为空。"""
    file = request.files.get("video")
    if file is None or not file.filename:
        return jsonify(code=400, message="请上传视频（field: video）"), 400
    src_path = None
    try:
        src_path = _save_temp_video(file)
        from services.badminton import extract_video_frame
        data = extract_video_frame(src_path, 0, auto_detect_court=True)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"球场检测失败：{e}"), 500
    finally:
        if src_path and os.path.isfile(src_path):
            try:
                os.remove(src_path)
            except OSError:
                pass
    msg = "自动检测成功" if data.get("autoDetected") else "未能可靠检测球场，请手动标注四角"
    return jsonify(code=0, message=msg, data=_json_safe(data))


@badminton_bp.post("/analyze")
@permission_required("ai:badminton:list")
def analyze():
    """启动羽毛球视频分析（异步）。"""
    file = request.files.get("video")
    if file is None or not file.filename:
        return jsonify(code=400, message="请上传视频"), 400

    try:
        pose_id = int(request.form.get("poseId", 0))
    except (TypeError, ValueError):
        return jsonify(code=400, message="poseId 无效"), 400
    if pose_id <= 0:
        return jsonify(code=400, message="请选择姿态模型"), 400

    pose_m = AiModel.query.get(pose_id)
    if pose_m is None:
        return jsonify(code=404, message="姿态模型不存在"), 404
    pose_lib = (pose_m.library or "ultralytics").lower()
    if pose_lib not in _POSE_LIBS:
        return jsonify(code=400, message="姿态模型须为 ultralytics 或 rtmlib"), 400
    if (pose_m.task or "") != "pose-estimation":
        return jsonify(code=400, message="所选模型任务类型须为 pose-estimation"), 400

    pose_path = _abs_model_path(pose_m)
    if pose_lib == "ultralytics" and pose_path is None:
        return jsonify(code=400, message="姿态模型暂无本地权重，请先拉取"), 400

    ball_path = None
    raw_ball = (request.form.get("ballId") or "").strip()
    if raw_ball:
        try:
            ball_id = int(raw_ball)
            ball_m = AiModel.query.get(ball_id)
            if ball_m and (ball_m.library or "") == "ultralytics":
                ball_path = _abs_model_path(ball_m)
        except (TypeError, ValueError):
            pass

    court_raw = request.form.get("courtPoints") or "[]"
    try:
        court_pts = json.loads(court_raw)
        if len(court_pts) != 4:
            raise ValueError("need 4 points")
    except (json.JSONDecodeError, ValueError, TypeError):
        return jsonify(code=400, message="请标注球场四个角点（courtPoints JSON）"), 400

    try:
        conf = float(request.form.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25

    language = (request.form.get("language") or "zh").lower()
    if language not in ("zh", "en"):
        language = "zh"

    opts = {
        "conf": conf,
        "show_skeleton": _flag("showSkeleton", True),
        "show_trajectories": _flag("showTrajectories", True),
        "show_shuttle": _flag("showShuttle", True),
        "show_stats": _flag("showStats", True),
        "show_court": _flag("showCourt", True),
        "language": language,
    }

    try:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
            return jsonify(code=400, message="不支持的视频格式"), 400
    except Exception:
        return jsonify(code=400, message="不支持的视频格式"), 400

    video_folder = current_app.config["VIDEO_FOLDER"]
    _ensure_dir(video_folder)
    _ensure_dir(current_app.config["BADMINTON_FOLDER"])

    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "match"
    src_path = os.path.join(video_folder, f"bdm_{base}_{ts}{ext}")
    file.save(src_path)

    job_id = uuid.uuid4().hex
    out_dir = _job_dir(job_id)
    _ensure_dir(out_dir)

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running", "processed": 0, "total": 0,
            "stats": None, "error": None, "jobId": job_id,
        }

    threading.Thread(
        target=_worker,
        args=(job_id, pose_path, ball_path, src_path, out_dir, court_pts, opts,
              pose_lib, pose_m.model_key or ""),
        daemon=True,
    ).start()

    return jsonify(code=0, message="分析已启动", data={"jobId": job_id})


@badminton_bp.get("/progress/<job_id>")
@permission_required("ai:badminton:list")
def progress(job_id):
    with _jobs_lock:
        j = _jobs.get(job_id)
    if j is None:
        return jsonify(code=404, message="任务不存在或已过期"), 404
    data = {
        "jobId": job_id,
        "status": j["status"],
        "processed": j.get("processed", 0),
        "total": j.get("total", 0),
        "stats": j.get("stats"),
        "error": j.get("error"),
    }
    if j["status"] == "done" and j.get("stats"):
        stats = j["stats"]
        data["artifacts"] = {
            "video": f"/api/ai/badminton/artifact/{job_id}/{stats['outputVideo']}",
            "heatmap": f"/api/ai/badminton/artifact/{job_id}/{stats['heatmap']}",
            "scatter": f"/api/ai/badminton/artifact/{job_id}/{stats['scatter']}",
            "detections": f"/api/ai/badminton/artifact/{job_id}/{stats['detections']}",
            "metadata": f"/api/ai/badminton/artifact/{job_id}/{stats['metadata']}",
        }
    return jsonify(code=0, data=_json_safe(data))


@badminton_bp.get("/artifact/<job_id>/<path:name>")
@permission_required("ai:badminton:list")
def artifact(job_id, name):
    safe = os.path.basename(name)
    path = os.path.join(_job_dir(job_id), safe)
    if not os.path.isfile(path):
        return jsonify(code=404, message="文件不存在"), 404
    ext = os.path.splitext(safe)[1].lower()
    mime = {
        ".mp4": "video/mp4",
        ".png": "image/png",
        ".json": "application/json",
        ".jsonl": "application/json",
    }.get(ext, "application/octet-stream")
    return send_file(path, mimetype=mime, as_attachment=False, download_name=safe)
