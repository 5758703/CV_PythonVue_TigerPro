"""Open API → 控制台 /api/* 桥接（AppKey + Scope 后以服务账号 JWT 内调）。"""
from __future__ import annotations

from flask import Response, current_app, request
from flask_jwt_extended import create_access_token
from werkzeug.datastructures import FileStorage

from models import User
from security_open import (
    current_open_app,
    current_request_id,
    open_error,
    require_open_scope,
)
from services.openapi_catalog import app_allows_endpoint, resolve_api_endpoint
from services import metrics_registry as metrics

BRIDGE_USER = "openapi_bridge"


def _service_token() -> str | None:
    user = User.query.filter_by(username=BRIDGE_USER, del_flag="0").first()
    if user is None or user.status != "0":
        return None
    return create_access_token(identity=str(user.id))


def _forward_headers(token: str) -> dict:
    skip = {
        "host", "content-length", "authorization", "x-api-key", "x-app-id",
        "connection", "transfer-encoding",
    }
    headers = {}
    for k, v in request.headers:
        if k.lower() in skip:
            continue
        headers[k] = v
    headers["Authorization"] = f"Bearer {token}"
    headers["X-OpenAPI-Bridge"] = "1"
    headers["X-Request-Id"] = current_request_id()
    app = current_open_app()
    if app:
        headers["X-Open-App-Id"] = app.app_id
    return headers


def _build_form_data():
    """重建 form + files 供 test_client 发送。"""
    data = {}
    for key in request.form:
        vals = request.form.getlist(key)
        data[key] = vals[0] if len(vals) == 1 else vals
    for key in request.files:
        files = request.files.getlist(key)
        packed = []
        for fs in files:
            if not isinstance(fs, FileStorage):
                continue
            raw = fs.read()
            fs.stream.seek(0)
            packed.append((fs.filename, raw, fs.content_type or "application/octet-stream"))
        if not packed:
            continue
        if len(packed) == 1:
            fn, raw, ctype = packed[0]
            data[key] = (fn, raw, ctype)
        else:
            # werkzeug 多文件：同名多值较麻烦，取第一个并附带其余为 key_i（极少见）
            fn, raw, ctype = packed[0]
            data[key] = (fn, raw, ctype)
    return data


def handle_bridge(subpath: str):
    """将 /openapi/v1/x/<subpath> 转到 /api/<subpath>。"""
    api_path = "/api/" + (subpath or "").lstrip("/")
    method = request.method.upper()
    endpoint = resolve_api_endpoint(method, api_path)

    if endpoint is None:
        # 仍尝试转发未知路径（兼容动态规则），但要求域级或通配授权
        endpoint = {
            "method": method,
            "path": api_path,
            "domain": "other",
            "scope": "open:other:access",
            "bridgeable": api_path.startswith("/api/") and not api_path.startswith("/api/system/open-app"),
            "summary": api_path,
        }

    if not endpoint.get("bridgeable", False):
        return open_error(403, 403, f"该接口不可通过 Open API 桥接：{api_path}", "forbidden")

    app = current_open_app()
    owned = app.scope_list() if app else []
    if not app_allows_endpoint(owned, endpoint):
        need = endpoint.get("scope") or f"domain:{endpoint.get('domain')}"
        return open_error(
            403, 403,
            f"缺少能力授权：需要 {need} 或 domain:{endpoint.get('domain')} 或 *:*:*",
            "forbidden",
        )

    token = _service_token()
    if not token:
        return open_error(503, 503, "桥接服务账号 openapi_bridge 未就绪，请重启后端以写入种子", "unavailable")

    headers = _forward_headers(token)
    client = current_app.test_client()
    try:
        if method in ("POST", "PUT", "PATCH", "DELETE") and (
            request.files or (request.form and not request.is_json)
        ):
            # multipart / form
            data = _build_form_data()
            # DELETE 也可能有 body，少见
            resp = client.open(
                api_path,
                method=method,
                data=data if data else request.get_data(),
                headers=headers,
                query_string=request.query_string,
                content_type=request.content_type if not data else None,
            )
        elif method in ("POST", "PUT", "PATCH") and request.is_json:
            resp = client.open(
                api_path,
                method=method,
                data=request.get_data(),
                headers=headers,
                query_string=request.query_string,
                content_type="application/json",
            )
        else:
            resp = client.open(
                api_path,
                method=method,
                data=request.get_data() if method not in ("GET", "HEAD") else None,
                headers=headers,
                query_string=request.query_string,
                content_type=request.content_type,
            )
    except Exception as e:  # noqa: BLE001
        return open_error(502, 502, f"桥接调用失败：{e}", "bad_gateway")

    metrics.incr(
        "tigerpro_open_bridge",
        domain=endpoint.get("domain") or "other",
        status=str(resp.status_code),
    )

    out = Response(resp.get_data(), status=resp.status_code)
    # 透传内容类型
    ctype = resp.headers.get("Content-Type")
    if ctype:
        out.headers["Content-Type"] = ctype
    out.headers["X-Request-Id"] = current_request_id()
    out.headers["X-OpenAPI-Bridge-Path"] = api_path
    # 流式 / MJPEG 等
    for h in ("Content-Disposition", "Cache-Control", "Accept-Ranges"):
        if resp.headers.get(h):
            out.headers[h] = resp.headers.get(h)
    return out


def register_bridge_routes(bp):
    """挂到 openapi_v1_bp。先走 AppKey 鉴权（空 scope），再按接口鉴权。"""

    @bp.route("/x/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    @require_open_scope("")
    def openapi_bridge(subpath):
        return handle_bridge(subpath)

    @bp.get("/catalog")
    @require_open_scope("")
    def openapi_catalog_view():
        from security_open import open_ok
        from services.openapi_catalog import catalog_stats, list_domains
        from services.openapi_catalog import app_allows_endpoint

        app = current_open_app()
        owned = app.scope_list() if app else []
        domains = []
        for d in list_domains():
            eps = []
            for e in d["endpoints"]:
                if not e.get("bridgeable"):
                    continue
                eps.append({
                    **{k: e[k] for k in (
                        "method", "path", "openPath", "scope", "summary", "bridgeable"
                    )},
                    "granted": app_allows_endpoint(owned, e),
                })
            domains.append({
                "id": d["id"],
                "label": d["label"],
                "risk": d["risk"],
                "domainScope": d["domainScope"],
                "domainGranted": (
                    f"domain:{d['id']}" in owned or "*" in owned or "*:*:*" in owned
                ),
                "bridgeableCount": d["bridgeableCount"],
                "endpoints": eps,
            })
        return open_ok({"stats": catalog_stats(), "domains": domains, "scopes": owned})
