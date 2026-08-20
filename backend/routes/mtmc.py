"""跨摄像头 / 跨视频 MTMC 重识别 API /api/ai/mtmc。"""
from __future__ import annotations

import os

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from flask_jwt_extended import verify_jwt_in_request

from extensions import db
from models import AiModel, Camera
from models.mtmc import CameraTopology, MtmcTrackEvent, MtmcVehiclePass
from security import current_user, has_perm, permission_required
from services import mtmc_engine
from services.mtmc_engine import MtmcConfig

mtmc_bp = Blueprint("mtmc", __name__, url_prefix="/api/ai/mtmc")


def _abs_weight(m: AiModel | None) -> str | None:
    if m is None or not m.file_path:
        return None
    root = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    if os.path.isfile(root):
        return root
    if os.path.isdir(root):
        preferred = (
            "best.pt", "best.onnx", "yolo26n.pt", "yolo26n.onnx",
            "yolo11n.pt", "yolov8n.pt",
        )
        for name in preferred:
            p = os.path.join(root, name)
            if os.path.isfile(p):
                return p
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.lower().endswith((".pt", ".onnx", ".engine")):
                    return os.path.join(dirpath, f)
        return root
    return None


def _pick_model(mid: int | None, *, task=None, library=None, keys=None):
    m = AiModel.query.get(mid) if mid else None
    if m is None and keys:
        for key in keys:
            m = AiModel.query.filter_by(model_key=key, status="0").filter(
                AiModel.file_path.isnot(None)
            ).first()
            if m:
                break
    if m is None and task:
        q = AiModel.query.filter_by(task=task, status="0").filter(AiModel.file_path.isnot(None))
        if library:
            q = q.filter(AiModel.library == library)
        m = q.order_by(AiModel.id.asc()).first()
    return m


def _build_ocr_fn(det_id, rec_id):
    if not det_id or not rec_id:
        return None
    det_m = AiModel.query.get(det_id)
    rec_m = AiModel.query.get(rec_id)
    if not det_m or not rec_m or not det_m.file_path or not rec_m.file_path:
        return None
    det_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], det_m.file_path)
    rec_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], rec_m.file_path)
    from inference import paddle_ocr

    def _fn(img_bytes: bytes):
        return paddle_ocr(det_dir, rec_dir, img_bytes, plate_mode=True, rec_only=True)

    return _fn


# ---------------- 拓扑 ----------------

@mtmc_bp.get("/topology")
@permission_required("ai:mtmc:list")
def list_topology():
    rows = CameraTopology.query.order_by(CameraTopology.id.asc()).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": len(rows)})


@mtmc_bp.post("/topology")
@permission_required("ai:mtmc:edit")
def add_topology():
    data = request.get_json(silent=True) or {}
    a = int(data.get("fromCameraId") or 0)
    b = int(data.get("toCameraId") or 0)
    if not a or not b or a == b:
        return jsonify(code=400, message="请填写不同的 from/to 摄像头"), 400
    row = CameraTopology(
        from_camera_id=a,
        to_camera_id=b,
        min_transit_sec=float(data.get("minTransitSec") or 0),
        max_transit_sec=float(data.get("maxTransitSec") or 120),
        weight=float(data.get("weight") or 1),
        remark=(data.get("remark") or "").strip() or None,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(code=0, message="已添加", data=row.to_dict())


@mtmc_bp.delete("/topology/<int:tid>")
@permission_required("ai:mtmc:edit")
def remove_topology(tid):
    row = CameraTopology.query.get_or_404(tid)
    db.session.delete(row)
    db.session.commit()
    return jsonify(code=0, message="已删除")


# ---------------- 会话 ----------------

@mtmc_bp.get("/sessions")
@permission_required("ai:mtmc:list")
def sessions():
    return jsonify(code=0, data={"rows": mtmc_engine.list_sessions()})


@mtmc_bp.get("/sessions/<sid>")
@permission_required("ai:mtmc:query")
def session_detail(sid):
    s = mtmc_engine.get_session(sid)
    if not s:
        return jsonify(code=404, message="会话不存在"), 404
    return jsonify(code=0, data=s.to_dict())


@mtmc_bp.get("/sessions/<sid>/alive")
def session_alive(sid):
    """轻量会话探活（监控墙用，避免无效 overlay 流 404 刷屏）。"""
    try:
        verify_jwt_in_request()
    except Exception:  # noqa: BLE001
        return jsonify(code=401, message="未登录或令牌无效"), 401
    user = current_user()
    if not has_perm(user, "ai:mtmc:query") and not has_perm(user, "camera:query"):
        return jsonify(code=403, message="没有访问权限"), 403
    s = mtmc_engine.get_session(sid)
    active = bool(s and s.running)
    return jsonify(code=0, data={"sessionId": sid, "active": active})


@mtmc_bp.post("/sessions/start")
@permission_required("ai:mtmc:edit")
def start_session():
    data = request.get_json(silent=True) or {}
    camera_ids = data.get("cameraIds") or []
    if isinstance(camera_ids, str):
        camera_ids = [int(x) for x in camera_ids.split(",") if x.strip()]
    camera_ids = [int(x) for x in camera_ids]
    if len(camera_ids) < 1:
        return jsonify(code=400, message="请至少选择 1 路摄像头"), 400

    cams = Camera.query.filter(Camera.id.in_(camera_ids), Camera.status == "0").all()
    if not cams:
        return jsonify(code=400, message="无可用摄像头"), 400

    person_m = _pick_model(
        data.get("personDetModelId"),
        task="object-detection",
        keys=["yolo26n", "winedarksea-yolo26n_person", "yolo11n", "yolov8n"],
    )
    vehicle_m = _pick_model(
        data.get("vehicleDetModelId"),
        task="object-detection",
        keys=["yolo26n", "yolo11n", "yolov8n"],
    )
    youtu_m = _pick_model(
        data.get("youtuModelId"),
        task="person-reid",
        keys=["opencv-person-reid-youtu"],
    )
    strong_m = _pick_model(
        data.get("strongReidModelId"),
        task="person-reid",
        keys=["osnet-x1-0", "clip-reid-person", "fastreid-osnet"],
    )
    vreid_m = _pick_model(
        data.get("vehicleReidModelId"),
        task="vehicle-reid",
        keys=["transreid-vehicle", "clip-reid-vehicle", "vehicle-vit-reid"],
    )
    plate_m = _pick_model(data.get("plateModelId"), keys=["yolo26s-plate-pose", "yolo26n-plate"])

    ocr_fn = _build_ocr_fn(data.get("ocrDetModelId"), data.get("ocrRecModelId"))

    cfg = MtmcConfig(
        camera_ids=[c.id for c in cams],
        det_person_path=_abs_weight(person_m),
        det_vehicle_path=_abs_weight(vehicle_m),
        youtu_root=_abs_weight(youtu_m),
        strong_reid_root=_abs_weight(strong_m),
        vehicle_reid_root=_abs_weight(vreid_m),
        plate_model_path=_abs_weight(plate_m),
        ocr_fn=ocr_fn,
        enable_person=bool(data.get("enablePerson", True)),
        enable_vehicle=bool(data.get("enableVehicle", True)),
        conf=float(data.get("conf") or 0.35),
        sample_fps=float(data.get("sampleFps") or 2.0),
        meters_per_pixel=float(data.get("metersPerPixel") or 0.05),
        appear_thresh=float(data.get("appearThresh") or 0.48),
        time_window_sec=float(data.get("timeWindowSec") or 90),
        fuse_weight_strong=float(data.get("fuseWeightStrong") or 0.65),
        width=int(data.get("width") or 640),
        fps=int(data.get("fps") or 10),
        persist_events=bool(data.get("persistEvents", True)),
    )
    if cfg.enable_person and not cfg.det_person_path:
        return jsonify(code=400, message="人员检测模型未就绪，请先拉取 YOLO"), 400
    if cfg.enable_person and not cfg.youtu_root and not cfg.strong_reid_root:
        return jsonify(code=400, message="请至少准备 Youtu 或强 ReID（OSNet/CLIP）权重"), 400
    if cfg.enable_vehicle and not cfg.det_vehicle_path:
        return jsonify(code=400, message="车辆检测模型未就绪"), 400

    edges = [e.to_dict() for e in CameraTopology.query.filter_by(status="0").all()]
    session = mtmc_engine.start_session(
        cfg,
        cameras=cams,
        upload_folder=current_app.config["UPLOAD_FOLDER"],
        app=current_app._get_current_object(),
        topology_edges=edges,
    )
    return jsonify(code=0, message="跨镜会话已启动", data=session.to_dict())


@mtmc_bp.post("/sessions/<sid>/stop")
@permission_required("ai:mtmc:edit")
def stop_session(sid):
    ok = mtmc_engine.stop_session(sid)
    if not ok:
        return jsonify(code=404, message="会话不存在"), 404
    return jsonify(code=0, message="已停止")


@mtmc_bp.get("/events")
@permission_required("ai:mtmc:query")
def list_events():
    sid = (request.args.get("sessionId") or "").strip()
    gid = (request.args.get("globalId") or "").strip()
    ot = (request.args.get("objectType") or "").strip()
    page = max(1, int(request.args.get("pageNum") or 1))
    size = min(200, max(1, int(request.args.get("pageSize") or 50)))
    q = MtmcTrackEvent.query
    if sid:
        q = q.filter(MtmcTrackEvent.session_id == sid)
    if gid:
        q = q.filter(MtmcTrackEvent.global_id == gid)
    if ot:
        q = q.filter(MtmcTrackEvent.object_type == ot)
    total = q.count()
    rows = q.order_by(MtmcTrackEvent.id.desc()).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": total})


@mtmc_bp.get("/passes")
@permission_required("ai:mtmc:query")
def list_passes():
    sid = (request.args.get("sessionId") or "").strip()
    plate = (request.args.get("plate") or "").strip()
    page = max(1, int(request.args.get("pageNum") or 1))
    size = min(200, max(1, int(request.args.get("pageSize") or 50)))
    q = MtmcVehiclePass.query
    if sid:
        q = q.filter(MtmcVehiclePass.session_id == sid)
    if plate:
        q = q.filter(MtmcVehiclePass.plate.contains(plate))
    total = q.count()
    rows = q.order_by(MtmcVehiclePass.id.desc()).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": total})


@mtmc_bp.get("/trajectory/<gid>")
@permission_required("ai:mtmc:query")
def trajectory(gid):
    """按 global_id 汇总跨镜轨迹。"""
    rows = (
        MtmcTrackEvent.query.filter_by(global_id=gid)
        .order_by(MtmcTrackEvent.event_time.asc())
        .limit(500)
        .all()
    )
    # 运行中会话内存事件补充
    live = []
    for s in mtmc_engine.list_sessions():
        for ev in s.get("recentEvents") or []:
            if ev.get("globalId") == gid:
                live.append(ev)
    return jsonify(code=0, data={
        "globalId": gid,
        "dbEvents": [r.to_dict() for r in rows],
        "liveEvents": live,
    })


@mtmc_bp.get("/overlay/<sid>/<int:cid>/stream")
def overlay_stream(sid, cid):
    """监控墙 AI 叠加 MJPEG（query jwt）。"""
    try:
        verify_jwt_in_request(locations=["query_string"])
    except Exception:  # noqa: BLE001
        return jsonify(code=401, message="未登录或令牌无效"), 401
    user = current_user()
    if not has_perm(user, "ai:mtmc:query") and not has_perm(user, "camera:query"):
        return jsonify(code=403, message="没有访问权限"), 403
    s = mtmc_engine.get_session(sid)
    cam = Camera.query.get_or_404(cid)
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    from services.camera_stream import _resolve_source, mjpeg_stream_mtmc_overlay, mjpeg_stream_shared
    try:
        source = _resolve_source(cam, upload_folder)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=400, message=str(e)), 400
    width = cam.resolution or 640
    fps = cam.fps or 10
    if not s or not s.running:
        gen = mjpeg_stream_shared(cam.id, cam.source_type, source, width, fps)
        resp = Response(stream_with_context(gen), mimetype="multipart/x-mixed-replace; boundary=frame")
        resp.headers["X-Mtmc-Overlay"] = "inactive"
    else:
        if cam.id not in s.cfg.camera_ids:
            return jsonify(code=400, message="摄像头不在该会话中"), 400
        width = s.cfg.width or width
        fps = s.cfg.fps or fps
        gen = mjpeg_stream_mtmc_overlay(sid, cam.id, cam.source_type, source, width, fps)
        resp = Response(stream_with_context(gen), mimetype="multipart/x-mixed-replace; boundary=frame")
        resp.headers["X-Mtmc-Overlay"] = "active"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp
