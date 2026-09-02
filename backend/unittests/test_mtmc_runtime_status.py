from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from routes import mtmc as mtmc_routes
from services import mtmc_engine
from services.mtmc_associator import MtmcAssociator
from services.mtmc_engine import CamState, MtmcConfig, MtmcSession, _process_frame


def _frame() -> np.ndarray:
    return np.full((120, 200, 3), 127, dtype=np.uint8)


def _person() -> dict:
    return {
        "bbox": [40.0, 10.0, 110.0, 115.0],
        "confidence": 0.94,
        "classId": 0,
        "className": "person",
    }


def test_session_runtime_exposes_effective_thresholds_and_directed_topology():
    cfg = MtmcConfig(
        camera_ids=[1, 2], appear_thresh=0.48, vehicle_appear_thresh=0.66,
        confirm_thresh=0.57, candidate_thresh=0.39,
    )
    edges = [{
        "fromCameraId": 1,
        "toCameraId": 2,
        "minTransitSec": 3,
        "maxTransitSec": 20,
        "weight": 0.75,
        "edgeType": "non_overlap",
    }]

    session = mtmc_engine.start_session(
        cfg, cameras=[], upload_folder="", topology_edges=edges,
    )
    try:
        runtime = session.to_dict()["runtime"]
    finally:
        mtmc_engine._sessions.pop(session.session_id, None)

    assert runtime.get("effectiveThresholds") == {
        "appearance": 0.48,
        "vehicleAppearance": 0.66,
        "confirm": 0.57,
        "candidate": 0.39,
        "minMatchMargin": 0.04,
    }
    assert runtime.get("topologyPolicy") == {
        "directed": True,
        "authoritative": True,
        "missingEdgePolicy": "reject",
        "edges": [{
            "fromCameraId": 1,
            "toCameraId": 2,
            "minTransitSec": 3.0,
            "maxTransitSec": 20.0,
            "weight": 0.75,
            "edgeType": "non_overlap",
        }],
    }


def test_degraded_strong_reid_reports_actual_youtu_runtime_and_budget_counters():
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=True, enable_vehicle=False,
        det_person_path="person.pt", strong_reid_root="strong", youtu_root="youtu",
        person_reid_budget=1, sample_fps=10,
    )
    cfg.selected_models = {
        "personReidStrong": {
            "selectedModelKey": "osnet-x1-0", "modelVersion": "osnet-v7",
            "provider": "onnxruntime", "ready": True,
        },
        "personReidFallback": {
            "selectedModelKey": "opencv-person-reid-youtu", "modelVersion": "youtu-v3",
            "provider": "opencv", "ready": True,
        },
    }
    session = MtmcSession("runtime-model", cfg, MtmcAssociator())
    cam_state = CamState(camera_id=1)
    session.cams[1] = cam_state
    meta = {
        "backend": "youtu-reid-opencv",
        "activeBackend": "youtu",
        "bestModelKey": "opencv-person-reid-youtu",
        "associationModelKey": "opencv-person-reid-youtu",
        "availableModelSpaces": ["opencv-person-reid-youtu"],
        "modelVersionsBySpace": {"opencv-person-reid-youtu": "youtu-v3"},
        "inputSize": [128, 256],
        "backends": {
            "strong": {"ready": False, "error": "shape mismatch"},
            "youtu": {
                "ready": True, "modelKey": "opencv-person-reid-youtu",
                "modelVersion": "youtu-v3", "dim": 3,
            },
        },
    }
    spaces = {"opencv-person-reid-youtu": np.asarray([1.0, 0.0, 0.0], dtype=np.float32)}

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([_person()], [])):
        with patch("services.strong_reid.extract_person_embeddings", return_value=(spaces, meta)):
            with patch("services.mtmc_engine._match_gallery", return_value={"matched": False, "ready": True}):
                _process_frame(session, cam_state, _frame(), {}, now=10.0)

    runtime = session.to_dict()["runtime"]
    actual = (runtime.get("models") or {}).get("personReid")
    assert actual is not None
    assert actual["selectedModelKey"] == "opencv-person-reid-youtu"
    assert actual["modelVersion"] == "youtu-v3"
    assert actual["ready"] is True
    assert actual["provider"] == "youtu-reid-opencv"
    assert actual["inputSize"] == [128, 256]
    assert actual["embeddingDim"] == 3
    assert actual["degraded"] is True
    assert actual["degradedReason"] == "strong: shape mismatch"
    assert actual["byCamera"]["1"]["selectedModelKey"] == "opencv-person-reid-youtu"
    assert runtime["budgets"]["personReid"] == {
        "limitPerFrame": 1,
        "queued": 1,
        "consumed": 1,
        "skipped": 0,
        "lastFrameByCamera": {"1": {"queued": 1, "consumed": 1, "skipped": 0}},
    }


def test_association_response_adds_score_breakdown_without_changing_legacy_fields():
    legacy = {
        "id": 7,
        "decision": "candidate",
        "scores": {"reid": 0.72, "topology": 0.8, "time": 0.5, "final": 0.288},
        "evidence": {"matchMargin": 0.03, "eventScore": 0.91},
    }
    row = SimpleNamespace(to_dict=lambda: legacy.copy())
    formatter = getattr(mtmc_routes, "_association_public_row", lambda value: value.to_dict())

    result = formatter(row)

    assert result["id"] == 7
    assert result["scores"] == legacy["scores"]
    assert result["evidence"] == legacy["evidence"]
    assert result["appearanceScore"] == 0.72
    assert result["topologyScore"] == 0.8
    assert result["timeScore"] == 0.5
    assert result["margin"] == 0.03
    assert result["finalScore"] == 0.288
    assert result["finalScore"] != result["evidence"]["eventScore"]


def test_runtime_does_not_guess_strong_model_input_shape_from_its_key():
    cfg = MtmcConfig(camera_ids=[1], strong_reid_root="missing-test-asset")
    meta = {
        "activeBackend": "strong",
        "associationModelKey": "osnet-x1-0",
        "modelVersionsBySpace": {"osnet-x1-0": "custom-shape-v1"},
        "backends": {"strong": {"ready": True}},
    }

    status = mtmc_engine._person_reid_runtime_observation(
        cfg, meta, {"osnet-x1-0": np.asarray([1.0, 0.0], dtype=np.float32)},
    )

    assert status["inputSize"] is None


def test_vehicle_runtime_prefers_loaded_asset_version_over_catalog_label():
    cfg = MtmcConfig(camera_ids=[1], vehicle_reid_root="vehicle-model")
    cfg.selected_models = {
        "vehicleReid": {
            "selectedModelKey": "transreid-vehicle",
            "modelVersion": "catalog-v1",
        },
    }

    status = mtmc_engine._vehicle_reid_runtime_observation(
        cfg,
        {
            "backend": "vehicle-onnx",
            "onnx": "transreid-production-v7.onnx",
            "inputSize": "256x384",
            "dim": 1024,
        },
        np.ones(1024, dtype=np.float32),
    )

    assert status["selectedModelKey"] == "transreid-vehicle"
    assert status["modelVersion"] == "transreid-production-v7.onnx"
    assert status["provider"] == "onnxruntime-cpu"
    assert status["inputSize"] == "256x384"
    assert status["embeddingDim"] == 1024
