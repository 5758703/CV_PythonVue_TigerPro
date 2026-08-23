"""跨摄像头 / 跨视频 MTMC 重识别 API /api/ai/mtmc。"""
from __future__ import annotations

import os
import tempfile
from werkzeug.utils import secure_filename

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from flask_jwt_extended import verify_jwt_in_request

from extensions import db
from models import AiModel, Camera
from models.mtmc import (
    CameraTopology,
    MtmcAssociationEdge,
    MtmcCandidatePair,
    MtmcCrossCameraEvent,
    MtmcGlobalPerson,
    MtmcGlobalVehicle,
    MtmcSearchJob,
    MtmcTrackEvent,
    MtmcTracklet,
    MtmcVehiclePass,
)
from security import current_user, has_perm, permission_required
from services import mtmc_engine
from services.mtmc_engine import MtmcConfig

mtmc_bp = Blueprint("mtmc", __name__, url_prefix="/api/ai/mtmc")


def _abs_weight(m: AiModel | None) -> str | None:
    if m is None or not m.file_path:
        return None
    from services.model_paths import resolve_model_weight_path

    return resolve_model_weight_path(current_app.config["UPLOAD_FOLDER"], m.file_path)


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


def _pick_ocr_models():
    det = _pick_model(
        None,
        task="ocr",
        keys=["paddleocr-det", "PP-OCRv6_small_det_onnx", "pp-ocrv6-det"],
    )
    rec = _pick_model(
        None,
        task="ocr",
        keys=["paddleocr-rec", "PP-OCRv6_small_rec_onnx", "pp-ocrv6-rec"],
    )
    return det, rec


def _build_ocr_fn(det_id, rec_id):
    if det_id and rec_id:
        fn = _build_ocr_fn_from_ids(det_id, rec_id)
        if fn:
            return fn
    det_m, rec_m = _pick_ocr_models()
    if det_m and rec_m:
        return _build_ocr_fn_from_ids(det_m.id, rec_m.id)
    return None


def _build_ocr_fn_from_ids(det_id, rec_id):
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

    track_backend = str(data.get("localTrackBackend") or "bytetrack").strip().lower()
    if track_backend not in ("iou", "bytetrack", "botsort"):
        track_backend = "bytetrack"

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
        conf=float(data.get("conf") or 0.28),
        sample_fps=float(data.get("sampleFps") or 2.0),
        meters_per_pixel=float(data.get("metersPerPixel") or 0.05),
        appear_thresh=float(data.get("appearThresh") or 0.48),
        vehicle_appear_thresh=float(data.get("vehicleAppearThresh") or 0),
        confirm_thresh=float(data.get("confirmThresh") or 0),
        candidate_thresh=float(data.get("candidateThresh") or 0),
        use_faiss_gallery=bool(data.get("useFaissGallery", True)),
        gallery_model_key=(data.get("galleryModelKey") or "").strip() or None,
        time_window_sec=float(data.get("timeWindowSec") or 90),
        fuse_weight_strong=float(data.get("fuseWeightStrong") or 0.65),
        width=int(data.get("width") or 640),
        fps=int(data.get("fps") or 10),
        persist_events=bool(data.get("persistEvents", True)),
        local_track_backend=track_backend,
        local_track_max_age=int(data.get("localTrackMaxAge") or 30),
        local_track_iou_thresh=float(data.get("localTrackIouThresh") or 0.3),
        enable_cmc=bool(data.get("enableCmc", False)),
        enable_mask_cue=bool(data.get("enableMaskCue", False)),
        lost_revive_sec=float(data.get("lostReviveSec") or 1.0),
        mcbyte_decouple=bool(data.get("mcbyteDecouple", True)),
    )
    if cfg.enable_person and not cfg.det_person_path:
        return jsonify(code=400, message="人员检测模型未就绪，请先拉取 YOLO"), 400
    if cfg.enable_person and not os.path.isfile(cfg.det_person_path):
        return jsonify(
            code=400,
            message=f"人员检测模型路径无效（非文件）: {cfg.det_person_path}",
        ), 400
    if cfg.enable_person and not cfg.youtu_root and not cfg.strong_reid_root:
        return jsonify(code=400, message="请至少准备 Youtu 或强 ReID（OSNet/CLIP）权重"), 400
    if cfg.enable_vehicle and not cfg.det_vehicle_path:
        return jsonify(code=400, message="车辆检测模型未就绪"), 400
    if cfg.enable_vehicle and not os.path.isfile(cfg.det_vehicle_path):
        return jsonify(
            code=400,
            message=f"车辆检测模型路径无效（非文件）: {cfg.det_vehicle_path}",
        ), 400

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


@mtmc_bp.get("/tracklets")
@permission_required("ai:mtmc:query")
def list_tracklets():
    sid = (request.args.get("sessionId") or "").strip()
    gid = (request.args.get("globalId") or "").strip()
    ot = (request.args.get("objectType") or "").strip()
    page = max(1, int(request.args.get("pageNum") or 1))
    size = min(200, max(1, int(request.args.get("pageSize") or 50)))
    q = MtmcTracklet.query
    if sid:
        q = q.filter(MtmcTracklet.session_id == sid)
    if gid:
        q = q.filter(MtmcTracklet.global_id == gid)
    if ot:
        q = q.filter(MtmcTracklet.object_type == ot)
    total = q.count()
    rows = q.order_by(MtmcTracklet.id.desc()).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": total})


@mtmc_bp.get("/globals/person")
@permission_required("ai:mtmc:query")
def list_global_persons():
    gid = (request.args.get("globalId") or "").strip()
    page = max(1, int(request.args.get("pageNum") or 1))
    size = min(200, max(1, int(request.args.get("pageSize") or 50)))
    q = MtmcGlobalPerson.query
    if gid:
        q = q.filter(MtmcGlobalPerson.global_id == gid)
    total = q.count()
    rows = q.order_by(MtmcGlobalPerson.last_seen_at.desc()).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": total})


@mtmc_bp.get("/globals/vehicle")
@permission_required("ai:mtmc:query")
def list_global_vehicles():
    gid = (request.args.get("globalId") or "").strip()
    plate = (request.args.get("plate") or "").strip()
    page = max(1, int(request.args.get("pageNum") or 1))
    size = min(200, max(1, int(request.args.get("pageSize") or 50)))
    q = MtmcGlobalVehicle.query
    if gid:
        q = q.filter(MtmcGlobalVehicle.global_id == gid)
    if plate:
        q = q.filter(MtmcGlobalVehicle.plate.contains(plate))
    total = q.count()
    rows = q.order_by(MtmcGlobalVehicle.last_seen_at.desc()).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": total})


@mtmc_bp.get("/sessions/<sid>/candidates")
@permission_required("ai:mtmc:query")
def session_candidates(sid):
    s = mtmc_engine.get_session(sid)
    live = s.associator.list_candidates() if s else []
    q = MtmcCandidatePair.query.filter_by(session_id=sid)
    status = (request.args.get("status") or "").strip()
    if status:
        q = q.filter(MtmcCandidatePair.status == status)
    db_rows = q.order_by(MtmcCandidatePair.id.desc()).limit(200).all()
    return jsonify(
        code=0,
        data={
            "live": live,
            "rows": [r.to_dict() for r in db_rows],
            "total": len(db_rows),
        },
    )


@mtmc_bp.get("/candidates")
@permission_required("ai:mtmc:query")
def list_candidates_db():
    sid = (request.args.get("sessionId") or "").strip()
    status = (request.args.get("status") or "pending").strip()
    page = max(1, int(request.args.get("pageNum") or 1))
    size = min(200, max(1, int(request.args.get("pageSize") or 50)))
    q = MtmcCandidatePair.query
    if sid:
        q = q.filter(MtmcCandidatePair.session_id == sid)
    if status:
        q = q.filter(MtmcCandidatePair.status == status)
    total = q.count()
    rows = q.order_by(MtmcCandidatePair.id.desc()).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": total})


@mtmc_bp.post("/candidates/promote")
@permission_required("ai:mtmc:edit")
def promote_candidate():
    data = request.get_json(silent=True) or {}
    sid = (data.get("sessionId") or "").strip()
    gid = (data.get("globalId") or "").strip()
    cand = (data.get("candidateGlobalId") or "").strip()
    if not sid or not gid or not cand:
        return jsonify(code=400, message="sessionId、globalId、candidateGlobalId 必填"), 400
    result = mtmc_engine.promote_candidate(sid, gid, cand)
    if not result.get("ok"):
        return jsonify(code=400, message=result.get("message") or "晋升失败"), 400
    return jsonify(code=0, message="已晋升合并", data=result)


@mtmc_bp.post("/candidates/reject")
@permission_required("ai:mtmc:edit")
def reject_candidate():
    data = request.get_json(silent=True) or {}
    sid = (data.get("sessionId") or "").strip()
    gid = (data.get("globalId") or "").strip()
    cand = (data.get("candidateGlobalId") or "").strip()
    if not sid or not gid or not cand:
        return jsonify(code=400, message="sessionId、globalId、candidateGlobalId 必填"), 400
    result = mtmc_engine.reject_candidate(sid, gid, cand)
    if not result.get("ok"):
        return jsonify(code=400, message="驳回失败或记录不存在"), 400
    return jsonify(code=0, message="已驳回", data=result)


@mtmc_bp.get("/cross-events")
@permission_required("ai:mtmc:query")
def list_cross_events():
    sid = (request.args.get("sessionId") or "").strip()
    gid = (request.args.get("globalId") or "").strip()
    page = max(1, int(request.args.get("pageNum") or 1))
    size = min(200, max(1, int(request.args.get("pageSize") or 50)))
    q = MtmcCrossCameraEvent.query
    if sid:
        q = q.filter(MtmcCrossCameraEvent.session_id == sid)
    if gid:
        q = q.filter(MtmcCrossCameraEvent.global_id == gid)
    total = q.count()
    rows = q.order_by(MtmcCrossCameraEvent.id.desc()).offset((page - 1) * size).limit(size).all()
    live = []
    for s in mtmc_engine.list_sessions():
        if sid and s.get("sessionId") != sid:
            continue
        live.extend(s.get("crossEvents") or [])
    return jsonify(
        code=0,
        data={"rows": [r.to_dict() for r in rows], "total": total, "live": live[-50:]},
    )


@mtmc_bp.post("/search/jobs")
@permission_required("ai:mtmc:edit")
def submit_search_job():
    from services.mtmc_search import submit_job

    data = request.get_json(silent=True) or {}
    job_type = (data.get("jobType") or request.form.get("jobType") or "global_trace").strip()
    params: dict = {}

    if job_type == "global_trace":
        params["globalId"] = (data.get("globalId") or request.form.get("globalId") or "").strip()
        params["sessionId"] = (data.get("sessionId") or request.form.get("sessionId") or "").strip()
        if not params["globalId"]:
            return jsonify(code=400, message="globalId 必填"), 400
    elif job_type == "multi_video_reid":
        camera_ids = data.get("cameraIds") or request.form.get("cameraIds") or []
        if isinstance(camera_ids, str):
            camera_ids = [int(x) for x in camera_ids.split(",") if x.strip()]
        camera_ids = [int(x) for x in camera_ids]
        if not camera_ids:
            return jsonify(code=400, message="cameraIds 必填"), 400
        qfile = request.files.get("query") or request.files.get("file")
        if qfile is None or not qfile.filename:
            return jsonify(code=400, message="请上传查询行人图 query"), 400
        suffix = os.path.splitext(secure_filename(qfile.filename))[1] or ".jpg"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=current_app.config["UPLOAD_FOLDER"])
        tmp_path = tmp.name
        tmp.close()
        qfile.save(tmp_path)
        youtu_m = _pick_model(
            data.get("youtuModelId") or request.form.get("youtuModelId"),
            task="person-reid",
            keys=["opencv-person-reid-youtu"],
        )
        person_m = _pick_model(
            data.get("personDetModelId") or request.form.get("personDetModelId"),
            task="object-detection",
            keys=["yolo26n", "yolo11n", "yolov8n"],
        )
        params = {
            "cameraIds": camera_ids,
            "queryImagePath": tmp_path,
            "reidRoot": _abs_weight(youtu_m),
            "modelKey": youtu_m.model_key if youtu_m else "opencv-person-reid-youtu",
            "detPath": _abs_weight(person_m),
            "threshold": float(data.get("threshold") or request.form.get("threshold") or 0.45),
            "sampleFps": float(data.get("sampleFps") or request.form.get("sampleFps") or 1.0),
            "maxFrames": int(data.get("maxFrames") or request.form.get("maxFrames") or 120),
            "topk": int(data.get("topk") or request.form.get("topk") or 20),
        }
    else:
        return jsonify(code=400, message="jobType 无效"), 400

    job_id = submit_job(current_app._get_current_object(), job_type, params)
    return jsonify(code=0, message="检索任务已提交", data={"jobId": job_id, "jobType": job_type})


@mtmc_bp.get("/search/jobs")
@permission_required("ai:mtmc:query")
def list_search_jobs():
    from services.mtmc_search import list_jobs

    job_type = (request.args.get("jobType") or "").strip() or None
    rows = list_jobs(current_app._get_current_object(), job_type=job_type, limit=int(request.args.get("limit") or 50))
    return jsonify(code=0, data={"rows": rows, "total": len(rows)})


@mtmc_bp.get("/search/jobs/<job_id>")
@permission_required("ai:mtmc:query")
def get_search_job(job_id):
    from services.mtmc_search import get_job

    row = get_job(current_app._get_current_object(), job_id)
    if not row:
        return jsonify(code=404, message="任务不存在"), 404
    return jsonify(code=0, data=row)


@mtmc_bp.get("/associations")
@permission_required("ai:mtmc:query")
def list_associations():
    sid = (request.args.get("sessionId") or "").strip()
    gid = (request.args.get("globalId") or "").strip()
    tid = (request.args.get("trackletId") or "").strip()
    page = max(1, int(request.args.get("pageNum") or 1))
    size = min(200, max(1, int(request.args.get("pageSize") or 50)))
    q = MtmcAssociationEdge.query
    if sid:
        q = q.filter(MtmcAssociationEdge.session_id == sid)
    if gid:
        q = q.filter(MtmcAssociationEdge.target_global_id == gid)
    if tid:
        q = q.filter(MtmcAssociationEdge.tracklet_id == tid)
    total = q.count()
    rows = q.order_by(MtmcAssociationEdge.id.desc()).offset((page - 1) * size).limit(size).all()
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
