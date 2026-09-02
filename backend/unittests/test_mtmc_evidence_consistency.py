"""Regression coverage for MTMC evidence and shutdown consistency."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from flask import Flask

from extensions import db
from models.mtmc import (
    MtmcAssociationEdge,
    MtmcCandidatePair,
    MtmcCrossCameraEvent,
    MtmcGlobalVehicle,
    MtmcTrackEvent,
    MtmcTracklet,
    MtmcVehiclePass,
)
from services import mtmc_engine
from services.mtmc_associator import MtmcAssociator
from services.mtmc_engine import MtmcConfig, MtmcSession
from services.mtmc_persist import resolve_candidate_pair
from services import vehicle_reid_feat


def test_vehicle_visual_score_is_candidate_similarity():
    """The score must compare the current tracklet to the candidate prototype."""
    unit_x = np.asarray([1.0, 0.0], dtype=np.float32)
    unit_y = np.asarray([0.0, 1.0], dtype=np.float32)

    assert vehicle_reid_feat.vehicle_candidate_score(unit_x, unit_y) == pytest.approx(0.0)
    assert vehicle_reid_feat.vehicle_candidate_score(unit_x, unit_x) == pytest.approx(1.0)


def test_vehicle_plate_vote_normalizes_characters_across_observations():
    plate, score = vehicle_reid_feat.aggregate_vehicle_plate_votes([
        ("粤 A·O12B3", 0.71),
        ("粤A01283", 0.88),
        (" 粤A-012B3 ", 0.76),
    ])

    assert plate == "粤A01283"
    assert score == pytest.approx((0.71 + 0.88 + 0.76) / 3)


def test_association_evidence_is_call_local_under_concurrency():
    associator = MtmcAssociator(appear_thresh=0.99, confirm_thresh=0.99)
    barrier = __import__("threading").Barrier(2)

    def associate(camera_id: int):
        barrier.wait(timeout=2)
        return associator.associate_with_evidence(
            object_type="vehicle",
            camera_id=camera_id,
            embedding=np.asarray([float(camera_id), 1.0], dtype=np.float32),
            local_track_id=camera_id,
            now=float(camera_id),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(associate, [1, 2]))

    assert first.evidence is not second.evidence
    assert first.evidence.target_global_id == first.global_track.global_id
    assert second.evidence.target_global_id == second.global_track.global_id


def test_stop_session_joins_workers_finalizes_then_cleans_uploads(monkeypatch, tmp_path):
    order: list[str] = []

    class StopFlag:
        def set(self):
            order.append("stop")

    class Worker:
        def join(self, timeout=None):
            order.append("join")

    upload_dir = tmp_path / "mtmc-upload"
    upload_dir.mkdir()
    session = SimpleNamespace(
        _stop=StopFlag(), running=True, _threads=[Worker()],
        cams={1: object()}, upload_dir=str(upload_dir),
    )
    monkeypatch.setitem(mtmc_engine._sessions, "s", session)
    monkeypatch.setattr(mtmc_engine, "_flush_camera_tracklets", lambda *_args: order.append("finalize"))
    monkeypatch.setattr("shutil.rmtree", lambda path, **_kwargs: order.append("cleanup"))

    assert mtmc_engine.stop_session("s")
    assert order == ["stop", "join", "finalize", "cleanup"]


@pytest.fixture
def candidate_db(tmp_path):
    app = Flask("mtmc-evidence")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{Path(tmp_path) / 'mtmc.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.mark.parametrize("status", ["promoted", "rejected"])
def test_candidate_resolution_updates_every_related_persisted_row(candidate_db, status):
    with candidate_db.app_context():
        db.session.add_all([
            MtmcCandidatePair(session_id="s", global_id="new", candidate_global_id="known", object_type="vehicle"),
            MtmcCandidatePair(session_id="s", global_id="new", candidate_global_id="known", object_type="vehicle"),
            MtmcTracklet(tracklet_id="t-new", session_id="s", camera_id=1, object_type="vehicle", global_id="new"),
            MtmcTracklet(tracklet_id="t-known", session_id="s", camera_id=2, object_type="vehicle", global_id="known"),
        ])
        db.session.commit()

        assert resolve_candidate_pair(
            candidate_db, session_id="s", global_id="new", candidate_global_id="known", status=status,
        )

        pairs = MtmcCandidatePair.query.filter_by(session_id="s").all()
        tracklets = {row.tracklet_id: row for row in MtmcTracklet.query.filter_by(session_id="s").all()}
        assert [row.status for row in pairs] == [status, status]
        assert all(row.resolve_time is not None for row in pairs)
        assert tracklets["t-new"].global_id == ("known" if status == "promoted" else "new")
        assert tracklets["t-known"].global_id == "known"


def test_promotion_rewrites_all_persisted_old_global_references(candidate_db):
    with candidate_db.app_context():
        db.session.add_all([
            MtmcCandidatePair(session_id="s", global_id="new", candidate_global_id="known", object_type="vehicle"),
            MtmcTracklet(tracklet_id="t", session_id="s", camera_id=1, object_type="vehicle", global_id="new"),
            MtmcTrackEvent(session_id="s", camera_id=1, object_type="vehicle", global_id="new"),
            MtmcAssociationEdge(session_id="s", object_type="vehicle", decision="candidate", source_global_id="new", target_global_id="new"),
            MtmcCrossCameraEvent(session_id="s", global_id="new", object_type="vehicle", from_camera_id=1, to_camera_id=2),
            MtmcVehiclePass(session_id="s", camera_id=1, global_id="new"),
            MtmcGlobalVehicle(global_id="new", plate="A"),
            MtmcGlobalVehicle(global_id="known", visual_key="V"),
        ])
        db.session.commit()

        assert resolve_candidate_pair(
            candidate_db, session_id="s", global_id="new", candidate_global_id="known", status="promoted",
        )

        assert MtmcGlobalVehicle.query.filter_by(global_id="new").first() is None
        assert MtmcGlobalVehicle.query.filter_by(global_id="known").first().plate == "A"
        assert all(row.global_id != "new" for row in MtmcTracklet.query.all())
        assert all(row.global_id != "new" for row in MtmcTrackEvent.query.all())
        assert all(row.global_id != "new" for row in MtmcCrossCameraEvent.query.all())
        assert all(row.global_id != "new" for row in MtmcVehiclePass.query.all())
        assert all(
            row.source_global_id != "new" and row.target_global_id != "new"
            for row in MtmcAssociationEdge.query.all()
        )
        assert all(
            row.global_id != "new" and row.candidate_global_id != "new"
            for row in MtmcCandidatePair.query.all()
        )


def test_failed_promotion_keeps_live_associator_and_candidates_unchanged(monkeypatch):
    associator = MtmcAssociator(appear_thresh=0.99, confirm_thresh=0.99)
    known = associator.associate(object_type="vehicle", camera_id=1, embedding=np.asarray([1.0, 0.0]), now=1.0)
    pending = associator.associate(object_type="vehicle", camera_id=2, embedding=np.asarray([0.0, 1.0]), now=2.0)
    associator._candidates.append({"globalId": pending.global_id, "candidateGlobalId": known.global_id})
    candidates_before = associator.list_candidates()
    session = MtmcSession("s", MtmcConfig(camera_ids=[]), associator, app=object())

    monkeypatch.setattr(mtmc_engine, "get_session", lambda _sid: session)
    monkeypatch.setattr("services.mtmc_persist.resolve_candidate_pair", lambda *_args, **_kwargs: False)

    result = mtmc_engine.promote_candidate("s", pending.global_id, known.global_id)

    assert result["ok"] is False
    assert associator.get_track(known.global_id) is known
    assert associator.get_track(pending.global_id) is pending
    assert associator.list_candidates() == candidates_before


def test_stop_timeout_does_not_finalize_or_cleanup(monkeypatch, tmp_path):
    order: list[str] = []

    class Worker:
        def join(self, timeout=None):
            order.append("join")

        def is_alive(self):
            return True

    session = MtmcSession("stop-timeout", MtmcConfig(camera_ids=[]), MtmcAssociator())
    session.running = True
    session._threads = [Worker()]
    session.cams = {1: object()}
    session.upload_dir = str(tmp_path)
    monkeypatch.setitem(mtmc_engine._sessions, session.session_id, session)
    monkeypatch.setattr(mtmc_engine, "_flush_camera_tracklets", lambda *_args: order.append("finalize"))
    monkeypatch.setattr("shutil.rmtree", lambda *_args, **_kwargs: order.append("cleanup"))

    assert mtmc_engine.stop_session(session.session_id) is False
    assert order == ["join"]


def test_concurrent_stop_finalizes_and_cleans_up_once(monkeypatch, tmp_path):
    order: list[str] = []

    class Worker:
        def join(self, timeout=None):
            order.append("join")

        def is_alive(self):
            return False

    session = MtmcSession("stop-once", MtmcConfig(camera_ids=[]), MtmcAssociator())
    session.running = True
    session._threads = [Worker()]
    session.cams = {1: object()}
    session.upload_dir = str(tmp_path)
    monkeypatch.setitem(mtmc_engine._sessions, session.session_id, session)
    monkeypatch.setattr(mtmc_engine, "_flush_camera_tracklets", lambda *_args: order.append("finalize"))
    monkeypatch.setattr("shutil.rmtree", lambda *_args, **_kwargs: order.append("cleanup"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(lambda _n: mtmc_engine.stop_session(session.session_id), range(2)))

    assert order.count("join") == order.count("finalize") == order.count("cleanup") == 1
