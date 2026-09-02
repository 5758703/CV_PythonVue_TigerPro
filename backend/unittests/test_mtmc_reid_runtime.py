"""Runtime contracts for isolated MTMC person ReID model spaces."""
from __future__ import annotations

import numpy as np
import pytest

from services import reid_gallery
from services import strong_reid
from services.mtmc_engine import _match_gallery


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
