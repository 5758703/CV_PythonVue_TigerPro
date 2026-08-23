"""MTMC P2：跨镜检索任务队列（全局轨迹 / 多视频 ReID）。"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid

log = logging.getLogger(__name__)

_lock = threading.Lock()
_running: set[str] = set()


def _update_job(app, job_id: str, **kwargs):
    with app.app_context():
        from extensions import db
        from models.mtmc import MtmcSearchJob

        row = MtmcSearchJob.query.get(job_id)
        if row is None:
            return None
        for k, v in kwargs.items():
            if k == "result":
                row.set_result(v)
            elif k == "params":
                row.set_params(v)
            elif hasattr(row, k):
                setattr(row, k, v)
        db.session.commit()
        return row


def submit_job(app, job_type: str, params: dict) -> str:
    job_id = uuid.uuid4().hex[:16]
    with app.app_context():
        from extensions import db
        from models.mtmc import MtmcSearchJob

        row = MtmcSearchJob(id=job_id, job_type=job_type, status="queued", message="排队中")
        row.set_params(params or {})
        db.session.add(row)
        db.session.commit()
    th = threading.Thread(
        target=_run_job,
        args=(app, job_id),
        name=f"mtmc-search-{job_id}",
        daemon=True,
    )
    th.start()
    return job_id


def get_job(app, job_id: str) -> dict | None:
    with app.app_context():
        from models.mtmc import MtmcSearchJob

        row = MtmcSearchJob.query.get(job_id)
        return row.to_dict() if row else None


def list_jobs(app, job_type: str | None = None, limit: int = 50) -> list[dict]:
    with app.app_context():
        from models.mtmc import MtmcSearchJob

        q = MtmcSearchJob.query.order_by(MtmcSearchJob.create_time.desc())
        if job_type:
            q = q.filter(MtmcSearchJob.job_type == job_type)
        rows = q.limit(max(1, min(200, int(limit)))).all()
        return [r.to_dict() for r in rows]


def _run_job(app, job_id: str):
    with _lock:
        if job_id in _running:
            return
        _running.add(job_id)
    try:
        with app.app_context():
            from models.mtmc import MtmcSearchJob

            row = MtmcSearchJob.query.get(job_id)
            if row is None:
                return
            params = row.params()
            job_type = row.job_type
        _update_job(app, job_id, status="running", progress=0.05, message="执行中")
        if job_type == "global_trace":
            result = _job_global_trace(app, params)
        elif job_type == "multi_video_reid":
            result = _job_multi_video_reid(app, params, job_id)
        else:
            _update_job(app, job_id, status="failed", error=f"未知任务类型: {job_type}")
            return
        _update_job(
            app,
            job_id,
            status="succeeded",
            progress=1.0,
            message="完成",
            result=result,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("mtmc search job %s failed: %s", job_id, e)
        _update_job(app, job_id, status="failed", error=str(e), message="失败")
    finally:
        with _lock:
            _running.discard(job_id)


def _job_global_trace(app, params: dict) -> dict:
    global_id = (params.get("globalId") or "").strip()
    if not global_id:
        raise ValueError("globalId 必填")
    session_id = (params.get("sessionId") or "").strip()
    with app.app_context():
        from models.mtmc import MtmcCrossCameraEvent, MtmcTrackEvent, MtmcTracklet

        ev_q = MtmcTrackEvent.query.filter_by(global_id=global_id)
        tl_q = MtmcTracklet.query.filter_by(global_id=global_id)
        cc_q = MtmcCrossCameraEvent.query.filter_by(global_id=global_id)
        if session_id:
            ev_q = ev_q.filter(MtmcTrackEvent.session_id == session_id)
            tl_q = tl_q.filter(MtmcTracklet.session_id == session_id)
            cc_q = cc_q.filter(MtmcCrossCameraEvent.session_id == session_id)
        events = ev_q.order_by(MtmcTrackEvent.event_time.asc()).limit(500).all()
        tracklets = tl_q.order_by(MtmcTracklet.start_time.asc()).limit(200).all()
        cross_events = cc_q.order_by(MtmcCrossCameraEvent.event_time.asc()).limit(200).all()
        cameras = sorted({e.camera_id for e in events} | {t.camera_id for t in tracklets})
        return {
            "globalId": global_id,
            "sessionId": session_id or None,
            "cameraPath": cameras,
            "events": [e.to_dict() for e in events],
            "tracklets": [t.to_dict() for t in tracklets],
            "crossEvents": [c.to_dict() for c in cross_events],
            "eventCount": len(events),
            "trackletCount": len(tracklets),
        }


def _job_multi_video_reid(app, params: dict, job_id: str) -> dict:
    upload_folder = app.config.get("UPLOAD_FOLDER") or ""
    camera_ids = [int(x) for x in (params.get("cameraIds") or [])]
    if not camera_ids:
        raise ValueError("cameraIds 必填（本地视频摄像头 ID 列表）")
    query_path = (params.get("queryImagePath") or "").strip()
    if not query_path or not os.path.isfile(query_path):
        raise ValueError("查询图无效")
    reid_root = (params.get("reidRoot") or "").strip()
    model_key = (params.get("modelKey") or "opencv-person-reid-youtu").strip()
    det_path = (params.get("detPath") or "").strip() or None
    threshold = float(params.get("threshold") or 0.45)
    sample_fps = float(params.get("sampleFps") or 1.0)
    max_frames = int(params.get("maxFrames") or 120)
    topk = int(params.get("topk") or 20)

    with open(query_path, "rb") as f:
        query_bytes = f.read()

    from models import Camera
    from inference import search_reid_in_video

    hits_all: list[dict] = []
    total = len(camera_ids)
    for i, cid in enumerate(camera_ids):
        cam = Camera.query.get(cid)
        if cam is None or cam.source_type != "file" or not cam.source:
            continue
        video_path = cam.source
        if not os.path.isabs(video_path):
            video_path = os.path.join(upload_folder, video_path)
        if not os.path.isfile(video_path):
            continue
        try:
            data = search_reid_in_video(
                reid_root,
                model_key,
                query_bytes,
                video_path,
                threshold=threshold,
                topk=topk,
                sample_fps=sample_fps,
                max_frames=max_frames,
                det_abs_path=det_path,
                det_conf=float(params.get("detConf") or 0.35),
            )
            for h in data.get("matches") or []:
                h["cameraId"] = cid
                h["cameraName"] = cam.name
                hits_all.append(h)
        except Exception as e:  # noqa: BLE001
            hits_all.append({
                "cameraId": cid,
                "cameraName": cam.name,
                "error": str(e),
            })
        _update_job(
            app,
            job_id,
            progress=0.1 + 0.85 * (i + 1) / max(total, 1),
            message=f"已处理 {i + 1}/{total} 路视频",
        )
    hits_all.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return {
        "matchCount": len(hits_all),
        "matches": hits_all[:topk * total],
        "cameraIds": camera_ids,
    }
