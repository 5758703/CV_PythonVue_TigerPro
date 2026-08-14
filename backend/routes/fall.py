"""跌倒检测与报警 /api/ai/fall。

姿态关键点 -> person 检测框(+trackId) -> fall_detection 规则判定 -> 合成 fall 框 + 告警事件。
"""
import json
import uuid

from flask import Blueprint, jsonify, request

from extensions import db
from models import AiModel
from models.alert import AlertEvent
from security import permission_required
from services.alert_engine import (
    active_overlay_style,
    evaluate_rules,
    fall_config,
    fall_detections,
    reset_runtime,
)
from services.alert_rules_query import load_enabled_alert_rules, parse_rule_keys

fall_bp = Blueprint("fall", __name__, url_prefix="/api/ai/fall")


def _form_float(name, default):
    try:
        return float(request.form.get(name, default))
    except (TypeError, ValueError):
        return default


def _fall_rules(rules):
    return [r for r in rules if r.rule_type == "fall_detection"]


def _max_track_max_age(rules) -> int:
    """多条 fall 规则取 track_max_age 最大值（ID 分配层只能有一份配置）。"""
    ages = [fall_config(r.config())["track_max_age"] for r in _fall_rules(rules)]
    return max(ages) if ages else 15


def _min_kp_conf(rules) -> float:
    """多条 fall 规则取 kp_min_conf 最小值，保证任一规则都能拿到所需关键点。"""
    confs = [fall_config(r.config())["kp_min_conf"] for r in _fall_rules(rules)]
    return min(confs) if confs else 0.3


@fall_bp.post("/detect")
@permission_required("ai:fall:list")
def detect():
    """单帧跌倒检测：姿态关键点 + 四指标规则判定 + 合成 fall 框 + 告警事件。

    表单：file 图片；modelId 姿态模型；conf 姿态置信度(默认0.25)；
    sourceKey 来源标识(默认 fall-live)；sourceType(默认 camera)；
    ruleKeys 规则过滤(不传=全部启用规则，传 [] =不评估)；persist 是否落事件(默认1)；
    draw 是否返回骨架图 base64(默认0)。
    """
    from routes.ai_model import _resolve_pose_runtime
    from services.fall_detect import assign_track_ids, build_person_detections

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400
    try:
        mid = int(request.form.get("modelId", 0))
    except (TypeError, ValueError):
        mid = 0
    if not mid:
        return jsonify(code=400, message="缺少 modelId"), 400
    m = AiModel.query.get(mid)
    if m is None:
        return jsonify(code=404, message="模型不存在"), 404
    try:
        lib, abs_path, _task = _resolve_pose_runtime(m)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400

    conf = _form_float("conf", 0.25)
    draw = (request.form.get("draw") or "0") in ("1", "true", "True")
    source_key = (request.form.get("sourceKey") or "fall-live").strip() or "fall-live"
    source_type = (request.form.get("sourceType") or "camera").strip() or "camera"
    persist = (request.form.get("persist") or "1") in ("1", "true", "True")

    raw_keys = request.form.get("ruleKeys")
    rule_keys = parse_rule_keys(raw_keys) if raw_keys is not None else None

    try:
        image_bytes = file.read()
        if lib == "rtmlib":
            from inference import estimate_pose_rtmlib
            result = estimate_pose_rtmlib(
                m.model_key or "rtmo-s", abs_path, image_bytes, conf=conf, draw=draw)
        else:
            from inference import estimate_pose
            result = estimate_pose(abs_path, image_bytes, conf=conf, draw=draw)
    except FileNotFoundError as e:
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"姿态估计失败：{e}"), 500

    width = result.get("width")
    height = result.get("height")
    rules = load_enabled_alert_rules(rule_keys)
    kp_min_conf = _min_kp_conf(rules)
    detections = build_person_detections(
        result.get("persons") or [], width, height, kp_min_conf)
    assign_track_ids(
        detections, source_key, max_age=_max_track_max_age(rules), kp_min_conf=kp_min_conf)

    data = {
        "persons": result.get("persons") or [],
        "count": result.get("count", 0),
        "width": width,
        "height": height,
        "keypointCount": result.get("keypointCount", 17),
        "imageBase64": result.get("imageBase64"),
        "detections": detections,
        "triggered": [],
        "overlay": None,
    }
    if not rules:
        return jsonify(code=0, message="无匹配的启用规则", data=data)

    frame_token = str(uuid.uuid4())

    def _persist(rule, title, message, detail):
        ev = AlertEvent(
            rule_id=rule.id,
            rule_key=rule.rule_key,
            rule_name=rule.name,
            severity=rule.severity,
            title=title,
            message=message,
            source_type=source_type,
            source_key=source_key,
            model_id=mid,
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
        frame_width=width,
        frame_height=height,
        frame_token=frame_token,
    )
    boxes = fall_detections(
        rules,
        detections,
        source_key=source_key,
        frame_width=width,
        frame_height=height,
        frame_token=frame_token,
    )
    overlay = active_overlay_style(
        rules,
        detections,
        video=False,
        frame_width=width,
        frame_height=height,
        source_key=source_key,
        frame_token=frame_token,
    )
    data["detections"] = detections + boxes
    data["triggered"] = triggered
    data["overlay"] = overlay
    return jsonify(code=0, message="ok", data=data)


@fall_bp.post("/reset-runtime")
@permission_required("ai:fall:list")
def reset_runtime_api():
    """停止检测时清连续帧/冷却/跌倒跟踪状态。"""
    data = request.get_json(silent=True) or {}
    source_key = (data.get("sourceKey") or "").strip() or None
    reset_runtime(source_key)
    return jsonify(code=0, message="已重置")
