"""Regression policy for directed MTMC topology and authoritative finals."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import FrozenInstanceError
import sys
from types import SimpleNamespace
from types import ModuleType

import numpy as np
import pytest

from services.mtmc_associator import GlobalTrack, MtmcAssociator, TopologyRule


def _embedding() -> np.ndarray:
    return np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


def test_topology_rule_is_immutable():
    rule = TopologyRule(1, 20, 0.7, "non_overlap")

    with pytest.raises(FrozenInstanceError):
        rule.weight = 1.0


def test_topology_is_directed_and_missing_non_overlap_edges_reject():
    assoc = MtmcAssociator(appear_thresh=0.4)
    assoc.set_topology([{
        "fromCameraId": 1, "toCameraId": 2,
        "minTransitSec": 5, "maxTransitSec": 20,
    }])

    assert assoc._topology_ok(1, 2, 10) > 0
    assert assoc._topology_ok(2, 1, 10) == 0
    assert assoc._topology_ok(1, 3, 10) == 0


def test_non_overlap_rejects_zero_while_overlap_accepts_it():
    assoc = MtmcAssociator(appear_thresh=0.4)
    assoc.set_topology([{
        "fromCameraId": 1, "toCameraId": 2,
        "minTransitSec": 0, "maxTransitSec": 20,
    }, {
        "fromCameraId": 2, "toCameraId": 3,
        "minTransitSec": 0, "maxTransitSec": 20,
        "edgeType": "overlap",
    }])

    assert assoc._topology_ok(1, 2, 0) == 0
    assert assoc._topology_ok(2, 3, 0) > 0


def test_final_multiplies_time_likelihood_and_configured_topology_weight():
    assoc = MtmcAssociator(appear_thresh=0.4)
    assoc.set_topology([{
        "fromCameraId": 1, "toCameraId": 2,
        "minTransitSec": 1, "maxTransitSec": 20,
        "weight": 0.4,
    }])
    track = GlobalTrack(
        global_id="P1", object_type="person", embedding=_embedding(),
        camera_id=1, last_seen=0.0, reid_person_id=17,
    )

    final, breakdown = assoc._score_long_term(
        track, object_type="person", camera_id=2, embedding=_embedding(),
        identity_key=None, plate=None, reid_person_id=17, now=10.0,
    )

    assert breakdown["topology"] == pytest.approx(0.4)
    assert breakdown["time"] < 1.0
    assert final == pytest.approx(
        0.99 * breakdown["topology"] * breakdown["time"]
        * breakdown["recency"] * breakdown["xcamBoost"]
    )


def test_raw_reid_cannot_bypass_low_final_threshold():
    assoc = MtmcAssociator(
        appear_thresh=0.4, confirm_thresh=0.4, candidate_thresh=0.2,
    )
    assoc.set_topology([{
        "fromCameraId": 1, "toCameraId": 2,
        "minTransitSec": 1, "maxTransitSec": 20,
        "weight": 0.1,
    }])
    first = assoc.associate(
        object_type="person", camera_id=1, embedding=_embedding(),
        reid_person_id=17, local_track_id=1, now=0.0,
    )
    second = assoc.associate(
        object_type="person", camera_id=2, embedding=_embedding(),
        reid_person_id=17, local_track_id=2, now=10.0,
    )

    assert second.global_id != first.global_id
    assert second.last_assoc_mode == "new"


def test_pipeline_session_receives_database_topology(monkeypatch):
    from services import pipeline_mtmc

    class Query:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return [SimpleNamespace(id=1), SimpleNamespace(id=2)]

    class Column:
        def in_(self, _ids):
            return None

        def asc(self):
            return None

    class Camera:
        id = Column()
        status = "0"
        query = Query()

    fake_models = ModuleType("models")
    fake_camera_module = ModuleType("models.camera")
    fake_camera_module.Camera = Camera
    monkeypatch.setitem(sys.modules, "models", fake_models)
    monkeypatch.setitem(sys.modules, "models.camera", fake_camera_module)
    captured = {}
    monkeypatch.setattr(
        pipeline_mtmc, "build_mtmc_config_from_node",
        lambda _cfg: SimpleNamespace(camera_ids=[1, 2]),
    )
    monkeypatch.setattr(
        pipeline_mtmc, "load_database_topology",
        lambda: [{"fromCameraId": 1, "toCameraId": 2, "edgeType": "overlap"}],
        raising=False,
    )
    def start_session(*_args, **kwargs):
        captured["edges"] = kwargs.get("topology_edges")
        return "session"

    monkeypatch.setattr("services.mtmc_engine.start_session", start_session)

    session, owned = pipeline_mtmc.start_or_attach_mtmc(
        SimpleNamespace(app_context=nullcontext), {}, upload_folder="uploads",
    )

    assert (session, owned) == ("session", True)
    assert captured["edges"] == [{"fromCameraId": 1, "toCameraId": 2, "edgeType": "overlap"}]
