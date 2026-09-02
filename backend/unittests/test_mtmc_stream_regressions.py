"""Deterministic engine-boundary replays for four MTMC field failures."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from services import mtmc_engine
from services.mtmc_associator import MtmcAssociator
from services.mtmc_engine import CamState, MtmcConfig, MtmcSession, _process_frame
from services.mtmc_local_track import Tracklet


def _v(*values: float) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def _track(local_id: int) -> Tracklet:
    return Tracklet(
        track_id=local_id,
        bbox=[30.0, 20.0, 170.0, 110.0],
        class_name="car",
        conf=0.95,
        is_new=True,
        trail=[(100.0, 65.0)],
    )


def _det() -> dict:
    return {
        "bbox": [30.0, 20.0, 170.0, 110.0],
        "confidence": 0.95,
        "classId": 2,
        "className": "car",
    }


class _ReplayTracker:
    def __init__(self, events):
        self.events = list(events)
        self.removed = set()

    def update(self, _raw, frame=None):
        event = self.events.pop(0)
        self.removed = set(event.get("removed") or ())
        return [_track(local_id) for local_id in event.get("locals") or ()]

    def pop_removed_track_ids(self):
        removed, self.removed = self.removed, set()
        return removed


def _fixtures():
    return {
        "wrong_reuse": {
            "topology": None,
            "steps": [
                {"camera": 1, "now": 1.0, "locals": [10, 20], "entities": {10: "car-a", 20: "car-b"},
                 "embeddings": [_v(1.0, 0.0), _v(1.0, 0.0)]},
                {"camera": 1, "now": 1.1, "locals": [10, 20], "entities": {10: "car-a", 20: "car-b"},
                 "embeddings": [_v(1.0, 0.0), _v(1.0, 0.0)]},
            ],
        },
        "static_vehicle_short_misses": {
            "topology": None,
            "steps": [
                {"camera": 1, "now": 1.0, "locals": [10], "entities": {10: "static"},
                 "embeddings": [_v(1.0, 0.0)]},
                {"camera": 1, "now": 1.1, "locals": [], "removed": [10], "entities": {}, "embeddings": []},
                {"camera": 1, "now": 2.0, "locals": [99], "entities": {99: "static"},
                 "embeddings": [_v(1.0, 0.0)]},
            ],
        },
        "non_overlap_continuation": {
            "topology": [{
                "fromCameraId": 1, "toCameraId": 2,
                "minTransitSec": 3, "maxTransitSec": 20,
                "edgeType": "non_overlap",
            }],
            "steps": [
                {"camera": 1, "now": 1.0, "locals": [10], "entities": {10: "through"},
                 "embeddings": [_v(1.0, 0.0)]},
                {"camera": 1, "now": 1.1, "locals": [], "removed": [10], "entities": {}, "embeddings": []},
                {"camera": 2, "now": 6.0, "locals": [20], "entities": {20: "through"},
                 "embeddings": [_v(1.0, 0.0)]},
            ],
        },
        "delayed_oscillation": {
            "topology": [
                {"fromCameraId": 1, "toCameraId": 2, "minTransitSec": 2, "maxTransitSec": 20},
                {"fromCameraId": 2, "toCameraId": 1, "minTransitSec": 2, "maxTransitSec": 20},
            ],
            "steps": [
                {"camera": 1, "now": 1.0, "locals": [10], "entities": {10: "live"},
                 "embeddings": [_v(1.0, 0.0)]},
                {"camera": 1, "now": 1.1, "locals": [], "removed": [10], "entities": {}, "embeddings": []},
                {"camera": 2, "now": 5.0, "locals": [20], "entities": {20: "live"},
                 "embeddings": [_v(1.0, 0.0)]},
                {"camera": 1, "now": 5.1, "locals": [99], "entities": {99: "delayed"},
                 "embeddings": [_v(1.0, 0.0)]},
                {"camera": 2, "now": 5.2, "locals": [20], "entities": {20: "live"},
                 "embeddings": [_v(1.0, 0.0)]},
            ],
        },
    }


def replay_fixture(name: str, monkeypatch) -> tuple[dict[str, list[str]], list[tuple]]:
    fixture = _fixtures()[name]
    associator = MtmcAssociator(
        appear_thresh=0.4,
        vehicle_appear_thresh=0.4,
        confirm_thresh=0.4,
        candidate_thresh=0.3,
        same_cam_min_gap=0.3,
        lost_revive_sec=0.0,
    )
    if fixture["topology"] is not None:
        associator.set_topology(fixture["topology"])
    camera_ids = sorted({step["camera"] for step in fixture["steps"]})
    cfg = MtmcConfig(
        camera_ids=camera_ids,
        enable_person=False,
        enable_vehicle=True,
        det_vehicle_path="vehicle.pt",
        vehicle_reid_root="vehicle-reid",
        vehicle_reid_budget=8,
        plate_budget=0,
        sample_fps=100,
        local_track_backend="iou",
        # Explicit tracker removals drive finalization in this replay. A zero
        # engine timeout would finalize every live builder at its own end_ts.
        lost_revive_sec=1.0,
    )
    session = MtmcSession(f"replay-{name}", cfg, associator)
    for camera_id in camera_ids:
        camera_events = [step for step in fixture["steps"] if step["camera"] == camera_id]
        session.cams[camera_id] = CamState(
            camera_id=camera_id,
            tracker_person=_ReplayTracker([{"locals": []}] * len(camera_events)),
            tracker_vehicle=_ReplayTracker(camera_events),
        )

    trace = []
    real_resolve = mtmc_engine._resolve_overlay_global
    real_flush = mtmc_engine._FrameAssociationCollector.flush
    real_release = associator.release_local

    def traced_resolve(session_arg, builder, **kwargs):
        trace.append((
            "resolve", builder.camera_id, builder.local_track_id,
            bool(kwargs.get("sticky_gid")), len(kwargs.get("claimed") or ()),
            kwargs.get("collector") is not None,
        ))
        return real_resolve(session_arg, builder, **kwargs)

    def traced_flush(collector, object_type, items):
        trace.append(("collector.flush", object_type, len(collector.pending[object_type])))
        return real_flush(collector, object_type, items)

    def traced_release(object_type, camera_id, local_ids, now=None):
        trace.append(("tracker.release", object_type, camera_id, tuple(sorted(local_ids))))
        return real_release(object_type, camera_id, local_ids, now=now)

    monkeypatch.setattr(mtmc_engine, "_resolve_overlay_global", traced_resolve)
    monkeypatch.setattr(mtmc_engine._FrameAssociationCollector, "flush", traced_flush)
    monkeypatch.setattr(associator, "release_local", traced_release)
    monkeypatch.setattr(
        mtmc_engine,
        "_detect_person_vehicle",
        lambda _cfg, _frame, **_kwargs: ([], [_det()] * len(current_step["locals"])),
    )
    monkeypatch.setattr(
        mtmc_engine,
        "_publish_overlay",
        lambda state, _frame, items, _congestion=None: setattr(state, "last_dets", list(items or [])),
    )

    current_embeddings = iter(())
    monkeypatch.setattr(
        "services.vehicle_reid_feat.extract_vehicle_embedding",
        lambda _root, _crop: (
            next(current_embeddings),
            {
                "backend": "vehicle-onnx",
                "provider": "onnxruntime-cpu",
                "onnx": "vehicle.onnx",
                "inputSize": "256x256",
                "dim": 2,
            },
        ),
    )

    ids: dict[str, list[str]] = defaultdict(list)
    current_step = fixture["steps"][0]
    for current_step in fixture["steps"]:
        current_embeddings = iter(current_step["embeddings"])
        cam_state = session.cams[current_step["camera"]]
        _process_frame(
            session,
            cam_state,
            np.full((120, 200, 3), 127, dtype=np.uint8),
            {},
            now=current_step["now"],
        )
        by_local = {
            int(row["localTrackId"]): row.get("globalId")
            for row in cam_state.last_dets
            if row.get("localTrackId") is not None
        }
        for local_id, entity in current_step["entities"].items():
            ids[entity].append(by_local[local_id])
    return dict(ids), trace


def test_stream_regression_wrong_reuse_keeps_simultaneous_vehicles_distinct(monkeypatch):
    ids, trace = replay_fixture("wrong_reuse", monkeypatch)

    assert ids["car-a"][0] != ids["car-b"][0]
    assert len(set(ids["car-a"])) == 1
    assert len(set(ids["car-b"])) == 1
    assert any(row[:2] == ("collector.flush", "vehicle") and row[2] == 2 for row in trace)
    assert any(row[0] == "resolve" and row[4] == 1 for row in trace)


def test_stream_regression_static_vehicle_keeps_global_id_after_tracker_release(monkeypatch):
    ids, trace = replay_fixture("static_vehicle_short_misses", monkeypatch)

    assert len(set(ids["static"])) == 1
    assert ("tracker.release", "vehicle", 1, (10,)) in trace


def test_stream_regression_valid_non_overlap_transition_continues_global_id(monkeypatch):
    ids, trace = replay_fixture("non_overlap_continuation", monkeypatch)

    assert len(set(ids["through"])) == 1
    assert ("tracker.release", "vehicle", 1, (10,)) in trace
    assert sum(1 for row in trace if row[:2] == ("collector.flush", "vehicle")) >= 2


def test_stream_regression_delayed_frame_cannot_oscillate_live_global_id(monkeypatch):
    ids, trace = replay_fixture("delayed_oscillation", monkeypatch)

    assert len(set(ids["live"])) == 1
    assert ids["delayed"][0] != ids["live"][0]
    assert any(row[0] == "resolve" and row[3] is True for row in trace)
