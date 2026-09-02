"""Phase 1 whole-review regressions for MTMC reliability contracts."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from flask import Flask

from models.mtmc import MtmcCandidatePair
from routes import mtmc as mtmc_routes
from services import mtmc_engine, reid_gallery, vehicle_reid_feat
from services.mtmc_active_gallery import MtmcActiveGallery
from services.mtmc_associator import MtmcAssociator
from services.mtmc_engine import CamState, MtmcConfig, MtmcSession, _process_frame
from services.mtmc_tracklet import TrackletBuilder


def _unit(*values: float) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def _vehicle_detection(confidence: float = 0.95) -> dict:
    return {
        "bbox": [20.0, 20.0, 180.0, 100.0],
        "confidence": confidence,
        "classId": 2,
        "className": "car",
    }


def _frame() -> np.ndarray:
    return np.full((120, 200, 3), 127, dtype=np.uint8)


def _run_faiss_cold_cache_probe(*, real_faiss: bool) -> subprocess.CompletedProcess:
    backend = Path(__file__).resolve().parents[1]
    fake_setup = ""
    if not real_faiss:
        fake_setup = """
class FakeIndex:
    def __init__(self, dim):
        self.dim = dim
        self.rows = np.zeros((0, dim), dtype=np.float32)
    @property
    def ntotal(self):
        return len(self.rows)
    def add(self, rows):
        self.rows = np.asarray(rows, dtype=np.float32)
    def search(self, query, topk):
        scores = self.rows @ query[0]
        order = np.argsort(-scores)[:topk]
        return scores[order][None, :], order.astype(np.int64)[None, :]
class FakeFaiss:
    IndexFlatIP = FakeIndex
reid_gallery._import_faiss = lambda: FakeFaiss()
"""
    script = f"""
import numpy as np
from services import reid_gallery
{fake_setup}
reid_gallery._gallery_cache.clear()
reid_gallery._faiss_cache.clear()
reid_gallery._load_gallery = lambda *args, **kwargs: (
    [7], ['Ada'], np.asarray([[1.0, 0.0]], dtype=np.float32), [17]
)
result = reid_gallery.match_embedding_faiss(
    np.asarray([1.0, 0.0], dtype=np.float32),
    'osnet-x1-0', threshold=0.5, model_version='v1',
)
assert result['personId'] == 7
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend)
    return subprocess.run(
        [sys.executable, "-c", script], cwd=backend, env=env,
        capture_output=True, text=True, timeout=3,
    )


def test_registered_gallery_fake_faiss_cold_cache_does_not_self_deadlock():
    """Moving cold index construction back under the ordinary lock must fail."""
    result = _run_faiss_cold_cache_probe(real_faiss=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("faiss") is None,
    reason="faiss-cpu is optional and is not installed",
)
def test_registered_gallery_real_faiss_cold_cache_does_not_self_deadlock():
    """The installed FAISS implementation must obey the same cold-cache contract."""
    result = _run_faiss_cold_cache_probe(real_faiss=True)
    assert result.returncode == 0, result.stderr


def test_finalized_sticky_tracklet_commits_aggregate_without_reassociation():
    """Returning the bound Global without committing tail evidence must fail."""
    associator = MtmcAssociator(prototype_quality_thresh=0.0)
    first = _unit(1.0, 0.0)
    later = _unit(0.0, 1.0)
    space = ("vehicle-onnx", 2, "vehicle-v1.onnx")
    global_track = associator.associate(
        object_type="vehicle", camera_id=1, embedding=first,
        embedding_spaces={space: first}, association_model_key=space[0],
        model_version=space[2], local_track_id=7, now=1.0,
    )
    builder = TrackletBuilder.create(
        session_id="sticky-final", camera_id=1, object_type="vehicle",
        local_track_id=7, now=1.0,
    )
    builder.assigned_global_id = global_track.global_id
    builder.add_observation(
        bbox=[10, 10, 190, 110], conf=0.95, frame_h=120, frame_w=200,
        embedding=first, model_key=space[0], model_version=space[2],
        meta={"reidModelKey": space[0]}, now=1.0,
    )
    builder.add_observation(
        bbox=[10, 10, 190, 110], conf=0.99, frame_h=120, frame_w=200,
        embedding=later, model_key=space[0], model_version=space[2],
        meta={"reidModelKey": space[0]}, now=2.0,
    )
    builder.add_plate_observation("粤A12345", 0.92, quality=0.9, now=2.0)
    session = MtmcSession("sticky-final", MtmcConfig(camera_ids=[]), associator)

    finalized = mtmc_engine._finalize_tracklet(session, builder)

    assert finalized.global_id == global_track.global_id
    assert len(associator.tracks) == 1
    assert finalized.plate == "粤A12345"
    assert finalized.identity_key == "粤A12345"
    assert float(finalized.embedding_spaces[space][1]) > 0.05
    prototype = associator._gallery.prototype(
        "vehicle", global_track.global_id, camera_id=1,
        model_key=space[0], model_version=space[2],
    )
    assert prototype is not None and float(prototype[1]) > 0.05


def test_topology_uses_a_viable_camera_observation_not_last_summary_camera():
    """A later unrelated camera summary must not hide the actual source edge."""
    associator = MtmcAssociator(
        appear_thresh=0.4, vehicle_appear_thresh=0.4,
        confirm_thresh=0.4, candidate_thresh=0.2, lost_revive_sec=0.0,
    )
    associator.set_topology([
        {"fromCameraId": 1, "toCameraId": 2, "minTransitSec": 0,
         "maxTransitSec": 200, "edgeType": "overlap"},
        {"fromCameraId": 1, "toCameraId": 3, "minTransitSec": 5,
         "maxTransitSec": 30, "edgeType": "non_overlap"},
    ])
    emb = _unit(1.0, 0.0)
    original = associator.associate(
        object_type="vehicle", camera_id=1, embedding=emb,
        local_track_id=11, now=1.0,
    )
    associator.release_local("vehicle", 1, [11], now=2.0)
    on_other_camera = associator.associate(
        object_type="vehicle", camera_id=2, embedding=emb,
        local_track_id=22, now=10.0,
    )
    assert on_other_camera.global_id == original.global_id

    continued = associator.associate(
        object_type="vehicle", camera_id=3, embedding=emb,
        local_track_id=33, now=16.0,
    )

    assert continued.global_id == original.global_id
    assert associator.last_evidence.extra["sourceCameraId"] == 1
    assert associator.last_evidence.extra["sourceObservedAt"] == pytest.approx(1.0)


def test_sticky_expiry_uses_that_camera_binding_observation_time():
    """Another camera updating a Global must not refresh an old local binding."""
    associator = MtmcAssociator(local_sticky_sec=10.0)
    emb = _unit(1.0, 0.0)
    global_track = associator.associate(
        object_type="person", camera_id=1, embedding=emb,
        local_track_id=10, now=1.0,
    )
    associator._update_track(
        global_track, camera_id=2, embedding=emb,
        embedding_spaces=global_track.embedding_spaces,
        association_model_space=global_track.association_model_space,
        identity_key=None, plate=None, reid_person_id=None,
        face_person_id=None, display_name=None, visual_key=None,
        vehicle_class=None, local_track_id=20, now=100.0,
        mode=__import__("services.mtmc_associator", fromlist=["AssocMode"]).AssocMode.LONG_TERM,
    )

    assert associator.peek_sticky(
        object_type="person", camera_id=1, local_track_id=10, now=105.0,
    ) is None


def test_real_stream_misses_fewer_than_tracker_max_age_keep_builder():
    """A seconds grace shorter than max_age/sample_fps must not finalize early."""
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=False, enable_vehicle=True,
        det_vehicle_path="vehicle.pt", local_track_backend="iou",
        local_track_max_age=4, sample_fps=2, vehicle_reid_budget=0,
        plate_budget=0, lost_revive_sec=1.0,
    )
    session = MtmcSession("real-grace", cfg, MtmcAssociator())
    cam_state = CamState(camera_id=1)
    session.cams[1] = cam_state
    detections = [([], [_vehicle_detection()]), ([], []), ([], [])]
    with patch("services.mtmc_engine._detect_person_vehicle", side_effect=detections):
        _process_frame(session, cam_state, _frame(), {}, now=10.0)
        _process_frame(session, cam_state, _frame(), {}, now=10.5)
        _process_frame(session, cam_state, _frame(), {}, now=11.0)

    assert 1 in cam_state.vehicle_builders


def test_plate_samples_are_independent_and_cached_display_is_not_a_vote():
    """Replaying a display cache on every frame must not amplify one OCR result."""
    builder = TrackletBuilder.create(
        session_id="ocr", camera_id=1, object_type="vehicle",
        local_track_id=7, now=1.0,
    )
    assert builder.reserve_plate_sample(1.0, 0.3)
    builder.add_plate_observation("粤 A·O12B3", 0.60, quality=0.3, now=1.0)
    assert not builder.reserve_plate_sample(1.2, 0.3)
    assert builder.reserve_plate_sample(1.8, 0.5)
    builder.add_plate_observation("粤A01283", 0.90, quality=0.5, now=1.8)
    for now in (1.1, 1.2, 1.3, 1.4):
        builder.add_observation(
            bbox=[10, 10, 190, 110], conf=0.9,
            frame_h=120, frame_w=200,
            plate="粤 A·O12B3", plate_score=0.60, now=now,
        )

    assert len(builder.plate_observations) == 2
    plate, score = builder.aggregate_plate()
    assert plate == "粤A01283"
    assert score == pytest.approx(0.75)


def test_vehicle_identity_uses_reliable_plate_and_visual_key_is_diagnostic_only():
    """Exact float hashes must never become the durable vehicle identity key."""
    emb = _unit(1.0, 0.0)
    plated = vehicle_reid_feat.fuse_plate_visual(
        plate="粤A12345", plate_score=0.95, emb_a=emb, emb_b=emb,
        model_space_a=("vehicle-onnx", 2, "v1"),
        model_space_b=("vehicle-onnx", 2, "v1"),
    )
    unplated = vehicle_reid_feat.fuse_plate_visual(
        plate=None, emb_a=emb, emb_b=emb,
        model_space_a=("vehicle-onnx", 2, "v1"),
        model_space_b=("vehicle-onnx", 2, "v1"),
    )

    assert plated["identityKey"] == "粤A12345"
    assert plated["visualKey"].startswith("V")
    assert unplated["identityKey"] is None
    assert unplated["visualKey"].startswith("V")


def test_vehicle_visual_comparison_rejects_dimension_or_version_mismatch():
    """Padding or comparing different model versions must fail this contract."""
    assert vehicle_reid_feat.vehicle_candidate_score(
        _unit(1.0, 0.0), _unit(1.0, 0.0, 0.0),
        model_space_a=("vehicle-onnx", 2, "v1"),
        model_space_b=("vehicle-onnx", 3, "v1"),
    ) is None
    assert vehicle_reid_feat.vehicle_candidate_score(
        _unit(1.0, 0.0), _unit(1.0, 0.0),
        model_space_a=("vehicle-onnx", 2, "v1"),
        model_space_b=("vehicle-onnx", 2, "v2"),
    ) is None


def test_vehicle_engine_carries_exact_model_space_into_global():
    """Dropping extractor model metadata and storing a legacy space must fail."""
    cfg = MtmcConfig(
        camera_ids=[1], enable_person=False, enable_vehicle=True,
        det_vehicle_path="vehicle.pt", vehicle_reid_root="vehicle-reid",
        local_track_backend="iou", local_track_max_age=4,
        sample_fps=10, vehicle_reid_budget=1, plate_budget=0,
    )
    associator = MtmcAssociator(prototype_quality_thresh=0.0)
    session = MtmcSession("vehicle-space", cfg, associator)
    cam_state = CamState(camera_id=1)
    session.cams[1] = cam_state
    meta = {
        "backend": "vehicle-onnx", "onnx": "vehicle-v7.onnx",
        "dim": 2, "inputSize": "256x256",
    }
    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([], [_vehicle_detection()])):
        with patch("services.vehicle_reid_feat.extract_vehicle_embedding", return_value=(_unit(1, 0), meta)):
            _process_frame(session, cam_state, _frame(), {}, now=10.0)

    global_track = next(iter(associator.tracks.values()))
    assert global_track.association_model_space == ("vehicle-onnx", 2, "vehicle-v7.onnx")


def test_active_gallery_shortlist_carries_exact_model_space(monkeypatch):
    """Removing model key/version from a FAISS shortlist must fail."""
    class FakeIndex:
        ntotal = 1

        def search(self, _query, _topk):
            return np.asarray([[1.0]], np.float32), np.asarray([[0]], np.int64)

    gallery = MtmcActiveGallery()
    emb = _unit(1.0, 0.0)
    gallery.upsert(
        "vehicle", "V1", emb, camera_id=1,
        model_key="vehicle-onnx", model_version="v7",
    )
    monkeypatch.setattr("services.mtmc_active_gallery._import_faiss", lambda: object())
    bucket = ("vehicle", "vehicle-onnx", 2, "v7")
    gallery._index[bucket] = FakeIndex()
    gallery._gids[bucket] = ["V1"]
    gallery._dirty.discard(bucket)

    hits = gallery.search(
        "vehicle", emb, topk=1, model_key="vehicle-onnx",
        model_version="v7", include_space=True,
    )

    assert len(hits) == 1
    assert hits[0][0] == "V1"
    assert hits[0][1] == pytest.approx(1.0)
    assert hits[0][2] == ("vehicle-onnx", 2, "v7")


def test_external_stop_timeout_is_pending_and_schedules_eventual_finalizer(monkeypatch):
    """A live worker after join timeout is pending, not missing or complete."""
    scheduled: list[str] = []

    class Worker:
        def join(self, timeout=None):
            return None

        def is_alive(self):
            return True

    session = MtmcSession("stop-pending", MtmcConfig(camera_ids=[]), MtmcAssociator())
    session.running = True
    session._threads = [Worker()]
    monkeypatch.setitem(mtmc_engine._sessions, session.session_id, session)
    monkeypatch.setattr(
        mtmc_engine, "_schedule_post_worker_finalizer",
        lambda current: scheduled.append(current.session_id),
    )

    result = mtmc_engine.stop_session_status(session.session_id)

    assert result == {
        "status": "pending", "retryable": True, "accepted": False,
        "message": "workers are still stopping",
    }
    assert scheduled == [session.session_id]
    assert not session._stop_finalized


def test_finalization_failure_preserves_builder_and_does_not_mark_flushed(monkeypatch):
    """Popping before persistence success would make a retry impossible."""
    session = MtmcSession("flush-failed", MtmcConfig(camera_ids=[]), MtmcAssociator())
    cam_state = CamState(camera_id=1)
    builder = TrackletBuilder.create(
        session_id=session.session_id, camera_id=1, object_type="vehicle",
        local_track_id=7, now=1.0,
    )
    builder.add_observation(
        bbox=[10, 10, 190, 110], conf=0.95, frame_h=120, frame_w=200,
        embedding=_unit(1.0, 0.0), now=1.0,
    )
    cam_state.vehicle_builders[7] = builder
    monkeypatch.setattr(
        mtmc_engine, "_finalize_tracklet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db unavailable")),
    )

    with pytest.raises(RuntimeError, match="vehicle#7"):
        mtmc_engine._flush_camera_tracklets(session, cam_state)

    assert cam_state.vehicle_builders[7] is builder
    assert not cam_state.builders_flushed
    assert session.runtime_status["finalization"]["runtimeState"] == "failed"


def test_failed_stop_keeps_resources_and_can_be_retried(monkeypatch, tmp_path):
    """A finalization error must not delete uploads or claim a completed stop."""
    session = MtmcSession("retry-stop", MtmcConfig(camera_ids=[]), MtmcAssociator())
    session.running = True
    session._threads = []
    session.cams = {1: SimpleNamespace()}
    session.upload_dir = str(tmp_path)
    monkeypatch.setitem(mtmc_engine._sessions, session.session_id, session)
    cleanup: list[str] = []
    attempts = iter([RuntimeError("persist failed"), None])

    def flush(*_args):
        error = next(attempts)
        if error:
            raise error

    monkeypatch.setattr(mtmc_engine, "_flush_camera_tracklets", flush)
    monkeypatch.setattr("shutil.rmtree", lambda path: cleanup.append(path))

    failed = mtmc_engine.stop_session_status(session.session_id)
    assert failed["status"] == "failed"
    assert failed["retryable"] is True
    assert cleanup == []
    assert not session._stop_finalized

    stopped = mtmc_engine.stop_session_status(session.session_id)
    assert stopped["status"] == "stopped"
    assert cleanup == [str(tmp_path)]
    assert session._stop_finalized


@pytest.mark.parametrize(
    ("status", "http_status", "code"),
    [("not_found", 404, 404), ("pending", 202, 0), ("failed", 503, 503), ("stopped", 200, 0)],
)
def test_stop_route_preserves_each_structured_state(monkeypatch, status, http_status, code):
    """The HTTP boundary must not collapse pending/failed into not-found."""
    retryable = status in {"pending", "failed"}
    monkeypatch.setattr(
        mtmc_engine, "stop_session_status",
        lambda _sid: {"status": status, "retryable": retryable, "message": status},
    )
    app = Flask("stop-route-state")
    with app.test_request_context("/api/ai/mtmc/sessions/s/stop", method="POST"):
        result = mtmc_routes.stop_session.__wrapped__("s")
    response, actual_status = result if isinstance(result, tuple) else (result, 200)

    assert actual_status == http_status
    assert response.get_json()["code"] == code
    assert response.get_json()["data"]["status"] == status


def test_candidate_db_row_exposes_complete_score_breakdown():
    """Persisted candidates must be as inspectable as live candidates."""
    row = MtmcCandidatePair(
        session_id="s", global_id="new", candidate_global_id="known",
        object_type="vehicle", final_score=0.7, reid_score=0.8,
        evidence_json=(
            '{"bestScore":0.7,"secondBestScore":0.65,"matchMargin":0.05,'
            '"reid":0.8,"topology":1.0,"time":0.5,"final":0.7}'
        ),
    )

    public = row.to_dict()

    assert public["bestScore"] == pytest.approx(0.7)
    assert public["secondBestScore"] == pytest.approx(0.65)
    assert public["matchMargin"] == pytest.approx(0.05)
    assert public["appearanceScore"] == pytest.approx(0.8)
    assert public["topologyScore"] == pytest.approx(1.0)
    assert public["timeScore"] == pytest.approx(0.5)
