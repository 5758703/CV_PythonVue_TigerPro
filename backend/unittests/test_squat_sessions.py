from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from services.squat_counter import SquatConfig
from services.squat_sessions import SessionError, SquatSessionManager


def _person(angle=170.0):
    radians = math.radians(angle)
    points = [[0.0, 0.0, 0.0] for _ in range(17)]
    for x, indices in ((20.0, (11, 13, 15)), (44.0, (12, 14, 16))):
        values = ((x, 10, 0.95), (x, 30, 0.95), (x + 20 * math.sin(radians), 30 - 20 * math.cos(radians), 0.95))
        for index, value in zip(indices, values):
            points[index] = list(value)
    return {"bbox": [5, 5, 58, 60], "score": 0.95, "keypoints": points}


class StaticEstimator:
    def __init__(self, angle=170):
        self.angle = angle

    def infer(self, _frame):
        return [_person(self.angle)]


def _jpeg():
    ok, encoded = cv2.imencode(".jpg", np.zeros((64, 64, 3), dtype=np.uint8))
    assert ok
    return encoded.tobytes()


def test_local_session_accepts_ordered_frames_and_rejects_duplicates():
    manager = SquatSessionManager(max_sessions_per_owner=2, idle_seconds=30)
    session = manager.create_local("user-1", StaticEstimator(), SquatConfig(confirm_frames=1))
    first = manager.submit_frame(session.id, "user-1", 1, 0.0, _jpeg())
    assert first["frameSequence"] == 1
    assert first["state"]["stage"] == "standing"
    assert first["annotatedJpeg"]
    with pytest.raises(SessionError, match="strictly increasing"):
        manager.submit_frame(session.id, "user-1", 1, 0.1, _jpeg())


def test_session_is_owner_isolated_and_stop_is_idempotent():
    manager = SquatSessionManager(max_sessions_per_owner=1)
    session = manager.create_local("owner", StaticEstimator(), SquatConfig())
    with pytest.raises(SessionError, match="not found"):
        manager.snapshot(session.id, "other")
    first = manager.stop(session.id, "owner")
    second = manager.stop(session.id, "owner")
    assert first["status"] == "stopped"
    assert second == first


def test_active_session_limit_and_idle_reaping():
    clock = [10.0]
    manager = SquatSessionManager(
        max_sessions_per_owner=1,
        idle_seconds=5,
        clock=lambda: clock[0],
    )
    session = manager.create_local("owner", StaticEstimator(), SquatConfig())
    with pytest.raises(SessionError, match="limit"):
        manager.create_local("owner", StaticEstimator(), SquatConfig())
    clock[0] = 16.0
    assert manager.reap_idle() == [session.id]
    assert manager.snapshot(session.id, "owner")["status"] == "expired"


def test_frame_payload_size_is_limited_before_decode():
    manager = SquatSessionManager(max_frame_bytes=8)
    session = manager.create_local("owner", StaticEstimator(), SquatConfig())
    with pytest.raises(SessionError, match="size limit"):
        manager.submit_frame(session.id, "owner", 1, 0.0, b"x" * 9)
