from __future__ import annotations

import numpy as np

from services.mtmc_associator import AssocMode, MtmcAssociator


def _v(*values: float) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def test_camera_observation_state_keeps_overlapping_cameras_active():
    assoc = MtmcAssociator(
        appear_thresh=0.4,
        confirm_thresh=0.4,
        topology={(1, 2): (0.0, 20.0)},
    )
    embedding = _v(1.0, 0.0)
    first = assoc.associate(
        object_type="person", camera_id=1, embedding=embedding,
        local_track_id=10, now=10.0,
    )
    second = assoc.associate(
        object_type="person", camera_id=2, embedding=embedding,
        local_track_id=20, now=10.0,
    )

    assert second.global_id == first.global_id
    assert first.camera_id == 2  # compatibility summary remains latest camera
    assert first.last_seen == 10.0
    assert first.camera_observations[1].active is True
    assert first.camera_observations[2].active is True
    assert first.camera_observations[1].last_observed_at == 10.0
    assert first.camera_observations[2].last_observed_at == 10.0


def test_local_reconstruction_recovers_same_camera_global_after_loss():
    assoc = MtmcAssociator(appear_thresh=0.4, confirm_thresh=0.4, lost_revive_sec=1.0)
    embedding = _v(1.0, 0.0)
    first = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=embedding,
        local_track_id=10, now=10.0,
    )
    assoc.release_local("vehicle", 1, [10], now=10.1)
    recovered = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=embedding,
        local_track_id=99, now=12.0,
    )

    assert recovered.global_id == first.global_id
    assert recovered.camera_observations[1].active is True


def test_active_same_camera_global_is_hard_occupied():
    assoc = MtmcAssociator(appear_thresh=0.4, confirm_thresh=0.4)
    embedding = _v(1.0, 0.0)
    first = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=embedding,
        local_track_id=10, now=10.0,
    )
    later_similar = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=embedding,
        local_track_id=11, now=10.1,
    )

    assert later_similar.global_id != first.global_id
    assert first.camera_observations[1].active is True


def test_two_static_vehicles_never_exchange_globals():
    assoc = MtmcAssociator(appear_thresh=0.4, confirm_thresh=0.4)
    left, right = _v(1.0, 0.0), _v(0.98, 0.2)
    frames = []
    for now in range(20):
        frames.append((
            assoc.associate(
                object_type="vehicle", camera_id=1, embedding=left,
                local_track_id=10, now=float(now),
            ).global_id,
            assoc.associate(
                object_type="vehicle", camera_id=1, embedding=right,
                local_track_id=20, now=float(now),
            ).global_id,
        ))

    assert all(frame[0] == frames[0][0] for frame in frames)
    assert all(frame[1] == frames[0][1] for frame in frames)
    assert frames[0][0] != frames[0][1]


def test_physically_invalid_transition_cannot_steal_global():
    assoc = MtmcAssociator(
        appear_thresh=0.4,
        confirm_thresh=0.4,
        topology={(1, 2): (3.0, 20.0)},
    )
    first = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=_v(1.0, 0.0),
        local_track_id=10, now=10.0,
    )
    second = assoc.associate(
        object_type="vehicle", camera_id=2, embedding=_v(1.0, 0.0),
        local_track_id=20, now=11.0,
    )

    assert second.global_id != first.global_id


def test_low_best_second_margin_creates_candidate_without_prototypes():
    assoc = MtmcAssociator(
        appear_thresh=0.6,
        confirm_thresh=0.6,
        candidate_thresh=0.5,
        min_match_margin=0.1,
        topology={(1, 3): (0.0, 20.0), (2, 3): (0.0, 20.0)},
    )
    left = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=_v(1.0, 0.0),
        local_track_id=1, now=1.0,
    )
    right = assoc.associate(
        object_type="vehicle", camera_id=2, embedding=_v(0.0, 1.0),
        local_track_id=2, now=1.0,
    )
    assoc.release_local("vehicle", 1, [1], now=1.1)
    assoc.release_local("vehicle", 2, [2], now=1.1)
    left_before = assoc._gallery.prototype("vehicle", left.global_id, camera_id=1).copy()
    candidate = assoc.associate(
        object_type="vehicle", camera_id=3, embedding=_v(1.0, 1.0),
        local_track_id=3, now=3.0,
    )

    assert candidate.global_id not in {left.global_id, right.global_id}
    assert assoc.last_mode == AssocMode.CANDIDATE
    assert assoc.last_evidence.extra["secondBestScore"] == assoc.last_evidence.extra["bestScore"]
    assert assoc._gallery.prototype("vehicle", candidate.global_id, camera_id=3) is None
    np.testing.assert_allclose(
        assoc._gallery.prototype("vehicle", left.global_id, camera_id=1), left_before,
    )


def test_low_quality_observation_does_not_update_confirmed_prototype():
    assoc = MtmcAssociator(appear_thresh=0.4, confirm_thresh=0.4, prototype_quality_thresh=0.5)
    first = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=_v(1.0, 0.0),
        local_track_id=10, now=10.0, observation_quality=1.0,
    )
    before = assoc._gallery.prototype("vehicle", first.global_id, camera_id=1).copy()
    assoc.associate(
        object_type="vehicle", camera_id=1, embedding=_v(0.0, 1.0),
        local_track_id=10, now=10.1, observation_quality=0.1,
    )

    np.testing.assert_allclose(
        assoc._gallery.prototype("vehicle", first.global_id, camera_id=1), before,
    )
