"""Vehicle model outputs and revisions must not contaminate association spaces."""
from types import SimpleNamespace

import numpy as np
import pytest

from services import vehicle_reid_feat as features
from services.mtmc_engine import _vehicle_embedding_space


class Session:
    def __init__(self, output):
        self.output = output

    def get_inputs(self):
        return [SimpleNamespace(name="images", shape=[1, 3, 32, 16], type="tensor(float)")]

    def get_outputs(self):
        return [SimpleNamespace(name="embedding")]

    def run(self, outputs, feed):
        assert feed["images"].shape == (1, 3, 32, 16)
        return [self.output]


@pytest.mark.parametrize("output", [np.array([[np.nan, 1]]), np.array([[np.inf, 1]]),
                                   np.zeros((1, 4)), np.empty((1, 0)), np.ones((2, 3))])
def test_invalid_model_output_is_reported_as_degraded(monkeypatch, output):
    monkeypatch.setattr(features, "resolve_vehicle_onnx", lambda p: "broken.onnx")
    monkeypatch.setattr(features, "_get_ort", lambda p: Session(output))
    emb, meta = features.extract_vehicle_embedding("broken.onnx", np.zeros((64, 64, 3), dtype=np.uint8))
    assert meta["backend"] == "hist-fallback"
    assert meta["onnxError"]
    assert np.isfinite(emb).all()


def test_model_revision_is_part_of_vehicle_association_space():
    emb = np.ones(512, dtype=np.float32)
    before = _vehicle_embedding_space({"backend": "vehicle-onnx", "onnx": "model.onnx", "modelVersion": "sha256:old"}, emb)
    after = _vehicle_embedding_space({"backend": "vehicle-onnx", "onnx": "model.onnx", "modelVersion": "sha256:new"}, emb)
    assert before != after


def test_histogram_is_independent_of_crop_pixel_count():
    # Same colours with the same proportions, at different camera distances.
    image = np.full((20, 40, 3), [40, 110, 190], dtype=np.uint8)
    enlarged = np.repeat(np.repeat(image, 4, axis=0), 4, axis=1)
    assert np.allclose(features._color_hist_embedding(image), features._color_hist_embedding(enlarged), atol=1e-6)


def test_auxiliary_inputs_follow_declared_dtype_and_shape():
    session = SimpleNamespace(get_inputs=lambda: [
        SimpleNamespace(name="images", shape=[1, 3, 32, 16], type="tensor(float)"),
        SimpleNamespace(name="cam", shape=[1, 1], type="tensor(int32)"),
    ])
    feed = features._build_feed(session, np.zeros((1, 3, 32, 16), dtype=np.float32))
    assert feed["cam"].shape == (1, 1)
    assert feed["cam"].dtype == np.int32


def test_model_digest_changes_when_weight_revision_changes(tmp_path):
    path = tmp_path / "model.onnx"
    path.write_bytes(b"first revision")
    before = features.model_version(str(path))
    path.write_bytes(b"a different second revision")
    after = features.model_version(str(path))
    assert before != after


def test_session_cache_replaces_stale_weights_and_has_a_bound(monkeypatch, tmp_path):
    import sys
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=lambda *a, **k: object()))
    monkeypatch.setattr(features, "_sess_cache", features.OrderedDict())
    path = tmp_path / "vehicle.onnx"
    path.write_bytes(b"first")
    first = features._get_ort(str(path))
    assert features._get_ort(str(path)) is first
    path.write_bytes(b"replacement")
    assert features._get_ort(str(path)) is not first
    assert len(features._sess_cache) == 1
    for index in range(6):
        other = tmp_path / f"{index}.onnx"
        other.write_bytes(b"weights")
        features._get_ort(str(other))
    assert len(features._sess_cache) == features._MAX_CACHED_SESSIONS


def test_vehicle_class_does_not_change_when_camera_distance_changes():
    for bbox in ([10, 10, 80, 60], [10, 10, 600, 350]):
        assert features.infer_vehicle_class("car", bbox, frame_h=360, frame_w=640) == "car"


def test_live_vehicle_binding_refreshes_time_and_new_camera_prototype(monkeypatch):
    from services import mtmc_engine as engine
    from services.mtmc_associator import MtmcAssociator
    from services.mtmc_local_track import LocalTracker
    from services import vehicle_reid_feat

    session = engine.MtmcSession("vehicle-live", engine.MtmcConfig(
        camera_ids=[1], enable_person=False, det_vehicle_path="det.pt", sample_fps=2,
        plate_budget=0,
    ), MtmcAssociator(use_faiss_gallery=False, local_sticky_sec=2))
    state = engine.CamState(camera_id=1)
    session.cams[1] = state
    state.tracker_person = LocalTracker()
    state.tracker_vehicle = LocalTracker()
    monkeypatch.setattr(engine, "_detect", lambda *a, **k: [
        {"bbox": [20, 10, 170, 100], "className": "car", "classId": 2, "confidence": 0.95}])
    vectors = iter([np.array([1., 0.]), np.array([0.8, 0.6]), np.array([0.6, 0.8])])
    monkeypatch.setattr(vehicle_reid_feat, "extract_vehicle_embedding", lambda *a: (
        next(vectors), {"backend": "vehicle-onnx", "onnx": "model.onnx", "modelVersion": "test-v1"}))
    gids = []
    for timestamp in (100., 101.5, 103.):
        engine._process_frame(session, state, np.zeros((120, 200, 3), dtype=np.uint8), {}, now=timestamp)
        gids.append(state.last_dets[0]["globalId"])
    assert len(set(gids)) == 1
    global_track = session.associator.get_track(gids[0])
    assert global_track.camera_observations[1].last_observed_at == 103.
    prototype = session.associator._gallery.prototype("vehicle", gids[0], camera_id=1, model_key="vehicle-onnx", model_version="test-v1")
    assert prototype[1] > 0.05


def test_vehicle_refresh_does_not_confirm_candidate_or_update_wrong_binding():
    from services.mtmc_associator import MtmcAssociator
    assoc = MtmcAssociator(appear_thresh=0.5, confirm_thresh=0.95,
                          candidate_thresh=0.5, min_match_margin=0, use_faiss_gallery=False)
    confirmed = assoc.associate(object_type="vehicle", camera_id=1, local_track_id=1,
                                embedding=np.array([1., 0.]), now=100.)
    candidate = assoc.associate(object_type="vehicle", camera_id=2, local_track_id=2,
                                embedding=np.array([0.8, 0.6]), now=100.5)
    assert not candidate.confirmed
    result = assoc.observe_bound_vehicle(global_id=candidate.global_id, camera_id=2,
                                         local_track_id=2, embedding=np.array([0.8, 0.6]), now=101.)
    assert not result.confirmed
    assert assoc._gallery.prototype_count("vehicle", candidate.global_id) == 0
    assert assoc.observe_bound_vehicle(global_id=confirmed.global_id, camera_id=2,
                                       local_track_id=2, now=101.5) is None


def test_cached_vehicle_refresh_updates_time_without_replaying_old_embedding():
    from services.mtmc_associator import MtmcAssociator
    assoc = MtmcAssociator(use_faiss_gallery=False)
    original = assoc.associate(object_type="vehicle", camera_id=1, local_track_id=1,
                               embedding=np.array([1., 0.]), now=100.)
    before = original.embedding.copy()
    updated = assoc.observe_bound_vehicle(global_id=original.global_id, camera_id=1,
                                          local_track_id=1, now=102.)
    assert updated.last_seen == 102.
    assert np.array_equal(updated.embedding, before)
