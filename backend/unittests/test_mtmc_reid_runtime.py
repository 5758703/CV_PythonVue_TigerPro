"""Runtime contracts for isolated MTMC person ReID model spaces."""
from __future__ import annotations

import numpy as np
import pytest
import sys
import types

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

    def fake_load(model_key, modality, dim, model_version=None):
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


def test_gallery_fuses_raw_scores_before_applying_the_final_threshold(monkeypatch):
    """A valid fused identity must retain a below-threshold per-space score."""
    def fake_match(_embedding, model_key, threshold):
        score = {"osnet-x1-0": 0.8, "opencv-person-reid-youtu": 0.4}[model_key]
        return {"personId": 11, "facePersonId": None, "name": "Lin", "score": score, "matched": score >= threshold}

    monkeypatch.setattr(reid_gallery, "match_embedding_faiss", fake_match)
    result = _match_gallery(
        {"osnet-x1-0": np.array([1.0, 0.0]), "opencv-person-reid-youtu": np.array([0.0, 1.0])},
        threshold=0.48,
        score_weights={"osnet-x1-0": 0.75, "opencv-person-reid-youtu": 0.25},
    )

    assert result["matched"] is True
    assert result["score"] == pytest.approx(0.7)
    assert result["scoreByModelKey"] == {"osnet-x1-0": 0.8, "opencv-person-reid-youtu": 0.4}


def test_tracklet_separates_same_key_and_dim_when_model_versions_differ():
    """Dropping model version must not average embeddings from different assets."""
    builder = TrackletBuilder.create(
        session_id="s", camera_id=1, object_type="person", local_track_id=9, now=1.0,
    )
    builder.add_observation(
        bbox=[0, 0, 160, 240], conf=0.9, frame_h=300, frame_w=300,
        embedding_spaces={"clip-reid-person": np.array([1.0, 0.0])},
        embedding_space_versions={"clip-reid-person": "clip-v1"}, now=1.0,
    )
    builder.add_observation(
        bbox=[0, 0, 160, 240], conf=0.9, frame_h=300, frame_w=300,
        embedding_spaces={"clip-reid-person": np.array([0.0, 1.0])},
        embedding_space_versions={"clip-reid-person": "clip-v2"}, now=2.0,
    )

    assert set(builder.aggregate_embedding_spaces()) == {
        ("clip-reid-person", 2, "clip-v1"),
        ("clip-reid-person", 2, "clip-v2"),
    }


def test_extraction_returns_a_model_version_for_each_available_space(monkeypatch):
    """Losing Youtu's version before Tracklet persistence must fail."""
    monkeypatch.setattr(strong_reid, "extract_strong", lambda _root, _image: (np.array([1.0, 0.0]), {
        "modelKey": "osnet-x1-0", "modelVersion": "osnet-v1",
    }))
    monkeypatch.setattr(strong_reid, "extract_youtu", lambda _root, _image: (np.array([0.0, 1.0]), {
        "modelVersion": "youtu-v3",
    }))

    _spaces, meta = strong_reid.extract_person_embeddings(np.zeros((10, 10, 3), dtype=np.uint8))

    assert meta["modelVersionsBySpace"] == {
        "osnet-x1-0": "osnet-v1", "opencv-person-reid-youtu": "youtu-v3",
    }


@pytest.mark.parametrize(
    ("fuse_weight_strong", "available_space", "expected_weight"),
    [(1.0, "opencv-person-reid-youtu", 1.0), (0.0, "osnet-x1-0", 1.0)],
)
def test_single_available_backend_weight_is_always_one(fuse_weight_strong, available_space, expected_weight):
    """A missing configured backend cannot zero out the remaining backend."""
    weights = mtmc_engine._reid_score_weights(
        MtmcConfig(camera_ids=[], fuse_weight_strong=fuse_weight_strong),
        {available_space: np.array([1.0, 0.0])},
    )

    assert weights == {available_space: expected_weight}


def test_gallery_fusion_returns_the_actual_winning_identity(monkeypatch):
    """Different per-space Top-1 identities must return the winning score group."""
    calls = []

    def fake_match(_embedding, model_key, threshold, model_version=None):
        calls.append((model_key, model_version))
        if model_key == "osnet-x1-0":
            return {"candidatePersonId": 101, "candidateName": "Winner", "score": 0.9, "matched": True}
        return {"candidatePersonId": 202, "candidateName": "Other", "score": 0.7, "matched": True}

    monkeypatch.setattr(reid_gallery, "match_embedding_faiss", fake_match)
    result = _match_gallery(
        {"osnet-x1-0": np.array([1.0, 0.0]), "opencv-person-reid-youtu": np.array([0.0, 1.0])},
        threshold=0.5,
        model_versions_by_space={"osnet-x1-0": "osnet-v1", "opencv-person-reid-youtu": "youtu-v2"},
    )

    assert result["personId"] == 101
    assert result["name"] == "Winner"
    assert calls == [("osnet-x1-0", "osnet-v1"), ("opencv-person-reid-youtu", "youtu-v2")]


@pytest.mark.parametrize("raw, expected", [(None, 0.65), (0, 0.0), (-2, 0.0), (3, 1.0)])
def test_fuse_weight_preserves_explicit_zero_and_is_bounded(raw, expected):
    assert mtmc_engine.normalize_fuse_weight_strong(raw) == expected


def test_gallery_cache_is_model_version_scoped(monkeypatch):
    calls = []

    def fake_load(model_key, modality, dim, model_version):
        calls.append((model_key, modality, dim, model_version))
        return [], [], np.zeros((0, dim), dtype=np.float32), []

    monkeypatch.setattr(reid_gallery, "_load_gallery", fake_load)
    reid_gallery.invalidate_gallery()
    reid_gallery.get_gallery("clip-reid-person", dim=2, model_version="v1")
    reid_gallery.get_gallery("clip-reid-person", dim=2, model_version="v2")
    reid_gallery.get_gallery("clip-reid-person", dim=2, model_version=None)

    assert calls == [
        ("clip-reid-person", "appearance", 2, "v1"),
        ("clip-reid-person", "appearance", 2, "v2"),
        ("clip-reid-person", "appearance", 2, None),
    ]


def test_gallery_match_forwards_explicit_model_version(monkeypatch):
    calls = []

    def fake_gallery(model_key, modality, dim, model_version):
        calls.append((model_key, modality, dim, model_version))
        return [1], ["Ada"], np.array([[1.0, 0.0]], dtype=np.float32), [None]

    monkeypatch.setattr(reid_gallery, "get_gallery", fake_gallery)
    result = reid_gallery.match_embedding(
        np.array([1.0, 0.0]), "clip-reid-person", model_version="weights-v7", threshold=0.5,
    )

    assert result["personId"] == 1
    assert calls == [("clip-reid-person", "appearance", 2, "weights-v7")]


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), float("-inf"), "nan"])
def test_fuse_weight_non_finite_values_use_safe_default(raw):
    assert mtmc_engine.normalize_fuse_weight_strong(raw) == 0.65


def test_association_score_fusion_keeps_full_versioned_space_keys():
    scores = {
        ("clip-reid-person", 2, "v1"): 0.9,
        ("clip-reid-person", 2, "v2"): 0.1,
    }
    result = MtmcAssociator._fuse_space_scores(scores, {"clip-reid-person": 1.0})
    assert result == pytest.approx(0.5)


def test_gallery_failure_is_structured_and_visible_in_runtime():
    class Session:
        def __init__(self):
            self.runtime_status = {}

    session = Session()
    meta = {}
    mtmc_engine._record_gallery_failure(session, meta, RuntimeError("index corrupt"))

    assert meta["gallery"] == {"ready": False, "degraded": True, "error": "index corrupt"}
    assert session.runtime_status["gallery"] == {
        "ready": False, "degraded": True, "error": "index corrupt", "errorCount": 1,
    }


def test_recognize_and_search_forward_extracted_onnx_version(monkeypatch):
    import inference
    import person_reid_dnn

    image = np.zeros((8, 4, 3), dtype=np.uint8)
    monkeypatch.setattr(inference, "_decode_bgr", lambda _raw: image)
    monkeypatch.setattr(
        person_reid_dnn, "extract_feature",
        lambda _root, _crop: (np.array([1.0, 0.0]), {"onnx": "person_reid_v7.onnx", "backend": "fake"}),
    )
    calls = []
    monkeypatch.setattr(
        reid_gallery, "match_embedding",
        lambda emb, key, threshold, model_version=None: calls.append(("match", model_version)) or {
            "personId": 1, "name": "Ada", "score": 1.0, "matched": True,
        },
    )
    monkeypatch.setattr(
        reid_gallery, "topk_match",
        lambda emb, key, topk, model_version=None: calls.append(("topk", model_version)) or [{"personId": 1}],
    )

    recognized = inference.recognize_persons("root", "youtu", b"image", draw=False)
    searched = inference.search_reid_gallery("root", "youtu", b"image")

    assert recognized["detections"][0]["personId"] == 1
    assert searched["matches"][0]["personId"] == 1
    assert calls == [("match", "person_reid_v7.onnx"), ("topk", "person_reid_v7.onnx")]


def test_gallery_match_reports_partial_backend_errors(monkeypatch):
    def faiss(_emb, key, threshold, model_version=None):
        if key == "broken":
            raise RuntimeError("faiss broken")
        return {"candidatePersonId": 1, "candidateName": "Ada", "score": 0.9}

    def plain(_emb, key, threshold, model_version=None):
        raise RuntimeError("sql broken")

    monkeypatch.setattr(reid_gallery, "match_embedding_faiss", faiss)
    monkeypatch.setattr(reid_gallery, "match_embedding", plain)
    result = _match_gallery({"good": np.ones(2), "broken": np.ones(2)}, 0.5)
    assert result["matched"] is True
    assert result["degraded"] is True
    assert result["errorsByModelKey"]["broken"] == ["faiss broken", "sql broken"]


def test_gallery_match_reports_total_backend_failure(monkeypatch):
    monkeypatch.setattr(
        reid_gallery, "match_embedding_faiss",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("faiss unavailable")),
    )
    monkeypatch.setattr(
        reid_gallery, "match_embedding",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("sql unavailable")),
    )

    result = _match_gallery({"osnet-x1-0": np.ones(2)}, 0.5)

    assert result["ready"] is False
    assert result["degraded"] is True
    assert result["errorsByModelKey"]["osnet-x1-0"] == ["faiss unavailable", "sql unavailable"]


def test_model_family_weight_is_split_across_versions():
    spaces = {
        ("osnet-x1-0", 2, "v1"): 0.9,
        ("osnet-x1-0", 2, "v2"): 0.7,
        ("opencv-person-reid-youtu", 3, "y1"): 0.4,
    }
    weights = MtmcAssociator._space_score_weights(spaces, {
        "osnet-x1-0": 0.65, "opencv-person-reid-youtu": 0.35,
    })
    assert weights == {
        ("osnet-x1-0", 2, "v1"): pytest.approx(0.325),
        ("osnet-x1-0", 2, "v2"): pytest.approx(0.325),
        ("opencv-person-reid-youtu", 3, "y1"): pytest.approx(0.35),
    }


def test_runtime_gallery_success_does_not_erase_other_camera_failure():
    import threading

    class Session:
        runtime_status = {}
        runtime_status_lock = threading.Lock()

    session = Session()
    session.runtime_status = {}
    barrier = threading.Barrier(2)

    def fail_camera_one():
        barrier.wait()
        mtmc_engine._record_gallery_failure(
            session, {}, RuntimeError("cam1"), camera_id=1,
            errors_by_space={"osnet": ["faiss broken", "sql broken"]},
        )

    def pass_camera_two():
        barrier.wait()
        mtmc_engine._record_gallery_ready(session, {}, camera_id=2)

    threads = [threading.Thread(target=fail_camera_one), threading.Thread(target=pass_camera_two)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert session.runtime_status["gallery"]["errorCount"] == 1
    assert session.runtime_status["gallery"]["errorsByCamera"]["1"] == "cam1"
    assert session.runtime_status["gallery"]["errorsBySpace"]["1"] == {
        "osnet": ["faiss broken", "sql broken"],
    }
    assert session.runtime_status["gallery"]["degraded"] is True


def test_runtime_status_snapshot_is_detached_from_concurrent_state():
    class Associator:
        @staticmethod
        def list_candidates():
            return []

        @staticmethod
        def snapshot():
            return []

    session = mtmc_engine.MtmcSession("s1", MtmcConfig(camera_ids=[]), Associator())
    session.runtime_status["gallery"] = {"errorsByCamera": {"1": "broken"}}

    snapshot = session.to_dict()["runtime"]
    session.runtime_status["gallery"]["errorsByCamera"]["2"] = "later"

    assert snapshot == {"gallery": {"errorsByCamera": {"1": "broken"}}}


def test_video_search_forwards_exact_extracted_model_version(monkeypatch):
    import inference
    import person_reid_dnn

    frame = np.zeros((8, 4, 3), dtype=np.uint8)

    class Capture:
        def __init__(self, _path):
            self.frames = [frame]

        def isOpened(self):
            return True

        def get(self, _prop):
            return 1.0

        def read(self):
            return (True, self.frames.pop(0)) if self.frames else (False, None)

        def release(self):
            return None

    monkeypatch.setattr(inference, "_decode_bgr", lambda _raw: frame)
    monkeypatch.setattr(inference.cv2, "VideoCapture", Capture)
    monkeypatch.setattr(inference, "search_reid_gallery", lambda *_args, **_kwargs: {"matches": []})
    monkeypatch.setattr(
        person_reid_dnn, "extract_feature",
        lambda _root, _crop: (np.array([1.0, 0.0]), {"onnx": "person_reid_v9.onnx"}),
    )
    versions = []
    monkeypatch.setattr(
        reid_gallery, "match_embedding",
        lambda _emb, _key, threshold, model_version=None: versions.append(model_version) or {"matched": False},
    )

    inference.search_reid_in_video("root", "youtu", b"query", "video.mp4", max_frames=1)

    assert versions == ["person_reid_v9.onnx"]
