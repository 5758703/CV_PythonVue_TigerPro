"""MTMC Tracklet 聚合单测。"""
from __future__ import annotations

import numpy as np

from services.mtmc_tracklet import TrackletBuilder, frame_quality


def test_frame_quality_small_bbox_zero():
    q = frame_quality([0, 0, 2, 2], 0.9, 480, 640)
    assert q == 0.0


def test_tracklet_aggregate_weighted_embedding():
    b = TrackletBuilder.create(session_id="s1", camera_id=1, object_type="person", local_track_id=3, now=1.0)
    e1 = np.array([1.0, 0.0], dtype=np.float32)
    e2 = np.array([0.0, 1.0], dtype=np.float32)
    b.add_observation(bbox=[10, 10, 50, 80], conf=0.9, frame_h=480, frame_w=640, embedding=e1, now=1.0)
    b.add_observation(bbox=[12, 12, 52, 82], conf=0.95, frame_h=480, frame_w=640, embedding=e2, now=1.1)
    agg = b.aggregate_embedding()
    assert agg is not None
    assert abs(float(np.linalg.norm(agg)) - 1.0) < 1e-5


def test_tracklet_ready_for_tentative():
    b = TrackletBuilder.create(session_id="s1", camera_id=1, object_type="person", local_track_id=1, now=1.0)
    assert not b.ready_for_tentative()
    b.add_observation(
        bbox=[50, 50, 150, 200], conf=0.8, frame_h=480, frame_w=640,
        embedding=np.ones(8, dtype=np.float32), now=1.0,
    )
    assert b.ready_for_tentative()
