"""跨摄像头 / 跨视频 MTMC 重识别 API /api/ai/mtmc。"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
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
from services.mtmc_engine import MtmcConfig, VirtualVideoSource, next_virtual_cam_id

mtmc_bp = Blueprint("mtmc", __name__, url_prefix="/api/ai/mtmc")


def _form_bool(val, default=False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _parse_session_params(data: dict) -> MtmcConfig:
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
    camera_ids = data.get("cameraIds") or []
    if isinstance(camera_ids, str):
        camera_ids = [int(x) for x in camera_ids.split(",") if x.strip()]
    camera_ids = [int(x) for x in camera_ids]
    return MtmcConfig(
        camera_ids=camera_ids,
        det_person_path=_abs_weight(person_m),
        det_vehicle_path=_abs_weight(vehicle_m),
        youtu_root=_abs_weight(youtu_m),
        strong_reid_root=_abs_weight(strong_m),
        vehicle_reid_root=_abs_weight(vreid_m),
        plate_model_path=_abs_weight(plate_m),
        ocr_fn=ocr_fn,
        enable_person=_form_bool(data.get("enablePerson"), True),
        enable_vehicle=_form_bool(data.get("enableVehicle"), True),
        conf=float(data.get("conf") or 0.28),
        sample_fps=float(data.get("sampleFps") or 4.0),
        meters_per_pixel=float(data.get("metersPerPixel") or 0.05),
        appear_thresh=float(data.get("appearThresh") or 0.48),
        vehicle_appear_thresh=float(data.get("vehicleAppearThresh") or 0),
        confirm_thresh=float(data.get("confirmThresh") or 0),
        candidate_thresh=float(data.get("candidateThresh") or 0),
        use_faiss_gallery=_form_bool(data.get("useFaissGallery"), True),
        gallery_model_key=(data.get("galleryModelKey") or "").strip() or None,
        time_window_sec=float(data.get("timeWindowSec") or 90),
        fuse_weight_strong=mtmc_engine.normalize_fuse_weight_strong(data.get("fuseWeightStrong")),
        width=int(data.get("width") or 960),
        fps=int(data.get("fps") or 10),
        persist_events=_form_bool(data.get("persistEvents"), False),
        reid_budget=int(data.get("reidBudget") or 2),
        plate_budget=int(data.get("plateBudget") or 1),
        local_track_backend=track_backend,
        local_track_max_age=int(data.get("localTrackMaxAge") or 30),
        local_track_iou_thresh=float(data.get("localTrackIouThresh") or 0.3),
        enable_cmc=_form_bool(data.get("enableCmc"), False),
        enable_mask_cue=_form_bool(data.get("enableMaskCue"), False),
        lost_revive_sec=float(data.get("lostReviveSec") or 1.0),
        mcbyte_decouple=_form_bool(data.get("mcbyteDecouple"), True),
        detect_only=_form_bool(data.get("detectOnly"), False),
    )


def _validate_mtmc_config(cfg: MtmcConfig):
    if cfg.enable_person and not cfg.det_person_path:
        return "人员检测模型未就绪，请先拉取 YOLO"
    if cfg.enable_person and not os.path.isfile(cfg.det_person_path):
        return f"人员检测模型路径无效（非文件）: {cfg.det_person_path}"
    if cfg.enable_vehicle and not cfg.det_vehicle_path:
        return "车辆检测模型未就绪"
    if cfg.enable_vehicle and not os.path.isfile(cfg.det_vehicle_path):
        return f"车辆检测模型路径无效（非文件）: {cfg.det_vehicle_path}"
    return None


def _resolve_mtmc_video_path(raw_path: str, upload_folder: str) -> str:
    """解析 MTMC 服务器本地视频路径（uploads 相对路径 / docs/test_data / 绝对路径）。"""
    src = (raw_path or "").strip().replace("\\", "/")
    if not src:
        raise ValueError("路径为空")
    if os.path.isabs(src):
        p = os.path.abspath(src)
        if os.path.isfile(p):
            return p
        raise FileNotFoundError(f"视频不存在：{raw_path}")
    upload_base = os.path.abspath(upload_folder)
    p_up = os.path.abspath(os.path.join(upload_base, src))
    if p_up.startswith(upload_base) and os.path.isfile(p_up):
        return p_up
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(backend_dir)
    docs_base = os.path.join(repo_root, "docs", "test_data")
    p_docs = os.path.abspath(os.path.join(docs_base, src))
    if p_docs.startswith(docs_base) and os.path.isfile(p_docs):
        return p_docs
    raise FileNotFoundError(f"视频不存在：{raw_path}")


def _start_mtmc_video_session(
    *,
    video_items: list[tuple[str, str, str]],
    params: dict,
    upload_dir: str | None = None,
    source_type: str = "file",
):
    """video_items: [(abs_path_or_url, display_name, original_filename), ...]"""
    detect_only = _form_bool(params.get("detectOnly"), False)
    if detect_only and len(video_items) > 1:
        video_items = video_items[:1]
    cam_ids: list[int] = []
    video_sources: dict[int, VirtualVideoSource] = {}
    st = (source_type or "file").strip().lower()
    for idx, (abs_path, label, orig_name) in enumerate(video_items):
        cid = next_virtual_cam_id()
        cam_ids.append(cid)
        ext = os.path.splitext(abs_path)[1].lower()
        img_ext = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        item_st = "image" if ext in img_ext else st
        is_stream = item_st in ("rtsp", "device")
        video_sources[cid] = VirtualVideoSource(
            id=cid,
            name=label or os.path.splitext(orig_name)[0] or f"镜头{idx + 1}",
            abs_path="" if is_stream else abs_path,
            source=abs_path if is_stream else "",
            source_type=item_st,
            original_filename=orig_name or os.path.basename(abs_path),
            resolution=int(params.get("width") or 960),
            fps=int(params.get("fps") or 10),
        )
    if detect_only:
        params = {**params, "persistEvents": False, "reidBudget": 0, "plateBudget": 0}
    cfg = _parse_session_params({**params, "cameraIds": cam_ids})
    err = _validate_mtmc_config(cfg)
    if err:
        return None, err
    edges = None if detect_only else mtmc_engine._auto_topology_edges(cam_ids)
    session = mtmc_engine.start_session(
        cfg,
        video_sources=video_sources,
        upload_folder=current_app.config["UPLOAD_FOLDER"],
        app=current_app._get_current_object(),
        topology_edges=edges,
        upload_dir=upload_dir,
    )
    return session, None


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
        edge_type=str(data.get("edgeType") or "non_overlap").strip().lower(),
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

    cfg = _parse_session_params({**data, "cameraIds": camera_ids})
    err = _validate_mtmc_config(cfg)
    if err:
        return jsonify(code=400, message=err), 400

    edges = mtmc_engine.load_database_topology()
    session = mtmc_engine.start_session(
        cfg,
        cameras=cams,
        upload_folder=current_app.config["UPLOAD_FOLDER"],
        app=current_app._get_current_object(),
        topology_edges=edges,
    )
    return jsonify(code=0, message="跨镜会话已启动", data=session.to_dict())


@mtmc_bp.post("/sessions/start-videos")
@permission_required("ai:mtmc:edit")
def start_session_videos():
    """上传本地视频启动跨镜会话（无需预建摄像头）。"""
    files = request.files.getlist("videos") or request.files.getlist("videos[]")
    if not files:
        for key in sorted(request.files.keys()):
            if key.startswith("video"):
                files.append(request.files[key])
    files = [f for f in files if f and f.filename]
    if len(files) < 1:
        return jsonify(code=400, message="请至少上传 1 个本地视频或图片"), 400

    names_raw = (request.form.get("videoNames") or "").strip()
    names: list[str] = []
    if names_raw:
        try:
            parsed = json.loads(names_raw)
            if isinstance(parsed, list):
                names = [str(x).strip() for x in parsed]
        except json.JSONDecodeError:
            names = [n.strip() for n in names_raw.split(",") if n.strip()]

    upload_root = current_app.config["UPLOAD_FOLDER"]
    batch_dir = os.path.join(upload_root, "mtmc_videos", uuid.uuid4().hex[:16])
    os.makedirs(batch_dir, exist_ok=True)

    allowed = current_app.config.get("VIDEO_ALLOWED_EXT") or {".mp4", ".avi", ".mov", ".mkv"}
    img_allowed = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    video_items: list[tuple[str, str, str]] = []
    session_source_type = "file"

    for idx, vf in enumerate(files):
        ext = os.path.splitext(vf.filename)[1].lower()
        if ext not in allowed and ext not in img_allowed:
            return jsonify(code=400, message=f"不支持的文件格式：{vf.filename}"), 400
        if ext in img_allowed:
            session_source_type = "image"
        base = secure_filename(os.path.splitext(vf.filename)[0]) or f"cam{idx}"
        fname = f"cam_{idx}_{base}{ext}"
        abs_path = os.path.join(batch_dir, fname)
        vf.save(abs_path)
        if not os.path.isfile(abs_path):
            return jsonify(code=400, message=f"文件保存失败：{vf.filename}"), 400
        label = names[idx] if idx < len(names) and names[idx] else os.path.splitext(vf.filename)[0]
        video_items.append((abs_path, label, vf.filename))

    form_data = {k: request.form.get(k) for k in request.form.keys()}
    session, err = _start_mtmc_video_session(
        video_items=video_items,
        params=form_data,
        upload_dir=batch_dir,
        source_type=session_source_type,
    )
    if err:
        return jsonify(code=400, message=err), 400
    return jsonify(code=0, message="本地视频跨镜会话已启动", data=session.to_dict())


@mtmc_bp.post("/sessions/start-video-paths")
@permission_required("ai:mtmc:edit")
def start_session_video_paths():
    """使用服务器已有视频路径启动跨镜（免上传，适合 docs/test_data 大文件）。"""
    data = request.get_json(silent=True) or {}
    paths = data.get("videoPaths") or []
    if isinstance(paths, str):
        paths = [p.strip() for p in paths.split(",") if p.strip()]
    if len(paths) < 1:
        return jsonify(code=400, message="请至少提供 1 个服务器视频/图片路径"), 400

    names = data.get("videoNames") or []
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",") if n.strip()]

    upload_root = current_app.config["UPLOAD_FOLDER"]
    allowed = current_app.config.get("VIDEO_ALLOWED_EXT") or {".mp4", ".avi", ".mov", ".mkv"}
    img_allowed = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    video_items: list[tuple[str, str, str]] = []
    session_source_type = "file"

    for idx, raw in enumerate(paths):
        ext = os.path.splitext(str(raw))[1].lower()
        if ext not in allowed and ext not in img_allowed:
            return jsonify(code=400, message=f"不支持的文件格式：{raw}"), 400
        if ext in img_allowed:
            session_source_type = "image"
        try:
            abs_path = _resolve_mtmc_video_path(str(raw), upload_root)
        except (ValueError, FileNotFoundError) as e:
            return jsonify(code=400, message=str(e)), 400
        orig = os.path.basename(abs_path)
        label = names[idx] if idx < len(names) and names[idx] else os.path.splitext(orig)[0]
        video_items.append((abs_path, label, orig))

    session, err = _start_mtmc_video_session(
        video_items=video_items,
        params=data,
        upload_dir=None,
        source_type=session_source_type,
    )
    if err:
        return jsonify(code=400, message=err), 400
    return jsonify(code=0, message="服务器视频跨镜会话已启动", data=session.to_dict())


@mtmc_bp.post("/sessions/start-sources")
@permission_required("ai:mtmc:edit")
def start_session_sources():
    """混合源启动：file/path/image/rtsp/device，至少 1 路。"""
    data = request.get_json(silent=True) or {}
    sources = data.get("sources") or []
    if not isinstance(sources, list) or len(sources) < 1:
        return jsonify(code=400, message="请至少配置 1 路视频源"), 400
    detect_only = _form_bool(data.get("detectOnly"), False)
    if detect_only:
        sources = sources[:1]
        data = {**data, "persistEvents": False, "reidBudget": 0, "plateBudget": 0}

    upload_root = current_app.config["UPLOAD_FOLDER"]
    video_items: list[tuple[str, str, str]] = []
    # 同源类型会话：若混用，以首路为准；rtsp/device 与 file 可混但各自 VirtualVideoSource.source_type 独立
    # 这里按路独立创建，不共用 session_source_type
    cam_ids: list[int] = []
    video_sources: dict[int, VirtualVideoSource] = {}
    for idx, row in enumerate(sources):
        if not isinstance(row, dict):
            return jsonify(code=400, message=f"第 {idx + 1} 路源格式无效"), 400
        st = str(row.get("type") or row.get("sourceType") or "file").strip().lower()
        name = (row.get("name") or f"镜头{idx + 1}").strip()
        cid = next_virtual_cam_id()
        width = int(data.get("width") or row.get("width") or 960)
        fps = int(data.get("fps") or row.get("fps") or 10)
        if st == "rtsp":
            url = (row.get("url") or row.get("source") or "").strip()
            if not url.startswith("rtsp://"):
                return jsonify(code=400, message=f"{name}: RTSP 地址无效"), 400
            video_sources[cid] = VirtualVideoSource(
                id=cid, name=name, abs_path="", source=url, source_type="rtsp",
                original_filename=url, resolution=width, fps=fps,
            )
        elif st == "device":
            device = (row.get("device") or row.get("source") or "").strip()
            if not device:
                return jsonify(code=400, message=f"{name}: 请填写本机摄像头设备名"), 400
            video_sources[cid] = VirtualVideoSource(
                id=cid, name=name, abs_path="", source=device, source_type="device",
                original_filename=device, resolution=width, fps=fps,
            )
        elif st in ("file", "path", "image", "video"):
            raw = (row.get("path") or row.get("source") or "").strip()
            if not raw:
                return jsonify(code=400, message=f"{name}: 请填写文件路径"), 400
            try:
                abs_path = _resolve_mtmc_video_path(raw, upload_root)
            except (ValueError, FileNotFoundError) as e:
                return jsonify(code=400, message=str(e)), 400
            ext = os.path.splitext(abs_path)[1].lower()
            img_ext = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
            vst = "image" if ext in img_ext or st == "image" else "file"
            video_sources[cid] = VirtualVideoSource(
                id=cid, name=name, abs_path=abs_path, source="", source_type=vst,
                original_filename=os.path.basename(abs_path), resolution=width, fps=fps,
            )
        else:
            return jsonify(code=400, message=f"不支持的源类型：{st}"), 400
        cam_ids.append(cid)

    cfg = _parse_session_params({**data, "cameraIds": cam_ids})
    err = _validate_mtmc_config(cfg)
    if err:
        return jsonify(code=400, message=err), 400
    edges = None if detect_only else (mtmc_engine._auto_topology_edges(cam_ids) if len(cam_ids) >= 2 else [])
    session = mtmc_engine.start_session(
        cfg,
        video_sources=video_sources,
        upload_folder=upload_root,
        app=current_app._get_current_object(),
        topology_edges=edges,
        upload_dir=None,
    )
    return jsonify(code=0, message="实时检测会话已启动", data=session.to_dict())


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
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    from services.camera_stream import mjpeg_stream_mtmc_overlay, mjpeg_stream_shared
    cam_row, source, width, fps = mtmc_engine.resolve_overlay_source(s, cid, upload_folder)
    if cam_row is None or not source:
        return jsonify(code=404, message="视频源不存在或无法解析"), 404
    if not s or not s.running:
        gen = mjpeg_stream_shared(cid, getattr(cam_row, "source_type", "file"), source, width, fps)
        resp = Response(stream_with_context(gen), mimetype="multipart/x-mixed-replace; boundary=frame")
        resp.headers["X-Mtmc-Overlay"] = "inactive"
    else:
        if cid not in s.cfg.camera_ids:
            return jsonify(code=400, message="该源不在当前会话中"), 400
        # 与识别 worker 使用完全相同的 hub 参数，防止同一摄像头因 FPS/宽度
        # key 不同而额外启动一套 FFmpeg 拉流进程。
        width, fps = mtmc_engine._hub_stream_params(s, cam_row)
        stype = getattr(cam_row, "source_type", "file")
        gen = mjpeg_stream_mtmc_overlay(sid, cid, stype, source, width, fps)
        resp = Response(stream_with_context(gen), mimetype="multipart/x-mixed-replace; boundary=frame")
        resp.headers["X-Mtmc-Overlay"] = "active"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@mtmc_bp.get("/raw/<sid>/<int:cid>/stream")
def raw_stream(sid, cid):
    """实时检测测试：原视频 MJPEG（query jwt），与 overlay 同节拍。"""
    try:
        verify_jwt_in_request(locations=["query_string"])
    except Exception:  # noqa: BLE001
        return jsonify(code=401, message="未登录或令牌无效"), 401
    user = current_user()
    if not has_perm(user, "ai:mtmc:query") and not has_perm(user, "camera:query"):
        return jsonify(code=403, message="没有访问权限"), 403
    s = mtmc_engine.get_session(sid)
    if not s or not s.running:
        return jsonify(code=404, message="检测会话不存在或未运行"), 404
    if cid not in s.cfg.camera_ids:
        return jsonify(code=400, message="该源不在当前会话中"), 400
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    from services.camera_stream import mjpeg_stream_mtmc_raw
    cam_row, source, width, fps = mtmc_engine.resolve_overlay_source(s, cid, upload_folder)
    if cam_row is None or not source:
        return jsonify(code=404, message="视频源不存在或无法解析"), 404
    width = s.cfg.width or width
    fps = s.cfg.fps or fps
    stype = getattr(cam_row, "source_type", "file")
    gen = mjpeg_stream_mtmc_raw(sid, cid, stype, source, width, fps)
    resp = Response(stream_with_context(gen), mimetype="multipart/x-mixed-replace; boundary=frame")
    resp.headers["X-Mtmc-Raw"] = "active"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp
