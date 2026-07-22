"""道路车辆（车牌）智能追踪 /api/ai/vehicle。"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from models import AiModel
from security import permission_required

vehicle_bp = Blueprint("vehicle", __name__, url_prefix="/api/ai/vehicle")

_video_jobs: dict = {}
_video_jobs_lock = threading.Lock()

DEFAULT_VEHICLE_CLASSES = [1, 2, 3, 5, 7]


def _abs_weight_file(m):
    if m is None or not m.file_path:
        return None
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    if os.path.isfile(p):
        return p
    if os.path.isdir(p):
        for root, _dirs, files in os.walk(p):
            for f in files:
                if f.lower().endswith((".pt", ".onnx")):
                    return os.path.join(root, f)
    return None


def _abs_model_dir(m):
    if m is None or not m.file_path:
        return None
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    return p if os.path.exists(p) else None


def _parse_line(raw):
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) == 4:
            return [float(v) for v in parsed]
    except (TypeError, ValueError):
        return None
    return None


def _parse_float(name, default=None):
    raw = request.form.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _parse_bool(name, default=False):
    return str(request.form.get(name, "1" if default else "0")).strip().lower() in (
        "1", "true", "on", "yes",
    )


def _resolve_models():
    def _int(name):
        try:
            return int(request.form.get(name, 0))
        except (TypeError, ValueError):
            return 0

    detect_id = _int("detectId")
    plate_id = _int("plateId")
    det_id = _int("detId")
    rec_id = _int("recId")
    if not detect_id:
        return None, "请选择车辆检测模型（detectId）"

    detect_m = AiModel.query.get(detect_id)
    if detect_m is None:
        return None, "车辆检测模型不存在"
    if (detect_m.library or "").lower() != "ultralytics" or detect_m.task != "object-detection":
        return None, "车辆检测模型需为 ultralytics + object-detection"

    detect_path = _abs_weight_file(detect_m)
    if detect_path is None:
        return None, "车辆检测模型暂无本地权重，请先拉取"

    plate_path = None
    plate_m = None
    if plate_id:
        plate_m = AiModel.query.get(plate_id)
        if plate_m is None:
            return None, "车牌检测模型不存在"
        if (plate_m.library or "").lower() != "ultralytics":
            return None, "车牌检测模型需为 ultralytics 目标检测"
        plate_path = _abs_weight_file(plate_m)
        if plate_path is None:
            return None, "车牌检测模型暂无本地权重，请先拉取"

    ocr_fn = None
    if det_id and rec_id:
        det_m = AiModel.query.get(det_id)
        rec_m = AiModel.query.get(rec_id)
        if det_m is None or rec_m is None:
            return None, "OCR 模型不存在"
        if (det_m.library or "").lower() != "rapidocr" or (rec_m.library or "").lower() != "rapidocr":
            return None, "OCR 需选择 library=rapidocr 的检测与识别模型"
        det_dir = _abs_model_dir(det_m)
        rec_dir = _abs_model_dir(rec_m)
        if det_dir is None or rec_dir is None:
            return None, "RapidOCR 模型权重未就绪，请先拉取"
        from inference import paddle_ocr

        def ocr_fn(img_bytes):
            return paddle_ocr(det_dir, rec_dir, img_bytes, plate_mode=True)

    return {
        "detect_m": detect_m,
        "detect_path": detect_path,
        "plate_m": plate_m,
        "plate_path": plate_path,
        "ocr_fn": ocr_fn,
    }, None


def _vehicle_worker(job_id, cfg_bundle):
    from inference import _get_model, _open_h264, _write_bgr, _video_alert_ctx, _apply_frame_video_alerts, _video_alert_stats
    from services.vehicle_track import (
        DEFAULT_VEHICLE_CLASSES,
        draw_vehicle_hud,
        enrich_vehicle_frame,
        get_session,
    )

    detect_path = cfg_bundle["detect_path"]
    src_path = cfg_bundle["src_path"]
    dst_path = cfg_bundle["dst_path"]
    conf = cfg_bundle["conf"]
    imgsz = cfg_bundle["imgsz"]
    line = cfg_bundle["line"]
    classes = cfg_bundle.get("classes") or DEFAULT_VEHICLE_CLASSES
    session = get_session(cfg_bundle["session_id"], reset=True)
    alert_ctx = _video_alert_ctx(cfg_bundle.get("alert_rules"), job_id, line=line)

    cap = None
    writer = None
    try:
        import cv2

        cap = cv2.VideoCapture(src_path)
        if not cap.isOpened():
            raise ValueError("无法打开视频文件")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        # 尽早上报总帧数，避免前端长时间停在 0/?
        if cfg_bundle.get("progress_cb"):
            cfg_bundle["progress_cb"](0, total)
        writer, ew, eh = _open_h264(dst_path, fps, w, h)
        px_line = [line[0] * w, line[1] * h, line[2] * w, line[3] * h] if line else None

        model = _get_model(detect_path)
        # 预加载车牌模型：失败则降级为无车牌检测（启发式 ROI），避免首帧卡死
        plate_path = cfg_bundle.get("plate_path")
        if plate_path:
            try:
                _get_model(plate_path)
            except Exception as plate_err:  # noqa: BLE001
                cfg_bundle["plate_path"] = None
                with _video_jobs_lock:
                    j = _video_jobs.get(job_id)
                    if j is not None:
                        j["warning"] = f"车牌模型不可用，已降级启发式 ROI：{plate_err}"
        frames = 0
        congestion_samples = []

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            track_kw = dict(persist=True, tracker="bytetrack.yaml", conf=conf, imgsz=imgsz, verbose=False)
            if classes:
                track_kw["classes"] = classes
            r = model.track(frame, **track_kw)[0]
            names = r.names
            detections = []
            if r.boxes is not None and r.boxes.id is not None:
                ids = r.boxes.id.int().tolist()
                clss = r.boxes.cls.int().tolist()
                confs = r.boxes.conf.cpu().tolist()
                xyxy = r.boxes.xyxy.cpu().tolist()
                for tid, cid, conf_v, box in zip(ids, clss, confs, xyxy):
                    detections.append({
                        "className": names.get(cid, str(cid)),
                        "classId": int(cid),
                        "confidence": round(float(conf_v), 4),
                        "bbox": [round(float(v), 1) for v in box],
                        "trackId": int(tid),
                    })

            enriched = enrich_vehicle_frame(
                frame,
                detections,
                session,
                plate_model_path=cfg_bundle.get("plate_path"),
                ocr_fn=cfg_bundle.get("ocr_fn"),
                enable_ocr=cfg_bundle.get("enable_ocr", True),
                enable_speed=cfg_bundle.get("enable_speed", True),
                meters_per_pixel=cfg_bundle.get("meters_per_pixel"),
                line_px=px_line,
                plate_conf=cfg_bundle.get("plate_conf", 0.2),
                ocr_cooldown_sec=cfg_bundle.get("ocr_cooldown_sec", 0.55),
                congestion_thresholds=cfg_bundle.get("congestion_thresholds"),
            )
            congestion_samples.append(enriched.get("congestion", {}).get("level"))
            annotated = draw_vehicle_hud(frame, enriched, line_px=px_line)
            frames += 1
            if alert_ctx:
                annotated = _apply_frame_video_alerts(
                    annotated, enriched.get("detections") or [], alert_ctx, frames, fps, line=line)
            _write_bgr(writer, annotated, ew, eh)
            if cfg_bundle.get("progress_cb"):
                cfg_bundle["progress_cb"](frames, total)

        result = {
            "frames": frames,
            "totalFrames": total,
            "fps": round(float(fps), 2),
            "width": ew,
            "height": eh,
            "uniqueObjects": len(session.track_history),
            "crossing": dict(session.crossing),
            "records": session.records,
            "recordCount": len(session.records),
            "congestionSummary": {
                "samples": len(congestion_samples),
                "severeRatio": round(congestion_samples.count("severe") / max(1, len(congestion_samples)), 3),
                "busyRatio": round(
                    (congestion_samples.count("busy") + congestion_samples.count("severe")) / max(1, len(congestion_samples)),
                    3,
                ),
            },
            "output": cfg_bundle["out_name"],
        }
        result.update(_video_alert_stats(alert_ctx))
        with _video_jobs_lock:
            _video_jobs[job_id].update(status="done", stats=result, processed=frames, total=frames or total)
    except Exception as e:  # noqa: BLE001
        with _video_jobs_lock:
            _video_jobs[job_id].update(status="error", error=str(e))
    finally:
        if cap is not None:
            cap.release()
        if writer is not None:
            writer.close()
        if os.path.isfile(cfg_bundle.get("src_path", "")):
            try:
                os.remove(cfg_bundle["src_path"])
            except OSError:
                pass


@vehicle_bp.post("/detect-image")
@permission_required("ai:vehicle:list")
def detect_image_api():
    """上传单张车辆图片：检测车辆 + 车牌定位/OCR，返回标注图与明细。"""
    import base64

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片（field: file）"), 400

    models, err = _resolve_models()
    if err:
        return jsonify(code=400, message=err), 400

    conf = _parse_float("conf", 0.25) or 0.25
    imgsz = int(_parse_float("imgsz", 640) or 640)
    enable_ocr = _parse_bool("enableOcr", True)
    plate_conf = _parse_float("plateConf", 0.2) or 0.2
    vehicle_only = _parse_bool("vehicleOnly", True)
    classes = DEFAULT_VEHICLE_CLASSES if vehicle_only else None

    image_bytes = file.read()
    try:
        import cv2
        from inference import _get_model, _safe_class_name
        from services.vehicle_track import analyze_vehicle_image, draw_vehicle_hud

        arr = __import__("numpy").frombuffer(image_bytes, __import__("numpy").uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return jsonify(code=400, message="无法解析图片"), 400

        model = _get_model(models["detect_path"])
        predict_kw = dict(conf=conf, imgsz=imgsz, verbose=False)
        if classes:
            predict_kw["classes"] = classes
        r = model.predict(img, **predict_kw)[0]
        names = getattr(r, "names", None) or getattr(model, "names", None) or {}
        detections = []
        if r.boxes is not None:
            for b in r.boxes:
                cls_id = int(b.cls[0])
                detections.append({
                    "className": _safe_class_name(names, cls_id),
                    "classId": cls_id,
                    "confidence": round(float(b.conf[0]), 4),
                    "bbox": [round(float(v), 1) for v in b.xyxy[0].tolist()],
                })

        plate_path = models.get("plate_path")
        if plate_path:
            try:
                _get_model(plate_path)
            except Exception as plate_err:  # noqa: BLE001
                plate_path = None
                current_app.logger.warning("车牌模型不可用，降级启发式 ROI：%s", plate_err)

        enriched = analyze_vehicle_image(
            img,
            detections,
            plate_model_path=plate_path,
            ocr_fn=models.get("ocr_fn") if enable_ocr else None,
            enable_ocr=enable_ocr and models.get("ocr_fn") is not None,
            plate_conf=plate_conf,
        )
        vis = draw_vehicle_hud(img, enriched)
        ok, buf = cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        image_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None
        dets = enriched.get("detections") or []
        plate_hit = sum(1 for d in dets if d.get("plate"))
        return jsonify(code=0, message="ok", data={
            "detections": dets,
            "count": len(dets),
            "plateCount": plate_hit,
            "imageBase64": image_b64,
            "width": enriched.get("width"),
            "height": enriched.get("height"),
            "congestion": enriched.get("congestion"),
        })
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"车辆图片识别失败：{e}"), 500


@vehicle_bp.post("/track-frame")
@permission_required("ai:vehicle:list")
def track_frame():
    """实时单帧：车辆追踪 + 车牌 OCR + 测速 + 拥堵 + 越线。"""
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片（field: file）"), 400

    models, err = _resolve_models()
    if err:
        return jsonify(code=400, message=err), 400

    conf = _parse_float("conf", 0.25) or 0.25
    imgsz = int(_parse_float("imgsz", 640) or 640)
    line = _parse_line(request.form.get("line"))
    enable_ocr = _parse_bool("enableOcr", True)
    enable_speed = _parse_bool("enableSpeed", True)
    meters_per_pixel = _parse_float("metersPerPixel")
    plate_conf = _parse_float("plateConf", 0.2) or 0.2
    session_id = (request.form.get("sessionId") or "").strip() or uuid.uuid4().hex
    reset = _parse_bool("reset", False)
    vehicle_only = _parse_bool("vehicleOnly", True)
    classes = DEFAULT_VEHICLE_CLASSES if vehicle_only else None
    congestion = {
        "light": int(_parse_float("congestionLight", 3) or 3),
        "moderate": int(_parse_float("congestionModerate", 8) or 8),
        "heavy": int(_parse_float("congestionHeavy", 15) or 15),
    }

    image_bytes = file.read()
    try:
        import cv2
        from inference import track_frame as yolo_track_frame
        from services.vehicle_track import enrich_vehicle_frame, get_session

        arr = __import__("numpy").frombuffer(image_bytes, __import__("numpy").uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return jsonify(code=400, message="无法解析图片"), 400

        base = yolo_track_frame(
            models["detect_path"], image_bytes, conf=conf, reset=reset,
            imgsz=imgsz, classes=classes,
        )
        session = get_session(session_id, reset=reset)
        h, w = img.shape[:2]
        px_line = [line[0] * w, line[1] * h, line[2] * w, line[3] * h] if line else None

        enriched = enrich_vehicle_frame(
            img,
            base.get("detections") or [],
            session,
            plate_model_path=models.get("plate_path"),
            ocr_fn=models.get("ocr_fn") if enable_ocr else None,
            enable_ocr=enable_ocr and models.get("ocr_fn") is not None,
            enable_speed=enable_speed,
            meters_per_pixel=meters_per_pixel if meters_per_pixel and meters_per_pixel > 0 else None,
            line_px=px_line,
            plate_conf=plate_conf,
            ocr_cooldown_sec=0.5,
            congestion_thresholds=congestion,
        )
        enriched["sessionId"] = session_id
        return jsonify(code=0, message="ok", data=enriched)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"车辆追踪失败：{e}"), 500


@vehicle_bp.post("/track-video")
@permission_required("ai:vehicle:list")
def track_video():
    """上传视频异步追踪，输出带标注 MP4 与过车记录。"""
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到视频"), 400

    models, err = _resolve_models()
    if err:
        return jsonify(code=400, message=err), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的视频格式"), 400

    conf = _parse_float("conf", 0.25) or 0.25
    imgsz = int(_parse_float("imgsz", 640) or 640)
    line = _parse_line(request.form.get("line"))
    enable_ocr = _parse_bool("enableOcr", True)
    enable_speed = _parse_bool("enableSpeed", True)
    meters_per_pixel = _parse_float("metersPerPixel")
    plate_conf = _parse_float("plateConf", 0.2) or 0.2
    session_id = uuid.uuid4().hex
    vehicle_only = _parse_bool("vehicleOnly", True)
    classes = DEFAULT_VEHICLE_CLASSES if vehicle_only else None
    congestion = {
        "light": int(_parse_float("congestionLight", 3) or 3),
        "moderate": int(_parse_float("congestionModerate", 8) or 8),
        "heavy": int(_parse_float("congestionHeavy", 15) or 15),
    }

    alert_rules = None
    if _parse_bool("alertEnabled", False):
        from services.alert_rules_query import load_enabled_alert_rules, parse_rule_keys, serialize_alert_rules_payload
        raw_keys = request.form.get("alertRuleKeys")
        rule_keys = parse_rule_keys(raw_keys) if raw_keys else None
        enabled = load_enabled_alert_rules(rule_keys)
        if not enabled:
            return jsonify(code=400, message="启用告警但无可用规则，请先到检测告警页配置"), 400
        alert_rules = serialize_alert_rules_payload(enabled)

    video_folder = current_app.config["VIDEO_FOLDER"]
    out_folder = current_app.config["OUTPUT_FOLDER"]
    os.makedirs(video_folder, exist_ok=True)
    os.makedirs(out_folder, exist_ok=True)

    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "video"
    src_path = os.path.join(video_folder, f"{base}_{ts}{ext}")
    out_name = f"{base}_{ts}_vehicle.mp4"
    out_path = os.path.join(out_folder, out_name)
    file.save(src_path)

    job_id = uuid.uuid4().hex

    def progress_cb(processed, total):
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j["processed"] = processed
                j["total"] = total

    cfg_bundle = {
        "detect_path": models["detect_path"],
        "plate_path": models.get("plate_path"),
        "ocr_fn": models.get("ocr_fn"),
        "src_path": src_path,
        "dst_path": out_path,
        "out_name": out_name,
        "conf": conf,
        "imgsz": imgsz,
        "line": line,
        "enable_ocr": enable_ocr and models.get("ocr_fn") is not None,
        "enable_speed": enable_speed,
        "meters_per_pixel": meters_per_pixel if meters_per_pixel and meters_per_pixel > 0 else None,
        "plate_conf": plate_conf,
        "ocr_cooldown_sec": 0.55,
        "session_id": session_id,
        "classes": classes,
        "congestion_thresholds": congestion,
        "alert_rules": alert_rules,
        "progress_cb": progress_cb,
    }

    with _video_jobs_lock:
        _video_jobs[job_id] = {"status": "running", "processed": 0, "total": 0, "stats": None, "error": None}

    threading.Thread(target=_vehicle_worker, args=(job_id, cfg_bundle), daemon=True).start()
    return jsonify(code=0, message="任务已启动", data={"jobId": job_id, "sessionId": session_id})


@vehicle_bp.get("/video-progress/<job_id>")
@permission_required("ai:vehicle:list")
def video_progress(job_id):
    with _video_jobs_lock:
        j = _video_jobs.get(job_id)
    if j is None:
        return jsonify(code=404, message="任务不存在"), 404
    return jsonify(code=0, data=j)


@vehicle_bp.post("/reset-session")
@permission_required("ai:vehicle:list")
def reset_session():
    session_id = (request.json or {}).get("sessionId") or request.form.get("sessionId")
    if not session_id:
        return jsonify(code=400, message="缺少 sessionId"), 400
    from services.vehicle_track import clear_session
    clear_session(str(session_id))
    return jsonify(code=0, message="已重置会话")


@vehicle_bp.post("/export-records")
@permission_required("ai:vehicle:list")
def export_records():
    """按 sessionId 导出过车记录 CSV 文本。"""
    import csv
    import io

    session_id = (request.json or {}).get("sessionId") or request.form.get("sessionId")
    if not session_id:
        return jsonify(code=400, message="缺少 sessionId"), 400
    from services.vehicle_track import get_session

    session = get_session(str(session_id), reset=False)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["time", "trackId", "className", "plate", "plateScore", "speedKmh", "confidence"])
    for row in session.records:
        writer.writerow([
            row.get("time"),
            row.get("trackId"),
            row.get("className"),
            row.get("plate"),
            row.get("plateScore"),
            row.get("speedKmh"),
            row.get("confidence"),
        ])
    return jsonify(code=0, data={"csv": buf.getvalue(), "count": len(session.records)})
