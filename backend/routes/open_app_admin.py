"""控制台：开放应用与 API Key 管理 /api/system/open-app"""
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from sqlalchemy import func

from extensions import db
from models.open_app import OpenApp, OpenApiKey, OpenApiCallLog
from security import permission_required
from security_open import generate_api_key, hash_api_key, key_prefix
from services.webhook import deliver_webhook

open_app_bp = Blueprint("sys_open_app", __name__, url_prefix="/api/system/open-app")


@open_app_bp.get("/scopes")
@permission_required("system:openapp:list")
def list_scopes():
    from services.openapi_catalog import all_scopes, catalog_stats, list_domains
    return jsonify(code=0, data={
        "scopes": all_scopes(),
        "webhookEvents": ["job.succeeded", "job.failed", "api.call", "*"],
        "stats": catalog_stats(),
        "domains": [
            {
                "id": d["id"],
                "label": d["label"],
                "order": d["order"],
                "risk": d["risk"],
                "domainScope": d["domainScope"],
                "endpointCount": d["endpointCount"],
                "bridgeableCount": d["bridgeableCount"],
                "scopes": d["scopes"],
                "endpoints": [
                    {
                        "method": e["method"],
                        "path": e["path"],
                        "openPath": e.get("openPath"),
                        "scope": e["scope"],
                        "summary": e["summary"],
                        "bridgeable": e["bridgeable"],
                    }
                    for e in d["endpoints"]
                ],
            }
            for d in list_domains()
        ],
    })


@open_app_bp.get("")
@permission_required("system:openapp:list")
def list_apps():
    page = int(request.args.get("pageNum", 1))
    size = int(request.args.get("pageSize", 10))
    name = (request.args.get("name") or "").strip()
    query = OpenApp.query
    if name:
        query = query.filter(OpenApp.name.contains(name))
    total = query.count()
    rows = query.order_by(OpenApp.id.desc()).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [a.to_dict() for a in rows], "total": total})


@open_app_bp.get("/<int:aid>")
@permission_required("system:openapp:query")
def get_app(aid):
    app = OpenApp.query.get_or_404(aid)
    return jsonify(code=0, data=app.to_dict(with_keys=True))


def _apply_webhook_fields(app: OpenApp, data: dict):
    if "webhookUrl" in data:
        app.webhook_url = (data.get("webhookUrl") or "").strip() or None
    if "webhookSecret" in data:
        secret = (data.get("webhookSecret") or "").strip()
        if secret:
            app.webhook_secret = secret
        elif data.get("webhookSecret") == "":
            app.webhook_secret = None
    if "webhookEvents" in data:
        app.set_webhook_events(data.get("webhookEvents") or [])


@open_app_bp.post("")
@permission_required("system:openapp:add")
def create_app():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    app_id = (data.get("appId") or "").strip()
    if not name:
        return jsonify(code=400, message="应用名称必填"), 400
    if not app_id:
        import secrets
        app_id = "app_" + secrets.token_hex(8)
    if OpenApp.query.filter_by(app_id=app_id).first():
        return jsonify(code=409, message="appId 已存在"), 409

    app = OpenApp(
        app_id=app_id,
        name=name,
        status=data.get("status") or "0",
        qps_limit=int(data.get("qpsLimit") or 10),
        daily_limit=int(data.get("dailyLimit") or 10000),
        remark=(data.get("remark") or "").strip() or None,
    )
    app.set_scopes(data.get("scopes") or [])
    _apply_webhook_fields(app, data)
    db.session.add(app)
    db.session.flush()

    plaintext = None
    if data.get("createKey", True):
        plaintext = generate_api_key()
        row = OpenApiKey(
            app_pk=app.id,
            name=(data.get("keyName") or "default").strip() or "default",
            key_prefix=key_prefix(plaintext),
            key_hash=hash_api_key(plaintext),
            status="0",
        )
        db.session.add(row)

    db.session.commit()
    payload = app.to_dict(with_keys=True)
    if plaintext:
        payload["apiKey"] = plaintext
        payload["apiKeyHint"] = "请立即保存，服务端只存哈希"
    return jsonify(code=0, message="创建成功", data=payload), 201


@open_app_bp.put("/<int:aid>")
@permission_required("system:openapp:edit")
def update_app(aid):
    app = OpenApp.query.get_or_404(aid)
    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify(code=400, message="应用名称不能为空"), 400
        app.name = name
    if "status" in data and data["status"] in ("0", "1"):
        app.status = data["status"]
    if "scopes" in data:
        app.set_scopes(data.get("scopes") or [])
    if "qpsLimit" in data:
        app.qps_limit = int(data.get("qpsLimit") or 0)
    if "dailyLimit" in data:
        app.daily_limit = int(data.get("dailyLimit") or 0)
    if "remark" in data:
        app.remark = (data.get("remark") or "").strip() or None
    _apply_webhook_fields(app, data)
    db.session.commit()
    return jsonify(code=0, message="已更新", data=app.to_dict(with_keys=True))


@open_app_bp.delete("/<int:aid>")
@permission_required("system:openapp:remove")
def delete_app(aid):
    app = OpenApp.query.get_or_404(aid)
    db.session.delete(app)
    db.session.commit()
    return jsonify(code=0, message="已删除")


@open_app_bp.post("/<int:aid>/keys")
@permission_required("system:openapp:add")
def create_key(aid):
    app = OpenApp.query.get_or_404(aid)
    data = request.get_json(silent=True) or {}
    plaintext = generate_api_key()
    row = OpenApiKey(
        app_pk=app.id,
        name=(data.get("name") or "default").strip() or "default",
        key_prefix=key_prefix(plaintext),
        key_hash=hash_api_key(plaintext),
        status="0",
    )
    db.session.add(row)
    db.session.commit()
    payload = row.to_dict()
    payload["apiKey"] = plaintext
    payload["apiKeyHint"] = "请立即保存，服务端只存哈希"
    return jsonify(code=0, message="密钥已创建", data=payload), 201


@open_app_bp.put("/<int:aid>/keys/<int:kid>")
@permission_required("system:openapp:edit")
def update_key(aid, kid):
    row = OpenApiKey.query.filter_by(id=kid, app_pk=aid).first_or_404()
    data = request.get_json(silent=True) or {}
    if "name" in data:
        row.name = (data.get("name") or "").strip() or row.name
    if "status" in data and data["status"] in ("0", "1"):
        row.status = data["status"]
    db.session.commit()
    return jsonify(code=0, message="已更新", data=row.to_dict())


@open_app_bp.delete("/<int:aid>/keys/<int:kid>")
@permission_required("system:openapp:remove")
def delete_key(aid, kid):
    row = OpenApiKey.query.filter_by(id=kid, app_pk=aid).first_or_404()
    db.session.delete(row)
    db.session.commit()
    return jsonify(code=0, message="密钥已删除")


@open_app_bp.get("/<int:aid>/logs")
@permission_required("system:openapp:query")
def list_logs(aid):
    app = OpenApp.query.get_or_404(aid)
    page = int(request.args.get("pageNum", 1))
    size = min(int(request.args.get("pageSize", 20)), 100)
    query = OpenApiCallLog.query.filter_by(app_pk=app.id)
    total = query.count()
    rows = (
        query.order_by(OpenApiCallLog.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": total})


@open_app_bp.get("/<int:aid>/usage")
@permission_required("system:openapp:query")
def usage_stats(aid):
    """近 N 日调用量 + 按 capability 聚合（供图表）。"""
    app = OpenApp.query.get_or_404(aid)
    days = min(int(request.args.get("days", 7)), 90)
    since = datetime.utcnow() - timedelta(days=days)

    day_expr = func.date(OpenApiCallLog.create_time)
    daily = (
        db.session.query(day_expr.label("day"), func.count().label("cnt"))
        .filter(OpenApiCallLog.app_pk == app.id, OpenApiCallLog.create_time >= since)
        .group_by(day_expr)
        .order_by(day_expr)
        .all()
    )
    by_cap = (
        db.session.query(
            OpenApiCallLog.capability, func.count().label("cnt"),
            func.avg(OpenApiCallLog.latency_ms).label("avgLatency"),
        )
        .filter(OpenApiCallLog.app_pk == app.id, OpenApiCallLog.create_time >= since)
        .group_by(OpenApiCallLog.capability)
        .all()
    )
    err_cnt = OpenApiCallLog.query.filter(
        OpenApiCallLog.app_pk == app.id,
        OpenApiCallLog.create_time >= since,
        OpenApiCallLog.biz_code != 0,
    ).count()
    total = OpenApiCallLog.query.filter(
        OpenApiCallLog.app_pk == app.id,
        OpenApiCallLog.create_time >= since,
    ).count()

    return jsonify(code=0, data={
        "days": days,
        "total": total,
        "errorCount": err_cnt,
        "daily": [{"day": str(d), "count": int(c)} for d, c in daily],
        "byCapability": [
            {
                "capability": cap or "(none)",
                "count": int(c),
                "avgLatencyMs": round(float(avg or 0), 1),
            }
            for cap, c, avg in by_cap
        ],
    })


@open_app_bp.post("/<int:aid>/webhook/test")
@permission_required("system:openapp:edit")
def test_webhook(aid):
    app = OpenApp.query.get_or_404(aid)
    if not (app.webhook_url or "").strip():
        return jsonify(code=400, message="请先配置 webhookUrl"), 400
    ok = deliver_webhook(app, "webhook.test", {"message": "TigerPro webhook ping"})
    return jsonify(code=0 if ok else 502, message="投递成功" if ok else "投递失败或非 2xx")
