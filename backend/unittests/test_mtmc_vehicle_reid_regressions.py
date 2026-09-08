"""Regression coverage for field-reported vehicle MTMC failures."""
from __future__ import annotations

import numpy as np

from services.mtmc_associator import AssocMode, MtmcAssociator
from services.mtmc_engine import MtmcConfig, start_session


def _v(*values: float) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def test_empty_topology_is_not_an_authoritative_cross_camera_blocklist():
    assoc = MtmcAssociator(
        appear_thresh=0.2, vehicle_appear_thresh=0.2,
        confirm_thresh=0.2, candidate_thresh=0.1,
    )
    assoc.set_topology([])
    first = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=_v(1.0, 0.0),
        local_track_id=1, now=1.0,
    )
    second = assoc.associate(
        object_type="vehicle", camera_id=2, embedding=_v(0.98, 0.2),
        local_track_id=2, now=2.0,
    )

    assert second.global_id == first.global_id
    assert assoc.last_mode == AssocMode.LONG_TERM


def test_stable_local_vehicle_id_never_switches_global_when_appearance_drifts():
    assoc = MtmcAssociator(vehicle_sticky_warmup_sec=0.0)
    first = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=_v(1.0, 0.0),
        local_track_id=7, now=1.0,
    )
    for ts, embedding in ((2.0, _v(0.7, 0.7)), (10.0, _v(0.0, 1.0)), (19.0, None)):
        current = assoc.associate(
            object_type="vehicle", camera_id=1, embedding=embedding,
            local_track_id=7, now=ts,
        )
        assert current.global_id == first.global_id


def test_session_exposes_zero_match_margin_so_low_thresholds_are_effective():
    cfg = MtmcConfig(
        camera_ids=[], appear_thresh=0.15, vehicle_appear_thresh=0.15,
        confirm_thresh=0.15, candidate_thresh=0.05, min_match_margin=0.0,
    )
    session = start_session(cfg, cameras=[], upload_folder=".", topology_edges=[])

    assert session.associator.min_match_margin == 0.0


def test_single_view_ocr_disagreement_does_not_veto_strong_visual_match():
    assoc = MtmcAssociator(
        appear_thresh=0.4, vehicle_appear_thresh=0.4,
        confirm_thresh=0.4, candidate_thresh=0.2, min_match_margin=0.0,
    )
    first = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=_v(1.0, 0.0),
        plate="粤A12345", identity_key="粤A12345", local_track_id=1, now=1.0,
    )
    second = assoc.associate(
        object_type="vehicle", camera_id=2, embedding=_v(0.99, 0.1),
        plate="粤A12845", identity_key="粤A12845", local_track_id=2, now=2.0,
    )

    assert second.global_id == first.global_id
