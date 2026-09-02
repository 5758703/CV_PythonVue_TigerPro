"""Runtime contracts for isolated MTMC person ReID model spaces."""
from __future__ import annotations

import numpy as np
import pytest

from services import reid_gallery
from services import strong_reid
from services.mtmc_associator import MtmcAssociator
from services import mtmc_engine
from services.mtmc_engine import MtmcConfig, _match_gallery
from services.mtmc_tracklet import TrackletBuilder


class _FakeInput:
    name = "images"
    shape = [1, 3, 256, 128]


class _FakeOutput:
    name = "embedding"


class _FakeSession:
    def __init__(self):
        self.blob = None

    def get_inputs(self):
        return [_FakeInput()]

    def get_outputs(self):
        return [_FakeOutput()]

    def run(self, _outputs, inputs):
        self.blob = inputs["images"]
        return [np.array([[3.0, 4.0]], dtype=np.float32)]


def test_onnx_nchw_shape_is_used_without_model_type_guessing(monkeypatch):
    """Changing a declared 256x128 input to square preprocessing must fail."""
    session = _FakeSession()
    monkeypatch.setattr(strong_reid, "_get_ort", lambda _path: session)

    strong_reid._infer_onnx("person.onnx", np.zeros((80, 40, 3), dtype=np.uint8))

    assert session.blob.shape == (1, 3, 256, 128)


def test_person_embeddings_keep_strong_and_youtu_in_separate_model_spaces(monkeypatch):
    """Replacing per-space embeddings with a padded or averaged vector must fail."""
    monkeypatch.setattr(strong_reid, "resolve_strong_onnx", lambda _root: "C:/models/osnet_x1_0.onnx")
    monkeypatch.setattr(strong_reid, "_infer_onnx", lambda _path, _image: np.array([3.0, 4.0]))
    monkeypatch.setattr(
        strong_reid,
        "extract_youtu",
        lambda _root, _image: (np.array([1.0, 2.0, 2.0]), {"modelVersion": "youtu-v1"}),
    )

    spaces, meta = strong_reid.extract_person_embeddings(
        np.zeros((32, 16, 3), dtype=np.uint8), strong_root="models", youtu_root="youtu"
    )

    assert set(spaces) == {"osnet-x1-0", "opencv-person-reid-youtu"}
    assert spaces["osnet-x1-0"].shape == (2,)
    assert spaces["opencv-person-reid-youtu"].shape == (3,)
    assert meta["backends"]["strong"]["ready"] is True
    assert meta["backends"]["youtu"]["ready"] is True


def test_person_embeddings_report_failed_backend_and_keep_available_space(monkeypatch):
    """Dropping all embeddings after one backend fails must fail."""
    monkeypatch.setattr(strong_reid, "extract_strong", lambda _root, _image: (None, {"strongError": "bad model"}))
    monkeypatch.setattr(
        strong_reid,
        "extract_youtu",
        lambda _root, _image: (np.array([1.0, 2.0, 2.0]), {"modelVersion": "youtu-v1"}),
    )

    spaces, meta = strong_reid.extract_person_embeddings(
        np.zeros((32, 16, 3), dtype=np.uint8), strong_root="models", youtu_root="youtu"
    )

    assert set(spaces) == {"opencv-person-reid-youtu"}
    assert meta["backends"]["strong"] == {"ready": False, "error": "bad model"}
    assert meta["backends"]["youtu"]["ready"] is True


def test_gallery_lookup_receives_only_its_matching_model_space(monkeypatch):
    """Passing any embedding to a different gallery model key must fail."""
    calls = []

    def fake_match(embedding, model_key, threshold):
        calls.append((model_key, tuple(embedding.tolist())))
        return {
            "personId": model_key,
            "facePersonId": None,
            "name": model_key,
            "score": 0.9 if model_key == "osnet-x1-0" else 0.8,
            "matched": True,
        }

    monkeypatch.setattr(reid_gallery, "match_embedding_faiss", fake_match)

    result = _match_gallery(
        {
            "osnet-x1-0": np.array([1.0, 0.0]),
            "opencv-person-reid-youtu": np.array([0.0, 1.0, 0.0]),
        },
        threshold=0.45,
    )

    assert calls == [
        ("osnet-x1-0", (1.0, 0.0)),
        ("opencv-person-reid-youtu", (0.0, 1.0, 0.0)),
    ]
    assert result["modelKey"] == "osnet-x1-0"


def test_fuse_similarity_scores_renormalizes_available_weights():
    """Treating a missing calibrated score as zero without weight normalization must fail."""
    assert strong_reid.fuse_similarity_scores(
        {"strong": 0.8, "youtu": None}, {"strong": 0.65, "youtu": 0.35}
    ) == pytest.approx(0.8)
    assert strong_reid.fuse_similarity_scores(
        {"strong": 0.8, "youtu": 0.4}, {"strong": 0.65, "youtu": 0.35}
    ) == pytest.approx(0.66)
    assert strong_reid.fuse_similarity_scores({"strong": None}, {"strong": 1.0}) is None


def test_tracklet_keeps_strong_and_youtu_fallback_prototypes_separate():
    """A Strong outage followed by Youtu must not average their vectors."""
    builder = TrackletBuilder.create(
        session_id="s", camera_id=1, object_type="person", local_track_id=7, now=1.0,
    )
    builder.add_observation(
        bbox=[0, 0, 160, 240], conf=0.9, frame_h=300, frame_w=300,
        embedding=np.array([1.0, 0.0]), model_key="osnet-x1-0", now=1.0,
    )
    builder.add_observation(
        bbox=[0, 0, 160, 240], conf=0.9, frame_h=300, frame_w=300,
        embedding=np.array([0.0, 1.0, 0.0]), model_key="opencv-person-reid-youtu", now=2.0,
    )

    spaces = builder.aggregate_embedding_spaces()

    assert set(spaces) == {("osnet-x1-0", 2, None), ("opencv-person-reid-youtu", 3, None)}
    np.testing.assert_allclose(spaces[("osnet-x1-0", 2, None)], [1.0, 0.0])
    np.testing.assert_allclose(spaces[("opencv-person-reid-youtu", 3, None)], [0.0, 1.0, 0.0])


def test_global_prototypes_only_compare_matching_model_space():
    """A same-looking Youtu vector cannot revive a Global containing only Strong."""
    assoc = MtmcAssociator(appear_thresh=0.45, confirm_thresh=0.45, time_window_sec=30)
    strong = assoc.associate(
        object_type="person", camera_id=1, local_track_id=1, now=1.0,
        embedding_spaces={"osnet-x1-0": np.array([1.0, 0.0])},
        association_model_key="osnet-x1-0",
    )
    fallback = assoc.associate(
        object_type="person", camera_id=2, local_track_id=1, now=2.0,
        embedding_spaces={"opencv-person-reid-youtu": np.array([1.0, 0.0, 0.0])},
        association_model_key="opencv-person-reid-youtu", force_long_term=True,
    )

    assert fallback.global_id != strong.global_id
    assert set(strong.embedding_spaces) == {("osnet-x1-0", 2, None)}


def test_matching_gallery_scores_fuse_per_identity_using_configured_weights(monkeypatch):
    """The production gallery decision must use calibrated score fusion, not raw max."""
    def fake_match(_embedding, model_key, threshold):
        score = {"osnet-x1-0": 0.8, "opencv-person-reid-youtu": 0.4}[model_key]
        return {"personId": 9, "facePersonId": None, "name": "Ada", "score": score, "matched": score >= threshold}

    monkeypatch.setattr(reid_gallery, "match_embedding_faiss", fake_match)
    embeddings = {
        "osnet-x1-0": np.array([1.0, 0.0]),
        "opencv-person-reid-youtu": np.array([0.0, 1.0, 0.0]),
    }
    cfg = MtmcConfig(camera_ids=[], fuse_weight_strong=0.75)

    result = _match_gallery(embeddings, threshold=0.3, score_weights=mtmc_engine._reid_score_weights(cfg, embeddings))

    assert result["personId"] == 9
    assert result["score"] == pytest.approx(0.7)
    assert result["scoreByModelKey"] == {"osnet-x1-0": 0.8, "opencv-person-reid-youtu": 0.4}


def test_gallery_cache_and_query_are_dimension_scoped(monkeypatch):
    """Changing a same-key query's dimension must select a separate gallery cache entry."""
    calls = []

    def fake_load(model_key, modality, dim):
        calls.append((model_key, modality, dim))
        return [], [], np.zeros((0, dim), dtype=np.float32), []

    monkeypatch.setattr(reid_gallery, "_load_gallery", fake_load)
    reid_gallery.invalidate_gallery()

    reid_gallery.get_gallery("osnet-x1-0", dim=2)
    reid_gallery.get_gallery("osnet-x1-0", dim=3)

    assert calls == [("osnet-x1-0", "appearance", 2), ("osnet-x1-0", "appearance", 3)]


def test_runtime_metadata_reports_actual_spaces_and_selected_keys(monkeypatch):
    """Reporting Strong after it fails must fail instead of hiding the fallback."""
    monkeypatch.setattr(strong_reid, "extract_strong", lambda _root, _image: (None, {"strongError": "offline"}))
    monkeypatch.setattr(
        strong_reid, "extract_youtu", lambda _root, _image: (np.array([1.0, 0.0, 0.0]), {"modelVersion": "y1"}),
    )

    spaces, meta = strong_reid.extract_person_embeddings(
        np.zeros((10, 10, 3), dtype=np.uint8), strong_root="s", youtu_root="y"
    )

    assert meta["availableModelSpaces"] == ["opencv-person-reid-youtu"]
    assert meta["associationModelKey"] == "opencv-person-reid-youtu"
    assert meta["activeBackend"] == "youtu"
