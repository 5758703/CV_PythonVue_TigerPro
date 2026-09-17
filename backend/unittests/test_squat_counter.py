from __future__ import annotations

import math

import pytest

from services.squat_counter import SquatConfig, SquatCounter, knee_angle


def _leg_points(angle: float, *, origin_x: float = 100.0, confidence: float = 0.95):
    """Return hip/knee/ankle points whose knee angle is ``angle`` degrees."""
    radians = math.radians(angle)
    knee = (origin_x, 200.0, confidence)
    hip = (origin_x, 100.0, confidence)
    ankle = (
        origin_x + 100.0 * math.sin(radians),
        200.0 - 100.0 * math.cos(radians),
        confidence,
    )
    return hip, knee, ankle


def _person(
    angle: float,
    *,
    bbox=(50.0, 50.0, 250.0, 350.0),
    confidence: float = 0.95,
    right_angle: float | None = None,
    right_confidence: float | None = None,
):
    keypoints = [[0.0, 0.0, 0.0] for _ in range(17)]
    left = _leg_points(angle, origin_x=100.0, confidence=confidence)
    right = _leg_points(
        angle if right_angle is None else right_angle,
        origin_x=180.0,
        confidence=confidence if right_confidence is None else right_confidence,
    )
    for index, point in zip((11, 13, 15), left):
        keypoints[index] = list(point)
    for index, point in zip((12, 14, 16), right):
        keypoints[index] = list(point)
    return {"bbox": list(bbox), "score": confidence, "keypoints": keypoints}


def _feed(counter: SquatCounter, angles, *, start=0.0, step=0.1):
    state = None
    for offset, angle in enumerate(angles):
        persons = [] if angle is None else [_person(angle)]
        state = counter.update(persons, start + offset * step)
    return state


def test_knee_angle_is_ninety_degrees():
    assert knee_angle((0, 0), (0, 1), (1, 1)) == pytest.approx(90.0)


def test_knee_angle_rejects_degenerate_limb():
    assert knee_angle((0, 0), (0, 0), (1, 1)) is None


def test_counter_uses_only_confident_leg():
    counter = SquatCounter(SquatConfig(confirm_frames=1, smoothing_window=1))
    result = counter.update([
        _person(170, right_angle=80, right_confidence=0.05),
    ], 0.0)
    assert result["kneeAngle"] == pytest.approx(170.0)


def test_complete_stand_bottom_stand_cycle_counts_once():
    counter = SquatCounter(SquatConfig(confirm_frames=2, smoothing_window=1))
    state = _feed(counter, [170, 170, 130, 95, 95, 125, 165, 165])
    assert state["count"] == 1
    assert state["stage"] == "standing"
    assert state["completedRep"] is True


def test_half_squat_does_not_count():
    counter = SquatCounter(SquatConfig(confirm_frames=2, smoothing_window=1))
    state = _feed(counter, [170, 170, 130, 115, 115, 130, 165, 165])
    assert state["count"] == 0


def test_initial_bottom_pose_must_stand_before_first_rep():
    counter = SquatCounter(SquatConfig(confirm_frames=2, smoothing_window=1))
    state = _feed(counter, [90, 90, 130, 170, 170])
    assert state["count"] == 0
    assert state["stage"] == "standing"


def test_threshold_jitter_does_not_duplicate_count():
    counter = SquatCounter(SquatConfig(confirm_frames=2, smoothing_window=1))
    state = _feed(counter, [170, 170, 99, 103, 99, 99, 130, 161, 158, 162, 162])
    assert state["count"] == 1


def test_two_complete_repetitions_accumulate():
    counter = SquatCounter(SquatConfig(confirm_frames=1, smoothing_window=1))
    state = _feed(counter, [170, 95, 170, 130, 90, 170])
    assert state["count"] == 2


def test_larger_distractor_does_not_replace_continuing_target():
    counter = SquatCounter(SquatConfig(confirm_frames=1, smoothing_window=1))
    counter.update([_person(170)], 0.0)
    target = _person(95, bbox=(55, 50, 255, 350))
    distractor = _person(170, bbox=(350, 20, 630, 470))
    state = counter.update([distractor, target], 0.1)
    assert state["stage"] == "bottom"


def test_brief_loss_preserves_partial_repetition():
    counter = SquatCounter(SquatConfig(confirm_frames=1, smoothing_window=1, lost_grace_seconds=1.0))
    _feed(counter, [170, 95], step=0.1)
    counter.update([], 0.5)
    state = counter.update([_person(170)], 0.6)
    assert state["count"] == 1


def test_long_loss_cancels_partial_repetition_but_keeps_completed_count():
    counter = SquatCounter(SquatConfig(confirm_frames=1, smoothing_window=1, lost_grace_seconds=1.0))
    _feed(counter, [170, 95, 170, 95], step=0.1)
    lost_state = counter.update([], 1.5)
    assert lost_state["stage"] == "waiting_stand"
    state = counter.update([_person(170)], 1.6)
    assert state["count"] == 1
    assert state["stage"] == "standing"
