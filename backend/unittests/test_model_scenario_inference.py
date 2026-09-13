from __future__ import annotations

import io
from importlib import import_module

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
):
    relative = f"{key}.pt"
    if with_weights:
        (model_folder / relative).write_bytes(b"weights")
    elif (model_folder / relative).exists():
        (model_folder / relative).unlink()
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


def test_registered_model_task_must_match_scenario_ability(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder, task="object-detection")

    with pytest.raises(_dispatcher().ScenarioInputError, match="does not match scenario ability"):
        _run(app, "yolo26n-obb", _files(image=_file()))


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


@pytest.mark.parametrize("key", ["efficient-sam", "mobile-sam"])
def test_segmentation_forwards_points_labels_and_box(scenario_app, monkeypatch, key):
    app, _headers, model_folder = scenario_app
    library = "opencv-sam" if key == "efficient-sam" else "mobilesam"
    _register_model(
        app,
        model_folder,
        key=key,
        task="interactive-segmentation",
        library=library,
    )
    dispatcher = _dispatcher()
    calls = []

    def segment_call(path, raw, **kwargs):
        calls.append((path, raw, kwargs))
        return {"masks": [1]}

    target = "inference.segment_image_efficientsam" if key == "efficient-sam" else "inference.segment_image_mobilesam"
    monkeypatch.setattr(target, segment_call)

    result = _run(app, key, _files(image=_file()), {
        "points": "[[1, 2], [3, 4]]",
        "labels": "[1, 0]",
        "box": "[0, 0, 7, 7]",
    })

    assert calls[0][2]["points"] == [[1, 2], [3, 4]]
    assert calls[0][2]["point_labels"] == [1, 0]
    assert calls[0][2]["box"] == [0, 0, 7, 7]
    assert result["result"] == {"masks": [1]}


@pytest.mark.parametrize(
    ("key", "task", "workbench"),
    [
        ("keremberke-yolov5n-license-plate", "object-detection", "plate_detection"),
        ("yolo26n-obb", "obb", "obb_detection"),
    ],
)
def test_plate_and_obb_forward_conf_and_imgsz_and_normalize_result(
    scenario_app, monkeypatch, key, task, workbench,
):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder, key=key, task=task)
    dispatcher = _dispatcher()
    calls = []

    def predict(path, raw, **kwargs):
        calls.append((path, raw, kwargs))
        return {"detections": [{"bbox": [1, 2, 3, 4]}]}

    monkeypatch.setattr(dispatcher, "_predict_detection", predict)
    result = _run(app, key, _files(image=_file()), {"conf": "0.42", "imgsz": "960"})

    assert calls[0][2] == {"conf": 0.42, "imgsz": 960, "obb": task == "obb"}
    assert result["modelKey"] == key
    assert result["workbench"] == workbench
    assert isinstance(result["elapsedMs"], int)
    assert result["elapsedMs"] >= 0
    assert result["result"] == {"detections": [{"bbox": [1, 2, 3, 4]}]}
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
        return next(embeddings), {"backend": "test-onnx", "dim": 2}

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
