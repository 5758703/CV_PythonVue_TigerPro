"""MTMC P2：跨镜事件、候选晋升、检索任务。"""
from __future__ import annotations

import numpy as np

from services.mtmc_associator import MtmcAssociator, AssocMode
from services.strong_reid import _l2


def test_merge_globals_promote():
    assoc = MtmcAssociator(appear_thresh=0.99, confirm_thresh=0.99)
    emb_a = _l2(np.ones(32, dtype=np.float32))
    emb_b = _l2(np.random.randn(32).astype(np.float32))
    keep = assoc.associate(object_type="person", camera_id=1, embedding=emb_a, local_track_id=1, now=1.0)
    drop = assoc.associate(object_type="person", camera_id=2, embedding=emb_b, local_track_id=2, now=2.0)
    assert keep.global_id != drop.global_id
    merged = assoc.merge_globals(keep.global_id, drop.global_id, now=3.0)
    assert merged is not None
    assert merged.global_id == keep.global_id
    assert drop.global_id not in assoc.tracks
    assert assoc.last_evidence.decision == "promoted"


def test_cross_camera_event_persist_fields():
    """跨镜事件模型字段映射。"""
    from models.mtmc import MtmcCrossCameraEvent

    row = MtmcCrossCameraEvent(
        session_id="s1",
        global_id="P000001-abc",
        object_type="person",
        from_camera_id=1,
        to_camera_id=2,
        transit_sec=5.5,
        decision="long_term",
    )
    d = row.to_dict()
    assert d["fromCameraId"] == 1
    assert d["toCameraId"] == 2
    assert d["transitSec"] == 5.5


def test_candidate_pair_to_dict():
    from models.mtmc import MtmcCandidatePair

    row = MtmcCandidatePair(
        session_id="s1",
        global_id="P000002",
        candidate_global_id="P000001",
        object_type="person",
        status="pending",
        final_score=0.6,
    )
    d = row.to_dict()
    assert d["status"] == "pending"
    assert d["candidateGlobalId"] == "P000001"
