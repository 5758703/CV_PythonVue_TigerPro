"""流水线 ↔ MTMC 复合节点桥接：启动/附着会话，跨镜事件转发到 Sink。"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from services.pipeline_schema import _parse_camera_ids, make_event_envelope

log = logging.getLogger(__name__)


def build_mtmc_config_from_node(cfg: dict):
    """复用 routes.mtmc 的模型挑选逻辑，从 DAG 节点 config 构建 MtmcConfig。"""
    from routes.mtmc import _parse_session_params, _validate_mtmc_config

    data = dict(cfg or {})
    cams = _parse_camera_ids(data.get("cameraIds"))
    data["cameraIds"] = cams
    # 默认开启证据落库，否则跨镜事件不会写入 cross_events
    if "persistEvents" not in data:
        data["persistEvents"] = True
    mtmc_cfg = _parse_session_params(data)
    err = _validate_mtmc_config(mtmc_cfg)
    if err:
        raise ValueError(err)
    if len(mtmc_cfg.camera_ids) < 2:
        raise ValueError("composite.mtmc 至少需要 2 路摄像头")
    return mtmc_cfg


def start_or_attach_mtmc(app, cfg: dict, *, upload_folder: str):
    """返回 (MtmcSession, owned: bool)。"""
    from models.camera import Camera
    from services import mtmc_engine

    attach_id = (cfg.get("sessionId") or "").strip()
    own = bool(cfg.get("ownSession", True))
    if attach_id:
        sess = mtmc_engine.get_session(attach_id)
        if not sess or not sess.running:
            raise ValueError(f"无法附着 MTMC 会话: {attach_id}")
        return sess, False

    mtmc_cfg = build_mtmc_config_from_node(cfg)
    with app.app_context():
        cams = (
            Camera.query.filter(Camera.id.in_(mtmc_cfg.camera_ids), Camera.status == "0")
            .order_by(Camera.id.asc())
            .all()
        )
        found = {int(c.id) for c in cams}
        missing = [cid for cid in mtmc_cfg.camera_ids if cid not in found]
        if missing:
            raise ValueError(f"摄像头不存在或已停用: {missing}")

    session = mtmc_engine.start_session(
        mtmc_cfg,
        cameras=cams,
        upload_folder=upload_folder,
        app=app,
    )
    return session, own


def stop_owned_mtmc(session_id: str | None, owned: bool) -> bool:
    if not session_id or not owned:
        return False
    from services import mtmc_engine

    return bool(mtmc_engine.stop_session(session_id))


def cross_event_to_envelope(row: dict, *, pipeline_id: str, run_id: str) -> dict:
    cam_id = row.get("cameraId") or row.get("toCameraId") or row.get("fromCameraId")
    return make_event_envelope(
        event_type="mtmc.cross_camera",
        pipeline_id=str(pipeline_id),
        run_id=run_id,
        camera_id=int(cam_id) if cam_id is not None else None,
        rule_key="mtmc-cross",
        track_id=row.get("globalId") if isinstance(row.get("globalId"), int) else None,
        score=row.get("score") or row.get("appearScore"),
        payload=row,
    )


def run_mtmc_bridge_loop(
    pipeline_sess: Any,
    mtmc_sess: Any,
    *,
    dispatch_fn,
    poll_sec: float = 0.5,
):
    """轮询 MTMC cross_events，转为流水线 EventEnvelope 并投递 Sink。"""
    last_n = 0
    while not pipeline_sess._stop.is_set():
        try:
            if not mtmc_sess or not getattr(mtmc_sess, "running", False):
                pipeline_sess.error = "mtmc session stopped"
                time.sleep(0.5)
                continue
            events = list(getattr(mtmc_sess, "cross_events", None) or [])
            if len(events) > last_n:
                batch = events[last_n:]
                last_n = len(events)
                envs = [
                    cross_event_to_envelope(
                        row,
                        pipeline_id=str(pipeline_sess.pipeline_id),
                        run_id=pipeline_sess.run_key,
                    )
                    for row in batch
                ]
                pipeline_sess.last_events = (pipeline_sess.last_events + envs)[-50:]
                pipeline_sess.stats["mtmcCrossEvents"] = int(
                    pipeline_sess.stats.get("mtmcCrossEvents") or 0
                ) + len(envs)
                pipeline_sess.stats["alerts"] = int(pipeline_sess.stats.get("alerts") or 0) + len(envs)
                dispatch_fn(pipeline_sess, envs)

            # 汇总 MTMC 侧统计
            st = getattr(mtmc_sess, "stats", None) or {}
            if isinstance(st, dict):
                pipeline_sess.stats["mtmcFrames"] = st.get("frames") or st.get("processed") or 0
            pipeline_sess.stats["mtmcSessionId"] = getattr(mtmc_sess, "session_id", None) or getattr(
                mtmc_sess, "id", None
            )
            # 取第一路 overlay 供预览（若有）
            cams = getattr(mtmc_sess, "cams", None) or {}
            for _cid, cam_state in cams.items():
                jpeg = getattr(cam_state, "overlay_jpeg", None)
                if jpeg:
                    pipeline_sess.overlay_jpeg = jpeg
                    pipeline_sess.frame_seq = int(getattr(cam_state, "frame_seq", 0) or 0)
                    break
            pipeline_sess.error = None
        except Exception as exc:  # noqa: BLE001
            log.warning("mtmc bridge %s: %s", pipeline_sess.run_key, exc)
            pipeline_sess.error = str(exc)
        pipeline_sess._stop.wait(poll_sec)

    pipeline_sess.running = False


def spawn_mtmc_bridge(pipeline_sess: Any, mtmc_sess: Any, dispatch_fn) -> threading.Thread:
    th = threading.Thread(
        target=run_mtmc_bridge_loop,
        args=(pipeline_sess, mtmc_sess),
        kwargs={"dispatch_fn": dispatch_fn},
        name=f"pipeline-mtmc-{pipeline_sess.run_key}",
        daemon=True,
    )
    th.start()
    return th
