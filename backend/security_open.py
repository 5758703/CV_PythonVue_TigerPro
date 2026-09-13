"""开放 API 鉴权：AppId + ApiKey、Scope、简易限流、调用审计。"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote

from flask import current_app, g, jsonify, request
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import RequestEntityTooLarge

from extensions import db
from models.open_app import (
    OpenApiCallLog,
    OpenApiKey,
    OpenApiNonce,
    OpenApiRateBucket,
    OpenApp,
)

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
_SIGNATURE_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_TIMESTAMP_RE = re.compile(r"^[0-9]{10,12}$")
_NONCE_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HASH_CHUNK_BYTES = 64 * 1024


class SignedPayloadTooLarge(ValueError):
    pass


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
        supplied = (request.headers.get("X-Request-Id") or "").strip()
        rid = supplied if _REQUEST_ID_RE.fullmatch(supplied) else uuid.uuid4().hex
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


def _read_and_restore(stream, maximum: int) -> bytes:
    try:
        position = stream.tell()
    except (AttributeError, OSError):
        position = 0
    chunks = []
    remaining = maximum + 1
    while remaining > 0:
        chunk = stream.read(min(_HASH_CHUNK_BYTES, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    try:
        stream.seek(position)
    except (AttributeError, OSError):
        pass
    raw = b"".join(chunks)
    if len(raw) > maximum:
        raise SignedPayloadTooLarge("image exceeds the scenario image size limit")
    return raw


def scenario_payload_hash() -> str:
    """Hash a reproducible scenario payload without multipart boundary bytes."""
    if request.method in ("GET", "HEAD"):
        return hashlib.sha256(b"").hexdigest()
    if request.mimetype == "multipart/form-data":
        lines = []
        for field, values in request.form.lists():
            for value in values:
                lines.append(
                    f"form:{quote(str(field), safe='')}={quote(str(value), safe='')}"
                )
        maximum = int(current_app.config.get("SCENARIO_MAX_IMAGE_BYTES", 12 * 1024 * 1024))
        for field, uploads in request.files.lists():
            for upload in uploads:
                digest = hashlib.sha256(_read_and_restore(upload.stream, maximum)).hexdigest()
                lines.append(f"file:{quote(str(field), safe='')}:{digest}")
        return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()
    maximum = int(current_app.config.get("SCENARIO_MAX_IMAGE_BYTES", 12 * 1024 * 1024))
    raw = request.get_data(cache=True)
    if len(raw) > maximum:
        raise SignedPayloadTooLarge("request exceeds the scenario payload size limit")
    return hashlib.sha256(raw).hexdigest()


def canonical_scenario_request(timestamp: str, nonce: str, payload_hash: str) -> str:
    return "\n".join((request.method.upper(), request.path, timestamp, nonce, payload_hash))


def _client_ip() -> str:
    if current_app.config.get("TRUST_PROXY", False):
        forwarded = request.headers.get("X-Forwarded-For") or ""
        candidate = forwarded.split(",", 1)[0].strip()
        if candidate:
            return candidate
    return (request.remote_addr or "").strip()


def _ip_allowed(app: OpenApp) -> bool:
    entries = app.ip_allowlist_entries()
    if not entries:
        return True
    try:
        address = ipaddress.ip_address(_client_ip())
    except ValueError:
        return False
    for entry in entries:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def _remember_nonce(app: OpenApp, nonce: str, now: datetime, max_age: int) -> bool:
    OpenApiNonce.query.filter(OpenApiNonce.expires_at <= now).delete(synchronize_session=False)
    db.session.add(OpenApiNonce(
        app_pk=app.id,
        nonce=nonce,
        expires_at=now + timedelta(seconds=max_age),
    ))
    try:
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        return False


def _verify_scenario_signature(app: OpenApp, api_key: str) -> tuple[str | None, str]:
    timestamp = (request.headers.get("X-Timestamp") or "").strip()
    nonce = (request.headers.get("X-Nonce") or "").strip()
    signature = (request.headers.get("X-Signature") or "").strip()
    if signature.lower().startswith("sha256="):
        signature = signature[7:]
    if not timestamp or not nonce or not signature:
        return "signed request headers are required", "signature"
    if (
        not _TIMESTAMP_RE.fullmatch(timestamp)
        or not _NONCE_RE.fullmatch(nonce)
        or not _SIGNATURE_RE.fullmatch(signature)
    ):
        return "signed request headers are invalid", "signature"
    max_age = int(current_app.config.get("OPENAPI_SIGNATURE_MAX_AGE_SECONDS", 300))
    now_seconds = int(time.time())
    if abs(now_seconds - int(timestamp)) > max_age:
        return "request timestamp is outside the allowed window", "signature"
    payload_hash = scenario_payload_hash()
    canonical = canonical_scenario_request(timestamp, nonce, payload_hash)
    expected = hmac.new(
        api_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        return "request signature is invalid", "signature"
    if not _remember_nonce(app, nonce, datetime.utcnow(), max_age):
        return "request nonce has already been used", "replay"
    return None, ""


def _consume_rate_bucket(
    app_pk: int,
    kind: str,
    key: str,
    limit: int,
    expires_at: datetime,
) -> bool:
    query = OpenApiRateBucket.query.filter_by(
        app_pk=app_pk, bucket_kind=kind, bucket_key=key,
    )
    updated = query.filter(OpenApiRateBucket.count < limit).update(
        {OpenApiRateBucket.count: OpenApiRateBucket.count + 1},
        synchronize_session=False,
    )
    if updated:
        db.session.commit()
        return True
    if query.first() is not None:
        db.session.rollback()
        return False
    db.session.add(OpenApiRateBucket(
        app_pk=app_pk,
        bucket_kind=kind,
        bucket_key=key,
        count=1,
        expires_at=expires_at,
    ))
    try:
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        updated = query.filter(OpenApiRateBucket.count < limit).update(
            {OpenApiRateBucket.count: OpenApiRateBucket.count + 1},
            synchronize_session=False,
        )
        db.session.commit()
        return bool(updated)


def _check_shared_rate_limit(app: OpenApp) -> tuple[str | None, int | None]:
    now_seconds = int(time.time())
    now = datetime.utcfromtimestamp(now_seconds)
    OpenApiRateBucket.query.filter(OpenApiRateBucket.expires_at <= now).delete(
        synchronize_session=False,
    )
    db.session.commit()

    daily = int(app.daily_limit or 0)
    if daily > 0:
        day = now.strftime("%Y-%m-%d")
        tomorrow = datetime(now.year, now.month, now.day) + timedelta(days=1)
        if not _consume_rate_bucket(app.id, "day", day, daily, tomorrow):
            return "daily request limit exceeded", max(1, int((tomorrow - now).total_seconds()))

    qps = int(app.qps_limit or 0)
    if qps > 0:
        key = str(now_seconds)
        if not _consume_rate_bucket(
            app.id, "second", key, qps, now + timedelta(seconds=2),
        ):
            return "QPS limit exceeded", 1
    return None, None


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


def require_open_scope(scope: str, *, signed_request: bool = False):
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

            if signed_request and not _ip_allowed(app):
                msg = "client IP is not allowed"
                resp = open_error(403, 403, msg, "ip_forbidden")
                log_open_call(
                    capability=scope,
                    status_code=403,
                    biz_code=403,
                    latency_ms=int((time.time() - started) * 1000),
                    error_message=msg,
                )
                return resp

            if signed_request:
                try:
                    signature_err, signature_type = _verify_scenario_signature(app, api_key)
                except (SignedPayloadTooLarge, RequestEntityTooLarge) as exc:
                    msg = (
                        str(exc) if isinstance(exc, SignedPayloadTooLarge)
                        else "request entity too large"
                    )
                    resp = open_error(413, 413, msg, "request_too_large")
                    log_open_call(
                        capability=scope,
                        status_code=413,
                        biz_code=413,
                        latency_ms=int((time.time() - started) * 1000),
                        error_message=msg,
                    )
                    return resp
                except Exception as exc:  # noqa: BLE001
                    msg = "request security validation failed"
                    resp = open_error(500, 500, msg, "internal")
                    log_open_call(
                        capability=scope,
                        status_code=500,
                        biz_code=500,
                        latency_ms=int((time.time() - started) * 1000),
                        error_message=type(exc).__name__,
                    )
                    return resp
                if signature_err:
                    status = 409 if signature_type == "replay" else 401
                    resp = open_error(status, status, signature_err, signature_type)
                    log_open_call(
                        capability=scope,
                        status_code=status,
                        biz_code=status,
                        latency_ms=int((time.time() - started) * 1000),
                        error_message=signature_err,
                    )
                    return resp

            retry_after = None
            if signed_request:
                rate_err, retry_after = _check_shared_rate_limit(app)
            else:
                rate_err = _check_rate_limit(app)
            if rate_err:
                resp = open_error(429, 429, rate_err, "rate_limited")
                if retry_after:
                    resp.headers["Retry-After"] = str(retry_after)
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
                msg = "internal server error"
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
