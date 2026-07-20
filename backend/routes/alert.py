"""检测告警 API /api/alerts。"""
from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from extensions import db
from models import AlertEvent, AlertRule
from security import permission_required
from services.alert_engine import active_overlay_style, evaluate_rules, reset_runtime

alert_bp = Blueprint("alert", __name__, url_prefix="/api/alerts")


@alert_bp.get("/rules")
@permission_required("ai:alert:list")
def list_rules():
    rows = AlertRule.query.order_by(AlertRule.id.asc()).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": len(rows)})


@alert_bp.get("/rules/<int:rid>")
@permission_required("ai:alert:query")
def get_rule(rid):
    rule = AlertRule.query.get_or_404(rid)
    return jsonify(code=0, data=rule.to_dict())


@alert_bp.put("/rules/<int:rid>")
@permission_required("ai:alert:edit")
def update_rule(rid):
    """管理员更新告警规则：阈值 / 文案模板 / 叠加样式 / 启停。"""
    rule = AlertRule.query.get_or_404(rid)
    data = request.get_json(silent=True) or {}

    if "name" in data and str(data["name"]).strip():
        rule.name = str(data["name"]).strip()[:128]
    if "description" in data:
        rule.description = (str(data["description"]) if data["description"] is not None else "")[:500]
    if "severity" in data and data["severity"] in ("low", "medium", "high"):
        rule.severity = data["severity"]
    if "status" in data and str(data["status"]) in ("0", "1"):
        rule.status = str(data["status"])

    if "config" in data and isinstance(data["config"], dict):
        cfg = rule.config()
        incoming = dict(data["config"])
        if isinstance(incoming.get("overlay"), dict):
            ov = dict(cfg.get("overlay") or {})
            ov.update(incoming["overlay"])
            incoming["overlay"] = ov
        cfg.update(incoming)
        for k in ("min_confidence", "min_count", "video_min_count", "consecutive_frames", "cooldown_sec"):
            if k in cfg and cfg[k] is not None:
                try:
                    if k == "min_confidence":
                        cfg[k] = float(cfg[k])
                    else:
                        cfg[k] = int(float(cfg[k]))
                except (TypeError, ValueError):
                    pass
        if "classes" in cfg and isinstance(cfg["classes"], str):
            cfg["classes"] = [x.strip() for x in cfg["classes"].replace("，", ",").split(",") if x.strip()]
        if "class_names" in cfg and isinstance(cfg["class_names"], str):
            cfg["class_names"] = [
                x.strip() for x in cfg["class_names"].replace("，", ",").split(",") if x.strip()
            ]
        if "line" in cfg:
            raw_line = cfg["line"]
            if isinstance(raw_line, str):
                parts = [p.strip() for p in raw_line.replace("，", ",").split(",") if p.strip()]
                try:
                    cfg["line"] = [float(p) for p in parts]
                except (TypeError, ValueError):
                    pass
            if isinstance(cfg.get("line"), (list, tuple)) and len(cfg["line"]) == 4:
                try:
                    cfg["line"] = [float(x) for x in cfg["line"]]
                except (TypeError, ValueError):
                    pass
        if "direction" in cfg and str(cfg["direction"]) not in ("in", "out", "both"):
            cfg["direction"] = "both"
        rule.config_json = json.dumps(cfg, ensure_ascii=False)

    db.session.commit()
    return jsonify(code=0, message="规则已更新", data=rule.to_dict())


@alert_bp.get("/events")
@permission_required("ai:alert:list")
def list_events():
    page = max(1, int(request.args.get("pageNum", 1)))
    size = min(100, max(1, int(request.args.get("pageSize", 20))))
    q = AlertEvent.query
    status = (request.args.get("status") or "").strip()
    if status in ("0", "1"):
        q = q.filter(AlertEvent.status == status)
    rule_key = (request.args.get("ruleKey") or "").strip()
    if rule_key:
        q = q.filter(AlertEvent.rule_key == rule_key)
    q = q.order_by(AlertEvent.id.desc())
    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    return jsonify(
        code=0,
        data={
            "rows": [e.to_dict() for e in rows],
            "total": total,
            "pageNum": page,
            "pageSize": size,
        },
    )


@alert_bp.put("/events/<int:eid>/ack")
@permission_required("ai:alert:edit")
def ack_event(eid):
    ev = AlertEvent.query.get_or_404(eid)
    ev.status = "1"
    db.session.commit()
    return jsonify(code=0, message="已确认", data=ev.to_dict())


@alert_bp.delete("/events/<int:eid>")
@permission_required("ai:alert:remove")
def remove_event(eid):
    ev = AlertEvent.query.get_or_404(eid)
    db.session.delete(ev)
    db.session.commit()
    return jsonify(code=0, message="已删除")


@alert_bp.post("/evaluate")
@permission_required("ai:alert:list")
def evaluate():
    """对一帧检测结果评估全部启用规则。

    JSON body:
      detections / sourceKey / sourceType / modelId / persist
      frameWidth / frameHeight / line（越线规则用，line 为归一化 [x1,y1,x2,y2]）
    返回 triggered + overlay（当前帧中央叠加样式，不依赖冷却）
    """
    import uuid

    data = request.get_json(silent=True) or {}
    detections = data.get("detections")
    if not isinstance(detections, list):
        return jsonify(code=400, message="缺少 detections 数组"), 400

    source_key = (data.get("sourceKey") or "camera-live").strip() or "camera-live"
    source_type = (data.get("sourceType") or "camera").strip() or "camera"
    model_id = data.get("modelId")
    persist = data.get("persist", True)
    frame_width = data.get("frameWidth") or data.get("frame_width")
    frame_height = data.get("frameHeight") or data.get("frame_height")
    line = data.get("line")
    frame_token = str(data.get("frameToken") or uuid.uuid4())

    # ruleKeys 未传 → 全部启用规则（兼容旧前端）；传 [] → 不评估
    from services.alert_rules_query import load_enabled_alert_rules, parse_rule_keys

    if "ruleKeys" in data or "rule_keys" in data:
        rule_keys = parse_rule_keys(data.get("ruleKeys", data.get("rule_keys")))
    else:
        rule_keys = None
    rules = load_enabled_alert_rules(rule_keys)
    if not rules:
        return jsonify(code=0, message="无匹配的启用规则", data={"triggered": [], "overlay": None})

    def _persist(rule, title, message, detail):
        if not persist:
            return None
        ev = AlertEvent(
            rule_id=rule.id,
            rule_key=rule.rule_key,
            rule_name=rule.name,
            severity=rule.severity,
            title=title,
            message=message,
            source_type=source_type,
            source_key=source_key,
            model_id=int(model_id) if model_id is not None else None,
            payload_json=json.dumps(detail, ensure_ascii=False),
            status="0",
        )
        db.session.add(ev)
        db.session.commit()
        return ev.to_dict()

    triggered = evaluate_rules(
        rules,
        detections,
        source_key,
        persist_event=_persist if persist else None,
        frame_width=frame_width,
        frame_height=frame_height,
        line=line,
        frame_token=frame_token,
    )
    overlay = active_overlay_style(
        rules,
        detections,
        video=False,
        frame_width=frame_width,
        frame_height=frame_height,
        line=line,
        source_key=source_key,
        frame_token=frame_token,
    )
    return jsonify(code=0, message="评估完成", data={"triggered": triggered, "overlay": overlay})


@alert_bp.post("/reset-runtime")
@permission_required("ai:alert:list")
def reset_runtime_api():
    """停止检测时清除连续帧/冷却状态。"""
    data = request.get_json(silent=True) or {}
    source_key = (data.get("sourceKey") or "").strip() or None
    reset_runtime(source_key)
    return jsonify(code=0, message="已重置")
