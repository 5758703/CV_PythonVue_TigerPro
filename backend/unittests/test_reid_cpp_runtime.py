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
            results = list(pool.map(lambda _: session.extract(crops), range(9)))
        for result in results:
            np.testing.assert_allclose(result, actual, rtol=1e-6, atol=1e-6)
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
