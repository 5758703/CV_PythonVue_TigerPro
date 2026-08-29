"""Webhook 投递：任务终态 / 可选 API 调用事件。"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import datetime

import requests

from extensions import db
from models.open_app import OpenApp

log = logging.getLogger(__name__)


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def deliver_webhook(app: OpenApp, event: str, payload: dict, timeout: float = 8.0) -> bool:
    url = (getattr(app, "webhook_url", None) or "").strip()
    if not url:
        return False
    events = app.webhook_event_list() if hasattr(app, "webhook_event_list") else []
    if events and event not in events and "*" not in events:
        return False

    body_obj = {
        "event": event,
        "appId": app.app_id,
        "deliveredAt": datetime.utcnow().isoformat() + "Z",
        "data": payload,
    }
    raw = json.dumps(body_obj, ensure_ascii=False, default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-TigerPro-Event": event,
        "User-Agent": "TigerPro-OpenAPI-Webhook/1.0",
    }
    secret = (getattr(app, "webhook_secret", None) or "").strip()
    if secret:
        headers["X-TigerPro-Signature"] = "sha256=" + _sign(secret, raw)

    try:
        resp = requests.post(url, data=raw, headers=headers, timeout=timeout)
        ok = 200 <= resp.status_code < 300
        if not ok:
            log.warning("webhook %s -> %s status=%s", event, url, resp.status_code)
        return ok
    except Exception as exc:  # noqa: BLE001
        log.warning("webhook %s failed: %s", event, exc)
        return False


def deliver_webhook_async(app_pk: int, event: str, payload: dict):
    """后台线程投递，避免阻塞请求。需在有 app context 的进程内调用。"""
    from flask import current_app

    app_obj = current_app._get_current_object()

    def _run():
        with app_obj.app_context():
            app = OpenApp.query.get(app_pk)
            if app is None:
                return
            deliver_webhook(app, event, payload)
            try:
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()

    threading.Thread(target=_run, daemon=True).start()


def deliver_url_webhook(
    url: str,
    event: str,
    payload: dict,
    *,
    secret: str | None = None,
    timeout: float = 8.0,
    retries: int = 2,
) -> bool:
    """向任意 URL 投递事件（流水线 sink.webhook），HMAC 可选；失败短暂重试。"""
    url = (url or "").strip()
    if not url:
        return False
    body_obj = {
        "event": event,
        "deliveredAt": datetime.utcnow().isoformat() + "Z",
        "data": payload,
    }
    raw = json.dumps(body_obj, ensure_ascii=False, default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-TigerPro-Event": event,
        "User-Agent": "TigerPro-Pipeline-Webhook/1.0",
    }
    if secret:
        headers["X-TigerPro-Signature"] = "sha256=" + _sign(secret, raw)
    attempts = max(1, int(retries) + 1)
    last_exc = None
    for i in range(attempts):
        try:
            resp = requests.post(url, data=raw, headers=headers, timeout=timeout)
            ok = 200 <= resp.status_code < 300
            if ok:
                return True
            log.warning("pipeline webhook %s -> %s status=%s attempt=%s", event, url, resp.status_code, i + 1)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("pipeline webhook %s failed attempt=%s: %s", event, i + 1, exc)
        if i + 1 < attempts:
            time.sleep(0.2 * (i + 1))
    if last_exc:
        log.warning("pipeline webhook %s exhausted retries: %s", event, last_exc)
    return False


def deliver_url_webhook_async(
    url: str,
    event: str,
    payload: dict,
    *,
    secret: str | None = None,
    on_done=None,
) -> bool:
    """异步投递；立即返回 True 表示已调度。on_done(success: bool)。"""
    if not (url or "").strip():
        return False

    def _run():
        ok = deliver_url_webhook(url, event, payload, secret=secret)
        if callable(on_done):
            try:
                on_done(ok)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_run, daemon=True).start()
    return True
