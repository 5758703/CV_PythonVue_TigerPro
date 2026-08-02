"""人员离岗检测 /api/ai/absence。"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from models import AiModel, FacePerson
from security import permission_required

absence_bp = Blueprint("absence", __name__, url_prefix="/api/ai/absence")

_video_jobs: dict = {}
_video_jobs_lock = threading.Lock()


def _parse_bool(name, default=False):
    return str(request.form.get(name, "1" if default else "0")).strip().lower() in (
        "1", "true", "yes", "on",
    )


def _parse_float(name, default=None):
    raw = request.form.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _parse_region(raw):
    if not raw:
        return None
    try:
        from services.track_zone import parse_region
        data = json.loads(raw) if isinstance(raw, str) else raw
        return parse_region(data)
    except (TypeError, ValueError):
        return None


def _parse_zone_style():
    raw = request.form.get("zoneStyle") or request.form.get("zone_style")
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                bw = parsed.get("borderWidth", parsed.get("border_width", parsed.get("lineWidth")))
                try:
                    bw = max(1, min(20, int(round(float(bw))))) if bw is not None else None
                except (TypeError, ValueError):
                    bw = None
                return {
                    "borderColor": parsed.get("borderColor") or parsed.get("border_color"),
                    "fillColor": parsed.get("fillColor") or parsed.get("fill_color"),
                    "fillAlpha": parsed.get("fillAlpha", parsed.get("fill_alpha")),
                    "borderWidth": bw,
                }
        except (TypeError, ValueError):
            pass
    return None


def _parse_staff_ids():
    raw = request.form.get("staffIds") or request.form.get("staff_ids") or "[]"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, list):
            return [int(x) for x in data]
    except (TypeError, ValueError):
        pass
    return []


def _parse_zones():
    """多工位 JSON；失败返回 None（由 enrich 回退到单 region/全画面）。"""
    raw = request.form.get("zones") or request.form.get("dutyZones")
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, list) and data:
            return data
    except (TypeError, ValueError):
        pass
    return None


def _abs_weight_file(m):
    if m is None or not m.file_path:
        return None
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    if os.path.isfile(p):
        return p
    if os.path.isdir(p):
        from routes.ai_model import _pick_local_weight
        return _pick_local_weight(p)
    return None


def _pack_name(m: AiModel) -> str:
    ver = (m.version or "").strip().lower()
    if ver.startswith("buffalo"):
        return ver
    key = (m.model_key or "").lower()
    if "buffalo_l" in key or "buffalo-l" in key:
        return "buffalo_l"
    return "buffalo_s"


def _resolve_detect(mid):
    m = AiModel.query.get(mid)
    if m is None:
        return None, "检测模型不存在"
    if (m.library or "").lower() != "ultralytics":
        return None, "人员检测须使用 ultralytics YOLO 模型"
    if m.status != "0":
        return None, "检测模型已停用"
    path = _abs_weight_file(m)
    if not path:
        return None, "检测模型暂无本地权重"
    return (m, path), None


def _resolve_face(mid):
    m = AiModel.query.get(mid)
    if m is None:
        return None, "人脸模型不存在"
    if (m.library or "").lower() != "insightface":
        return None, "请选择 library=insightface 的人脸模型"
    if m.status != "0":
        return None, "人脸模型已停用"
    root = os.path.join(current_app.config["UPLOAD_FOLDER"], "insightface")
    pack = _pack_name(m)
    pack_dir = os.path.join(root, "models", pack)
    if not os.path.isdir(pack_dir):
        return None, f"人脸模型包未就绪（{pack}），请先拉取权重"
    return (m, root, pack), None


def _absence_worker(job_id: str, cfg: dict):
    import cv2
    from inference import _open_h264, track_frame as yolo_track_frame
    from services.camera_motion import (
        compute_motion_profile,
        profile_matrix_at,
        visible_ratio,
        warp_region_norm,
    )
    from services.duty_absence import draw_duty_hud, enrich_duty_frame, get_session, parse_zones_payload
    from services.track_zone import region_to_pixels

    try:
        cap = cv2.VideoCapture(cfg["src_path"])
        if not cap.isOpened():
            raise RuntimeError("无法打开视频")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        writer, ew, eh = _open_h264(cfg["dst_path"], fps, w, h)
        session = get_session(cfg["session_id"], reset=True)
        zones = cfg.get("zones")
        zone_cfgs = parse_zones_payload(
            zones,
            region=cfg.get("region"),
            staff_ids=cfg.get("staff_ids") or [],
            absence_threshold_sec=cfg.get("absence_threshold_sec") or 30,
        )
        has_regions = any(z.get("region") for z in zone_cfgs)
        # 移动/手持镜头：先整段估计全局运动，检测时把工位从参考帧坐标
        # warp 到当前帧，保证工位钉在画面内容（真实桌位）上而非屏幕坐标
        motion_profile = None
        if has_regions:
            try:
                motion_profile = compute_motion_profile(cfg["src_path"])
            except Exception:  # noqa: BLE001
                motion_profile = None
        ref_mats = {
            z["id"]: profile_matrix_at(motion_profile, float(z.get("refSec") or 0.0))
            for z in zone_cfgs
        }
        # 有区域时统一走 enrich 内的多边形判定（逐帧可变），不给 YOLO 静态 region
        yolo_region = None if (zones or (motion_profile and has_regions)) else cfg.get("region")
        processed = 0
        last = None
        # 离岗计时必须按视频时间轴推进：处理慢于实时时，
        # 若用 wall-clock 会把处理耗时算进离岗时长（4 秒视频算出 180+ 秒离岗）
        start_ts = time.time()
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_ts = start_ts + processed / fps
            # 本帧的工位坐标（镜头运动补偿后）；出画面的工位暂停离岗计时
            c_cur = profile_matrix_at(motion_profile, processed / fps)
            zones_frame = []
            for zc in zone_cfgs:
                if not zc.get("region") or motion_profile is None:
                    zones_frame.append(dict(zc))
                    continue
                reg_w = warp_region_norm(zc["region"], ref_mats[zc["id"]], c_cur)
                zones_frame.append({
                    **zc,
                    "region": reg_w,
                    "outOfView": visible_ratio(reg_w) < 0.30,
                })
            zones_arg = zones_frame if (zones or (motion_profile and has_regions)) else None
            ok2, buf = cv2.imencode(".jpg", frame)
            if not ok2:
                continue
            image_bytes = buf.tobytes()
            reset = processed == 0
            base = yolo_track_frame(
                cfg["detect_path"],
                image_bytes,
                conf=cfg["conf"],
                reset=reset,
                imgsz=cfg["imgsz"],
                classes=[0],
                region=yolo_region,
                class_preset="person",
                session_id=cfg["session_id"],
            )
            last = enrich_duty_frame(
                frame,
                base,
                session,
                face_root=cfg["face_root"],
                face_pack=cfg["face_pack"],
                face_model_key=cfg["face_model_key"],
                staff_ids=cfg.get("staff_ids") or [],
                absence_threshold_sec=cfg["absence_threshold_sec"],
                face_threshold=cfg["face_threshold"],
                stream_ok=True,
                now=frame_ts,
                zones=zones_arg,
                region=cfg.get("region"),
            )
            status_by_id = {z.get("zoneId"): z for z in (last.get("zones") or [])}
            zones_px = []
            for zc in zones_frame:
                if not zc.get("region"):
                    continue
                # 出画面的多边形交给 OpenCV 画线时自然裁剪，无需特判
                st = status_by_id.get(zc["id"]) or {}
                zones_px.append({
                    "zoneId": zc["id"],
                    "zoneName": zc["name"],
                    "region_px": region_to_pixels(zc["region"], w, h),
                    "borderColor": zc.get("borderColor"),
                    "fillColor": zc.get("fillColor"),
                    "dutyStatus": st.get("dutyStatus"),
                    "awaySeconds": st.get("awaySeconds"),
                })
            px_region = (
                region_to_pixels(cfg.get("region"), w, h)
                if cfg.get("region") is not None and not zones_px
                else None
            )
            vis = draw_duty_hud(
                frame, last,
                region_px=px_region,
                zone_style=cfg.get("zone_style"),
                zones_px=zones_px or None,
            )
            if vis.shape[1] != ew or vis.shape[0] != eh:
                vis = cv2.resize(vis, (ew, eh))
            writer.append_data(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
            processed += 1
            cb = cfg.get("progress_cb")
            if cb:
                cb(processed, total)
        cap.release()
        writer.close()
        stats = {
            "frames": processed,
            "fps": fps,
            "output": cfg["out_name"],
            "dutyStatus": (last or {}).get("dutyStatus"),
            "eventCount": len(session.events),
            "events": session.events[-50:],
            "awaySeconds": (last or {}).get("awaySeconds"),
            "zones": [
                {
                    "zoneId": z.get("zoneId"),
                    "zoneName": z.get("zoneName"),
                    "dutyStatus": z.get("dutyStatus"),
                    "awaySeconds": z.get("awaySeconds"),
                }
                for z in ((last or {}).get("zones") or [])
            ],
        }
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j["status"] = "done"
                j["processed"] = processed
                j["total"] = total or processed
                j["stats"] = stats
    except Exception as e:  # noqa: BLE001
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j["status"] = "error"
                j["error"] = str(e)
    finally:
        try:
            if os.path.isfile(cfg["src_path"]):
                os.remove(cfg["src_path"])
        except OSError:
            pass


@absence_bp.get("/staff-options")
@permission_required("ai:absence:list")
def staff_options():
    """已启用且已录入特征的人员，供岗位名单勾选。"""
    model_key = (request.args.get("modelKey") or "").strip() or None
    rows = FacePerson.query.filter(FacePerson.status == "0").order_by(FacePerson.id.desc()).all()
    out = []
    for p in rows:
        embs = p.embeddings or []
        if model_key:
            embs = [e for e in embs if e.model_key == model_key]
            if not embs:
                continue
        elif not embs:
            continue
        d = p.to_dict()
        d["modelKeys"] = sorted({e.model_key for e in (p.embeddings or [])})
        out.append(d)
    return jsonify(code=0, data={"rows": out, "total": len(out)})


@absence_bp.post("/track-frame")
@permission_required("ai:absence:list")
def track_frame_api():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片（field: file）"), 400
    try:
        detect_id = int(request.form.get("detectId") or 0)
        face_id = int(request.form.get("faceModelId") or request.form.get("faceId") or 0)
    except (TypeError, ValueError):
        return jsonify(code=400, message="detectId / faceModelId 无效"), 400

    det, err = _resolve_detect(detect_id)
    if err:
        return jsonify(code=400, message=err), 400
    face, err = _resolve_face(face_id)
    if err:
        return jsonify(code=400, message=err), 400
    _dm, detect_path = det
    fm, face_root, face_pack = face

    conf = _parse_float("conf", 0.25) or 0.25
    imgsz = int(_parse_float("imgsz", 640) or 640)
    region = _parse_region(request.form.get("region"))
    zones = _parse_zones()
    zone_style = _parse_zone_style()
    staff_ids = _parse_staff_ids()
    absence_thr = _parse_float("absenceThresholdSec", 30) or 30.0
    face_thr = _parse_float("faceThreshold", 0.4) or 0.4
    session_id = (request.form.get("sessionId") or "").strip() or uuid.uuid4().hex
    reset = _parse_bool("reset", False)
    stream_ok = _parse_bool("streamOk", True)

    image_bytes = file.read()
    try:
        import cv2
        import numpy as np
        from inference import track_frame as yolo_track_frame
        from services.duty_absence import enrich_duty_frame, get_session

        arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return jsonify(code=400, message="无法解析图片"), 400

        yolo_region = None if zones else region
        base = yolo_track_frame(
            detect_path,
            image_bytes,
            conf=conf,
            reset=reset,
            imgsz=imgsz,
            classes=[0],
            region=yolo_region,
            class_preset="person",
            session_id=session_id,
        )
        session = get_session(session_id, reset=reset)
        enriched = enrich_duty_frame(
            img,
            base,
            session,
            face_root=face_root,
            face_pack=face_pack,
            face_model_key=fm.model_key,
            staff_ids=staff_ids,
            absence_threshold_sec=absence_thr,
            face_threshold=face_thr,
            stream_ok=stream_ok,
            zones=zones,
            region=region,
        )
        enriched["sessionId"] = session_id
        if zone_style:
            enriched["zoneStyle"] = zone_style
        return jsonify(code=0, message="ok", data=enriched)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"离岗检测失败：{e}"), 500


@absence_bp.post("/motion-profile")
@permission_required("ai:absence:list")
def motion_profile_api():
    """整段视频的逐帧全局运动轨迹（归一化空间累计仿射），供前端画布做镜头运动补偿。"""
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到视频"), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的视频格式"), 400
    from services.camera_motion import compute_motion_profile

    video_folder = current_app.config["VIDEO_FOLDER"]
    os.makedirs(video_folder, exist_ok=True)
    tmp_path = os.path.join(video_folder, f"motion_{uuid.uuid4().hex}{ext}")
    file.save(tmp_path)
    try:
        prof = compute_motion_profile(tmp_path)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"运动估计失败:{e}"), 500
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    return jsonify(code=0, data=prof)


@absence_bp.post("/track-video")
@permission_required("ai:absence:list")
def track_video_api():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到视频"), 400
    try:
        detect_id = int(request.form.get("detectId") or 0)
        face_id = int(request.form.get("faceModelId") or request.form.get("faceId") or 0)
    except (TypeError, ValueError):
        return jsonify(code=400, message="detectId / faceModelId 无效"), 400

    det, err = _resolve_detect(detect_id)
    if err:
        return jsonify(code=400, message=err), 400
    face, err = _resolve_face(face_id)
    if err:
        return jsonify(code=400, message=err), 400
    _dm, detect_path = det
    fm, face_root, face_pack = face

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的视频格式"), 400

    conf = _parse_float("conf", 0.25) or 0.25
    imgsz = int(_parse_float("imgsz", 640) or 640)
    region = _parse_region(request.form.get("region"))
    zones = _parse_zones()
    zone_style = _parse_zone_style()
    staff_ids = _parse_staff_ids()
    absence_thr = _parse_float("absenceThresholdSec", 30) or 30.0
    face_thr = _parse_float("faceThreshold", 0.4) or 0.4
    session_id = uuid.uuid4().hex

    video_folder = current_app.config["VIDEO_FOLDER"]
    out_folder = current_app.config["OUTPUT_FOLDER"]
    os.makedirs(video_folder, exist_ok=True)
    os.makedirs(out_folder, exist_ok=True)
    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "video"
    src_path = os.path.join(video_folder, f"{base}_{ts}{ext}")
    out_name = f"{base}_{ts}_absence.mp4"
    out_path = os.path.join(out_folder, out_name)
    file.save(src_path)

    job_id = uuid.uuid4().hex

    def progress_cb(processed, total):
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j["processed"] = processed
                j["total"] = total

    cfg = {
        "detect_path": detect_path,
        "face_root": face_root,
        "face_pack": face_pack,
        "face_model_key": fm.model_key,
        "src_path": src_path,
        "dst_path": out_path,
        "out_name": out_name,
        "conf": conf,
        "imgsz": imgsz,
        "region": region,
        "zones": zones,
        "zone_style": zone_style,
        "staff_ids": staff_ids,
        "absence_threshold_sec": absence_thr,
        "face_threshold": face_thr,
        "session_id": session_id,
        "progress_cb": progress_cb,
    }
    with _video_jobs_lock:
        _video_jobs[job_id] = {
            "status": "running", "processed": 0, "total": 0, "stats": None, "error": None,
        }
    threading.Thread(target=_absence_worker, args=(job_id, cfg), daemon=True).start()
    return jsonify(code=0, message="任务已启动", data={"jobId": job_id, "sessionId": session_id})


@absence_bp.get("/video-progress/<job_id>")
@permission_required("ai:absence:list")
def video_progress(job_id):
    with _video_jobs_lock:
        j = _video_jobs.get(job_id)
    if j is None:
        return jsonify(code=404, message="任务不存在"), 404
    return jsonify(code=0, data=j)


@absence_bp.get("/output/<path:name>")
@permission_required("ai:absence:list")
def output_video(name):
    if not name.endswith("_absence.mp4"):
        return jsonify(code=400, message="非法文件名"), 400
    path = os.path.join(current_app.config["OUTPUT_FOLDER"], name)
    if not os.path.isfile(path):
        return jsonify(code=404, message="文件不存在"), 404
    return send_file(path, mimetype="video/mp4", conditional=True)


@absence_bp.post("/reset-session")
@permission_required("ai:absence:list")
def reset_session():
    data = request.get_json(silent=True) or {}
    sid = (data.get("sessionId") or request.form.get("sessionId") or "").strip()
    if not sid:
        return jsonify(code=400, message="缺少 sessionId"), 400
    from services.duty_absence import clear_session
    clear_session(sid)
    return jsonify(code=0, message="已重置")


@absence_bp.post("/export-events")
@permission_required("ai:absence:list")
def export_events():
    data = request.get_json(silent=True) or {}
    sid = (data.get("sessionId") or request.form.get("sessionId") or "").strip()
    if not sid:
        return jsonify(code=400, message="缺少 sessionId"), 400
    from services.duty_absence import export_events_csv, get_session
    session = get_session(sid, reset=False)
    csv_text = export_events_csv(session)
    return jsonify(code=0, data={"csv": csv_text, "count": len(session.events)})
