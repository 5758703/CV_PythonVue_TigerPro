"""Vehicle native runtime compatibility, quality boundaries, and MTMC routing."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest

from services import vehicle_reid_feat as features


def test_vehicle_default_is_independent_of_person_runtime(monkeypatch):
    monkeypatch.setenv("REID_RUNTIME", "cpp")
    monkeypatch.delenv("VEHICLE_REID_RUNTIME", raising=False)
    monkeypatch.setattr(features, "resolve_vehicle_onnx", lambda _: None)
    _, meta = features.extract_vehicle_embedding(None, np.zeros((8, 8, 3), np.uint8))
    assert meta["backend"] == "hist-fallback"


def test_vehicle_cpp_strict_and_auto_python_fallback(monkeypatch):
    from services import reid_cpp
    monkeypatch.setattr(features, "resolve_vehicle_onnx", lambda _: "vehicle.onnx")
    monkeypatch.setattr(features, "model_version", lambda _: "sha256:weights")
    def fail(*a, **k): raise RuntimeError("vehicle native unavailable")
    monkeypatch.setattr(reid_cpp, "extract_batch", fail)
    session = SimpleNamespace(get_inputs=lambda: [SimpleNamespace(name="image", shape=[1, 3, 8, 4], type="tensor(float)")],
                              get_outputs=lambda: [SimpleNamespace(name="embedding")],
                              run=lambda *a: [np.array([[3., 4.]], np.float32)])
    monkeypatch.setattr(features, "_get_ort", lambda _: session)
    image = np.ones((8, 4, 3), np.uint8)
    with pytest.raises(RuntimeError, match="native unavailable"):
        features.extract_vehicle_embedding("model", image, runtime="cpp")
    vector, meta = features.extract_vehicle_embedding("model", image, runtime="auto")
    np.testing.assert_allclose(vector, [.6, .8])
    assert meta["backend"] == "vehicle-onnx"
    assert meta["modelVersion"] == "sha256:weights"
    assert meta["effectiveRuntime"] == "python"
    assert meta["degraded"] is True
    assert "native unavailable" in meta["fallbackReason"]


def test_vehicle_cpp_preserves_space_and_does_not_load_python_session(monkeypatch):
    from services import reid_cpp
    from services.mtmc_engine import _vehicle_embedding_space
    monkeypatch.setattr(features, "resolve_vehicle_onnx", lambda _: "vehicle.onnx")
    monkeypatch.setattr(features, "model_version", lambda _: "sha256:weights")
    monkeypatch.setattr(features, "_get_ort", lambda _: pytest.fail("duplicate Python model"))
    def extract(path, images, *, kind):
        assert kind == "vehicle"
        return np.array([[3., 4.]], np.float32), {"provider": "onnxruntime-cpp-cpu", "inputSize": [4, 8]}
    monkeypatch.setattr(reid_cpp, "extract_batch", extract)
    vector, meta = features.extract_vehicle_embedding("model", np.ones((8, 4, 3), np.uint8), runtime="cpp")
    assert meta["effectiveRuntime"] == "cpp"
    assert meta["runtimeBackend"] == "vehicle-cpp-ort"
    assert _vehicle_embedding_space(meta, vector) == ("vehicle-onnx", 2, "sha256:weights")


def test_vehicle_cpp_batch_uses_one_native_call(monkeypatch):
    from services import reid_cpp
    monkeypatch.setattr(features, "resolve_vehicle_onnx", lambda _: "vehicle.onnx")
    monkeypatch.setattr(features, "model_version", lambda _: "sha256:weights")
    calls = []
    def extract(path, images, *, kind):
        calls.append(len(images))
        return np.repeat([[3., 4.]], len(images), axis=0).astype(np.float32), {"provider": "onnxruntime-cpp-cpu", "inputSize": [4, 8]}
    monkeypatch.setattr(reid_cpp, "extract_batch", extract)
    pairs = features.extract_vehicle_embeddings("model", [np.ones((8, 4, 3), np.uint8)] * 3, runtime="cpp")
    assert calls == [3]
    assert len(pairs) == 3
    for vector, meta in pairs:
        np.testing.assert_allclose(vector, [.6, .8])
        assert meta["modelVersion"] == "sha256:weights"


def test_vehicle_status_reports_native_to_python_degradation():
    from services.mtmc_engine import MtmcConfig, _vehicle_reid_runtime_observation
    status = _vehicle_reid_runtime_observation(MtmcConfig(camera_ids=[]), {
        "backend": "vehicle-onnx", "provider": "CPUExecutionProvider", "degraded": True,
        "fallbackReason": "native failed", "effectiveRuntime": "python"}, np.ones(2))
    assert status["runtimeState"] == "degraded"
    assert status["degradedReason"] == "native failed"


@pytest.fixture
def vehicle_graph(tmp_path):
    onnx = pytest.importorskip("onnx")
    def create(aux_type=None, batch=1, flat=False):
        inputs = [onnx.helper.make_tensor_value_info("image", onnx.TensorProto.FLOAT, [batch, 3, 8, 4])]
        nodes = [onnx.helper.make_node("ReduceMean", ["image"], ["mean"], axes=[2, 3], keepdims=0)]
        output = "mean"
        if aux_type:
            inputs.append(onnx.helper.make_tensor_value_info("view", aux_type, []))
            nodes += [onnx.helper.make_node("Cast", ["view"], ["view_f"], to=onnx.TensorProto.FLOAT),
                      onnx.helper.make_node("Add", ["mean", "view_f"], ["combined"])]
            output = "combined"
        if flat:
            nodes.append(onnx.helper.make_node("Squeeze", [output], ["flat"], axes=[0]))
            output = "flat"
        out = onnx.helper.make_tensor_value_info(output, onnx.TensorProto.FLOAT, [3] if flat else [batch, 3])
        model = onnx.helper.make_model(onnx.helper.make_graph(nodes, "vehicle-native", inputs, [out]),
                                      opset_imports=[onnx.helper.make_opsetid("", 11)])
        model.ir_version = 8
        path = tmp_path / f"vehicle-{aux_type}-{batch}-{flat}.onnx"
        onnx.save(model, path)
        return path
    return create


@pytest.mark.parametrize("aux_type", [1, 6, 7, 9, 11])  # float, int32, int64, bool, double
def test_native_vehicle_auxiliary_zero_inputs_and_concurrency(vehicle_graph, aux_type):
    from services.reid_cpp import NativeReidSession, library_path
    if not library_path().is_file(): pytest.skip("build native core first")
    path = vehicle_graph(aux_type, batch="N")
    crops = [np.random.default_rng(i).integers(0, 256, (20, 10, 3), dtype=np.uint8) for i in range(3)]
    reference = features._get_ort(str(path))
    expected = np.stack([reference.run(None, features._build_feed(reference, features._preprocess(c, 4, 8)))[0][0] for c in crops])
    with NativeReidSession(path, kind="vehicle", threads=1) as session:
        np.testing.assert_allclose(session.extract(crops), expected, atol=2e-6, rtol=2e-6)
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: session.extract(crops), range(6)))
        for value in results: np.testing.assert_allclose(value, expected, atol=2e-6, rtol=2e-6)
    with pytest.raises(RuntimeError, match="exactly one input"):
        NativeReidSession(path, threads=1)


def test_native_vehicle_supports_flat_output_and_chunks(vehicle_graph):
    from services.reid_cpp import NativeReidSession, library_path
    if not library_path().is_file(): pytest.skip("build native core first")
    image = np.full((8, 4, 3), 160, np.uint8)
    with NativeReidSession(vehicle_graph(flat=True), kind="vehicle", threads=1) as session:
        output = session.extract([image] * 65)
        assert output.shape == (65, 3)
        np.testing.assert_allclose(output, np.repeat(output[:1], 65, axis=0))


def test_native_vehicle_features_are_used_for_cross_camera_binding(vehicle_graph, monkeypatch):
    from services import mtmc_engine as engine
    from services.mtmc_associator import MtmcAssociator
    path = str(vehicle_graph())
    monkeypatch.setattr(features, "resolve_vehicle_onnx", lambda _: path)
    monkeypatch.setattr(engine, "_detect", lambda *a, **k: [
        {"bbox": [10, 10, 85, 90], "confidence": .95, "className": "car", "classId": 2}])
    cfg = engine.MtmcConfig(camera_ids=[1, 2], enable_person=False, enable_vehicle=True,
                           det_vehicle_path="det.pt", vehicle_reid_root=path, vehicle_reid_runtime="cpp",
                           local_track_backend="iou", plate_budget=0, persist_events=False)
    session = engine.MtmcSession("vehicle-native", cfg, MtmcAssociator(
        use_faiss_gallery=False, vehicle_appear_thresh=.75, confirm_thresh=.75, min_match_margin=0))
    session.cams = {cid: engine.CamState(camera_id=cid) for cid in [1, 2]}
    image = np.full((100, 100, 3), 160, np.uint8)
    for cid in [1, 2]: engine._process_frame(session, session.cams[cid], image, {}, now=100. + cid)
    ids = [session.cams[cid].last_dets[0]["globalId"] for cid in [1, 2]]
    assert ids[0] and ids[0] == ids[1]
    status = session.to_dict()["runtime"]["models"]["vehicleReid"]
    assert status["provider"] == "onnxruntime-cpp-cpu"
    assert status["modelVersion"] == features.model_version(path)
    assert session.to_dict()["vehicleReidRuntime"] == "cpp"


def test_auto_histogram_does_not_create_visual_cross_camera_identity(monkeypatch):
    from services import mtmc_engine as engine
    from services.mtmc_associator import MtmcAssociator
    monkeypatch.setattr(features, "resolve_vehicle_onnx", lambda _: None)
    monkeypatch.setattr(engine, "_detect", lambda *a, **k: [
        {"bbox": [10, 10, 85, 90], "confidence": .95, "className": "car", "classId": 2}])
    cfg = engine.MtmcConfig(camera_ids=[1, 2], enable_person=False, vehicle_reid_runtime="auto",
                           det_vehicle_path="det.pt", local_track_backend="iou", plate_budget=0, persist_events=False)
    session = engine.MtmcSession("vehicle-degraded", cfg, MtmcAssociator(use_faiss_gallery=False))
    session.cams = {cid: engine.CamState(camera_id=cid) for cid in [1, 2]}
    for cid in [1, 2]:
        engine._process_frame(session, session.cams[cid], np.full((100, 100, 3), 160, np.uint8), {}, now=100. + cid)
        builders = session.cams[cid].vehicle_builders
        assert builders
        assert all(not builder.aggregate_embedding_spaces() for builder in builders.values())
    status = session.to_dict()["runtime"]["models"]["vehicleReid"]
    assert status["degraded"] is True
    assert "ONNX unavailable" in status["degradedReason"]


def test_invalid_vehicle_runtime_returns_400():
    from flask import Flask
    from routes.mtmc import mtmc_bp
    app = Flask("vehicle-runtime")
    app.register_blueprint(mtmc_bp)
    response = app.test_client().post("/api/ai/mtmc/sessions/start", json={"vehicleReidRuntime": "bad"})
    assert response.status_code == 400
    assert "vehicleReidRuntime" in response.get_json()["message"]


def test_explicit_vehicle_model_selection_and_thresholds(monkeypatch):
    from routes import mtmc
    choices = []
    vehicle_model = SimpleNamespace(model_key="clip-reid-vehicle", version="v1", library="onnx")
    def pick(mid, **kwargs):
        choices.append(kwargs)
        return vehicle_model if kwargs.get("keys") == ["clip-reid-vehicle"] else None
    monkeypatch.setattr(mtmc, "_pick_model", pick)
    monkeypatch.setattr(mtmc, "_abs_weight", lambda m: "vehicle.onnx" if m is vehicle_model else None)
    monkeypatch.setattr(mtmc, "_build_ocr_fn", lambda *a: None)
    cfg = mtmc._parse_session_params({"cameraIds": [], "vehicleReidRuntime": "cpp",
                                     "vehicleReidModelKey": "clip-reid-vehicle",
                                     "vehicleAppearThresh": .8, "minMatchMargin": .04})
    assert cfg.vehicle_reid_runtime == "cpp"
    assert cfg.vehicle_appear_thresh == .8 and cfg.min_match_margin == .04
    assert cfg.selected_models["vehicleReid"]["configuredModelKey"] == "clip-reid-vehicle"
    assert next(row for row in choices if row.get("keys") == ["clip-reid-vehicle"])["task"] is None


def test_pipeline_vehicle_key_is_validated_before_model_lookup(monkeypatch):
    from routes import mtmc
    from services.pipeline_mtmc import build_mtmc_config_from_node
    monkeypatch.setattr(mtmc, "_pick_model", lambda *a, **k: pytest.fail("model lookup before validation"))
    with pytest.raises(ValueError, match="vehicleReidModelKey"):
        build_mtmc_config_from_node({"cameraIds": [1, 2], "vehicleReidModelKey": "osnet-x1-0"})


def test_conflicting_vehicle_model_id_and_key_are_rejected(monkeypatch):
    from routes import mtmc
    monkeypatch.setattr(mtmc, "_pick_model", lambda mid, **k: SimpleNamespace(model_key="transreid-vehicle") if mid else None)
    with pytest.raises(ValueError, match="conflicts"):
        mtmc._parse_session_params({"vehicleReidModelId": 12, "vehicleReidModelKey": "clip-reid-vehicle"})


def test_start_route_maps_vehicle_config_conflict_to_400(monkeypatch):
    from flask import Flask
    from routes import mtmc
    monkeypatch.setattr(mtmc, "Camera", SimpleNamespace(id=SimpleNamespace(in_=lambda _: True), status="0",
        query=SimpleNamespace(filter=lambda *a: SimpleNamespace(all=lambda: [object()]))))
    def conflict(*a): raise ValueError("vehicleReidModelId conflicts with vehicleReidModelKey")
    monkeypatch.setattr(mtmc, "_parse_session_params", conflict)
    with Flask("vehicle-config-error").test_request_context(json={"cameraIds": [1]}):
        response, status = mtmc.start_session.__wrapped__()
    assert status == 400 and "conflicts" in response.get_json()["message"]


def test_strict_vehicle_missing_model_reports_failed_runtime(monkeypatch):
    from services import mtmc_engine as engine
    from services.mtmc_associator import MtmcAssociator
    monkeypatch.setattr(features, "resolve_vehicle_onnx", lambda _: None)
    monkeypatch.setattr(engine, "_detect", lambda *a, **k: [
        {"bbox": [10, 10, 85, 90], "confidence": .95, "className": "car", "classId": 2}])
    cfg = engine.MtmcConfig(camera_ids=[1], enable_person=False, vehicle_reid_runtime="cpp",
                           det_vehicle_path="det.pt", local_track_backend="iou", plate_budget=0, persist_events=False)
    session = engine.MtmcSession("vehicle-failed", cfg, MtmcAssociator(use_faiss_gallery=False))
    state = engine.CamState(camera_id=1)
    session.cams[1] = state
    with pytest.raises(RuntimeError, match="ONNX unavailable"):
        engine._process_frame(session, state, np.full((100, 100, 3), 160, np.uint8), {}, now=100.)
    status = session.to_dict()["runtime"]["models"]["vehicleReid"]
    assert status["runtimeState"] == "failed"
    assert status["provider"] == "unavailable"


def test_native_vehicle_zero_output_is_rejected(vehicle_graph, tmp_path):
    import onnx
    from services.reid_cpp import NativeReidSession
    model = onnx.load(vehicle_graph())
    model.graph.node[0].output[0] = "raw_mean"
    model.graph.node.extend([onnx.helper.make_node("Constant", [], ["zero"],
        value=onnx.numpy_helper.from_array(np.zeros((1, 3), np.float32))),
        onnx.helper.make_node("Mul", ["raw_mean", "zero"], ["mean"])])
    path = tmp_path / "zero-vehicle.onnx"
    onnx.save(model, path)
    with NativeReidSession(path, kind="vehicle", threads=1) as session:
        with pytest.raises(RuntimeError, match="zero vehicle embedding"):
            session.extract([np.full((8, 4, 3), 160, np.uint8)])


def test_vehicle_frame_batches_only_reserved_budget(monkeypatch):
    from services import mtmc_engine as engine
    from services.mtmc_associator import MtmcAssociator
    monkeypatch.setattr(engine, "_detect", lambda *a, **k: [
        {"bbox": [10 + i*90, 10, 80 + i*90, 140], "confidence": .95, "className": "car", "classId": 2} for i in range(3)])
    calls = []
    def batch(path, images, *, runtime):
        calls.append((len(images), runtime))
        return [(np.array([1., float(i)]), {"backend": "vehicle-onnx", "modelVersion": "v1", "provider": "onnxruntime-cpp-cpu"}) for i in range(len(images))]
    monkeypatch.setattr(features, "extract_vehicle_embeddings", batch)
    cfg = engine.MtmcConfig(camera_ids=[1], enable_person=False, vehicle_reid_runtime="cpp",
                           vehicle_reid_budget=2, det_vehicle_path="det.pt", local_track_backend="iou",
                           plate_budget=0, persist_events=False)
    session = engine.MtmcSession("vehicle-batch-budget", cfg, MtmcAssociator(use_faiss_gallery=False))
    state = engine.CamState(camera_id=1)
    session.cams[1] = state
    engine._process_frame(session, state, np.full((180, 300, 3), 160, np.uint8), {}, now=100.)
    assert calls == [(2, "cpp")]
    assert sum(bool(b.aggregate_embedding_spaces()) for b in state.vehicle_builders.values()) == 2


def test_native_vehicle_batch_limit_is_explicit(vehicle_graph, monkeypatch):
    from services.reid_cpp import NativeReidSession
    monkeypatch.delenv("VEHICLE_REID_CPP_BATCH_SIZE", raising=False)
    crops = [np.full((8, 4, 3), 160, np.uint8)] * 3
    with NativeReidSession(vehicle_graph(batch="N"), kind="vehicle", threads=1) as session:
        calls, infer = [], session._lib.reid_infer
        def record(*args):
            calls.append(args[3])
            return infer(*args)
        session._lib.reid_infer = record
        single = session.extract(crops)
        assert calls == [1, 1, 1]
        calls.clear()
        batched = session.extract(crops, batch_limit=3)
        assert calls == [3]
        np.testing.assert_allclose(single, batched)
