"""摄像头管理接口（/api/camera）。

CRUD + 本地视频上传 + MJPEG 实时预览(ffmpeg 按需转流)。
"""
import os

from flask import Blueprint, request, jsonify, current_app, Response, stream_with_context
from flask_jwt_extended import verify_jwt_in_request
from werkzeug.utils import secure_filename

from extensions import db
from models import Camera
from security import permission_required, current_user, has_perm
from services.camera_stream import list_dshow_devices, check_source_ready

camera_bp = Blueprint("camera", __name__, url_prefix="/api/camera")


def _camera_dict(cam):
    d = cam.to_dict()
    d["sourceReady"] = check_source_ready(cam)
    if cam.source_type == "file" and cam.source:
        d["sourceFileName"] = os.path.basename(cam.source.replace("\\", "/"))
    return d


@camera_bp.get("")
@permission_required("camera:list")
def list_cameras():
    page = int(request.args.get("pageNum", 1))
    size = int(request.args.get("pageSize", 10))
    name = request.args.get("name", "").strip()
    status = request.args.get("status", "").strip()
    query = Camera.query
    if name:
        query = query.filter(Camera.name.like(f"%{name}%"))
    if status:
        query = query.filter(Camera.status == status)
    total = query.count()
    rows = (query.order_by(Camera.id.desc())
            .offset((page - 1) * size).limit(size).all())
    return jsonify(code=0, data={"rows": [_camera_dict(c) for c in rows], "total": total})


@camera_bp.get("/devices")
@permission_required("camera:query")
def list_local_devices():
    """枚举服务器本机的 DirectShow 视频设备名（用于「获取本机摄像头」）。"""
    try:
        names = list_dshow_devices()
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"枚举本机摄像头失败：{e}"), 500
    return jsonify(code=0, data=names)


def _apply(cam, data):
    cam.name = (data.get("name") or "").strip()
    cam.source_type = data.get("sourceType") or "file"
    cam.source = (data.get("source") or "").strip()
    cam.location = (data.get("location") or "").strip()
    cam.resolution = int(data.get("resolution") or 640)
    cam.fps = int(data.get("fps") or 15)
    cam.status = data.get("status") or "0"


def _validate(cam):
    if not cam.name:
        return "请输入摄像头名称"
    if cam.source_type not in ("file", "rtsp", "device"):
        return "来源类型非法"
    if cam.source_type == "rtsp" and not cam.source.startswith("rtsp://"):
        return "rtsp 地址须以 rtsp:// 开头"
    if not cam.source:
        return "请填写来源(本地视频/rtsp 地址/本机摄像头设备名)"
    if cam.source_type == "file" and not check_source_ready(cam):
        return f"视频文件不存在或未上传：{cam.source}"
    return None


@camera_bp.post("")
@permission_required("camera:add")
def create_camera():
    data = request.get_json(silent=True) or {}
    cam = Camera()
    _apply(cam, data)
    err = _validate(cam)
    if err:
        return jsonify(code=400, message=err), 400
    db.session.add(cam)
    db.session.commit()
    return jsonify(code=0, message="新增成功", data=_camera_dict(cam))


@camera_bp.put("/<int:cid>")
@permission_required("camera:edit")
def update_camera(cid):
    cam = Camera.query.get_or_404(cid)
    data = request.get_json(silent=True) or {}
    _apply(cam, data)
    err = _validate(cam)
    if err:
        return jsonify(code=400, message=err), 400
    db.session.commit()
    return jsonify(code=0, message="修改成功", data=_camera_dict(cam))


@camera_bp.delete("/<int:cid>")
@permission_required("camera:remove")
def delete_camera(cid):
    cam = Camera.query.get_or_404(cid)
    db.session.delete(cam)
    db.session.commit()
    return jsonify(code=0, message="删除成功")


@camera_bp.post("/batch-delete")
@permission_required("camera:remove")
def batch_delete_cameras():
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    if ids:
        Camera.query.filter(Camera.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
    return jsonify(code=0, message="批量删除成功")


@camera_bp.post("/upload")
@permission_required("camera:add")
def upload_video():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到文件"), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        return jsonify(code=400, message="仅支持视频文件(mp4/avi/mov/mkv 等)"), 400
    folder = current_app.config["CAMERA_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    base = secure_filename(os.path.splitext(file.filename)[0]) or "camera"
    fname = f"{base}{ext}"
    abs_path = os.path.join(folder, fname)
    file.save(abs_path)
    rel = f"cameras/{fname}"   # 相对 UPLOAD_FOLDER
    return jsonify(code=0, message="上传成功", data={"filePath": rel, "fileName": file.filename})


@camera_bp.get("/<int:cid>/stream")
def stream_camera(cid):
    # <img> 无法带 header -> 用 query token 鉴权
    try:
        verify_jwt_in_request(locations=["query_string"])
    except Exception:  # noqa: BLE001
        return jsonify(code=401, message="未登录或令牌无效"), 401
    user = current_user()
    if not has_perm(user, "camera:query"):
        return jsonify(code=403, message="没有访问权限"), 403
    cam = Camera.query.get_or_404(cid)
    if cam.status != "0":
        return jsonify(code=409, message="摄像头已停用"), 409
    check_only = request.args.get("check") == "1"
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    try:
        from services.camera_stream import (
            _resolve_source, probe_file_mjpeg, probe_rtsp_mjpeg, mjpeg_stream_shared,
        )
        source = _resolve_source(cam, upload_folder)
        if check_only:
            if cam.source_type == "file":
                probe_err = probe_file_mjpeg(cam, upload_folder)
                if probe_err:
                    return jsonify(code=500, message=f"本地视频转流失败：{probe_err}"), 500
            elif cam.source_type == "rtsp":
                probe_err = probe_rtsp_mjpeg(cam, upload_folder)
                if probe_err:
                    return jsonify(code=500, message=f"RTSP 探活失败：{probe_err}"), 500
            return jsonify(code=0, message="ok")
    except FileNotFoundError as e:
        return jsonify(code=404, message=str(e)), 404
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400
    # 监控墙多路预览：共享拉流，避免每格一个 ffmpeg
    shared = request.args.get("shared", "1") != "0"
    gen = mjpeg_stream_shared(
        cam.id, cam.source_type, source, cam.resolution, cam.fps,
    ) if shared else None
    if gen is None:
        from services.camera_stream import mjpeg_stream
        gen = mjpeg_stream(cam.source_type, source, cam.resolution, cam.fps)
    resp = Response(
        stream_with_context(gen),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp
