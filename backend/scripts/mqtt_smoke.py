"""One-shot EMQX connect + publish smoke test. Run from backend/: python scripts/mqtt_smoke.py"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from config import Config  # noqa: E402
from services import mqtt_bus  # noqa: E402


def main() -> int:
    print("ENABLED", Config.MQTT_ENABLED)
    print("BROKER", Config.MQTT_BROKER, Config.MQTT_PORT, "TLS", Config.MQTT_TLS)
    print("CA", Config.MQTT_CA_CERTS, "exists", os.path.isfile(Config.MQTT_CA_CERTS or ""))
    if not Config.MQTT_ENABLED:
        print("FAIL: MQTT_ENABLED=0")
        return 1

    mqtt_bus._client = None
    mqtt_bus._connected = False
    mqtt_bus._disabled_logged = False
    client = mqtt_bus.get_client(force=True)
    for _ in range(50):
        if mqtt_bus._connected:
            break
        time.sleep(0.1)
    print("connected", mqtt_bus._connected, "client", bool(client))
    if not mqtt_bus._connected:
        print("FAIL: not connected")
        return 2

    topic = mqtt_bus.resolve_topic(
        "alerts/{site}/{ruleKey}",
        camera_id=1,
        rule_key="conn-test",
        site="default",
    )
    ok = mqtt_bus.publish_event(
        topic,
        {
            "eventId": "evt_conn_test",
            "type": "alert.fired",
            "ruleKey": "conn-test",
            "cameraId": 1,
            "ts": "2026-08-29T00:00:00Z",
            "note": "tigerpro emqx smoke",
        },
        qos=1,
        retries=1,
    )
    print("publish", ok, "topic", topic)
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
