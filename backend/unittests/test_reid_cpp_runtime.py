"""Runtime selection and native ABI integration (real graphs, no model download)."""
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from services import reid_runtime


def test_runtime_default_preserves_legacy(monkeypatch):
    monkeypatch.delenv("REID_RUNTIME", raising=False)
    assert reid_runtime.runtime_name(None) == "python"
    assert reid_runtime.runtime_name("cpp") == "cpp"
    with pytest.raises(ValueError, match="python.*cpp.*auto"):
        reid_runtime.runtime_name("cuda")


def test_python_never_loads_native_library(monkeypatch):
    monkeypatch.setattr(reid_runtime, "_native_extract", lambda *a, **k: pytest.fail("native called"))
    feature = np.array([1, 2], dtype=np.float32)
    result, meta = reid_runtime.extract_youtu("model", np.zeros((2, 2, 3), np.uint8),
                                             legacy=lambda: (feature, {"backend": "legacy"}))
    np.testing.assert_array_equal(result, feature)
    assert meta["backend"] == "legacy"


def test_strict_failure_and_auto_fallback_are_visible(monkeypatch):
    import person_reid_dnn
    monkeypatch.setattr(person_reid_dnn, "resolve_onnx", lambda *a, **k: "model.onnx")
    def unavailable(*args, **kwargs):
        raise RuntimeError("native library unavailable")
    monkeypatch.setattr(reid_runtime, "_native_extract", unavailable)
    image = np.zeros((2, 2, 3), np.uint8)
    legacy = lambda: (np.ones(3, np.float32), {"backend": "legacy"})
    with pytest.raises(RuntimeError, match="unavailable"):
        reid_runtime.extract_youtu("model", image, runtime="cpp", legacy=legacy)
    _, meta = reid_runtime.extract_youtu("model", image, runtime="auto", legacy=legacy)
    assert meta["requestedRuntime"] == "auto"
    assert meta["effectiveRuntime"] == "python"
    assert meta["degraded"] is True
    assert "unavailable" in meta["fallbackReason"]


def test_runtime_summary_preserves_earlier_fallback():
    native = {"provider": "onnxruntime-cpp-cpu", "effectiveRuntime": "cpp", "modelVersion": "v1"}
    fallback = {"provider": "opencv", "effectiveRuntime": "python", "degraded": True,
                "fallbackReason": "frame failed", "modelVersion": "v1"}
    summary = reid_runtime.summarize_runtime([native, fallback, native])
    assert summary["effectiveRuntime"] == "mixed"
    assert summary["provider"] == "mixed"
    assert summary["degraded"] is True
    assert summary["fallbackReason"] == "frame failed"
    assert summary["callCount"] == 3


def test_video_runtime_includes_frame_batch_fallback(monkeypatch):
    import inference
    import person_reid_dnn
    from services import reid_gallery
    image = np.zeros((12, 8, 3), np.uint8)
    native = {"provider": "onnxruntime-cpp-cpu", "effectiveRuntime": "cpp"}
    fallback = {"provider": "opencv", "effectiveRuntime": "python", "degraded": True,
                "fallbackReason": "batch failed"}
    class Capture:
        def isOpened(self): return True
        def get(self, key): return 25
        def read(self): return True, image
        def release(self): pass
    monkeypatch.setattr(inference.cv2, "VideoCapture", lambda _: Capture())
    monkeypatch.setattr(inference, "_decode_bgr", lambda _: image)
    monkeypatch.setattr(inference, "search_reid_gallery", lambda *a, **k: {"runtime": native})
    monkeypatch.setattr(person_reid_dnn, "extract_feature", lambda *a, **k: (np.ones(3), native))
    monkeypatch.setattr(reid_runtime, "extract_youtu_batch", lambda *a, **k: (np.ones((1, 3)), fallback))
    monkeypatch.setattr(reid_gallery, "match_embedding", lambda *a, **k: {"matched": False})
    result = inference.search_reid_in_video("model", "youtu", b"query", "video", max_frames=1, runtime="auto")
    assert result["runtime"]["effectiveRuntime"] == "mixed"
    assert result["runtime"]["fallbackReason"] == "batch failed"


def test_enroll_runtime_keeps_first_image_fallback(monkeypatch):
    from flask import Flask, g
    from io import BytesIO
    from types import SimpleNamespace
    from routes import reid
    import inference
    import person_reid_dnn
    person = SimpleNamespace(id=1, to_dict=lambda **k: {"id": 1})
    model = SimpleNamespace(model_key="youtu", version="v1")
    monkeypatch.setattr(reid, "ReidPerson", SimpleNamespace(query=SimpleNamespace(get_or_404=lambda _: person)))
    class Embedding:
        query = SimpleNamespace(filter_by=lambda **k: SimpleNamespace(all=lambda: []))
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    monkeypatch.setattr(reid, "ReidEmbedding", Embedding)
    monkeypatch.setattr(reid, "db", SimpleNamespace(session=SimpleNamespace(add=lambda _: None, commit=lambda: None)))
    monkeypatch.setattr(reid, "_resolve_reid_model", lambda _: ((model, "model"), None))
    monkeypatch.setattr(reid, "_resolve_detector", lambda _: (None, None, "no detector"))
    monkeypatch.setattr(reid, "_save_enroll_image", lambda *a: None)
    monkeypatch.setattr(reid, "invalidate_gallery", lambda *a: None)
    monkeypatch.setattr(inference, "_decode_bgr", lambda _: np.zeros((4, 4, 3), np.uint8))
    calls = iter([{"effectiveRuntime": "python", "degraded": True, "fallbackReason": "first image failed"},
                  {"effectiveRuntime": "cpp"}])
    monkeypatch.setattr(person_reid_dnn, "extract_feature", lambda *a, **k: (np.ones(3), next(calls)))
    app = Flask("enroll-runtime")
    with app.test_request_context(data={"modelId": "1", "files": [(BytesIO(b"a"), "a.jpg"), (BytesIO(b"b"), "b.jpg")]},
                                  method="POST"):
        g.reid_runtime = "auto"
        response = reid.enroll.__wrapped__(1)
    assert response.get_json()["data"]["runtime"]["effectiveRuntime"] == "mixed"
    assert response.get_json()["data"]["runtime"]["fallbackReason"] == "first image failed"


@pytest.fixture
def graph(tmp_path):
    onnx = pytest.importorskip("onnx")
    def create(batch):
        inp = onnx.helper.make_tensor_value_info("image", onnx.TensorProto.FLOAT, [batch, 3, 8, 4])
        out = onnx.helper.make_tensor_value_info("embedding", onnx.TensorProto.FLOAT, [batch, 3])
        node = onnx.helper.make_node("ReduceMean", ["image"], ["embedding"], axes=[2, 3], keepdims=0)
        model = onnx.helper.make_model(onnx.helper.make_graph([node], "reid-test", [inp], [out]),
                                      opset_imports=[onnx.helper.make_opsetid("", 13)])
        model.ir_version = 8
        path = tmp_path / f"person-{batch}.onnx"
        onnx.save(model, path)
        return path
    return create


@pytest.mark.parametrize("batch", [1, "N"])
def test_native_matches_reference_and_is_concurrent(graph, batch):
    from services.reid_cpp import NativeReidSession, library_path
    if not library_path().is_file():
        pytest.skip("build native runtime first; selection tests still run")
    import cv2
    import onnxruntime as ort
    path = graph(batch)
    crops = [np.random.default_rng(i).integers(0, 256, (19, 13, 3), dtype=np.uint8)[:, ::2] for i in range(3)]
    with NativeReidSession(path, threads=1) as session:
        actual = session.extract(crops)
        reference = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        expected = []
        for crop in crops:
            rgb = cv2.resize(crop, (4, 8))[:, :, ::-1].astype(np.float32) / 255
            blob = ((rgb - np.array([.485, .456, .406], np.float32)) /
                    np.array([.229, .224, .225], np.float32)).transpose(2, 0, 1)[None]
            expected.append(reference.run(None, {"image": blob})[0][0])
        np.testing.assert_allclose(actual, expected, rtol=2e-6, atol=2e-6)
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda i: session.extract(crops if i % 2 else crops[::-1]), range(9)))
        for i, result in enumerate(results):
            np.testing.assert_allclose(result, actual if i % 2 else actual[::-1], rtol=1e-6, atol=1e-6)
        with pytest.raises(ValueError):
            session.extract([np.zeros((0, 2, 3), np.uint8)])
        with pytest.raises(ValueError):
            session.extract([np.ones((2, 2, 3), np.float32)])
    with pytest.raises(RuntimeError, match="closed"):
        session.extract(crops)


def test_strong_cpp_retains_model_spaces(monkeypatch):
    from services import strong_reid
    monkeypatch.setattr(strong_reid, "resolve_strong_onnx", lambda _: "osnet_x1_0.onnx")
    monkeypatch.setattr(reid_runtime, "_native_extract", lambda path, images: (
        np.array([[1., 0.]], np.float32), {"backend": "reid-cpp-ort", "provider": "onnxruntime-cpp-cpu",
                                         "onnx": os.path.basename(path), "inputSize": [128, 256]}))
    spaces, meta = strong_reid.extract_person_embeddings(np.zeros((4, 4, 3), np.uint8),
                                                        strong_root="s", runtime="cpp")
    assert list(spaces) == ["osnet-x1-0"]
    assert meta["backends"]["strong"]["provider"] == "onnxruntime-cpp-cpu"
    assert meta["modelVersionsBySpace"]["osnet-x1-0"] == "osnet_x1_0.onnx"


def test_mtmc_cpp_status_does_not_load_a_second_python_model(monkeypatch):
    from services import mtmc_engine
    monkeypatch.setattr(mtmc_engine, "_strong_runtime_io", lambda _: pytest.fail("duplicate Python ORT session"))
    cfg = mtmc_engine.MtmcConfig(camera_ids=[], strong_reid_root="s", reid_runtime="cpp")
    meta = {"associationModelKey": "osnet-x1-0", "activeBackend": "strong",
            "modelVersionsBySpace": {"osnet-x1-0": "v1"},
            "backends": {"strong": {"ready": True, "backend": "reid-cpp-ort",
                                     "provider": "onnxruntime-cpp-cpu", "inputSize": [128, 256]}}}
    status = mtmc_engine._person_reid_runtime_observation(cfg, meta, {"osnet-x1-0": np.ones(2)})
    assert status["provider"] == "onnxruntime-cpp-cpu"
    assert status["ready"] is True


def test_recognize_cpp_batches_crops_and_passes_version(monkeypatch):
    import inference
    from services import reid_gallery
    image = np.zeros((100, 100, 3), np.uint8)
    monkeypatch.setattr(inference, "_decode_bgr", lambda _: image)
    monkeypatch.setattr(inference, "_detect_persons_yolo", lambda *a, **k: [
        {"bbox": [0, 0, 30, 90], "confidence": .9}, {"bbox": [50, 0, 90, 95], "confidence": .9}])
    batches, versions = [], []
    def native(path, images, runtime):
        batches.append((len(images), runtime))
        return np.ones((len(images), 3), np.float32), {"backend": "reid-cpp-ort", "modelVersion": "v7"}
    monkeypatch.setattr(reid_runtime, "extract_youtu_batch", native)
    monkeypatch.setattr(reid_gallery, "match_embedding", lambda emb, key, threshold, model_version: (
        versions.append(model_version) or {"personId": 5, "name": "A", "matched": True, "score": .9}))
    result = inference.recognize_persons("root", "youtu", b"image", det_abs_path="det", runtime="cpp", draw=False)
    assert batches == [(2, "cpp")]
    assert versions == ["v7", "v7"]
    assert result["count"] == 2
    assert result["backend"] == "reid-cpp-ort"


@pytest.mark.parametrize("module,path", [("reid", "/api/ai/reid/recognize"),
                                         ("mtmc", "/api/ai/mtmc/sessions/start")])
def test_invalid_runtime_returns_400_before_work(module, path):
    from flask import Flask
    from routes.reid import reid_bp
    from routes.mtmc import mtmc_bp
    app = Flask("runtime-validation")
    app.register_blueprint(reid_bp if module == "reid" else mtmc_bp)
    client = app.test_client()
    response = client.post(path, data={"reidRuntime": "unsupported"}) if module == "reid" else client.post(path, json={"reidRuntime": "unsupported"})
    assert response.status_code == 400
    assert "reidRuntime" in response.get_json()["message"]


def test_multi_video_search_forwards_runtime_and_returns_video_hits(monkeypatch, tmp_path):
    from flask import Flask
    import inference
    from services import mtmc_search
    import models
    class Query:
        def get(self, cid):
            return type("Camera", (), {"source_type": "file", "source": str(tmp_path / "video.mp4"), "name": "A"})()
    monkeypatch.setattr(models, "Camera", type("Camera", (), {"query": Query()}))
    (tmp_path / "query.jpg").write_bytes(b"query")
    (tmp_path / "video.mp4").write_bytes(b"video")
    calls = []
    def search(*args, **kwargs):
        calls.append(kwargs["runtime"])
        return {"hits": [{"score": .9, "frameIndex": 2}], "runtime": {"provider": "onnxruntime-cpp-cpu"}}
    monkeypatch.setattr(inference, "search_reid_in_video", search)
    monkeypatch.setattr(mtmc_search, "_update_job", lambda *a, **k: None)
    app = Flask("mtmc-search")
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    with app.app_context():
        result = mtmc_search._job_multi_video_reid(app, {"cameraIds": [1], "queryImagePath": str(tmp_path / "query.jpg"),
                                                       "reidRoot": "model", "reidRuntime": "cpp"}, "job")
    assert calls == ["cpp"]
    assert result["matchCount"] == 1
    assert result["matches"][0]["cameraId"] == 1
    assert result["runtimeByCamera"]["1"]["provider"] == "onnxruntime-cpp-cpu"


def test_real_mtmc_frame_uses_native_embeddings(graph, monkeypatch):
    from services.reid_cpp import library_path
    if not library_path().is_file():
        pytest.skip("build native runtime first")
    from services import mtmc_engine
    from services.mtmc_associator import MtmcAssociator
    cfg = mtmc_engine.MtmcConfig(camera_ids=[1], youtu_root=str(graph(1)), det_person_path="det.pt",
                                enable_vehicle=False, local_track_backend="iou", reid_runtime="cpp", persist_events=False)
    session = mtmc_engine.MtmcSession("native-test", cfg, MtmcAssociator())
    cam = mtmc_engine.CamState(camera_id=1)
    session.cams[1] = cam
    monkeypatch.setattr(mtmc_engine, "_detect_person_vehicle", lambda *a, **k: (
        [{"bbox": [5, 5, 80, 95], "confidence": .95, "className": "person", "classId": 0}], []))
    monkeypatch.setattr(mtmc_engine, "_publish_overlay", lambda state, frame, items, *a: setattr(state, "last_dets", list(items)))
    monkeypatch.setattr(mtmc_engine, "_match_gallery", lambda *a, **k: {"matched": False})
    image = np.full((100, 100, 3), 160, np.uint8)
    mtmc_engine._process_frame(session, cam, image, {}, now=10.)
    status = session.to_dict()["runtime"]["models"]["personReid"]
    assert status["provider"] == "onnxruntime-cpp-cpu"
    assert status["ready"] is True
    assert cam.last_dets[0]["globalId"]


def test_native_rejects_invalid_contract_and_bad_abi_buffers(graph):
    from services.reid_cpp import NativeReidSession, library_path
    if not library_path().is_file():
        pytest.skip("build native runtime first")
    import ctypes as ct
    with pytest.raises(RuntimeError, match="batch 1 or dynamic"):
        NativeReidSession(graph(2), threads=1)
    with NativeReidSession(graph(1), threads=1) as session:
        error = ct.create_string_buffer(4096)
        pixels = np.zeros((8, 4, 3), np.uint8)
        output = np.zeros(3, np.float32)
        code = session._lib.reid_infer(session._handle, pixels.ctypes.data, 1, 1,
                                       output.ctypes.data, output.size, error, len(error))
        assert code == -1
        assert b"buffer size mismatch" in error.value
