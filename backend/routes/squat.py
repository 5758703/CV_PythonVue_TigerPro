"""Squat counting video and live-session endpoints."""

from __future__ import annotations

import os
import base64
import threading
import uuid
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from werkzeug.utils import secure_filename

from models import AiModel, Camera
from security import current_user, has_perm, permission_required
from services.squat_counter import SquatConfig
from services.squat_video import PoseFrameEstimator
from services.squat_sessions import SessionError, SquatSessionManager


squat_bp = Blueprint("squat", __name__, url_prefix="/api/ai/squat")

_video_jobs: dict[str, dict] = {}
_video_jobs_lock = threading.Lock()
_session_manager = SquatSessionManager()


def _start_worker(target):
    threading.Thread(target=target, daemon=True).start()


def _number(name, default, *, integer=False):
    raw = request.form.get(name, default)
    try:
        return int(raw) if integer else float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _config_from_form():
    try:
        return SquatConfig(
            keypoint_conf=_number("keypointConf", 0.25),
            standing_angle=_number("standingAngle", 160.0),
            bottom_angle=_number("bottomAngle", 100.0),
            confirm_frames=_number("confirmFrames", 3, integer=True),
            lost_grace_seconds=_number("lostGraceSeconds", 1.0),
            smoothing_window=_number("smoothingWindow", 5, integer=True),
        )
    except ValueError as exc:
        message = str(exc)
        if "bottom_angle" in message:
            message = "standing angle must be greater than bottom angle"
        raise ValueError(message) from exc


def _config_from_json(data):
    def value(name, default, cast=float):
        try:
            return cast(data.get(name, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
    try:
        return SquatConfig(
            keypoint_conf=value("keypointConf", 0.25),
            standing_angle=value("standingAngle", 160.0),
            bottom_angle=value("bottomAngle", 100.0),
            confirm_frames=value("confirmFrames", 3, int),
            lost_grace_seconds=value("lostGraceSeconds", 1.0),
            smoothing_window=value("smoothingWindow", 5, int),
        )
    except ValueError as exc:
        message = str(exc)
        if "bottom_angle" in message:
            message = "standing angle must be greater than bottom angle"
        raise ValueError(message) from exc


def _resolve_estimator(model_id, conf):
    model = AiModel.query.get(int(model_id))
    if model is None:
        raise SessionError("pose model not found")
    if model.status != "0":
        raise SessionError("pose model is disabled")
    from routes.ai_model import _resolve_pose_runtime
    library, weight_path, _task = _resolve_pose_runtime(model)
    if not 0 <= float(conf) <= 1:
        raise SessionError("conf must be between 0 and 1")
    return PoseFrameEstimator(library, model.model_key or "", weight_path, conf=float(conf))


def _owned_job(job_id):
    owner_id = str(get_jwt_identity())
    with _video_jobs_lock:
        job = _video_jobs.get(job_id)
        return dict(job) if job and job.get("ownerId") == owner_id else None


def _video_worker(job_id, estimator, source: Path, output: Path, output_name: str, config):
    from services.squat_video import process_squat_video

    def progress(processed, total):
        with _video_jobs_lock:
            job = _video_jobs.get(job_id)
            if job:
                job.update(processed=processed, total=total)

    try:
        stats = process_squat_video(estimator, source, output, config, progress_cb=progress)
        stats["output"] = output_name
        with _video_jobs_lock:
            job = _video_jobs.get(job_id)
            if job:
                job.update(
                    status="done", stats=stats, processed=stats.get("frames", 0),
                    total=stats.get("frames", 0),
                )
    except Exception as exc:  # noqa: BLE001 - worker failure belongs in job status
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        with _video_jobs_lock:
            job = _video_jobs.get(job_id)
            if job:
                job.update(status="error", error=str(exc))
    finally:
        try:
            source.unlink(missing_ok=True)
        except OSError:
            pass


@squat_bp.post("/video")
@permission_required("ai:model:query")
def create_video_job():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify(code=400, message="video file is required"), 400
    extension = Path(uploaded.filename).suffix.lower()
    allowed = set(current_app.config.get("VIDEO_ALLOWED_EXT", {".mp4", ".avi", ".mov", ".mkv"}))
    if extension not in allowed:
        return jsonify(code=400, message="unsupported video format"), 400
    try:
        model_id = int(request.form.get("modelId", 0))
    except (TypeError, ValueError):
        model_id = 0
    model = AiModel.query.get(model_id) if model_id else None
    if model is None:
        return jsonify(code=404, message="pose model not found"), 404
    if model.status != "0":
        return jsonify(code=400, message="pose model is disabled"), 400
    try:
        from routes.ai_model import _resolve_pose_runtime
        library, weight_path, _task = _resolve_pose_runtime(model)
        config = _config_from_form()
        conf = _number("conf", 0.25)
        if not 0 <= conf <= 1:
            raise ValueError("conf must be between 0 and 1")
    except ValueError as exc:
        return jsonify(code=400, message=str(exc)), 400

    uploaded.stream.seek(0, os.SEEK_END)
    size = uploaded.stream.tell()
    uploaded.stream.seek(0)
    max_bytes = int(current_app.config.get("SQUAT_MAX_VIDEO_BYTES", 512 * 1024 * 1024))
    if size > max_bytes:
        return jsonify(code=413, message="video exceeds size limit"), 413

    video_dir = Path(current_app.config["VIDEO_FOLDER"])
    output_dir = Path(current_app.config["OUTPUT_FOLDER"])
    video_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    base = secure_filename(Path(uploaded.filename).stem) or "squats"
    source = video_dir / f"{base}_{job_id}{extension}"
    output_name = f"{base}_{job_id}_squat.mp4"
    output = output_dir / output_name
    uploaded.save(source)
    owner_id = str(get_jwt_identity())
    with _video_jobs_lock:
        _video_jobs[job_id] = {
            "ownerId": owner_id, "status": "running", "processed": 0,
            "total": 0, "stats": None, "error": None,
        }
    estimator = PoseFrameEstimator(library, model.model_key or "", weight_path, conf=conf)
    _start_worker(lambda: _video_worker(job_id, estimator, source, output, output_name, config))
    return jsonify(code=0, message="squat video job started", data={"jobId": job_id})


@squat_bp.get("/video-progress/<job_id>")
@permission_required("ai:model:query")
def video_progress(job_id):
    job = _owned_job(job_id)
    if job is None:
        return jsonify(code=404, message="video job not found"), 404
    job.pop("ownerId", None)
    return jsonify(code=0, data=job)


@squat_bp.get("/output/<path:name>")
@permission_required("ai:model:query")
def output_video(name):
    safe_name = secure_filename(name)
    if safe_name != name or not name.endswith("_squat.mp4"):
        return jsonify(code=400, message="invalid squat output name"), 400
    job = None
    with _video_jobs_lock:
        for candidate in _video_jobs.values():
            if candidate.get("ownerId") == str(get_jwt_identity()) and (candidate.get("stats") or {}).get("output") == name:
                job = candidate
                break
    if not job or job.get("status") != "done":
        return jsonify(code=404, message="squat output not found"), 404
    path = Path(current_app.config["OUTPUT_FOLDER"]) / safe_name
    if not path.is_file():
        return jsonify(code=404, message="squat output not found"), 404
    return send_file(path, mimetype="video/mp4", conditional=True)


@squat_bp.post("/sessions")
@permission_required("ai:model:query")
def create_session():
    data = request.get_json(silent=True) or {}
    source_type = str(data.get("sourceType") or "").lower()
    if source_type not in {"local", "network"}:
        return jsonify(code=400, message="sourceType must be local or network"), 400
    try:
        model_id = int(data.get("modelId", 0))
        config = _config_from_json(data)
        estimator = _resolve_estimator(model_id, data.get("conf", 0.25))
        owner_id = str(get_jwt_identity())
        if source_type == "local":
            if data.get("cameraId") is not None:
                raise SessionError("local session must not include cameraId")
            session = _session_manager.create_local(owner_id, estimator, config)
        else:
            camera_id = int(data.get("cameraId", 0))
            camera = Camera.query.get(camera_id) if camera_id else None
            if camera is None or camera.status != "0":
                raise SessionError("enabled managed camera not found")
            from services.camera_stream import _resolve_source
            source = _resolve_source(camera, current_app.config["UPLOAD_FOLDER"])
            session = _session_manager.create_network(owner_id, source, estimator, config)
    except (ValueError, SessionError) as exc:
        return jsonify(code=400, message=str(exc)), 400
    return jsonify(code=0, data=session.public_snapshot())


@squat_bp.post("/sessions/<session_id>/frames")
@permission_required("ai:model:query")
def submit_session_frame(session_id):
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify(code=400, message="JPEG frame is required"), 400
    try:
        result = _session_manager.submit_frame(
            session_id,
            str(get_jwt_identity()),
            int(request.form.get("sequence", -1)),
            float(request.form.get("capturedAt", 0)),
            uploaded.read(),
        )
    except (TypeError, ValueError, SessionError) as exc:
        return jsonify(code=400, message=str(exc)), 400
    payload = {
        "frameSequence": result["frameSequence"],
        "state": result["state"],
        "annotatedImageBase64": base64.b64encode(result["annotatedJpeg"]).decode("ascii"),
    }
    return jsonify(code=0, data=payload)


@squat_bp.get("/sessions/<session_id>")
@permission_required("ai:model:query")
def get_session(session_id):
    try:
        data = _session_manager.snapshot(session_id, str(get_jwt_identity()))
    except SessionError as exc:
        return jsonify(code=404, message=str(exc)), 404
    return jsonify(code=0, data=data)


@squat_bp.delete("/sessions/<session_id>")
@permission_required("ai:model:query")
def stop_session(session_id):
    try:
        data = _session_manager.stop(session_id, str(get_jwt_identity()))
    except SessionError as exc:
        return jsonify(code=404, message=str(exc)), 404
    return jsonify(code=0, data=data)


@squat_bp.get("/sessions/<session_id>/stream")
def stream_session(session_id):
    try:
        verify_jwt_in_request(locations=["query_string"])
    except Exception:  # noqa: BLE001 - return stable auth response for <img>
        return jsonify(code=401, message="authentication required"), 401
    user = current_user()
    if not has_perm(user, "ai:model:query"):
        return jsonify(code=403, message="permission denied"), 403
    try:
        frames = _session_manager.mjpeg(session_id, str(get_jwt_identity()))
    except SessionError as exc:
        return jsonify(code=404, message=str(exc)), 404
    return Response(frames, mimetype="multipart/x-mixed-replace; boundary=frame")
