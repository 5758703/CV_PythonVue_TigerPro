"""MQTT 事件总线（paho-mqtt）：告警等旁路发布，失败不影响主链路。

默认 MQTT_ENABLED=0；未启用时 publish 为 no-op 并返回 False。
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

_lock = threading.Lock()
_client = None
_connected = False
_disabled_logged = False


def mqtt_enabled() -> bool:
    try:
        from config import Config

        return bool(getattr(Config, "MQTT_ENABLED", False))
    except Exception:  # noqa: BLE001
        return (os.getenv("MQTT_ENABLED") or "0").strip() in ("1", "true", "True", "yes")


def _cfg(name: str, default: str = "") -> str:
    try:
        from config import Config

        return str(getattr(Config, name, default) or default)
    except Exception:  # noqa: BLE001
        return os.getenv(name, default) or default


def topic_prefix() -> str:
    return (_cfg("MQTT_TOPIC_PREFIX", "tigerpro/dev") or "tigerpro/dev").rstrip("/")


def resolve_topic(template: str, *, camera_id=None, rule_key=None, site: str | None = None) -> str:
    """支持 {env}/{cameraId}/{ruleKey}/{site} 占位；相对路径自动加前缀。"""
    tpl = (template or "").strip()
    if not tpl:
        return ""
    env = topic_prefix().split("/")[-1] if "/" in topic_prefix() else "dev"
    # 若 prefix 本身是 tigerpro/dev，env=dev
    parts = topic_prefix().split("/")
    env = parts[1] if len(parts) >= 2 else parts[0]
    site_v = (site or _cfg("MQTT_SITE", "default") or "default").strip()
    mapping = {
        "env": env,
        "cameraId": str(camera_id if camera_id is not None else ""),
        "camera_id": str(camera_id if camera_id is not None else ""),
        "ruleKey": str(rule_key or "unknown"),
        "rule_key": str(rule_key or "unknown"),
        "site": site_v,
    }
    out = tpl
    for k, v in mapping.items():
        out = out.replace("{" + k + "}", v)
    if not out.startswith(topic_prefix()) and not out.startswith("tigerpro/"):
        out = f"{topic_prefix()}/{out.lstrip('/')}"
    return out


def _make_client():
    from paho.mqtt import client as mqtt_client

    prefix = _cfg("MQTT_CLIENT_ID_PREFIX", "tigerpro-backend") or "tigerpro-backend"
    client_id = f"{prefix}-{random.randint(0, 99999)}"
    try:
        # paho-mqtt 2.x
        client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
    except (TypeError, AttributeError):
        client = mqtt_client.Client(client_id=client_id)

    user = _cfg("MQTT_USERNAME", "")
    password = _cfg("MQTT_PASSWORD", "")
    if user:
        client.username_pw_set(user, password or None)

    tls_on = (_cfg("MQTT_TLS", "0") or "0").strip() in ("1", "true", "True", "yes")
    if tls_on:
        ca = (_cfg("MQTT_CA_CERTS", "") or "").strip() or None
        if ca and not os.path.isabs(ca):
            try:
                from config import Config

                ca = os.path.join(Config.BASE_DIR, ca)
            except Exception:  # noqa: BLE001
                ca = os.path.abspath(ca)
        if ca and not os.path.isfile(ca):
            raise FileNotFoundError(f"MQTT_CA_CERTS not found: {ca}")
        try:
            client.tls_set(ca_certs=ca)
        except Exception as exc:  # noqa: BLE001
            log.warning("mqtt tls_set failed: %s", exc)
            raise

    def _on_connect(client, userdata, flags, reason_code, properties=None):
        global _connected
        rc = reason_code
        try:
            ok = int(getattr(rc, "value", rc)) == 0
        except Exception:  # noqa: BLE001
            ok = rc == 0
        _connected = bool(ok)
        if ok:
            log.info("mqtt connected to %s:%s", _cfg("MQTT_BROKER", ""), _cfg("MQTT_PORT", ""))
        else:
            log.warning("mqtt connect rc=%s", rc)

    try:
        client.on_connect = _on_connect
    except Exception:  # noqa: BLE001
        pass

    broker = _cfg("MQTT_BROKER", "127.0.0.1")
    port = int(_cfg("MQTT_PORT", "1883") or 1883)
    client.connect(broker, port, keepalive=60)
    client.loop_start()
    return client


def get_client(force: bool = False):
    """懒连接单例；MQTT 未启用返回 None。"""
    global _client, _connected, _disabled_logged
    if not mqtt_enabled():
        if not _disabled_logged:
            log.info("mqtt disabled (MQTT_ENABLED=0)")
            _disabled_logged = True
        return None
    with _lock:
        if _client is not None and not force:
            return _client
        try:
            _client = _make_client()
            # 短暂等待 on_connect
            for _ in range(20):
                if _connected:
                    break
                time.sleep(0.05)
            return _client
        except Exception as exc:  # noqa: BLE001
            log.warning("mqtt connect failed: %s", exc)
            _client = None
            _connected = False
            return None


def publish_event(
    topic: str,
    payload: dict | Any,
    *,
    qos: int = 1,
    retain: bool = False,
    retries: int = 2,
) -> bool:
    """同步发布 JSON；失败重试。未启用或无 client 返回 False。"""
    topic = (topic or "").strip()
    if not topic:
        return False
    client = get_client()
    if client is None:
        return False
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    last_err = None
    for attempt in range(max(1, int(retries) + 1)):
        try:
            info = client.publish(topic, raw, qos=int(qos), retain=bool(retain))
            # wait for qos1 mid completion briefly
            try:
                info.wait_for_publish(timeout=3.0)
            except Exception:  # noqa: BLE001
                pass
            rc = getattr(info, "rc", 0)
            if rc == 0:
                return True
            last_err = f"rc={rc}"
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            get_client(force=True)
        time.sleep(0.15 * (attempt + 1))
    log.warning("mqtt publish %s failed: %s", topic, last_err)
    return False


def publish_event_async(
    topic: str,
    payload: dict | Any,
    *,
    qos: int = 1,
    retain: bool = False,
    retries: int = 2,
    on_done: Callable[[bool], None] | None = None,
) -> bool:
    """异步发布；立即返回 True 表示已调度（含 MQTT 关闭时的 no-op 调度）。"""
    topic = (topic or "").strip()
    if not topic:
        return False

    def _run():
        ok = False
        try:
            if not mqtt_enabled():
                ok = False
            else:
                ok = publish_event(topic, payload, qos=qos, retain=retain, retries=retries)
        finally:
            if callable(on_done):
                try:
                    on_done(ok)
                except Exception:  # noqa: BLE001
                    pass

    threading.Thread(target=_run, daemon=True, name="mqtt-publish").start()
    return True


def alert_payload_from_event(ev: dict) -> dict:
    """对齐 docs/emqx-mqtt-usage-scenarios.md 告警 Payload。"""
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
    return {
        "eventId": ev.get("eventId"),
        "type": ev.get("type") or "alert.fired",
        "ruleKey": ev.get("ruleKey") or payload.get("ruleKey"),
        "ruleName": payload.get("ruleName") or detail.get("ruleName"),
        "cameraId": ev.get("cameraId"),
        "source": f"camera:{ev.get('cameraId')}" if ev.get("cameraId") is not None else None,
        "score": ev.get("score") if ev.get("score") is not None else detail.get("score"),
        "suggestion": payload.get("suggestion") or detail.get("suggestion"),
        "ts": ev.get("ts"),
        "snapshotUrl": ev.get("snapshotUrl"),
        "pipelineId": ev.get("pipelineId"),
        "runId": ev.get("runId"),
        "payload": payload,
    }
