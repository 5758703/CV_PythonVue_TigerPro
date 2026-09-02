from __future__ import annotations

from unittest.mock import patch

import numpy as np

from services.mtmc_associator import MtmcAssociator
from services.mtmc_engine import CamState, MtmcConfig, MtmcSession, _process_frame
from services.mtmc_local_track import LocalTracker
from services.mtmc_tracklet import TrackletBuilder


def static_vehicle(track_id: int = 7) -> dict:
    return {
        "bbox": [20.0, 20.0, 180.0, 100.0],
        "confidence": 0.9,
        "classId": 2,
        "className": "car",
    }


def _session(*, person: bool = False, vehicle: bool = True, max_age: int = 2) -> tuple[MtmcSession, CamState]:
    cfg = MtmcConfig(
        camera_ids=[1],
        enable_person=person,
        enable_vehicle=vehicle,
        det_person_path="person.pt" if person else None,
        det_vehicle_path="vehicle.pt" if vehicle else None,
        local_track_backend="iou",
        local_track_max_age=max_age,
        sample_fps=10,
        reid_budget=0,
    )
    session = MtmcSession("lifecycle", cfg, MtmcAssociator())
    cam_state = CamState(camera_id=1)
    session.cams[1] = cam_state
    return session, cam_state


def _frame() -> np.ndarray:
    return np.full((120, 200, 3), 127, dtype=np.uint8)


def test_tracker_reports_removal_only_after_grace_expires():
    tracker = LocalTracker(max_age=1)
    assert callable(getattr(tracker, "pop_removed_track_ids", None))

    tracker.update([static_vehicle(7)])
    tracker.update([])
    assert tracker.pop_removed_track_ids() == set()
    tracker.update([])
    assert tracker.pop_removed_track_ids() == {1}
    assert tracker.pop_removed_track_ids() == set()


def test_tracklet_survives_single_frame_detector_miss():
    session, cam_state = _session(max_age=1)
    with patch("services.mtmc_engine._detect_person_vehicle", side_effect=[([], [static_vehicle(7)]), ([], [])]):
        _process_frame(session, cam_state, _frame(), {}, now=10.0)
        _process_frame(session, cam_state, _frame(), {}, now=10.25)

    assert 1 in cam_state.vehicle_builders


def test_tracklet_finalizes_after_tracker_removal():
    session, cam_state = _session(max_age=1)
    with patch("services.mtmc_engine._detect_person_vehicle", side_effect=[([], [static_vehicle(7)]), ([], []), ([], [])]):
        _process_frame(session, cam_state, _frame(), {}, now=10.0)
        _process_frame(session, cam_state, _frame(), {}, now=10.25)
        _process_frame(session, cam_state, _frame(), {}, now=10.5)

    assert 1 not in cam_state.vehicle_builders


def test_keyframe_sampler_collects_spaced_quality_and_view_improvements():
    builder = TrackletBuilder.create(
        session_id="s", camera_id=1, object_type="vehicle", local_track_id=7, now=1.0,
    )
    assert callable(getattr(builder, "should_sample_embedding", None))

    assert builder.should_sample_embedding(1.0, 0.2, view_token="front")
    assert not builder.should_sample_embedding(1.1, 0.2, view_token="front")
    assert builder.should_sample_embedding(2.0, 0.5, view_token="front")
    assert builder.should_sample_embedding(3.0, 0.5, view_token="side")
    assert builder.should_sample_embedding(6.0, 0.5, view_token="side")


def test_vehicle_reid_budget_remains_available_in_crowded_person_frame():
    session, cam_state = _session(person=True, vehicle=True)
    session.cfg.person_reid_budget = 0
    session.cfg.vehicle_reid_budget = 1
    persons = [
        {
            "bbox": [10.0 + index * 40, 10.0, 40.0 + index * 40, 100.0],
            "confidence": 0.9,
            "classId": 0,
            "className": "person",
        }
        for index in range(3)
    ]
    vehicle_calls: list[bool] = []

    def vehicle_embedding(_root, _crop):
        vehicle_calls.append(True)
        return np.asarray([1.0, 0.0], dtype=np.float32), {"backend": "test"}

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=(persons, [static_vehicle(7)])):
        with patch("services.vehicle_reid_feat.extract_vehicle_embedding", side_effect=vehicle_embedding):
            _process_frame(session, cam_state, _frame(), {}, now=10.0)

    assert vehicle_calls == [True]


def test_configured_gallery_space_missing_is_structured_and_degraded():
    session, cam_state = _session(person=True, vehicle=False)
    session.cfg.reid_budget = 1
    session.cfg.gallery_model_key = "required-model"
    person = {
        "bbox": [20.0, 10.0, 90.0, 110.0],
        "confidence": 0.9,
        "classId": 0,
        "className": "person",
    }
    meta = {
        "backend": "test",
        "bestModelKey": "available-model",
        "associationModelKey": "available-model",
        "modelVersionsBySpace": {"available-model": "v1"},
        "availableModelSpaces": ["available-model"],
        "backends": {"test": {"ready": True}},
    }
    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([person], [])):
        with patch(
            "services.strong_reid.extract_person_embeddings",
            return_value=({"available-model": np.asarray([1.0, 0.0], dtype=np.float32)}, meta),
        ):
            _process_frame(session, cam_state, _frame(), {}, now=10.0)

    status = cam_state.last_dets[0]["attrs"]["galleryStatus"]
    assert status["code"] == "selected_space_unavailable"
    assert status["ready"] is False
    assert status["degraded"] is True
    assert session.runtime_status["gallery"]["code"] == "selected_space_unavailable"
