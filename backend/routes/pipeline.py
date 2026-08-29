"""边缘 AI 视频分析流水线 API（Phase 0 骨架）。"""
from __future__ import annotations

import json
from datetime import datetime

from flask import Blueprint, Response, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity

from extensions import db
from models.pipeline import AiPipeline, AiPipelineRun, AiPipelineVersion
from security import permission_required
from services import pipeline_runtime
from services.pipeline_schema import (
    NODE_TYPES,
    PHASE0_EXECUTABLE,
    PHASE1_EXECUTABLE,
    PHASE2_EXECUTABLE,
    PHASE3_EXECUTABLE,
    build_template,
    dag_required_phase,
    list_templates,
    parse_dag_json,
    validate_dag,
)

pipeline_bp = Blueprint("pipeline", __name__, url_prefix="/api/ai/pipeline")


def _uid():
    try:
        return int(get_jwt_identity())
    except (TypeError, ValueError):
        return None


def _phase_for_dag(dag: dict, explicit=None) -> int:
    if explicit is not None and explicit != "":
        return max(0, int(explicit))
    return max(1, dag_required_phase(dag))


@pipeline_bp.get("/node-types")
@permission_required("ai:pipeline:query")
def node_types():
    rows = []
    for k, meta in NODE_TYPES.items():
        rows.append({
            "type": k,
            **meta,
            "phase0": k in PHASE0_EXECUTABLE,
            "phase1": k in PHASE1_EXECUTABLE,
            "phase2": k in PHASE2_EXECUTABLE,
            "phase3": k in PHASE3_EXECUTABLE,
        })
    return jsonify(code=0, data={
        "rows": rows,
        "phase0Executable": sorted(PHASE0_EXECUTABLE),
        "phase1Executable": sorted(PHASE1_EXECUTABLE),
        "phase2Executable": sorted(PHASE2_EXECUTABLE),
        "phase3Executable": sorted(PHASE3_EXECUTABLE),
    })


@pipeline_bp.get("/templates")
@permission_required("ai:pipeline:query")
def templates():
    return jsonify(code=0, data={"rows": list_templates()})


@pipeline_bp.get("/templates/<tid>")
@permission_required("ai:pipeline:query")
def get_template(tid):
    try:
        dag = build_template(
            tid,
            cameraId=int(request.args.get("cameraId") or 1),
            modelKey=(request.args.get("modelKey") or "yolo26n").strip(),
            conf=float(request.args.get("conf") or 0.35),
            webhookUrl=(request.args.get("webhookUrl") or "").strip(),
            mqttTopic=(request.args.get("mqttTopic") or "").strip(),
            vlmPrompt=(request.args.get("vlmPrompt") or "").strip(),
            cameraIds=(request.args.get("cameraIds") or "").strip() or None,
            cameraId2=int(request.args.get("cameraId2") or 2),
            persistEvents=request.args.get("persistEvents", "1") not in ("0", "false", "False"),
        )
        validate_dag(dag, phase=_phase_for_dag(dag))
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400
    return jsonify(code=0, data=dag)


@pipeline_bp.get("/example-dag")
@permission_required("ai:pipeline:query")
def example_dag():
    camera_id = int(request.args.get("cameraId") or 1)
    model_key = (request.args.get("modelKey") or "yolo26n").strip()
    tpl = (request.args.get("template") or "tpl_rtsp_yolo_overlay").strip()
    try:
        dag = build_template(
            tpl,
            cameraId=camera_id,
            modelKey=model_key,
            mqttTopic=(request.args.get("mqttTopic") or "").strip(),
        )
        validate_dag(dag, phase=_phase_for_dag(dag))
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400
    return jsonify(code=0, data=dag)


@pipeline_bp.post("/validate")
@permission_required("ai:pipeline:query")
def validate():
    data = request.get_json(silent=True) or {}
    try:
        dag = parse_dag_json(data.get("dag") if "dag" in data else data)
        phase = 0 if data.get("phase0Only") else _phase_for_dag(dag, data.get("phase"))
        norm = validate_dag(dag, phase=phase)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400
    return jsonify(code=0, data={
        "ok": True,
        "sourceId": norm["sourceId"],
        "cameraId": norm["cameraId"],
        "order": norm["order"],
        "phase": norm.get("phase", phase),
        "mqttIds": norm.get("mqttIds") or [],
        "vlmGateIds": norm.get("vlmGateIds") or [],
        "mtmcIds": norm.get("mtmcIds") or [],
        "mode": norm.get("mode"),
    })


@pipeline_bp.get("/metrics")
@permission_required("ai:pipeline:query")
def pipeline_metrics():
    """独立指标：live 会话 + 近期 run 历史快照。"""
    live = pipeline_runtime.list_sessions()
    pids = {int(s["pipelineId"]) for s in live if s.get("pipelineId") is not None}
    name_map: dict[int, str] = {}
    if pids:
        for pl in AiPipeline.query.filter(AiPipeline.id.in_(pids)).all():
            name_map[int(pl.id)] = (pl.name or "").strip() or f"流水线{pl.id}"

    # 标题规则：任务名#流水线ID；同 ID 多路并发时追加序号 → 安防检测告警#2、安防检测告警#2-2
    by_pid: dict[int, list] = {}
    ordered = sorted(live, key=lambda x: float(x.get("createdAt") or 0))
    for s in ordered:
        pid = s.get("pipelineId")
        if pid is None:
            continue
        by_pid.setdefault(int(pid), []).append(s)

    title_by_run: dict[str, str] = {}
    name_by_run: dict[str, str] = {}
    for pid, items in by_pid.items():
        name = name_map.get(pid) or "流水线"
        for i, s in enumerate(items, start=1):
            rk = s.get("runKey")
            if not rk:
                continue
            name_by_run[rk] = name
            title_by_run[rk] = f"{name}#{pid}" if len(items) == 1 else f"{name}#{pid}-{i}"

    for s in live:
        rk = s.get("runKey")
        if rk in name_by_run:
            continue
        # 无 pipelineId 的会话（极少）
        name = "MTMC复合" if (s.get("mode") == "mtmc" or (s.get("stats") or {}).get("mode") == "mtmc") else "流水线"
        name_by_run[rk] = name
        title_by_run[rk] = f"{name}#1"

    enriched = []
    for s in live:
        d = dict(s)
        rk = d.get("runKey")
        d["pipelineName"] = name_by_run.get(rk) or "流水线"
        d["displayTitle"] = title_by_run.get(rk) or f"{d['pipelineName']}#{d.get('pipelineId') or 1}"
        d["mode"] = d.get("mode") or (d.get("stats") or {}).get("mode") or "classic"
        enriched.append(d)

    history_rows = AiPipelineRun.query.order_by(AiPipelineRun.id.desc()).limit(50).all()
    history = []
    for r in history_rows:
        d = r.to_dict()
        pl_name = None
        if r.pipeline_id:
            pl = AiPipeline.query.get(r.pipeline_id)
            pl_name = (pl.name if pl else None) or None
        history.append({
            "runKey": d.get("runKey"),
            "pipelineId": d.get("pipelineId"),
            "pipelineName": pl_name,
            "displayTitle": f"{pl_name}#{d.get('pipelineId')}" if pl_name else f"流水线#{d.get('pipelineId')}",
            "cameraId": d.get("cameraId"),
            "state": d.get("state"),
            "startedAt": d.get("startedAt"),
            "stoppedAt": d.get("stoppedAt"),
            "metrics": d.get("metrics") or {},
            "errorMessage": d.get("errorMessage"),
        })
    running = sum(1 for s in enriched if s.get("running"))
    stalled = sum(1 for s in enriched if (s.get("stats") or {}).get("sourceStalled"))
    alerts = sum(int((s.get("stats") or {}).get("alerts") or 0) for s in enriched)
    return jsonify(code=0, data={
        "live": enriched,
        "history": history,
        "summary": {
            "running": running,
            "stalled": stalled,
            "liveAlerts": alerts,
            "historyCount": len(history),
        },
    })


@pipeline_bp.get("")
@permission_required("ai:pipeline:list")
def list_pipelines():
    page = max(1, int(request.args.get("pageNum") or 1))
    size = min(100, max(1, int(request.args.get("pageSize") or 20)))
    q = AiPipeline.query.order_by(AiPipeline.id.desc())
    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": total})


@pipeline_bp.post("")
@permission_required("ai:pipeline:edit")
def create_pipeline():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(code=400, message="name 必填"), 400
    try:
        dag = parse_dag_json(data.get("dag"))
        validate_dag(dag, phase=_phase_for_dag(dag, data.get("phase")))
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400

    pl = AiPipeline(
        name=name,
        description=(data.get("description") or "")[:500] or None,
        status="0",
        current_version=1,
        create_by=_uid(),
    )
    db.session.add(pl)
    db.session.flush()
    ver = AiPipelineVersion(
        pipeline_id=pl.id,
        version=1,
        dag_json=json.dumps(dag, ensure_ascii=False),
        remark=(data.get("remark") or "v1")[:255],
    )
    db.session.add(ver)
    db.session.commit()
    return jsonify(code=0, message="已创建", data=pl.to_dict(with_dag=True))


@pipeline_bp.get("/<int:pid>")
@permission_required("ai:pipeline:query")
def get_pipeline(pid):
    pl = AiPipeline.query.get(pid)
    if not pl:
        return jsonify(code=404, message="流水线不存在"), 404
    return jsonify(code=0, data=pl.to_dict(with_dag=True))


@pipeline_bp.put("/<int:pid>")
@permission_required("ai:pipeline:edit")
def update_pipeline(pid):
    pl = AiPipeline.query.get(pid)
    if not pl:
        return jsonify(code=404, message="流水线不存在"), 404
    data = request.get_json(silent=True) or {}
    if "name" in data and str(data.get("name") or "").strip():
        pl.name = str(data.get("name")).strip()
    if "description" in data:
        pl.description = (data.get("description") or "")[:500] or None
    if "status" in data and str(data.get("status")) in ("0", "1"):
        pl.status = str(data.get("status"))

    if "dag" in data:
        try:
            dag = parse_dag_json(data.get("dag"))
            validate_dag(dag, phase=_phase_for_dag(dag, data.get("phase")))
        except ValueError as e:
            return jsonify(code=400, message=str(e)), 400
        new_ver = int(pl.current_version or 1) + 1
        ver = AiPipelineVersion(
            pipeline_id=pl.id,
            version=new_ver,
            dag_json=json.dumps(dag, ensure_ascii=False),
            remark=(data.get("remark") or f"v{new_ver}")[:255],
        )
        db.session.add(ver)
        pl.current_version = new_ver

    pl.update_time = datetime.utcnow()
    db.session.commit()
    return jsonify(code=0, message="已更新", data=pl.to_dict(with_dag=True))


@pipeline_bp.delete("/<int:pid>")
@permission_required("ai:pipeline:edit")
def delete_pipeline(pid):
    pl = AiPipeline.query.get(pid)
    if not pl:
        return jsonify(code=404, message="流水线不存在"), 404
    # 停掉相关运行中会话
    for s in pipeline_runtime.list_sessions():
        if s.get("pipelineId") == pid and s.get("running"):
            pipeline_runtime.stop_run(s["runKey"])
            pipeline_runtime.persist_run_stopped(current_app._get_current_object(), s["runKey"])
    db.session.delete(pl)
    db.session.commit()
    return jsonify(code=0, message="已删除")


@pipeline_bp.post("/<int:pid>/start")
@permission_required("ai:pipeline:edit")
def start_pipeline(pid):
    pl = AiPipeline.query.get(pid)
    if not pl:
        return jsonify(code=404, message="流水线不存在"), 404
    if pl.status == "1":
        return jsonify(code=400, message="流水线已停用"), 400
    ver = AiPipelineVersion.query.filter_by(
        pipeline_id=pl.id, version=pl.current_version
    ).first()
    if not ver:
        return jsonify(code=400, message="无可用版本 DAG"), 400
    dag = ver.dag()
    try:
        phase = _phase_for_dag(dag)
        norm = validate_dag(dag, phase=phase)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400

    app = current_app._get_current_object()
    try:
        sess = pipeline_runtime.start_run(
            app=app,
            pipeline_id=pl.id,
            version_id=ver.id,
            dag=dag,
            phase=phase,
        )
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"启动失败: {e}"), 500

    row = AiPipelineRun(
        run_key=sess.run_key,
        pipeline_id=pl.id,
        version_id=ver.id,
        camera_id=norm["cameraId"],
        state="running",
        started_at=datetime.utcnow(),
        metrics_json="{}",
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(code=0, message="流水线已启动", data={
        **sess.to_dict(),
        "runId": row.id,
        "overlayUrl": f"/api/ai/pipeline/runs/{sess.run_key}/overlay/stream",
    })


@pipeline_bp.post("/runs/<run_key>/stop")
@permission_required("ai:pipeline:edit")
def stop_run(run_key):
    ok = pipeline_runtime.stop_run(run_key)
    pipeline_runtime.persist_run_stopped(current_app._get_current_object(), run_key, state="stopped")
    if not ok:
        # 仍更新 DB
        row = AiPipelineRun.query.filter_by(run_key=run_key).first()
        if not row:
            return jsonify(code=404, message="运行实例不存在"), 404
    return jsonify(code=0, message="已停止")


@pipeline_bp.get("/runs")
@permission_required("ai:pipeline:query")
def list_runs():
    pid = request.args.get("pipelineId")
    q = AiPipelineRun.query
    if pid:
        q = q.filter_by(pipeline_id=int(pid))
    rows = q.order_by(AiPipelineRun.id.desc()).limit(50).all()
    live = {s["runKey"]: s for s in pipeline_runtime.list_sessions()}
    out = []
    for r in rows:
        d = r.to_dict()
        if r.run_key in live:
            d["live"] = live[r.run_key]
        out.append(d)
    return jsonify(code=0, data={"rows": out, "live": list(live.values())})


@pipeline_bp.get("/runs/<run_key>")
@permission_required("ai:pipeline:query")
def get_run(run_key):
    row = AiPipelineRun.query.filter_by(run_key=run_key).first()
    live = pipeline_runtime.get_session(run_key)
    data = row.to_dict() if row else {"runKey": run_key}
    if live:
        data["live"] = live.to_dict()
        data["state"] = "running" if live.running else data.get("state") or "stopped"
    elif not row:
        return jsonify(code=404, message="运行实例不存在"), 404
    return jsonify(code=0, data=data)


@pipeline_bp.get("/runs/<run_key>/alive")
@permission_required("ai:pipeline:query")
def run_alive(run_key):
    live = pipeline_runtime.get_session(run_key)
    active = bool(live and live.running)
    return jsonify(code=0, data={"active": active, "runKey": run_key, "live": live.to_dict() if live else None})


@pipeline_bp.get("/runs/<run_key>/overlay/stream")
def overlay_stream(run_key):
    """标注 MJPEG（query jwt，供 <img> 订阅）。"""
    from flask_jwt_extended import verify_jwt_in_request
    from security import current_user, has_perm

    try:
        verify_jwt_in_request(locations=["query_string"])
    except Exception:  # noqa: BLE001
        return jsonify(code=401, message="未登录或令牌无效"), 401
    user = current_user()
    if not has_perm(user, "ai:pipeline:query") and not has_perm(user, "ai:pipeline:list"):
        return jsonify(code=403, message="没有访问权限"), 403
    live = pipeline_runtime.get_session(run_key)
    if not live:
        return jsonify(code=404, message="运行实例不存在或未启动"), 404
    gen = pipeline_runtime.iter_overlay_mjpeg(run_key)
    return Response(
        gen,
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@pipeline_bp.get("/by-camera/<int:cid>/overlay/stream")
def overlay_by_camera(cid):
    """监控墙按摄像头取当前运行中流水线叠加（query jwt）。"""
    from flask_jwt_extended import verify_jwt_in_request
    from security import current_user, has_perm

    try:
        verify_jwt_in_request(locations=["query_string"])
    except Exception:  # noqa: BLE001
        return jsonify(code=401, message="未登录或令牌无效"), 401
    user = current_user()
    if not (
        has_perm(user, "ai:pipeline:query")
        or has_perm(user, "ai:pipeline:list")
        or has_perm(user, "camera:query")
    ):
        return jsonify(code=403, message="没有访问权限"), 403
    live = pipeline_runtime.get_session_for_camera(cid)
    if not live or not live.running:
        return jsonify(code=404, message="该摄像头无运行中的流水线"), 404
    gen = pipeline_runtime.iter_overlay_mjpeg(live.run_key)
    resp = Response(
        gen,
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )
    resp.headers["X-Pipeline-Run"] = live.run_key
    return resp


@pipeline_bp.get("/by-camera/<int:cid>/alive")
@permission_required("ai:pipeline:query")
def alive_by_camera(cid):
    live = pipeline_runtime.get_session_for_camera(cid)
    return jsonify(code=0, data={
        "active": bool(live and live.running),
        "runKey": live.run_key if live else None,
        "live": live.to_dict() if live else None,
    })
