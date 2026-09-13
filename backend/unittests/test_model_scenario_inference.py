from __future__ import annotations

import io
from importlib import import_module
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from flask import Flask
from flask_jwt_extended import create_access_token
from werkzeug.datastructures import FileStorage, MultiDict

from extensions import db, jwt
from models import AiModel, Role, User
from routes import all_blueprints


def _dispatcher():
    try:
        return import_module("services.model_scenario_inference")
    except ModuleNotFoundError:
        pytest.fail("services.model_scenario_inference has not been implemented")


@pytest.fixture(scope="module")
def _scenario_env(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("scenario-inference")
    model_folder = tmp_path / "models"
    upload_folder = tmp_path
    model_folder.mkdir()
    app = Flask("model-scenario-inference")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'scenario-inference.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="scenario-inference-test-secret",
        MODEL_FOLDER=str(model_folder),
        UPLOAD_FOLDER=str(upload_folder),
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    db.init_app(app)
    jwt.init_app(app)
    for blueprint in all_blueprints:
        app.register_blueprint(blueprint)

    with app.app_context():
        db.create_all()
        role = Role(role_name="Admin", role_key="admin")
        user = User(username="scenario-infer-admin", nickname="Scenario Infer Admin")
        user.set_password("unused")
        user.roles = [role]
        db.session.add_all([role, user])
        db.session.commit()
        token = create_access_token(identity=str(user.id))

    yield app, {"Authorization": f"Bearer {token}"}, model_folder

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def scenario_app(_scenario_env):
    app, headers, model_folder = _scenario_env
    yield app, headers, model_folder
    with app.app_context():
        AiModel.query.delete()
        db.session.commit()


def _png_bytes() -> bytes:
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _file(name: str = "sample.png", payload: bytes | None = None) -> FileStorage:
    return FileStorage(stream=io.BytesIO(payload or _png_bytes()), filename=name)


def _files(*, image: FileStorage | None = None, query=None, gallery=()) -> MultiDict:
    values = []
    if image is not None:
        values.append(("file", image))
    if query is not None:
        values.append(("query", query))
    values.extend(("gallery", item) for item in gallery)
    return MultiDict(values)


def _register_model(
    app,
    model_folder,
    *,
    key="yolo26n-obb",
    task="obb",
    library="ultralytics",
    status="0",
    with_weights=True,
    weight_extension=None,
):
    if weight_extension is not None:
        relative = f"{key}{weight_extension}"
        payload = b"x" * 100_001
    elif library in ("clip-reid", "transreid", "vit-reid", "opencv-sam"):
        relative = f"{key}.onnx"
        payload = b"x" * 100_001
    else:
        relative = f"{key}.pt"
        payload = b"weights"
    if with_weights:
        (model_folder / relative).write_bytes(payload)
    else:
        for extension in (".pt", ".onnx"):
            candidate = model_folder / f"{key}{extension}"
            if candidate.exists():
                candidate.unlink()
    with app.app_context():
        db.session.add(AiModel(
            model_name=key,
            model_key=key,
            task=task,
            library=library,
            file_path=f"models/{relative}",
            status=status,
        ))
        db.session.commit()


def _run(app, key, files, form=None):
    with app.app_context():
        return _dispatcher().run_scenario(key, files, MultiDict(form or {}))


def test_missing_image_is_rejected(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder)

    with pytest.raises(_dispatcher().ScenarioInputError, match="image is required"):
        _run(app, "yolo26n-obb", MultiDict())


def test_invalid_image_extension_is_rejected(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder)

    with pytest.raises(_dispatcher().ScenarioInputError, match="unsupported image extension"):
        _run(app, "yolo26n-obb", _files(image=_file("payload.exe")))


def test_image_larger_than_configured_limit_is_rejected(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder)

    with pytest.raises(_dispatcher().ScenarioInputError, match="configured upload size limit"):
        _run(app, "yolo26n-obb", _files(image=_file(payload=b"x" * (1024 * 1024 + 1))))


@pytest.mark.parametrize("value", ["-0.01", "1.01", "not-a-number"])
def test_conf_outside_zero_to_one_is_rejected(scenario_app, value):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder)

    with pytest.raises(_dispatcher().ScenarioInputError, match="conf must be a number between 0 and 1"):
        _run(app, "yolo26n-obb", _files(image=_file()), {"conf": value})


@pytest.mark.parametrize("value", ["0", "4097", "640.5", "wide"])
def test_invalid_imgsz_is_rejected(scenario_app, value):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder)

    with pytest.raises(_dispatcher().ScenarioInputError, match="imgsz must be an integer between 32 and 4096"):
        _run(app, "yolo26n-obb", _files(image=_file()), {"imgsz": value})


def test_malformed_segmentation_prompt_json_is_rejected(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(
        app,
        model_folder,
        key="mobile-sam",
        task="interactive-segmentation",
        library="mobilesam",
    )

    with pytest.raises(_dispatcher().ScenarioInputError, match="points must be valid JSON"):
        _run(app, "mobile-sam", _files(image=_file()), {"points": "[broken"})


@pytest.mark.parametrize(
    "form",
    [
        {"points": '{"x": 1}', "labels": "[1]"},
        {"points": "[[1, 2, 3]]", "labels": "[1]"},
        {"points": "[[1, NaN]]", "labels": "[1]"},
        {"points": "[[1, 2]]", "labels": '{"label": 1}'},
        {"points": "[[1, 2], [3, 4]]", "labels": "[1]"},
        {"points": "[[1, 2]]", "labels": "[Infinity]"},
        {"box": "[[0, 0], [7, 7]]"},
        {"box": "[0, 0, 7]"},
        {"box": "[0, 0, 7, NaN]"},
    ],
)
def test_segmentation_prompt_types_shapes_and_finite_values_are_validated(scenario_app, form):
    app, _headers, model_folder = scenario_app
    _register_model(
        app,
        model_folder,
        key="efficient-sam",
        task="interactive-segmentation",
        library="opencv-sam",
    )

    with pytest.raises(_dispatcher().ScenarioInputError, match="invalid segmentation prompts"):
        _run(app, "efficient-sam", _files(image=_file()), form)


def test_registered_model_task_must_match_scenario_ability(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder, task="object-detection")

    with pytest.raises(_dispatcher().ScenarioInputError, match="does not match scenario ability"):
        _run(app, "yolo26n-obb", _files(image=_file()))


@pytest.mark.parametrize(
    ("key", "task", "library"),
    [
        ("mobile-sam", "interactive-segmentation", "opencv-sam"),
        ("yolo26n-p2-plate", "object-detection", "transformers"),
        ("yolo26n-obb", "obb", "yolo-master"),
        ("clip-reid-vehicle", "vehicle-reid", "ultralytics"),
    ],
)
def test_scenario_rejects_task_compatible_but_unowned_runtime_library(
    scenario_app, key, task, library,
):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder, key=key, task=task, library=library)

    with pytest.raises(_dispatcher().ScenarioInputError, match="unsupported runtime library for scenario"):
        _run(app, key, _files(image=_file(), query=_file("query.png"), gallery=[_file("gallery.png")]))


@pytest.mark.parametrize(
    ("key", "task", "library", "extension"),
    [
        ("efficient-sam", "interactive-segmentation", "opencv-sam", ".pt"),
        ("mobile-sam", "interactive-segmentation", "mobilesam", ".onnx"),
        ("yolo26n-p2-plate", "object-detection", "ultralytics", ".weights"),
        ("yolo26n-obb", "obb", "ultralytics", ".weights"),
        ("clip-reid-vehicle", "vehicle-reid", "clip-reid", ".pt"),
    ],
)
def test_scenario_rejects_runtime_incompatible_weight_type(
    scenario_app, key, task, library, extension,
):
    app, _headers, model_folder = scenario_app
    _register_model(
        app,
        model_folder,
        key=key,
        task=task,
        library=library,
        weight_extension=extension,
    )

    with pytest.raises(_dispatcher().ScenarioInputError, match="model weights are incompatible with scenario runtime"):
        _run(app, key, _files(image=_file(), query=_file("query.png"), gallery=[_file("gallery.png")]))


def test_disabled_model_is_rejected_before_inference(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder, status="1")

    with pytest.raises(_dispatcher().ScenarioInputError, match="model is disabled"):
        _run(app, "yolo26n-obb", _files(image=_file()))


def test_missing_weights_are_rejected_without_downloading(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder, with_weights=False)

    with pytest.raises(_dispatcher().ScenarioInputError, match="model weights are missing"):
        _run(app, "yolo26n-obb", _files(image=_file()))


def test_efficientsam_forwards_points_labels_and_box(scenario_app, monkeypatch):
    app, _headers, model_folder = scenario_app
    key = "efficient-sam"
    _register_model(
        app,
        model_folder,
        key=key,
        task="interactive-segmentation",
        library="opencv-sam",
    )
    dispatcher = _dispatcher()
    calls = []

    def segment_call(path, raw, **kwargs):
        calls.append((path, raw, kwargs))
        return {"masks": [1]}

    monkeypatch.setattr("inference.segment_image_efficientsam", segment_call)

    result = _run(app, key, _files(image=_file()), {
        "points": "[[1, 2], [3, 4]]",
        "labels": "[1, 0]",
        "box": "[0, 0, 7, 7]",
    })

    assert calls[0][2]["points"] == [[1, 2], [3, 4]]
    assert calls[0][2]["point_labels"] == [1, 0]
    assert calls[0][2]["box"] == [0, 0, 7, 7]
    assert result["result"] == {"masks": [1]}


def test_mobilesam_box_prompt_reaches_real_prompt_encoder_as_box(
    scenario_app, monkeypatch,
):
    import torch
    from mobile_sam import SamPredictor, sam_model_registry

    app, _headers, model_folder = scenario_app
    _register_model(
        app,
        model_folder,
        key="mobile-sam",
        task="interactive-segmentation",
        library="mobilesam",
    )
    model = sam_model_registry["vit_t"](checkpoint=None)
    predictor = SamPredictor(model)
    prompt_calls = []
    decoder_calls = []

    class MaskDecoder(torch.nn.Module):
        def forward(self, **kwargs):
            decoder_calls.append(kwargs)
            return torch.zeros((1, 1, 256, 256)), torch.tensor([[0.9]])

    model.mask_decoder = MaskDecoder()

    def skip_image_encoder(image, _format="RGB"):
        predictor.reset_image()
        predictor.original_size = image.shape[:2]
        predictor.input_size = image.shape[:2]
        height, width = model.prompt_encoder.image_embedding_size
        predictor.features = torch.zeros((1, model.prompt_encoder.embed_dim, height, width))
        predictor.is_image_set = True

    def record_prompt(_module, _args, kwargs):
        prompt_calls.append(kwargs)

    predictor.set_image = skip_image_encoder
    handle = model.prompt_encoder.register_forward_pre_hook(record_prompt, with_kwargs=True)
    monkeypatch.setattr("inference._get_mobile_sam_predictor", lambda _path: predictor)
    try:
        result = _run(app, "mobile-sam", _files(image=_file()), {"box": "[1, 1, 6, 6]"})
    finally:
        handle.remove()

    assert result["result"]["count"] == 1
    assert len(prompt_calls) == 1
    assert prompt_calls[0]["points"] is None
    assert tuple(prompt_calls[0]["boxes"].shape) == (1, 1, 4)
    assert prompt_calls[0]["boxes"].tolist() == [[[128.0, 128.0, 768.0, 768.0]]]
    assert decoder_calls[0]["multimask_output"] is False


class _Tensor:
    def __init__(self, values):
        self.values = np.asarray(values)

    def cpu(self):
        return self

    def numpy(self):
        return self.values


def test_plate_detection_uses_model_predict_and_returns_bbox_without_ocr(scenario_app, monkeypatch):
    app, _headers, model_folder = scenario_app
    key = "yolo26n-p2-plate"
    _register_model(app, model_folder, key=key, task="object-detection")
    calls = []

    class Model:
        names = {0: "plate"}

        def predict(self, image, **kwargs):
            calls.append((image.shape, kwargs))
            box = SimpleNamespace(
                cls=np.array([0]), conf=np.array([0.88]), xyxy=np.array([[1, 2, 5, 6]]),
            )
            return [SimpleNamespace(boxes=[box], names=self.names, plot=lambda: image)]

    monkeypatch.setattr("inference._get_model", lambda _path: Model())
    result = _run(app, key, _files(image=_file()), {"conf": "0.42", "imgsz": "960"})

    assert calls[0][1]["conf"] == 0.42
    assert calls[0][1]["imgsz"] == 960
    assert result["modelKey"] == key
    assert result["workbench"] == "plate_detection"
    assert result["result"]["detections"] == [{
        "className": "plate", "classId": 0, "confidence": 0.88,
        "bbox": [1.0, 2.0, 5.0, 6.0],
    }]
    assert "text" not in result["result"]


def test_obb_detection_uses_model_predict_and_returns_quad(scenario_app, monkeypatch):
    app, _headers, model_folder = scenario_app
    key = "yolo26n-obb"
    _register_model(app, model_folder, key=key, task="obb")
    calls = []

    class Model:
        names = {0: "vehicle"}

        def predict(self, image, **kwargs):
            calls.append(kwargs)
            obb = SimpleNamespace(
                xyxy=_Tensor([[1, 2, 5, 6]]),
                xyxyxyxy=_Tensor([[[1, 2], [5, 2], [5, 6], [1, 6]]]),
                conf=_Tensor([0.91]),
                cls=_Tensor([0]),
            )
            return [SimpleNamespace(obb=obb, boxes=None, names=self.names, plot=lambda: image)]

    monkeypatch.setattr("inference._get_model", lambda _path: Model())
    result = _run(app, key, _files(image=_file()), {"conf": "0.35", "imgsz": "736"})

    assert calls[0]["conf"] == 0.35
    assert calls[0]["imgsz"] == 736
    assert result["result"]["detections"] == [{
        "className": "vehicle", "classId": 0, "confidence": 0.91,
        "bbox": [1.0, 2.0, 5.0, 6.0],
        "quad": [[1.0, 2.0], [5.0, 2.0], [5.0, 6.0], [1.0, 6.0]],
    }]
    assert "text" not in result["result"]


def test_detection_adapter_forwards_imgsz_to_legacy_yolov5(monkeypatch):
    dispatcher = _dispatcher()
    calls = []

    class LegacyModel:
        names = {0: "plate"}

        def __call__(self, image, *, size):
            calls.append((image.shape, size, self.conf))
            return type("LegacyResults", (), {
                "xyxy": [np.array([[1, 2, 5, 6, 0.8, 0]], dtype=np.float32)],
                "names": self.names,
            })()

    monkeypatch.setattr("inference._get_model", lambda _path: LegacyModel())
    result = dispatcher._predict_detection(
        "keremberke-yolov5n-license-plate.pt",
        _png_bytes(),
        conf=0.42,
        imgsz=960,
        obb=False,
    )

    assert calls == [((8, 8, 3), 960, 0.42)]
    assert result["detections"] == [{
        "className": "plate",
        "classId": 0,
        "confidence": 0.8,
        "bbox": [1.0, 2.0, 5.0, 6.0],
    }]


def test_reid_requires_query_and_at_least_one_gallery_image(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(
        app,
        model_folder,
        key="clip-reid-vehicle",
        task="vehicle-reid",
        library="clip-reid",
    )

    with pytest.raises(_dispatcher().ScenarioInputError, match="query image is required"):
        _run(app, "clip-reid-vehicle", _files(gallery=[_file("g.png")]))
    with pytest.raises(_dispatcher().ScenarioInputError, match="at least one gallery image is required"):
        _run(app, "clip-reid-vehicle", _files(query=_file("q.png")))


def test_reid_compares_query_with_each_gallery_image(scenario_app, monkeypatch):
    app, _headers, model_folder = scenario_app
    key = "clip-reid-vehicle"
    _register_model(app, model_folder, key=key, task="vehicle-reid", library="clip-reid")
    calls = []
    embeddings = iter((np.array([1.0, 0.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0])))

    def extract(path, image):
        calls.append((path, image.shape))
        return next(embeddings), {"backend": "vehicle-onnx", "dim": 2}

    monkeypatch.setattr("services.vehicle_reid_feat.extract_vehicle_embedding", extract)
    result = _run(
        app,
        key,
        _files(query=_file("query.png"), gallery=[_file("same.png"), _file("other.png")]),
        {"threshold": "0.7"},
    )

    assert len(calls) == 3
    assert result["result"]["matches"] == [
        {"filename": "same.png", "similarity": 1.0, "matched": True},
        {"filename": "other.png", "similarity": 0.0, "matched": False},
    ]


def test_reid_rejects_histogram_fallback(scenario_app, monkeypatch):
    app, _headers, model_folder = scenario_app
    key = "clip-reid-vehicle"
    _register_model(app, model_folder, key=key, task="vehicle-reid", library="clip-reid")
    monkeypatch.setattr(
        "services.vehicle_reid_feat.extract_vehicle_embedding",
        lambda *_args: (np.array([1.0, 0.0]), {"backend": "hist-fallback", "onnxError": "secret"}),
    )

    with pytest.raises(RuntimeError, match="vehicle ReID runtime did not use configured weights"):
        _run(app, key, _files(query=_file("query.png"), gallery=[_file("gallery.png")]))


def test_reid_histogram_fallback_is_sanitized_as_runtime_500(scenario_app, monkeypatch):
    app, headers, model_folder = scenario_app
    key = "clip-reid-vehicle"
    _register_model(app, model_folder, key=key, task="vehicle-reid", library="clip-reid")
    monkeypatch.setattr(
        "services.vehicle_reid_feat.extract_vehicle_embedding",
        lambda *_args: (np.array([1.0, 0.0]), {
            "backend": "hist-fallback",
            "onnxError": "C:/secret/models/vehicle.onnx failed",
        }),
    )

    response = app.test_client().post(
        f"/api/ai/model-scenarios/{key}/infer",
        headers=headers,
        data=MultiDict([
            ("query", (io.BytesIO(_png_bytes()), "query.png")),
            ("gallery", (io.BytesIO(_png_bytes()), "gallery.png")),
        ]),
    )

    assert response.status_code == 500
    assert response.get_json() == {"code": 500, "message": "inference failed", "data": None}


def test_reid_query_metadata_is_allowlisted(scenario_app, monkeypatch):
    app, _headers, model_folder = scenario_app
    key = "clip-reid-vehicle"
    _register_model(app, model_folder, key=key, task="vehicle-reid", library="clip-reid")
    monkeypatch.setattr(
        "services.vehicle_reid_feat.extract_vehicle_embedding",
        lambda *_args: (np.array([1.0, 0.0]), {
            "backend": "vehicle-onnx",
            "dim": 2,
            "inputSize": "256x256",
            "onnx": "C:/secret/models/vehicle.onnx",
            "onnxError": "runtime internals",
            "provider": "CPUExecutionProvider",
        }),
    )

    result = _run(app, key, _files(query=_file("query.png"), gallery=[_file("gallery.png")]))

    assert result["result"]["backend"] == {
        "backend": "vehicle-onnx", "dim": 2, "inputSize": "256x256",
    }


def test_infer_route_returns_management_envelope_and_sanitizes_failures(scenario_app, monkeypatch):
    app, headers, model_folder = scenario_app
    _register_model(app, model_folder)
    monkeypatch.setattr(
        "routes.model_scenario.run_scenario",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret path")),
    )

    response = app.test_client().post(
        "/api/ai/model-scenarios/yolo26n-obb/infer",
        headers=headers,
        data={"file": (io.BytesIO(_png_bytes()), "sample.png")},
    )

    assert response.status_code == 500
    assert response.get_json() == {"code": 500, "message": "inference failed", "data": None}


def test_infer_route_maps_scenario_input_error_to_400(scenario_app):
    app, headers, model_folder = scenario_app
    _register_model(app, model_folder)

    response = app.test_client().post(
        "/api/ai/model-scenarios/yolo26n-obb/infer",
        headers=headers,
        data={},
    )

    assert response.status_code == 400
    assert response.get_json() == {"code": 400, "message": "image is required", "data": None}


def test_infer_route_returns_success_management_envelope(scenario_app, monkeypatch):
    app, headers, _model_folder = scenario_app
    data = {"modelKey": "yolo26n-obb", "workbench": "obb_detection", "elapsedMs": 1, "result": {}}
    monkeypatch.setattr("routes.model_scenario.run_scenario", lambda *_args, **_kwargs: data)

    response = app.test_client().post(
        "/api/ai/model-scenarios/yolo26n-obb/infer",
        headers=headers,
        data={"file": (io.BytesIO(_png_bytes()), "sample.png")},
    )

    assert response.status_code == 200
    assert response.get_json() == {"code": 0, "message": "ok", "data": data}


def test_infer_route_preserves_request_too_large_as_413(scenario_app):
    app, headers, _model_folder = scenario_app

    response = app.test_client().post(
        "/api/ai/model-scenarios/yolo26n-obb/infer",
        headers=headers,
        data={"file": (io.BytesIO(b"x" * (1024 * 1024 + 1)), "sample.png")},
    )

    assert response.status_code == 413
    assert response.get_json() == {"code": 413, "message": "request entity too large", "data": None}
