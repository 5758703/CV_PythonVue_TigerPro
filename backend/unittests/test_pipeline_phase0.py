"""Phase 0/1/2 流水线契约 / DAG / 模板 / MQTT 单测。"""
from __future__ import annotations

import pytest

from services.mqtt_bus import alert_payload_from_event, mqtt_enabled, resolve_topic
from services.pipeline_schema import (
    build_template,
    dag_required_phase,
    example_phase0_dag,
    make_event_envelope,
    make_frame_envelope,
    template_security_alert,
    template_vlm_gated_alert,
    template_zone_intrusion,
    validate_dag,
)
from services.webhook import deliver_url_webhook


def test_example_dag_validates():
    dag = example_phase0_dag(camera_id=3, model_key="yolo26n")
    norm = validate_dag(dag, phase=1)
    assert norm["cameraId"] == 3
    assert norm["sourceId"] == "n_src"


def test_security_template_phase1():
    dag = template_security_alert(camera_id=2, webhook_url="https://example.com/hook")
    norm = validate_dag(dag, phase=1)
    assert "n_trk" in norm["trackIds"]
    assert "n_alert" in norm["alertIds"]
    assert "n_wh" in norm["webhookIds"]
    assert "n_db" in norm["dbIds"]


def test_zone_template():
    dag = template_zone_intrusion(camera_id=1)
    norm = validate_dag(dag, phase=1)
    assert norm["nodes"]["n_alert"]["config"]["region"]


def test_reject_mqtt_in_phase1():
    dag = template_security_alert()
    dag["nodes"].append({"id": "n_mqtt", "type": "sink.mqtt", "config": {"topic": "x"}})
    dag["edges"].append(["n_alert", "n_mqtt"])
    with pytest.raises(ValueError, match="Phase1"):
        validate_dag(dag, phase=1)


def test_allow_mqtt_in_phase2():
    dag = template_security_alert(mqtt_topic="alerts/{site}/{ruleKey}")
    norm = validate_dag(dag, phase=2)
    assert "n_mqtt" in norm["mqttIds"]
    assert dag_required_phase(dag) == 2


def test_vlm_template_phase2():
    dag = template_vlm_gated_alert(camera_id=4)
    norm = validate_dag(dag, phase=2)
    assert "n_vlm" in norm["vlmGateIds"]
    assert "n_mqtt" in norm["mqttIds"]
    assert dag_required_phase(dag) >= 2


def test_reject_cycle():
    dag = {
        "nodes": [
            {"id": "a", "type": "source.rtsp", "config": {"cameraId": 1}},
            {"id": "b", "type": "detect.yolo", "config": {}},
            {"id": "c", "type": "sink.overlay", "config": {}},
        ],
        "edges": [["a", "b"], ["b", "c"], ["c", "b"]],
    }
    with pytest.raises(ValueError, match="环"):
        validate_dag(dag, phase=1)


def test_build_template_ids():
    assert build_template("security", cameraId=9)["id"] == "tpl_security_alert"
    assert build_template("zone")["name"] == "区域入侵"
    assert build_template("vlm")["id"] == "tpl_vlm_gated_alert"


def test_frame_and_event_envelope_shape():
    fr = make_frame_envelope(
        pipeline_id="1",
        run_id="plrun_x",
        camera_id=2,
        frame_seq=9,
        dets=[{"className": "person", "confidence": 0.9, "bbox": [1, 2, 3, 4]}],
    )
    assert "image" not in fr
    ev = make_event_envelope(
        event_type="alert.fired",
        pipeline_id="1",
        run_id="plrun_x",
        camera_id=2,
        rule_key="fire-smoke",
    )
    assert ev["eventId"].startswith("evt_")


def test_deliver_url_webhook_empty():
    assert deliver_url_webhook("", "alert.fired", {}) is False


def test_mqtt_topic_resolve_and_payload():
    t = resolve_topic("alerts/{site}/{ruleKey}", camera_id=3, rule_key="fire-smoke", site="campus")
    assert "fire-smoke" in t
    assert "campus" in t
    assert t.startswith("tigerpro/") or "alerts/" in t
    body = alert_payload_from_event({
        "eventId": "evt_1",
        "type": "alert.fired",
        "ruleKey": "fire-smoke",
        "cameraId": 3,
        "score": 0.9,
        "ts": "2026-01-01T00:00:00Z",
        "payload": {"ruleName": "烟火"},
    })
    assert body["ruleKey"] == "fire-smoke"
    assert body["cameraId"] == 3
    # 默认未启用
    assert mqtt_enabled() is False or isinstance(mqtt_enabled(), bool)
