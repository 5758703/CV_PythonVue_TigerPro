"""Deterministic synthetic replays for four MTMC field failures."""
from __future__ import annotations

import numpy as np

from services.mtmc_associator import MtmcAssociator


def _v(*values: float) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def replay_fixture(name: str) -> dict[str, list[str]]:
    fixtures = {
        "wrong_reuse": {
            "topology": None,
            "events": [
                ("car-a", "see", 1, 10, 1.0, _v(1.0, 0.0)),
                ("car-b", "see", 1, 20, 1.1, _v(1.0, 0.0)),
            ],
        },
        "static_vehicle_short_misses": {
            "topology": None,
            "events": [
                ("static", "see", 1, 10, 1.0, _v(1.0, 0.0)),
                ("static", "release", 1, 10, 1.1, None),
                ("static", "see", 1, 99, 2.0, _v(1.0, 0.0)),
            ],
        },
        "non_overlap_continuation": {
            "topology": [{
                "fromCameraId": 1, "toCameraId": 2,
                "minTransitSec": 3, "maxTransitSec": 20,
                "edgeType": "non_overlap",
            }],
            "events": [
                ("through", "see", 1, 10, 1.0, _v(1.0, 0.0)),
                ("through", "release", 1, 10, 1.1, None),
                ("through", "see", 2, 20, 6.0, _v(1.0, 0.0)),
            ],
        },
        "delayed_oscillation": {
            "topology": [
                {"fromCameraId": 1, "toCameraId": 2, "minTransitSec": 2, "maxTransitSec": 20},
                {"fromCameraId": 2, "toCameraId": 1, "minTransitSec": 2, "maxTransitSec": 20},
            ],
            "events": [
                ("live", "see", 1, 10, 1.0, _v(1.0, 0.0)),
                ("live", "release", 1, 10, 1.1, None),
                ("live", "see", 2, 20, 5.0, _v(1.0, 0.0)),
                ("delayed", "see", 1, 99, 5.1, _v(1.0, 0.0)),
                ("live", "see", 2, 20, 5.2, _v(1.0, 0.0)),
            ],
        },
    }
    fixture = fixtures[name]
    assoc = MtmcAssociator(
        appear_thresh=0.4, confirm_thresh=0.4, candidate_thresh=0.3,
        same_cam_min_gap=0.3, lost_revive_sec=0.0,
    )
    if fixture["topology"] is not None:
        assoc.set_topology(fixture["topology"])
    ids: dict[str, list[str]] = {}
    for entity, action, camera_id, local_id, now, embedding in fixture["events"]:
        if action == "release":
            assoc.release_local("vehicle", camera_id, [local_id], now=now)
            continue
        # The stream engine resolves a valid local sticky binding before the
        # vehicle warm-up rematch. Replaying through that production boundary
        # is essential for the delayed-frame oscillation case.
        sticky = assoc.peek_sticky(
            object_type="vehicle", camera_id=camera_id, local_track_id=local_id, now=now,
        )
        track = assoc.get_track(sticky) if sticky else assoc.associate(
            object_type="vehicle", camera_id=camera_id, local_track_id=local_id,
            embedding=embedding, now=now,
        )
        ids.setdefault(entity, []).append(track.global_id)
    return ids


def test_stream_regression_wrong_reuse_keeps_simultaneous_vehicles_distinct():
    ids = replay_fixture("wrong_reuse")

    assert ids["car-a"][0] != ids["car-b"][0]


def test_stream_regression_static_vehicle_keeps_global_id():
    ids = replay_fixture("static_vehicle_short_misses")

    assert len(set(ids["static"])) == 1


def test_stream_regression_valid_non_overlap_transition_continues_global_id():
    ids = replay_fixture("non_overlap_continuation")

    assert len(set(ids["through"])) == 1


def test_stream_regression_delayed_frame_cannot_oscillate_live_global_id():
    ids = replay_fixture("delayed_oscillation")

    assert len(set(ids["live"])) == 1
    assert ids["delayed"][0] != ids["live"][0]
