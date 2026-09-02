from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from flask import Flask

import person_reid_dnn
from extensions import db
from models.ai_model import AiModel
from models.mtmc import MtmcAssociationEdge
from routes import mtmc as mtmc_routes
from services import mtmc_engine, strong_reid
from services.mtmc_associator import MtmcAssociator
from services.mtmc_engine import CamState, MtmcConfig, MtmcSession, _process_frame
from services.mtmc_local_track import Tracklet
from services.mtmc_tracklet import TrackletBuilder


def _frame() -> np.ndarray:
    return np.full((120, 200, 3), 127, dtype=np.uint8)


def _person() -> dict:
    return {
        "bbox": [40.0, 10.0, 110.0, 115.0],
        "confidence": 0.94,
        "classId": 0,
        "className": "person",
    }


def _vehicle() -> dict:
    return {
        "bbox": [30.0, 25.0, 170.0, 110.0],
        "confidence": 0.96,
        "classId": 2,
        "className": "car",
    }


class _RawFallbackTracker:
    def update(self, _raw, frame=None):
        return []

    def pop_removed_track_ids(self):
        return set()


class _OneVehicleTracker:
    def update(self, _raw, frame=None):
        return [Tracklet(
            track_id=8,
            bbox=[30.0, 25.0, 170.0, 110.0],
            class_name="car",
            conf=0.96,
            is_new=True,
            trail=[(100.0, 67.5)],
        )]

    def pop_removed_track_ids(self):
        return set()


def _configured_model(model_key: str, version: str, provider: str = "catalog-provider") -> dict:
    return {
        "configured": True,
        "assetPresent": True,
        "configuredModelKey": model_key,
        "configuredModelVersion": version,
        "configuredProvider": provider,
        "selectedModelKey": None,
        "modelVersion": None,
        "backend": None,
        "provider": None,
        "inputSize": None,
        "embeddingDim": None,
        "ready": None,
        "runtimeState": "pending",
        "degraded": False,
        "degradedReason": None,
    }


def _runtime_session(cfg: MtmcConfig, *, camera_id: int = 1) -> tuple[MtmcSession, CamState]:
    session = MtmcSession("runtime-review", cfg, MtmcAssociator())
    cam_state = CamState(camera_id=camera_id)
    session.cams[camera_id] = cam_state
    mtmc_engine._initialize_runtime_status(session)
    return session, cam_state


def test_asset_presence_starts_pending_until_real_execution(tmp_path):
    weight = tmp_path / "person.pt"
    weight.write_bytes(b"asset")
    model = SimpleNamespace(model_key="person-v1", version="catalog-v1", library="ultralytics")

    status = mtmc_routes._model_runtime_descriptor(model, str(weight))

    assert status["configured"] is True
    assert status["assetPresent"] is True
    assert status["configuredModelKey"] == "person-v1"
    assert status["selectedModelKey"] is None
    assert status["ready"] is None
    assert status["runtimeState"] == "pending"


def test_route_ocr_callable_retains_configured_assets_without_claiming_ready(tmp_path):
    app = Flask("mtmc-ocr-config")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'ocr-config.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=str(tmp_path),
    )
    db.init_app(app)
    (tmp_path / "ocr-det").mkdir()
    (tmp_path / "ocr-rec").mkdir()
    with app.app_context():
        db.create_all()
        det = AiModel(model_name="OCR det", model_key="ocr-det-v6", version="det-v6", file_path="ocr-det")
        rec = AiModel(model_name="OCR rec", model_key="ocr-rec-v6", version="rec-v6", file_path="ocr-rec")
        db.session.add_all([det, rec])
        db.session.commit()

        ocr_fn = mtmc_routes._build_ocr_fn_from_ids(det.id, rec.id)
        status = ocr_fn._mtmc_runtime

        assert status["configured"] is True
        assert status["assetPresent"] is True
        assert status["configuredModelKey"] == "ocr-det-v6+ocr-rec-v6"
        assert status["configuredModelVersion"] == "det-v6+rec-v6"
        assert status["ready"] is None
        assert status["runtimeState"] == "pending"
        db.session.remove()
        db.drop_all()


def test_detector_becomes_ready_only_after_process_frame_executes_it():
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=True, enable_vehicle=False,
        det_person_path="person.pt", detect_only=True,
        selected_models={"personDetection": _configured_model("person-v1", "v1")},
    )
    session, cam_state = _runtime_session(cfg)
    assert session.to_dict()["runtime"]["models"]["personDetection"]["ready"] is None

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([_person()], [])):
        with patch("services.mtmc_engine._publish_overlay"):
            _process_frame(session, cam_state, _frame(), {}, now=10.0)

    actual = session.to_dict()["runtime"]["models"]["personDetection"]
    assert actual["ready"] is True
    assert actual["runtimeState"] == "ready"
    assert actual["backend"] == "yolo"
    assert actual["byCamera"]["1"]["ready"] is True


def test_detector_exception_is_visible_in_runtime_status():
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=True, enable_vehicle=False,
        det_person_path="person.pt", detect_only=True,
        selected_models={"personDetection": _configured_model("person-v1", "v1")},
    )
    session, cam_state = _runtime_session(cfg)

    with patch("services.mtmc_engine._detect_person_vehicle", side_effect=RuntimeError("CUDA OOM")):
        with pytest.raises(RuntimeError, match="CUDA OOM"):
            _process_frame(session, cam_state, _frame(), {}, now=10.0)

    actual = session.to_dict()["runtime"]["models"]["personDetection"]
    assert actual["ready"] is False
    assert actual["runtimeState"] == "failed"
    assert "CUDA OOM" in actual["degradedReason"]


def test_separate_detector_failure_does_not_erase_successful_model_runtime():
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=True, enable_vehicle=True,
        det_person_path="person.pt", det_vehicle_path="vehicle.pt", detect_only=True,
        selected_models={
            "personDetection": _configured_model("person-v1", "p1"),
            "vehicleDetection": _configured_model("vehicle-v1", "v1"),
        },
    )
    session, cam_state = _runtime_session(cfg)

    with patch("services.mtmc_engine._detect", side_effect=[[], RuntimeError("vehicle CUDA OOM")]):
        with pytest.raises(RuntimeError, match="vehicle CUDA OOM"):
            _process_frame(session, cam_state, _frame(), {}, now=10.0)

    models = session.to_dict()["runtime"]["models"]
    assert models["personDetection"]["ready"] is True
    assert models["personDetection"]["degraded"] is False
    assert models["vehicleDetection"]["ready"] is False
    assert "vehicle CUDA OOM" in models["vehicleDetection"]["degradedReason"]


def test_tracker_fallback_reports_requested_and_actual_backend(monkeypatch):
    cfg = MtmcConfig(camera_ids=[1], enable_person=False, enable_vehicle=False, local_track_backend="bytetrack")
    session, cam_state = _runtime_session(cfg)
    monkeypatch.setattr("services.mtmc_local_track.bytetrack_available", lambda: False)

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([], [])):
        with patch("services.mtmc_engine._publish_overlay"):
            _process_frame(session, cam_state, _frame(), {}, now=10.0)

    actual = session.to_dict()["runtime"]["models"]["localTracker"]
    assert actual["configuredModelKey"] == "bytetrack"
    assert actual["selectedModelKey"] == "iou"
    assert actual["ready"] is True
    assert actual["degraded"] is True
    assert "fallback" in actual["degradedReason"]


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
        "backend": "youtu",
        "activeBackend": "youtu",
        "bestModelKey": "opencv-person-reid-youtu",
        "associationModelKey": "opencv-person-reid-youtu",
        "availableModelSpaces": ["opencv-person-reid-youtu"],
        "modelVersionsBySpace": {"opencv-person-reid-youtu": "youtu-v3"},
        "inputSize": [128, 256],
        "backends": {
            "strong": {
                "ready": False, "error": "shape mismatch",
                "backend": "strong-onnx", "provider": "onnxruntime-cpu",
            },
            "youtu": {
                "ready": True, "modelKey": "opencv-person-reid-youtu",
                "modelVersion": "youtu-v3", "dim": 3,
                "backend": "youtu-reid-opencv", "provider": "opencv-dnn-cpu",
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
    assert actual["backend"] == "youtu-reid-opencv"
    assert actual["provider"] == "opencv-dnn-cpu"
    assert actual["inputSize"] == [128, 256]
    assert actual["embeddingDim"] == 3
    assert actual["degraded"] is True
    assert actual["degradedReason"] == "strong: shape mismatch"
    assert actual["byCamera"]["1"]["selectedModelKey"] == "opencv-person-reid-youtu"
    assert runtime["budgets"]["personReid"] == {
        "limitPerFrame": 1,
        "considered": 1,
        "eligible": 1,
        "queued": 1,
        "consumed": 1,
        "budgetSkipped": 0,
        "samplerSkipped": 0,
        "lastFrameByCamera": {"1": {
            "considered": 1,
            "eligible": 1,
            "queued": 1,
            "consumed": 1,
            "budgetSkipped": 0,
            "samplerSkipped": 0,
        }},
    }


def test_real_extractor_metadata_keeps_backend_and_provider_per_model(monkeypatch):
    youtu_meta = {
        "backend": "youtu-reid-opencv",
        "provider": "opencv-dnn-cpu",
        "onnx": "person_reid_youtu_2021nov.onnx",
        "modelVersion": "person_reid_youtu_2021nov.onnx",
        "inputSize": [128, 256],
        "dim": 3,
    }
    monkeypatch.setattr(strong_reid, "extract_strong", lambda *_args: (
        None,
        {
            "strong": False,
            "strongError": "shape mismatch",
            "backend": "strong-onnx",
            "provider": "onnxruntime-cpu",
        },
    ))
    monkeypatch.setattr(strong_reid, "extract_youtu", lambda *_args: (
        np.asarray([1.0, 0.0, 0.0], dtype=np.float32),
        youtu_meta,
    ))

    embeddings, meta = strong_reid.extract_person_embeddings(
        _frame(), youtu_root="youtu", strong_root="strong",
    )
    runtime = mtmc_engine._person_reid_runtime_observation(
        MtmcConfig(camera_ids=[1], youtu_root="youtu", strong_reid_root="strong"),
        meta,
        embeddings,
    )

    assert meta["backends"]["strong"]["backend"] == "strong-onnx"
    assert meta["backends"]["strong"]["provider"] == "onnxruntime-cpu"
    assert meta["backends"]["youtu"]["backend"] == "youtu-reid-opencv"
    assert meta["backends"]["youtu"]["provider"] == "opencv-dnn-cpu"
    assert runtime["backend"] == "youtu-reid-opencv"
    assert runtime["provider"] == "opencv-dnn-cpu"


def test_youtu_extractor_reports_its_actual_execution_provider(monkeypatch):
    monkeypatch.setattr(person_reid_dnn, "resolve_onnx", lambda *_args, **_kwargs: "youtu.onnx")
    monkeypatch.setattr(
        person_reid_dnn,
        "preprocess_crop",
        lambda _image: np.zeros((1, 3, 256, 128), dtype=np.float32),
    )
    monkeypatch.setattr(person_reid_dnn, "_get_opencv_net", lambda _path: object())
    monkeypatch.setattr(
        person_reid_dnn,
        "_forward_opencv",
        lambda _net, _blob: np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32),
    )

    _embedding, meta = person_reid_dnn.extract_feature("youtu", _frame())

    assert meta["backend"] == "youtu-reid-opencv"
    assert meta["provider"] == "opencv-dnn-cpu"


def test_multi_camera_runtime_never_pairs_last_camera_metadata_with_mixed_models():
    session = MtmcSession("mixed-runtime", MtmcConfig(camera_ids=[1, 2]), MtmcAssociator())
    first = {
        "selectedModelKey": "osnet-x1-0",
        "modelVersion": "osnet-a.onnx",
        "ready": True,
        "runtimeState": "ready",
        "backend": "strong-onnx",
        "provider": "onnxruntime-cuda",
        "inputSize": [128, 256],
        "embeddingDim": 512,
        "degraded": False,
        "degradedReason": None,
    }
    second = {
        "selectedModelKey": "opencv-person-reid-youtu",
        "modelVersion": "youtu-b.onnx",
        "ready": True,
        "runtimeState": "ready",
        "backend": "youtu-reid-opencv",
        "provider": "opencv-dnn-cpu",
        "inputSize": [128, 256],
        "embeddingDim": 768,
        "degraded": True,
        "degradedReason": "strong unavailable",
    }

    mtmc_engine._record_runtime_model(session, "personReid", 1, first)
    mtmc_engine._record_runtime_model(session, "personReid", 2, second)
    actual = session.to_dict()["runtime"]["models"]["personReid"]

    assert actual["mixed"] is True
    assert actual["selectedModelKey"] is None
    assert actual["modelVersion"] is None
    assert actual["backend"] is None
    assert actual["provider"] is None
    assert actual["inputSize"] == [128, 256]
    assert actual["embeddingDim"] is None
    assert actual["selectedModelKeys"] == ["opencv-person-reid-youtu", "osnet-x1-0"]
    assert actual["providers"] == ["onnxruntime-cuda", "opencv-dnn-cpu"]
    assert actual["byCamera"] == {"1": first, "2": second}


def test_budget_zero_counts_only_eligible_tracks_without_reserving_sampler():
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=True, enable_vehicle=False,
        det_person_path="person.pt", youtu_root="youtu", person_reid_budget=0,
        sample_fps=100,
    )
    session, cam_state = _runtime_session(cfg)
    cam_state.tracker_person = _RawFallbackTracker()
    cam_state.tracker_vehicle = _RawFallbackTracker()

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([_person()], [])):
        with patch("services.mtmc_engine._publish_overlay"):
            _process_frame(session, cam_state, _frame(), {}, now=10.0)

    budget = session.to_dict()["runtime"]["budgets"]["personReid"]
    builder = cam_state.person_builders[800001]
    assert budget == {
        "limitPerFrame": 0,
        "considered": 1,
        "eligible": 1,
        "queued": 0,
        "consumed": 0,
        "budgetSkipped": 1,
        "samplerSkipped": 0,
        "lastFrameByCamera": {"1": {
            "considered": 1,
            "eligible": 1,
            "queued": 0,
            "consumed": 0,
            "budgetSkipped": 1,
            "samplerSkipped": 0,
        }},
    }
    assert builder.last_embedding_sample_at is None


def test_sampler_rejection_is_counted_without_queue_or_budget_skip():
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=True, enable_vehicle=False,
        det_person_path="person.pt", youtu_root="youtu", person_reid_budget=1,
        sample_fps=100,
    )
    session, cam_state = _runtime_session(cfg)
    cam_state.tracker_person = _RawFallbackTracker()
    cam_state.tracker_vehicle = _RawFallbackTracker()
    meta = {
        "activeBackend": "youtu",
        "associationModelKey": "opencv-person-reid-youtu",
        "modelVersionsBySpace": {"opencv-person-reid-youtu": "youtu.onnx"},
        "backends": {"youtu": {
            "ready": True,
            "backend": "youtu-reid-opencv",
            "provider": "opencv-dnn-cpu",
        }},
    }
    spaces = {"opencv-person-reid-youtu": np.asarray([1.0, 0.0], dtype=np.float32)}

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([_person()], [])):
        with patch("services.strong_reid.extract_person_embeddings", return_value=(spaces, meta)):
            with patch("services.mtmc_engine._match_gallery", return_value={"matched": False, "ready": True}):
                with patch("services.mtmc_engine._publish_overlay"):
                    _process_frame(session, cam_state, _frame(), {}, now=10.0)
                    _process_frame(session, cam_state, _frame(), {}, now=10.02)

    budget = session.to_dict()["runtime"]["budgets"]["personReid"]
    assert budget["considered"] == 2
    assert budget["eligible"] == 1
    assert budget["queued"] == 1
    assert budget["consumed"] == 1
    assert budget["budgetSkipped"] == 0
    assert budget["samplerSkipped"] == 1


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


def test_plate_detector_and_ocr_report_real_success_from_vehicle_frame():
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=False, enable_vehicle=True,
        det_vehicle_path="vehicle.pt", vehicle_reid_root="vehicle-reid",
        plate_model_path="plate.pt", ocr_fn=lambda _value: {},
        vehicle_reid_budget=1, plate_budget=1, sample_fps=100,
        selected_models={
            "vehicleDetection": _configured_model("vehicle-det", "det-v1"),
            "vehicleReid": _configured_model("vehicle-reid", "reid-v1"),
            "plateDetection": _configured_model("plate-det", "plate-v1"),
        },
    )
    session, cam_state = _runtime_session(cfg)
    cam_state.tracker_person = _RawFallbackTracker()
    cam_state.tracker_vehicle = _OneVehicleTracker()

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([], [_vehicle()])):
        with patch("services.vehicle_reid_feat.extract_vehicle_embedding", return_value=(
            np.asarray([1.0, 0.0], dtype=np.float32),
            {
                "backend": "vehicle-onnx", "provider": "onnxruntime-cpu",
                "onnx": "vehicle.onnx", "inputSize": "256x384", "dim": 2,
            },
        )):
            with patch("services.vehicle_track._plate_candidates", return_value=[(
                [50.0, 70.0, 145.0, 100.0], "plate-model", 0.9, None,
            )]):
                with patch("services.vehicle_track._ocr_plate", return_value={
                    "text": "粤A12345", "score": 0.96,
                }):
                    with patch("services.mtmc_engine._publish_overlay"):
                        _process_frame(session, cam_state, _frame(), {}, now=10.0)

    models = session.to_dict()["runtime"]["models"]
    assert models["vehicleDetection"]["ready"] is True
    assert models["vehicleReid"]["ready"] is True
    assert models["plateDetection"]["ready"] is True
    assert models["plateOcr"]["ready"] is True
    assert models["plateOcr"]["backend"] == "paddle-ocr"


def test_vehicle_reid_exception_records_failed_runtime_before_propagating():
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=False, enable_vehicle=True,
        det_vehicle_path="vehicle.pt", vehicle_reid_root="vehicle-reid",
        vehicle_reid_budget=1, sample_fps=100,
        selected_models={"vehicleReid": _configured_model("vehicle-reid", "reid-v1")},
    )
    session, cam_state = _runtime_session(cfg)
    cam_state.tracker_person = _RawFallbackTracker()
    cam_state.tracker_vehicle = _OneVehicleTracker()

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([], [_vehicle()])):
        with patch(
            "services.vehicle_reid_feat.extract_vehicle_embedding",
            side_effect=RuntimeError("vehicle ORT crash"),
        ):
            with patch("services.mtmc_engine._publish_overlay"):
                with pytest.raises(RuntimeError, match="vehicle ORT crash"):
                    _process_frame(session, cam_state, _frame(), {}, now=10.0)

    actual = session.to_dict()["runtime"]["models"]["vehicleReid"]
    assert actual["ready"] is False
    assert actual["runtimeState"] == "failed"
    assert "vehicle ORT crash" in actual["degradedReason"]


def test_plate_ocr_exception_is_not_silently_reported_ready():
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=False, enable_vehicle=True,
        det_vehicle_path="vehicle.pt", vehicle_reid_root="vehicle-reid",
        plate_model_path="plate.pt", ocr_fn=lambda _value: {},
        vehicle_reid_budget=1, plate_budget=1, sample_fps=100,
        selected_models={"plateDetection": _configured_model("plate-det", "plate-v1")},
    )
    session, cam_state = _runtime_session(cfg)
    cam_state.tracker_person = _RawFallbackTracker()
    cam_state.tracker_vehicle = _OneVehicleTracker()

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([], [_vehicle()])):
        with patch("services.vehicle_reid_feat.extract_vehicle_embedding", return_value=(
            np.asarray([1.0, 0.0], dtype=np.float32),
            {"backend": "vehicle-onnx", "onnx": "vehicle.onnx", "dim": 2},
        )):
            with patch("services.vehicle_track._plate_candidates", return_value=[(
                [50.0, 70.0, 145.0, 100.0], "plate-model", 0.9, None,
            )]):
                with patch("services.vehicle_track._ocr_plate", side_effect=RuntimeError("OCR crash")):
                    with patch("services.mtmc_engine._publish_overlay"):
                        _process_frame(session, cam_state, _frame(), {}, now=10.0)

    models = session.to_dict()["runtime"]["models"]
    assert models["plateDetection"]["ready"] is True
    assert models["plateOcr"]["ready"] is False
    assert models["plateOcr"]["runtimeState"] == "failed"
    assert "OCR crash" in models["plateOcr"]["degradedReason"]


def test_plate_heuristic_fallback_is_explicitly_degraded():
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=False, enable_vehicle=True,
        det_vehicle_path="vehicle.pt", vehicle_reid_root="vehicle-reid",
        plate_model_path=None, ocr_fn=lambda _value: {},
        vehicle_reid_budget=1, plate_budget=1, sample_fps=100,
    )
    session, cam_state = _runtime_session(cfg)
    cam_state.tracker_person = _RawFallbackTracker()
    cam_state.tracker_vehicle = _OneVehicleTracker()

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([], [_vehicle()])):
        with patch("services.vehicle_reid_feat.extract_vehicle_embedding", return_value=(
            np.asarray([1.0, 0.0], dtype=np.float32),
            {"backend": "vehicle-onnx", "onnx": "vehicle.onnx", "dim": 2},
        )):
            with patch("services.vehicle_track._plate_candidates", return_value=[(
                [50.0, 70.0, 145.0, 100.0], "heuristic", 0.9, None,
            )]):
                with patch("services.vehicle_track._ocr_plate", return_value={"text": "粤A12345", "score": 0.9}):
                    with patch("services.mtmc_engine._publish_overlay"):
                        _process_frame(session, cam_state, _frame(), {}, now=10.0)

    plate = session.to_dict()["runtime"]["models"]["plateDetection"]
    assert plate["selectedModelKey"] == "plate-roi-heuristic"
    assert plate["ready"] is True
    assert plate["degraded"] is True
    assert "fallback" in plate["degradedReason"]


def test_long_term_match_margin_survives_real_persistence_and_route_format(tmp_path):
    app = Flask("mtmc-margin")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'margin.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    assoc = MtmcAssociator(
        appear_thresh=0.3,
        vehicle_appear_thresh=0.3,
        confirm_thresh=0.3,
        candidate_thresh=0.2,
        min_match_margin=0.01,
        topology={(1, 3): (0.0, 20.0), (2, 3): (0.0, 20.0)},
    )
    assoc.associate(
        object_type="vehicle", camera_id=1, local_track_id=1,
        embedding=np.asarray([1.0, 0.0], dtype=np.float32), now=1.0,
    )
    assoc.associate(
        object_type="vehicle", camera_id=2, local_track_id=2,
        embedding=np.asarray([0.6, 0.8], dtype=np.float32), now=1.0,
    )
    assoc.release_local("vehicle", 1, [1], now=1.1)
    assoc.release_local("vehicle", 2, [2], now=1.1)
    result = assoc.associate_with_evidence(
        object_type="vehicle", camera_id=3, local_track_id=3,
        embedding=np.asarray([0.98, 0.2], dtype=np.float32), now=3.0,
    )
    assert result.evidence.decision == "long_term"
    assert result.evidence.extra.get("matchMargin") is not None

    session = MtmcSession(
        "margin-session", MtmcConfig(camera_ids=[1, 2, 3], persist_events=True), assoc, app=app,
    )
    builder = TrackletBuilder.create(
        session_id="margin-session", camera_id=3, object_type="vehicle", local_track_id=3, now=3.0,
    )
    builder.add_observation(
        bbox=[0.0, 0.0, 20.0, 20.0], conf=0.9, frame_h=100, frame_w=100,
        embedding=np.asarray([0.98, 0.2], dtype=np.float32), now=3.0,
    )
    with app.app_context():
        db.create_all()
        mtmc_engine._record_association(
            session, builder, result.global_track, prev_global_id=None, evidence=result.evidence,
        )
        persisted = MtmcAssociationEdge.query.one()
        public = mtmc_routes._association_public_row(persisted)
        assert public["margin"] is not None
        assert public["margin"] > 0
        assert public["margin"] == pytest.approx(persisted.to_dict()["evidence"]["matchMargin"])
        db.session.remove()
        db.drop_all()
