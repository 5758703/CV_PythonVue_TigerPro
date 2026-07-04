"""羽毛球比赛视频分析 /api/ai/badminton

POST /extract-frame   上传视频提取首帧（球场标注用）
POST /analyze         启动异步分析任务
GET  /progress/<jobId> 查询进度与结果
GET  /artifact/<jobId>/<name> 下载产物（视频/图片/json）
"""
import json
import os
import threading
import time
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from models import AiModel
from security import permission_required

badminton_bp = Blueprint("badminton", __name__, url_prefix="/api/ai/badminton")

_jobs = {}
_jobs_lock = threading.Lock()


def _ensure_dir(p):
    os.makedirs(p, exist_ok=True)


def _abs_model_path(m):
    if not m or not m.file_path:
        return None
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    return p if os.path.exists(p) else None


def _job_dir(job_id):
    return os.path.join(current_app.config["BADMINTON_FOLDER"], job_id)


def _worker(job_id, pose_path, ball_path, src_path, out_dir, court_points, opts):
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
    """提取视频首帧，用于球场四角标注。"""
    file = request.files.get("video")
    if file is None or not file.filename:
        return jsonify(code=400, message="请上传视频（field: video）"), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的视频格式"), 400

    video_folder = current_app.config["VIDEO_FOLDER"]
    _ensure_dir(video_folder)
    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "video"
    src_path = os.path.join(video_folder, f"bdm_frame_{base}_{ts}{ext}")
    file.save(src_path)
    try:
        from services.badminton import extract_video_frame
        data = extract_video_frame(src_path, 0)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"提取帧失败：{e}"), 500
    finally:
        if os.path.isfile(src_path):
            try:
                os.remove(src_path)
            except OSError:
                pass
    return jsonify(code=0, message="ok", data=data)


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
        return jsonify(code=400, message="请选择姿态模型（YOLO Pose）"), 400

    pose_m = AiModel.query.get(pose_id)
    if pose_m is None:
        return jsonify(code=404, message="姿态模型不存在"), 404
    if (pose_m.library or "") != "ultralytics":
        return jsonify(code=400, message="姿态模型须为 ultralytics（YOLO Pose）"), 400

    pose_path = _abs_model_path(pose_m)
    if pose_path is None:
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

    def _flag(name, default=True):
        v = (request.form.get(name) or str(default)).lower()
        return v not in ("0", "false", "no")

    opts = {
        "conf": conf,
        "show_skeleton": _flag("showSkeleton", True),
        "show_trajectories": _flag("showTrajectories", True),
        "show_shuttle": _flag("showShuttle", True),
        "show_stats": _flag("showStats", True),
        "show_court": _flag("showCourt", True),
        "language": language,
    }

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
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
        args=(job_id, pose_path, ball_path, src_path, out_dir, court_pts, opts),
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
    return jsonify(code=0, data=data)


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
