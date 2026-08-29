"""边缘 AI 视频流水线运行时（Phase 0–2）：检测 / 跟踪 / 告警 / VLM门控 / Overlay / DB / Webhook / MQTT。"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import cv2
import numpy as np

from services.pipeline_schema import (
    dag_required_phase,
    make_event_envelope,
    make_frame_envelope,
    validate_dag,
)

log = logging.getLogger(__name__)

_sessions_lock = threading.Lock()
_sessions: dict[str, "PipelineSession"] = {}
_STALL_SEC = 8.0
_vlm_lock = threading.Lock()
_vlm_busy = False


def _default_stats() -> dict:
    return {
        "frames": 0,
        "detections": 0,
        "tracks": 0,
        "alerts": 0,
        "webhooksOk": 0,
        "webhooksFail": 0,
        "mqttOk": 0,
        "mqttFail": 0,
        "dbEvents": 0,
        "vlmConfirm": 0,
        "vlmReject": 0,
        "vlmFail": 0,
        "vlmSkipped": 0,
        "sourceStalled": False,
        "reconnects": 0,
        "mtmcCrossEvents": 0,
        "mtmcFrames": 0,
        "mtmcSessionId": None,
        "mode": "classic",
        "inferMsSum": 0.0,
        "inferCount": 0,
        "dropped": 0,
        "lastFps": 0.0,
    }


@dataclass
class PipelineSession:
    run_key: str
    pipeline_id: int
    version_id: int | None
    camera_id: int
    dag_norm: dict
    model_abs_path: str
    model_key: str | None
    conf: float = 0.35
    sample_fps: float = 4.0
    app: Any = None
    running: bool = False
    error: str | None = None
    overlay_jpeg: bytes | None = None
    frame_seq: int = 0
    last_envelope: dict = field(default_factory=dict)
    last_events: list = field(default_factory=list)
    stats: dict = field(default_factory=_default_stats)
    created_at: float = field(default_factory=time.time)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _hub_key: str | None = None
    _tracker: Any = None
    _alert_region: list | None = None
    _alert_line: list | None = None
    _draw_region: bool = False
    _last_frame_at: float = 0.0
    _was_stalled: bool = False
    _mtmc_session_id: str | None = None
    _mtmc_owned: bool = False
    _last_metrics_persist: float = 0.0
    executor_mode: str = "inprocess"  # inprocess | subprocess | cli

    def to_dict(self) -> dict:
        st = dict(self.stats)
        if st.get("inferCount"):
            st["inferMsAvg"] = round(st["inferMsSum"] / max(1, st["inferCount"]), 2)
        return {
            "runKey": self.run_key,
            "pipelineId": self.pipeline_id,
            "versionId": self.version_id,
            "cameraId": self.camera_id,
            "running": self.running,
            "error": self.error,
            "frameSeq": self.frame_seq,
            "stats": st,
            "mode": st.get("mode") or "classic",
            "mtmcSessionId": self._mtmc_session_id,
            "executorMode": self.executor_mode,
            "lastEnvelope": {
                k: self.last_envelope.get(k)
                for k in ("frameSeq", "ts", "dets", "metrics", "attrs")
                if k in self.last_envelope
            },
            "lastEvents": list(self.last_events)[-10:],
            "createdAt": self.created_at,
            "hasOverlay": self.overlay_jpeg is not None,
        }


def list_sessions() -> list[dict]:
    with _sessions_lock:
        return [s.to_dict() for s in _sessions.values()]


def get_session(run_key: str) -> PipelineSession | None:
    with _sessions_lock:
        return _sessions.get(run_key)


def get_session_for_camera(camera_id: int) -> PipelineSession | None:
    with _sessions_lock:
        for s in _sessions.values():
            if s.running and int(s.camera_id) == int(camera_id):
                return s
    return None


def _draw_overlay(
    img: np.ndarray,
    dets: list[dict],
    *,
    region: list | None = None,
    draw_region: bool = False,
) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    if draw_region and region:
        pts = _region_to_pixels(region, w, h)
        if len(pts) >= 3:
            arr = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(out, [arr], True, (0, 255, 255), 2)
    for d in dets:
        bbox = d.get("bbox") or []
        if len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [int(float(v)) for v in bbox[:4]]
        tid = d.get("trackId") or d.get("localTrackId")
        color = (0, 180, 255) if not d.get("alerted") else (0, 0, 255)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        name = d.get("className", "?")
        conf = float(d.get("confidence") or 0)
        label = f"#{tid} {name} {conf:.2f}" if tid is not None else f"{name} {conf:.2f}"
        cv2.putText(
            out, label, (x1, max(16, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA,
        )
    return out


def _region_to_pixels(region: list, w: int, h: int) -> list[tuple[int, int]]:
    pts = []
    for p in region or []:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            continue
        x, y = float(p[0]), float(p[1])
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            pts.append((int(x * w), int(y * h)))
        else:
            pts.append((int(x), int(y)))
    return pts


def _resolve_model_path(app, model_id: int | None, model_key: str | None) -> tuple[str, str | None]:
    from models.ai_model import AiModel
    from routes.ai_model import _resolve_detect_runtime

    with app.app_context():
        m = None
        if model_id:
            m = AiModel.query.get(int(model_id))
        if m is None and model_key:
            m = AiModel.query.filter_by(model_key=model_key, status="0").filter(
                AiModel.file_path.isnot(None)
            ).first()
        if m is None:
            for key in ("yolo26n", "yolo11n", "yolov8n"):
                m = AiModel.query.filter_by(model_key=key, status="0").filter(
                    AiModel.file_path.isnot(None)
                ).first()
                if m:
                    break
        if m is None:
            m = (
                AiModel.query.filter_by(task="object-detection", status="0")
                .filter(AiModel.file_path.isnot(None))
                .order_by(AiModel.id.asc())
                .first()
            )
        if m is None:
            raise ValueError("未找到可用的目标检测模型，请先在模型管理拉取 YOLO 权重")
        _lib, path = _resolve_detect_runtime(m)
        return path, m.model_key


def start_run(
    *,
    app,
    pipeline_id: int,
    version_id: int | None,
    dag: dict,
    run_key: str | None = None,
    phase: int | None = None,
    executor_mode: str = "inprocess",
) -> PipelineSession:
    if phase is None:
        phase = max(1, dag_required_phase(dag))
    norm = validate_dag(dag, phase=int(phase))
    if norm.get("mode") == "mtmc" or norm.get("mtmcIds"):
        return _start_mtmc_run(
            app=app,
            pipeline_id=pipeline_id,
            version_id=version_id,
            norm=norm,
            run_key=run_key,
            executor_mode=executor_mode,
        )

    camera_id = int(norm["cameraId"])
    det_id = norm["detectIds"][0]
    det_cfg = norm["nodes"][det_id]["config"]
    conf = float(det_cfg.get("conf") or 0.35)
    sample_fps = float(det_cfg.get("sampleFps") or 4.0)
    model_id = det_cfg.get("modelId")
    model_key = det_cfg.get("modelKey")
    abs_path, resolved_key = _resolve_model_path(
        app,
        int(model_id) if model_id not in (None, "") else None,
        str(model_key) if model_key else None,
    )

    from models.camera import Camera

    with app.app_context():
        cam = Camera.query.get(camera_id)
        if not cam:
            raise ValueError(f"摄像头 #{camera_id} 不存在")
        if cam.status == "1":
            raise ValueError(f"摄像头 #{camera_id} 已停用")
        source_type = cam.source_type or "rtsp"
        source = cam.source or ""
        width = int(cam.resolution or 640)
        fps = int(cam.fps or 15)

    # alert geometry / overlay options
    alert_region = None
    alert_line = None
    draw_region = False
    for aid in norm.get("alertIds") or []:
        cfg = norm["nodes"][aid]["config"]
        if cfg.get("region"):
            alert_region = cfg.get("region")
        if cfg.get("line"):
            alert_line = cfg.get("line")
    for oid in norm.get("overlayIds") or []:
        if norm["nodes"][oid]["config"].get("drawRegion"):
            draw_region = True

    tracker = None
    if norm.get("trackIds"):
        from services.mtmc_local_track import create_local_tracker, bytetrack_available

        tcfg = norm["nodes"][norm["trackIds"][0]]["config"]
        backend = "bytetrack" if bytetrack_available() else "iou"
        tracker = create_local_tracker(
            backend,
            iou_thresh=float(tcfg.get("iouThresh") or 0.3),
            max_age=int(tcfg.get("maxAge") or 30),
        )

    rk = (run_key or f"plrun_{uuid.uuid4().hex[:12]}").strip()
    sess = PipelineSession(
        run_key=rk,
        pipeline_id=int(pipeline_id),
        version_id=version_id,
        camera_id=camera_id,
        dag_norm=norm,
        model_abs_path=abs_path,
        model_key=resolved_key,
        conf=conf,
        sample_fps=max(0.5, min(sample_fps, 15.0)),
        app=app,
        _tracker=tracker,
        _alert_region=alert_region,
        _alert_line=alert_line,
        _draw_region=draw_region,
    )
    sess.executor_mode = executor_mode or "inprocess"
    sess.stats["mode"] = "classic"

    with _sessions_lock:
        for old in list(_sessions.values()):
            if old.running and old.camera_id == camera_id:
                _stop_session_unlocked(old)
        _sessions[rk] = sess

    sess.running = True
    sess._thread = threading.Thread(
        target=_worker_loop,
        args=(sess, source_type, source, width, fps),
        name=f"pipeline-{rk}",
        daemon=True,
    )
    sess._thread.start()
    return sess


def _start_mtmc_run(
    *,
    app,
    pipeline_id: int,
    version_id: int | None,
    norm: dict,
    run_key: str | None = None,
    executor_mode: str = "inprocess",
) -> PipelineSession:
    from services.pipeline_mtmc import spawn_mtmc_bridge, start_or_attach_mtmc

    mid = (norm.get("mtmcIds") or [None])[0]
    if not mid:
        raise ValueError("缺少 composite.mtmc 节点")
    cfg = norm["nodes"][mid]["config"]
    camera_id = int(norm["cameraId"])
    upload_folder = getattr(app.config, "get", lambda *_: None)("UPLOAD_FOLDER") or ""
    try:
        from config import Config

        upload_folder = Config.UPLOAD_FOLDER
    except Exception:  # noqa: BLE001
        pass

    mtmc_sess, owned = start_or_attach_mtmc(app, cfg, upload_folder=upload_folder)
    rk = (run_key or f"plrun_{uuid.uuid4().hex[:12]}").strip()
    sess = PipelineSession(
        run_key=rk,
        pipeline_id=int(pipeline_id),
        version_id=version_id,
        camera_id=camera_id,
        dag_norm=norm,
        model_abs_path="",
        model_key=None,
        conf=0.35,
        sample_fps=float(cfg.get("sampleFps") or 4.0),
        app=app,
    )
    sess.executor_mode = executor_mode or "inprocess"
    sess.stats["mode"] = "mtmc"
    sess._mtmc_session_id = getattr(mtmc_sess, "session_id", None)
    sess._mtmc_owned = owned
    sess.stats["mtmcSessionId"] = sess._mtmc_session_id

    with _sessions_lock:
        for old in list(_sessions.values()):
            if old.running and old.camera_id == camera_id and old.stats.get("mode") == "mtmc":
                _stop_session_unlocked(old)
        _sessions[rk] = sess

    sess.running = True
    sess._thread = spawn_mtmc_bridge(sess, mtmc_sess, _dispatch_event_sinks)
    return sess


def stop_run(run_key: str) -> bool:
    with _sessions_lock:
        sess = _sessions.get(run_key)
        if not sess:
            return False
        _stop_session_unlocked(sess)
        return True


def _stop_session_unlocked(sess: PipelineSession):
    sess._stop.set()
    sess.running = False
    if sess._mtmc_session_id and sess._mtmc_owned:
        try:
            from services.pipeline_mtmc import stop_owned_mtmc

            stop_owned_mtmc(sess._mtmc_session_id, True)
        except Exception as exc:  # noqa: BLE001
            log.warning("stop mtmc for pipeline %s: %s", sess.run_key, exc)
    if sess._thread and sess._thread.is_alive() and threading.current_thread() is not sess._thread:
        sess._thread.join(timeout=3.0)


def _apply_tracking(sess: PipelineSession, dets: list[dict]) -> list[dict]:
    if not sess._tracker:
        return dets
    tracked = sess._tracker.update([
        {
            "bbox": d.get("bbox"),
            "confidence": float(d.get("confidence") or 0),
            "className": d.get("className") or "object",
            "classId": d.get("classId"),
        }
        for d in dets
        if d.get("bbox") and len(d.get("bbox") or []) >= 4
    ])
    out = []
    for t in tracked:
        item = {
            "className": getattr(t, "class_name", None) or "object",
            "classId": getattr(t, "class_id", -1),
            "confidence": float(getattr(t, "confidence", 0) or 0),
            "bbox": list(getattr(t, "bbox", None) or []),
            "trackId": int(getattr(t, "track_id", 0) or 0),
            "localTrackId": int(getattr(t, "track_id", 0) or 0),
        }
        out.append(item)
    sess.stats["tracks"] = int(sess.stats.get("tracks") or 0) + len(out)
    return out


def _load_alert_rules(app, alert_cfg: dict) -> list:
    from models.alert import AlertRule

    with app.app_context():
        q = AlertRule.query.filter_by(status="0")
        rule_ids = alert_cfg.get("ruleIds") or []
        rule_types = alert_cfg.get("ruleTypes") or []
        if rule_ids:
            q = q.filter(AlertRule.id.in_([int(x) for x in rule_ids]))
        if rule_types:
            q = q.filter(AlertRule.rule_type.in_(list(rule_types)))
        return q.order_by(AlertRule.id.asc()).all()


def _persist_alert_event(app, sess: PipelineSession, rule, title, message, detail):
    from extensions import db
    from models.alert import AlertEvent

    with app.app_context():
        ev = AlertEvent(
            rule_id=getattr(rule, "id", None),
            rule_key=getattr(rule, "rule_key", None),
            rule_name=getattr(rule, "name", None),
            severity=getattr(rule, "severity", None) or "medium",
            title=title,
            message=message,
            source_type="pipeline",
            source_key=f"pipeline:{sess.run_key}:cam:{sess.camera_id}",
            payload_json=json.dumps({
                "detail": detail,
                "pipelineId": sess.pipeline_id,
                "runKey": sess.run_key,
                "cameraId": sess.camera_id,
                "frameSeq": sess.frame_seq,
            }, ensure_ascii=False, default=str),
        )
        db.session.add(ev)
        db.session.commit()
        sess.stats["dbEvents"] = int(sess.stats.get("dbEvents") or 0) + 1
        return {"id": ev.id, "createTime": ev.create_time.isoformat() if ev.create_time else None}


def _run_alerts(sess: PipelineSession, dets: list[dict], img_shape) -> list[dict]:
    alert_ids = sess.dag_norm.get("alertIds") or []
    if not alert_ids:
        return []
    from services.alert_engine import evaluate_rules

    h, w = img_shape[:2]
    events: list[dict] = []
    app = sess.app
    has_db_sink = bool(sess.dag_norm.get("dbIds"))
    for aid in alert_ids:
        cfg = sess.dag_norm["nodes"][aid]["config"]
        rules = _load_alert_rules(app, cfg)
        if not rules:
            continue
        region = cfg.get("region") or sess._alert_region
        line = cfg.get("line") or sess._alert_line
        region_px = _region_to_pixels(region, w, h) if region else None
        line_px = _region_to_pixels(line, w, h) if line else None
        persist = bool(cfg.get("persist")) or has_db_sink

        def _persist(rule, title, message, detail, _sess=sess):
            return _persist_alert_event(app, _sess, rule, title, message, detail)

        triggered = evaluate_rules(
            rules,
            dets,
            source_key=f"pipeline:{sess.run_key}:cam:{sess.camera_id}",
            persist_event=_persist if persist else None,
            frame_width=float(w),
            frame_height=float(h),
            region=region_px,
            line=line_px,
            source_type="camera",
        )
        for item in triggered:
            env = make_event_envelope(
                event_type="alert.fired",
                pipeline_id=str(sess.pipeline_id),
                run_id=sess.run_key,
                camera_id=sess.camera_id,
                rule_key=item.get("ruleKey"),
                score=(item.get("detail") or {}).get("score") if isinstance(item.get("detail"), dict) else None,
                payload=item,
            )
            events.append(env)
            sess.stats["alerts"] = int(sess.stats.get("alerts") or 0) + 1
            # mark dets alerted for overlay color
            for d in dets:
                d["alerted"] = True
    return events


def _dispatch_event_sinks(sess: PipelineSession, events: list[dict]):
    if not events:
        return
    from services.webhook import deliver_url_webhook_async
    from services import mqtt_bus

    for wid in sess.dag_norm.get("webhookIds") or []:
        cfg = sess.dag_norm["nodes"][wid]["config"]
        url = (cfg.get("url") or "").strip()
        if not url:
            continue
        event_name = (cfg.get("event") or "alert.fired").strip()
        secret = (cfg.get("secret") or "").strip() or None
        for ev in events:
            if ev.get("type") != event_name and event_name != "*":
                continue
            ok = deliver_url_webhook_async(
                url,
                event_name,
                ev,
                secret=secret,
                on_done=lambda success, _s=sess: _webhook_stat(_s, success),
            )
            if not ok:
                sess.stats["webhooksFail"] = int(sess.stats.get("webhooksFail") or 0) + 1

    for mid in sess.dag_norm.get("mqttIds") or []:
        cfg = sess.dag_norm["nodes"][mid]["config"]
        topic_tpl = (cfg.get("topic") or "").strip()
        if not topic_tpl:
            continue
        event_name = (cfg.get("event") or "alert.fired").strip()
        qos = int(cfg.get("qos") if cfg.get("qos") is not None else 1)
        for ev in events:
            if ev.get("type") != event_name and event_name != "*":
                continue
            topic = mqtt_bus.resolve_topic(
                topic_tpl,
                camera_id=ev.get("cameraId") or sess.camera_id,
                rule_key=ev.get("ruleKey"),
                site=cfg.get("site"),
            )
            body = mqtt_bus.alert_payload_from_event(ev)
            ok = mqtt_bus.publish_event_async(
                topic,
                body,
                qos=qos,
                on_done=lambda success, _s=sess: _mqtt_stat(_s, success),
            )
            if not ok:
                sess.stats["mqttFail"] = int(sess.stats.get("mqttFail") or 0) + 1


def _webhook_stat(sess: PipelineSession, success: bool):
    if success:
        sess.stats["webhooksOk"] = int(sess.stats.get("webhooksOk") or 0) + 1
    else:
        sess.stats["webhooksFail"] = int(sess.stats.get("webhooksFail") or 0) + 1


def _mqtt_stat(sess: PipelineSession, success: bool):
    if success:
        sess.stats["mqttOk"] = int(sess.stats.get("mqttOk") or 0) + 1
    else:
        sess.stats["mqttFail"] = int(sess.stats.get("mqttFail") or 0) + 1


def _extract_bbox_from_event(ev: dict, dets: list[dict]) -> list | None:
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
    for key in ("bbox", "box"):
        b = detail.get(key) or payload.get(key)
        if isinstance(b, (list, tuple)) and len(b) >= 4:
            return list(b[:4])
    # fallback: first alerted / any det
    for d in dets or []:
        if d.get("alerted") and d.get("bbox") and len(d["bbox"]) >= 4:
            return list(d["bbox"][:4])
    for d in dets or []:
        if d.get("bbox") and len(d["bbox"]) >= 4:
            return list(d["bbox"][:4])
    return None


def _vlm_confirm_event(sess: PipelineSession, ev: dict, img, dets: list[dict], cfg: dict) -> str:
    """返回 confirm | reject | skip | fail。"""
    global _vlm_busy
    from services.defect_diagnosis import _crop_roi_b64, chat_vision_json, qwen_vl_configured

    if cfg.get("enabled") is False:
        return "skip"
    if not qwen_vl_configured():
        sess.stats["vlmFail"] = int(sess.stats.get("vlmFail") or 0) + 1
        return "fail"

    on_busy = (cfg.get("onBusy") or "pass").strip().lower()
    acquired = _vlm_lock.acquire(blocking=False)
    if not acquired:
        sess.stats["vlmSkipped"] = int(sess.stats.get("vlmSkipped") or 0) + 1
        return "skip" if on_busy == "pass" else "reject"
    _vlm_busy = True
    try:
        use_crop = cfg.get("useCrop", True)
        b64 = None
        if use_crop and img is not None:
            bbox = _extract_bbox_from_event(ev, dets)
            if bbox:
                b64 = _crop_roi_b64(img, bbox)
        if not b64 and img is not None:
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ok:
                import base64
                b64 = base64.b64encode(buf.tobytes()).decode()
        if not b64:
            sess.stats["vlmFail"] = int(sess.stats.get("vlmFail") or 0) + 1
            return "fail"

        prompt = (cfg.get("prompt") or (
            "请判断画面是否为真实安防告警。仅返回 JSON："
            '{"confirm": true|false, "reason": "..."}'
        )).strip()
        timeout = int(cfg.get("timeoutSec") or 12)
        obj = chat_vision_json(
            b64,
            prompt,
            system_prompt="You are a security video analyst. Respond with a single JSON object only.",
            timeout=max(5, min(timeout, 60)),
        )
        confirm = obj.get("confirm")
        if confirm is None:
            confirm = obj.get("ok") or obj.get("positive") or obj.get("is_alert")
        if isinstance(confirm, str):
            confirm = confirm.strip().lower() in ("1", "true", "yes", "y", "confirm")
        if bool(confirm):
            sess.stats["vlmConfirm"] = int(sess.stats.get("vlmConfirm") or 0) + 1
            return "confirm"
        sess.stats["vlmReject"] = int(sess.stats.get("vlmReject") or 0) + 1
        return "reject"
    except Exception as exc:  # noqa: BLE001
        log.warning("vlm gate failed %s: %s", sess.run_key, exc)
        sess.stats["vlmFail"] = int(sess.stats.get("vlmFail") or 0) + 1
        return "fail"
    finally:
        _vlm_busy = False
        _vlm_lock.release()


def _run_vlm_gate(sess: PipelineSession, events: list[dict], img, dets: list[dict]) -> list[dict]:
    """有 VLM 门控时过滤告警；无门控则原样返回。"""
    gate_ids = sess.dag_norm.get("vlmGateIds") or []
    if not gate_ids or not events:
        return events
    cfg = sess.dag_norm["nodes"][gate_ids[0]]["config"]
    on_fail = (cfg.get("onFail") or "pass").strip().lower()
    out: list[dict] = []
    for ev in events:
        if (ev.get("type") or "") != "alert.fired":
            out.append(ev)
            continue
        result = _vlm_confirm_event(sess, ev, img, dets, cfg)
        if result == "confirm":
            ev = dict(ev)
            pl = dict(ev.get("payload") or {})
            pl["vlmGate"] = "confirm"
            ev["payload"] = pl
            out.append(ev)
        elif result == "reject":
            suppressed = make_event_envelope(
                event_type="alert.suppressed",
                pipeline_id=str(sess.pipeline_id),
                run_id=sess.run_key,
                camera_id=sess.camera_id,
                rule_key=ev.get("ruleKey"),
                score=ev.get("score"),
                payload={"reason": "vlm_reject", "original": ev},
            )
            sess.last_events = (sess.last_events + [suppressed])[-50:]
        elif result == "skip":
            if (cfg.get("onBusy") or "pass").strip().lower() == "pass":
                out.append(ev)
        else:  # fail
            if on_fail == "pass":
                out.append(ev)
            # on_fail=drop → 丢弃
    return out


def _update_stall_state(sess: PipelineSession, now: float, got_frame: bool):
    if got_frame:
        if sess._was_stalled:
            sess.stats["reconnects"] = int(sess.stats.get("reconnects") or 0) + 1
            sess._was_stalled = False
        sess._last_frame_at = now
        sess.stats["sourceStalled"] = False
        if sess.error and "stalled" in (sess.error or "").lower():
            sess.error = None
        return
    if not sess._last_frame_at:
        sess._last_frame_at = now
        return
    if now - sess._last_frame_at >= _STALL_SEC:
        if not sess._was_stalled:
            sess._was_stalled = True
        sess.stats["sourceStalled"] = True
        sess.error = "source stalled / reconnecting"


def _worker_loop(sess: PipelineSession, source_type: str, source: str, width: int, fps: int):
    from services.camera_stream import ensure_shared_hub
    from inference import detect_image

    hub = None
    try:
        hub = ensure_shared_hub(sess.camera_id, source_type, source, width, fps)
        sess._hub_key = hub.key
        with hub._cond:
            hub.clients += 1
            hub._cond.notify_all()

        min_interval = 1.0 / max(0.5, float(sess.sample_fps))
        last_proc = 0.0
        last_seq = -1
        fps_window_t0 = time.time()
        fps_count = 0
        sess._last_frame_at = time.time()

        while not sess._stop.is_set():
            jpeg, seq = hub.get_latest()
            now = time.time()
            if not jpeg or seq == last_seq:
                _update_stall_state(sess, now, got_frame=False)
                time.sleep(0.02)
                continue
            _update_stall_state(sess, now, got_frame=True)
            if now - last_proc < min_interval:
                sess.stats["dropped"] = int(sess.stats.get("dropped") or 0) + 1
                last_seq = seq
                continue
            last_proc = now
            last_seq = seq

            t0 = time.time()
            try:
                result = detect_image(
                    sess.model_abs_path,
                    jpeg,
                    conf=sess.conf,
                    draw=False,
                    model_key=sess.model_key,
                )
            except Exception as e:  # noqa: BLE001
                sess.error = str(e)
                log.warning("pipeline detect failed %s: %s", sess.run_key, e)
                time.sleep(0.5)
                continue

            infer_ms = (time.time() - t0) * 1000.0
            dets = result.get("detections") or []
            dets = _apply_tracking(sess, dets)

            arr = np.frombuffer(jpeg, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                continue

            events = _run_alerts(sess, dets, img.shape)
            if events:
                events = _run_vlm_gate(sess, events, img, dets)
            if events:
                sess.last_events = (sess.last_events + events)[-50:]
                _dispatch_event_sinks(sess, events)

            plotted = _draw_overlay(
                img, dets,
                region=sess._alert_region,
                draw_region=sess._draw_region,
            )
            ok, buf = cv2.imencode(".jpg", plotted, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok:
                continue

            env = make_frame_envelope(
                pipeline_id=str(sess.pipeline_id),
                run_id=sess.run_key,
                camera_id=sess.camera_id,
                frame_seq=seq,
                dets=dets,
                attrs={
                    "alertCount": len(events),
                    "sourceStalled": bool(sess.stats.get("sourceStalled")),
                },
                metrics={"inferMs": round(infer_ms, 2)},
                ts=now,
            )
            sess.overlay_jpeg = buf.tobytes()
            sess.frame_seq = seq
            sess.last_envelope = env
            sess.stats["frames"] = int(sess.stats.get("frames") or 0) + 1
            sess.stats["detections"] = int(sess.stats.get("detections") or 0) + len(dets)
            sess.stats["inferMsSum"] = float(sess.stats.get("inferMsSum") or 0) + infer_ms
            sess.stats["inferCount"] = int(sess.stats.get("inferCount") or 0) + 1
            fps_count += 1
            if now - fps_window_t0 >= 2.0:
                sess.stats["lastFps"] = round(fps_count / (now - fps_window_t0), 2)
                fps_window_t0 = now
                fps_count = 0
            if not sess.stats.get("sourceStalled"):
                sess.error = None
            _maybe_persist_metrics(sess)

    except Exception as e:  # noqa: BLE001
        sess.error = str(e)
        log.exception("pipeline worker crashed %s", sess.run_key)
    finally:
        sess.running = False
        if hub is not None:
            with hub._cond:
                hub.clients = max(0, hub.clients - 1)
                hub._cond.notify_all()


def _maybe_persist_metrics(sess: PipelineSession, every_sec: float = 10.0):
    now = time.time()
    if now - float(sess._last_metrics_persist or 0) < every_sec:
        return
    sess._last_metrics_persist = now
    if not sess.app:
        return
    try:
        from models.pipeline import AiPipelineRun
        from extensions import db

        with sess.app.app_context():
            row = AiPipelineRun.query.filter_by(run_key=sess.run_key).first()
            if not row:
                return
            row.metrics_json = json.dumps(sess.to_dict().get("stats") or {}, ensure_ascii=False)
            db.session.commit()
    except Exception as exc:  # noqa: BLE001
        log.debug("metrics persist skip: %s", exc)


def iter_overlay_mjpeg(run_key: str):
    boundary = b"frame"
    last_seq = -1
    idle = 0
    while True:
        sess = get_session(run_key)
        if not sess or (not sess.running and sess.overlay_jpeg is None):
            idle += 1
            if idle > 200:
                break
            time.sleep(0.05)
            continue
        jpeg = sess.overlay_jpeg
        seq = sess.frame_seq
        if jpeg is None or seq == last_seq:
            time.sleep(0.03)
            continue
        last_seq = seq
        idle = 0
        yield (
            b"--" + boundary + b"\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        )


def persist_run_stopped(app, run_key: str, state: str = "stopped", error: str | None = None):
    from models.pipeline import AiPipelineRun
    from extensions import db

    with app.app_context():
        row = AiPipelineRun.query.filter_by(run_key=run_key).first()
        if not row:
            return
        sess = get_session(run_key)
        row.state = state
        row.stopped_at = datetime.utcnow()
        if error:
            row.error_message = (error or "")[:1000]
        if sess:
            row.metrics_json = json.dumps(sess.to_dict().get("stats") or {}, ensure_ascii=False)
            if sess.error and not error:
                row.error_message = (sess.error or "")[:1000]
        db.session.commit()
