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
    from services.openapi_catalog import (
        all_scopes, catalog_stats, list_domain_groups, list_domains,
    )
    return jsonify(code=0, data={
        "scopes": all_scopes(),
        "webhookEvents": ["job.succeeded", "job.failed", "api.call", "*"],
        "stats": catalog_stats(),
        "groups": list_domain_groups(),
        "domains": [
            {
                "id": d["id"],
                "label": d["label"],
                "order": d["order"],
                "risk": d["risk"],
                "group": d["group"],
                "groupLabel": d["groupLabel"],
                "blueprint": d["blueprint"],
                "domainScope": d["domainScope"],
                "fullScopes": d["fullScopes"],
                "endpointCount": d["endpointCount"],
                "bridgeableCount": d["bridgeableCount"],
                "scopes": d["scopes"],
                "suggestedAppId": d["suggestedAppId"],
                "suggestedName": d["suggestedName"],
                "endpoints": [
                    {
                        "method": e["method"],
                        "path": e["path"],
                        "openPath": e.get("openPath"),
                        "scope": e["scope"],
                        "summary": e["summary"],
                        "bridgeable": e["bridgeable"],
                        "blueprint": e.get("blueprint"),
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
    size = int(request.args.get("pageSize", 50))
    name = (request.args.get("name") or "").strip()
    domain_id = (request.args.get("domainId") or "").strip()
    category = (request.args.get("category") or "").strip()
    query = OpenApp.query
    if name:
        query = query.filter(OpenApp.name.contains(name))
    if domain_id:
        query = query.filter(OpenApp.domain_id == domain_id)
    if category:
        query = query.filter(OpenApp.category == category)
    total = query.count()
    rows = query.order_by(OpenApp.category.asc(), OpenApp.domain_id.asc(), OpenApp.id.asc())\
        .offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [a.to_dict() for a in rows], "total": total})


def _meta_for_domain(domain_id: str):
    from services.openapi_catalog import DOMAIN_META, list_domains
    for d in list_domains():
        if d["id"] == domain_id:
            return d
    meta = DOMAIN_META.get(domain_id)
    if meta:
        return {
            "id": domain_id,
            "label": meta["label"],
            "group": meta.get("group"),
            "fullScopes": [f"domain:{domain_id}"],
            "suggestedAppId": f"app_{domain_id}",
            "suggestedName": f"{meta['label']}开放应用",
        }
    return None


def _create_app_record(data: dict, *, default_scopes=None):
    """内部创建逻辑，返回 (app, plaintext_key|None, error_response|None)。"""
    name = (data.get("name") or "").strip()
    app_id = (data.get("appId") or "").strip()
    if not name:
        return None, None, (jsonify(code=400, message="应用名称必填"), 400)
    if not app_id:
        import secrets
        app_id = "app_" + secrets.token_hex(8)
    if OpenApp.query.filter_by(app_id=app_id).first():
        return None, None, (jsonify(code=409, message="appId 已存在"), 409)

    domain_id = (data.get("domainId") or "").strip() or None
    category = (data.get("category") or "").strip() or None
    if domain_id and not category:
        meta = _meta_for_domain(domain_id)
        if meta:
            category = meta.get("group")

    scopes = data.get("scopes")
    if scopes is None:
        scopes = default_scopes or []

    app = OpenApp(
        app_id=app_id,
        name=name,
        status=data.get("status") or "0",
        qps_limit=int(data.get("qpsLimit") or 10),
        daily_limit=int(data.get("dailyLimit") or 10000),
        remark=(data.get("remark") or "").strip() or None,
        domain_id=domain_id,
        category=category,
    )
    app.set_scopes(scopes)
    _apply_webhook_fields(app, data)
    db.session.add(app)
    db.session.flush()

    plaintext = None
    if data.get("createKey", True):
        plaintext = generate_api_key()
        db.session.add(OpenApiKey(
            app_pk=app.id,
            name=(data.get("keyName") or "default").strip() or "default",
            key_prefix=key_prefix(plaintext),
            key_hash=hash_api_key(plaintext),
            status="0",
        ))
    db.session.commit()
    return app, plaintext, None


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


@open_app_bp.post("/from-domain")
@permission_required("system:openapp:add")
def create_from_domain():
    """按业务域一键新建应用，Scope 覆盖该域全部接口。"""
    from services.openapi_catalog import scopes_for_domain
    data = request.get_json(silent=True) or {}
    domain_id = (data.get("domainId") or "").strip()
    if not domain_id:
        return jsonify(code=400, message="domainId 必填"), 400
    meta = _meta_for_domain(domain_id)
    if not meta:
        return jsonify(code=404, message=f"未知域：{domain_id}"), 404

    payload = {
        "name": (data.get("name") or meta["suggestedName"]).strip(),
        "appId": (data.get("appId") or meta["suggestedAppId"]).strip(),
        "domainId": domain_id,
        "category": meta.get("group"),
        "scopes": data.get("scopes") or scopes_for_domain(domain_id, include_fine=True),
        "qpsLimit": data.get("qpsLimit", 20),
        "dailyLimit": data.get("dailyLimit", 10000),
        "remark": data.get("remark") or f"按域自动覆盖：{meta['label']} 全部接口",
        "createKey": data.get("createKey", True),
        "status": data.get("status") or "0",
    }
    # 已存在则更新 Scope 为全覆盖（幂等）
    existing = OpenApp.query.filter_by(app_id=payload["appId"]).first()
    if existing:
        existing.name = payload["name"]
        existing.domain_id = domain_id
        existing.category = payload["category"]
        existing.set_scopes(payload["scopes"])
        existing.remark = payload["remark"]
        db.session.commit()
        return jsonify(code=0, message="域应用已存在，已刷新全量 Scope", data=existing.to_dict(with_keys=True))

    app, plaintext, err = _create_app_record(payload)
    if err:
        return err
    body = app.to_dict(with_keys=True)
    if plaintext:
        body["apiKey"] = plaintext
        body["apiKeyHint"] = "请立即保存，服务端只存哈希"
    return jsonify(code=0, message="按域创建成功", data=body), 201


@open_app_bp.post("/ensure-domains")
@permission_required("system:openapp:add")
def ensure_all_domain_apps():
    """为每个 Blueprint 域各建/刷新一个应用，覆盖项目全部可分类接口。"""
    from services.openapi_catalog import list_domains, scopes_for_all_bridgeable_domains, scopes_for_domain

    created, updated = [], []
    for d in list_domains():
        if d["id"] in ("other",):
            continue
        app_id = d["suggestedAppId"]
        scopes = scopes_for_domain(d["id"], include_fine=True)
        # open_app / openapi 仍建目录型应用（便于管理面看到覆盖），即便不可桥接
        existing = OpenApp.query.filter_by(app_id=app_id).first()
        if existing:
            existing.name = d["suggestedName"]
            existing.domain_id = d["id"]
            existing.category = d["group"]
            existing.set_scopes(scopes)
            existing.remark = f"域全覆盖 · Blueprint={d.get('blueprint') or '-'} · 接口 {d['endpointCount']}"
            updated.append(app_id)
        else:
            app, _pt, err = _create_app_record({
                "name": d["suggestedName"],
                "appId": app_id,
                "domainId": d["id"],
                "category": d["group"],
                "scopes": scopes,
                "remark": f"域全覆盖 · Blueprint={d.get('blueprint') or '-'} · 接口 {d['endpointCount']}",
                "createKey": True,
                "qpsLimit": 20,
                "dailyLimit": 10000,
            })
            if err:
                continue
            created.append(app_id)

    # 全量汇总应用
    full_id = "app_full_all"
    full_scopes = scopes_for_all_bridgeable_domains()
    full = OpenApp.query.filter_by(app_id=full_id).first()
    if full:
        full.set_scopes(full_scopes)
        full.domain_id = "full"
        full.category = "platform"
        full.name = "全量开放应用（所有域）"
        full.remark = "覆盖全部可桥接业务域"
        updated.append(full_id)
    else:
        app, _pt, err = _create_app_record({
            "name": "全量开放应用（所有域）",
            "appId": full_id,
            "domainId": "full",
            "category": "platform",
            "scopes": full_scopes,
            "remark": "覆盖全部可桥接业务域",
            "createKey": True,
            "qpsLimit": 50,
            "dailyLimit": 100000,
        })
        if not err:
            created.append(full_id)

    db.session.commit()
    return jsonify(code=0, message="域应用已对齐", data={
        "created": created,
        "updated": updated,
        "domainCount": len(list_domains()),
    })


@open_app_bp.post("")
@permission_required("system:openapp:add")
def create_app():
    data = request.get_json(silent=True) or {}
    # 若带 domainId 且未显式 scopes，自动域全覆盖
    if data.get("domainId") and not data.get("scopes"):
        from services.openapi_catalog import scopes_for_domain
        data = {**data, "scopes": scopes_for_domain(data["domainId"], include_fine=True)}
    app, plaintext, err = _create_app_record(data)
    if err:
        return err
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
    if "domainId" in data:
        app.domain_id = (data.get("domainId") or "").strip() or None
    if "category" in data:
        app.category = (data.get("category") or "").strip() or None
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
