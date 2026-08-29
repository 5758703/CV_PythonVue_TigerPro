"""Phase 3：MTMC 复合节点 / 车辆模板 / phase 校验。"""
from __future__ import annotations

import pytest

from services.pipeline_schema import (
    build_template,
    dag_required_phase,
    template_mtmc_composite,
    template_vehicle_pass,
    validate_dag,
)
from services.pipeline_mtmc import cross_event_to_envelope


def test_reject_mtmc_in_phase2():
    dag = template_mtmc_composite(camera_ids=[1, 2])
    with pytest.raises(ValueError, match="Phase2"):
        validate_dag(dag, phase=2)


def test_mtmc_template_phase3():
    dag = template_mtmc_composite(camera_ids=[3, 5])
    norm = validate_dag(dag, phase=3)
    assert norm["mode"] == "mtmc"
    assert "n_mtmc" in norm["mtmcIds"]
    assert norm["cameraId"] == 3
    assert set(norm["cameraIds"]) == {3, 5}
    assert dag_required_phase(dag) == 3


def test_mtmc_rejects_mixed_classic():
    dag = template_mtmc_composite()
    dag["nodes"].append({
        "id": "n_src",
        "type": "source.rtsp",
        "config": {"cameraId": 1},
    })
    with pytest.raises(ValueError, match="混用"):
        validate_dag(dag, phase=3)


def test_vehicle_template():
    dag = template_vehicle_pass(camera_id=7)
    # mqtt → phase 2+
    phase = max(2, dag_required_phase(dag))
    norm = validate_dag(dag, phase=phase)
    assert norm["cameraId"] == 7
    assert "n_mqtt" in norm["mqttIds"]


def test_build_mtmc_and_vehicle_ids():
    assert build_template("mtmc", cameraIds="4,8")["id"] == "tpl_mtmc_composite"
    assert build_template("vehicle")["id"] == "tpl_vehicle_pass"


def test_cross_event_envelope():
    env = cross_event_to_envelope(
        {"fromCameraId": 1, "toCameraId": 2, "globalId": "g1", "score": 0.7},
        pipeline_id="9",
        run_id="plrun_x",
    )
    assert env["type"] == "mtmc.cross_camera"
    assert env["ruleKey"] == "mtmc-cross"
    assert env["cameraId"] == 2
