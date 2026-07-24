"""开放 API 鉴权：AppId + ApiKey、Scope、简易限流、调用审计。"""
from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from datetime import datetime
from functools import wraps

from flask import g, jsonify, request

from extensions import db
from models.open_app import OpenApiCallLog, OpenApiKey, OpenApp

# 已知能力：动态取自全量目录（保留旧别名兼容）
def get_known_scopes():
    try:
        from services.openapi_catalog import all_scopes
        return all_scopes()
    except Exception:  # noqa: BLE001
        return [
            "vision:detect", "vision:ocr", "face:recognize", "water:read", "jobs:read",
            "*:*:*",
        ]


# 向后兼容：可迭代 / 可成员检测
class _KnownScopes:
    def __iter__(self):
        return iter(get_known_scopes())

    def __contains__(self, item):
        return item in get_known_scopes()

    def __len__(self):
        return len(get_known_scopes())


KNOWN_SCOPES = _KnownScopes()

# 进程内滑动窗口限流：{app_id: [(ts, ...)]}
_rate_buckets: dict[str, list[float]] = {}
_daily_counts: dict[str, tuple[str, int]] = {}  # app_id -> (YYYY-MM-DD, count)


def generate_api_key() -> str:
    """明文 Key，仅创建时返回一次。"""
    return "tp_live_" + secrets.token_hex(24)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256((raw_key or "").encode("utf-8")).hexdigest()


def key_prefix(raw_key: str) -> str:
    k = raw_key or ""
    return k[:12] if len(k) >= 12 else k


def _match_scope(required: str, owned: list[str]) -> bool:
    """支持精确匹配与前缀通配：vision:* / *。"""
    if not required:
        return True
    if "*" in owned or "*:*" in owned or "*:*:*" in owned:
        return True
    if required in owned:
        return True
    # domain:face 在 require 为具体 perm 时由 app_allows_endpoint 处理
    if required.startswith("domain:") and required in owned:
        return True
    # vision:* 覆盖 vision:detect
    prefix = required.split(":")[0] + ":*"
    return prefix in owned


def current_open_app() -> OpenApp | None:
    return getattr(g, "open_app", None)


def current_request_id() -> str:
    rid = getattr(g, "open_request_id", None)
    if not rid:
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        g.open_request_id = rid
    return rid


def _extract_credentials():
    """支持：
    - Header: X-App-Id + X-Api-Key
    - Authorization: Bearer <api_key>（app_id 仍建议带 X-App-Id；若 Key 能唯一定位可省略）
    """
    app_id = (request.headers.get("X-App-Id") or request.args.get("appId") or "").strip()
    api_key = (request.headers.get("X-Api-Key") or "").strip()
    if not api_key:
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            api_key = auth[7:].strip()
    return app_id, api_key


def _check_rate_limit(app: OpenApp) -> str | None:
    """返回错误信息或 None。"""
    now = time.time()
    app_id = app.app_id
    qps = int(app.qps_limit or 0)
    if qps > 0:
        bucket = _rate_buckets.setdefault(app_id, [])
        cutoff = now - 1.0
        bucket[:] = [t for t in bucket if t >= cutoff]
        if len(bucket) >= qps:
            return f"超过 QPS 限制（{qps}/s）"
        bucket.append(now)

    daily = int(app.daily_limit or 0)
    if daily > 0:
        day = datetime.utcnow().strftime("%Y-%m-%d")
        prev_day, count = _daily_counts.get(app_id, ("", 0))
        if prev_day != day:
            count = 0
        if count >= daily:
            return f"超过日调用上限（{daily}）"
        _daily_counts[app_id] = (day, count + 1)
    return None


def resolve_open_app(app_id: str, api_key: str) -> tuple[OpenApp | None, OpenApiKey | None, str | None]:
    """校验凭证，返回 (app, key_row, error_message)。"""
    if not api_key:
        return None, None, "缺少 API Key（X-Api-Key 或 Authorization: Bearer）"
    digest = hash_api_key(api_key)
    row = OpenApiKey.query.filter_by(key_hash=digest, status="0").first()
    if row is None:
        return None, None, "API Key 无效或已停用"
    if row.expires_at and row.expires_at < datetime.utcnow():
        return None, None, "API Key 已过期"
    app = OpenApp.query.get(row.app_pk)
    if app is None or app.status != "0":
        return None, None, "应用不存在或已停用"
    if app_id and app.app_id != app_id:
        return None, None, "X-App-Id 与 API Key 不匹配"
    return app, row, None


def log_open_call(*, capability: str, status_code: int, biz_code: int | None,
                  latency_ms: int, error_message: str | None = None):
    app = current_open_app()
    try:
        entry = OpenApiCallLog(
            app_pk=app.id if app else None,
            app_id=app.app_id if app else None,
            request_id=current_request_id(),
            method=request.method,
            path=request.path,
            capability=capability,
            status_code=status_code,
            biz_code=biz_code,
            latency_ms=latency_ms,
            error_message=(error_message or "")[:500] or None,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()


def open_error(http_status: int, code: int, message: str, err_type: str = "error"):
    body = {
        "code": code,
        "message": message,
        "error": {"type": err_type, "message": message},
        "requestId": current_request_id(),
    }
    resp = jsonify(body)
    resp.status_code = http_status
    resp.headers["X-Request-Id"] = current_request_id()
    return resp


def open_ok(data=None, message: str = "ok", http_status: int = 200):
    body = {"code": 0, "message": message, "requestId": current_request_id()}
    if data is not None:
        body["data"] = data
    resp = jsonify(body)
    resp.status_code = http_status
    resp.headers["X-Request-Id"] = current_request_id()
    return resp


def require_open_scope(scope: str):
    """开放 API 守卫：鉴权 + scope + 限流 + 调用日志。"""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            started = time.time()
            current_request_id()
            app_id, api_key = _extract_credentials()
            app, key_row, err = resolve_open_app(app_id, api_key)
            if err:
                resp = open_error(401, 401, err, "unauthorized")
                log_open_call(
                    capability=scope,
                    status_code=401,
                    biz_code=401,
                    latency_ms=int((time.time() - started) * 1000),
                    error_message=err,
                )
                return resp

            g.open_app = app
            g.open_api_key = key_row

            if not _match_scope(scope, app.scope_list()):
                msg = f"缺少能力授权：{scope}"
                resp = open_error(403, 403, msg, "forbidden")
                log_open_call(
                    capability=scope,
                    status_code=403,
                    biz_code=403,
                    latency_ms=int((time.time() - started) * 1000),
                    error_message=msg,
                )
                return resp

            rate_err = _check_rate_limit(app)
            if rate_err:
                resp = open_error(429, 429, rate_err, "rate_limited")
                log_open_call(
                    capability=scope,
                    status_code=429,
                    biz_code=429,
                    latency_ms=int((time.time() - started) * 1000),
                    error_message=rate_err,
                )
                return resp

            try:
                key_row.last_used_at = datetime.utcnow()
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()

            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                msg = f"内部错误：{exc}"
                resp = open_error(500, 500, msg, "internal")
                log_open_call(
                    capability=scope,
                    status_code=500,
                    biz_code=500,
                    latency_ms=int((time.time() - started) * 1000),
                    error_message=msg,
                )
                return resp

            latency = int((time.time() - started) * 1000)
            status_code = getattr(result, "status_code", 200)
            biz_code = 0
            err_msg = None
            try:
                payload = result.get_json(silent=True) or {}
                if isinstance(payload, dict) and "code" in payload:
                    biz_code = int(payload.get("code") or 0)
                    if biz_code != 0:
                        err_msg = payload.get("message")
            except Exception:  # noqa: BLE001
                pass
            if hasattr(result, "headers"):
                result.headers["X-Request-Id"] = current_request_id()
            log_open_call(
                capability=scope,
                status_code=status_code,
                biz_code=biz_code,
                latency_ms=latency,
                error_message=err_msg,
            )
            try:
                from services import metrics_registry as metrics
                metrics.observe_latency(
                    "tigerpro_open_request",
                    float(latency),
                    capability=scope or "auth",
                    status=str(status_code),
                )
            except Exception:  # noqa: BLE001
                pass
            return result

        return wrapper

    return decorator
