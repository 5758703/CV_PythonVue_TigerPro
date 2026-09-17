from __future__ import annotations

import io
import base64
import hashlib
import json
import sys
from importlib import import_module
from pathlib import Path
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
        SCENARIO_MAX_IMAGE_BYTES=1024,
        SCENARIO_MAX_PIXELS=64,
        SCENARIO_MAX_PROMPTS=2,
        SCENARIO_MAX_GALLERY_IMAGES=2,
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
    marker = model_folder / "production-manifest.json"
    if marker.exists():
        marker.unlink()


def _png_bytes() -> bytes:
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _file(name: str = "sample.png", payload: bytes | None = None) -> FileStorage:
    return FileStorage(stream=io.BytesIO(payload or _png_bytes()), filename=name)


def _files(*, image: FileStorage | None = None, mask=None, query=None, gallery=()) -> MultiDict:
    values = []
    if image is not None:
        values.append(("file", image))
    if mask is not None:
        values.append(("mask", mask))
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
    elif library in ("clip-reid", "transreid", "vit-reid", "opencv-sam", "opencv-lama", "opencv-dnn", "rtmlib"):
        relative = (
            "image_segmentation_efficientsam_ti_2025april.onnx"
            if key == "efficient-sam"
            else f"{key}.onnx"
        )
        payload = b"x" * 100_001
    else:
        relative = f"{key}.pt"
        payload = b"weights"
    if with_weights:
        artifact = model_folder / relative
        artifact.write_bytes(payload)
        if key in ("yolo26n-p2-plate", "efficient-sam") and weight_extension is None:
            manifest = {
                "modelKey": key,
                "task": task,
                "artifactFile": artifact.name,
                "artifactSha256": hashlib.sha256(payload).hexdigest(),
            }
            if key == "yolo26n-p2-plate":
                manifest.update({"trainingComplete": True, "classes": ["license_plate"]})
            (model_folder / "production-manifest.json").write_text(json.dumps({
                **manifest,
            }), encoding="utf-8")
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

    with pytest.raises(_dispatcher().ScenarioPayloadTooLarge, match="scenario image size limit"):
        _run(app, "yolo26n-obb", _files(image=_file(payload=b"x" * 1025)))


def test_image_header_pixel_limit_is_rejected_before_opencv_decode(scenario_app, monkeypatch):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder)
    image = np.zeros((8, 9, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    monkeypatch.setattr(cv2, "imdecode", lambda *_args, **_kwargs: pytest.fail("unsafe OpenCV decode"))

    with pytest.raises(_dispatcher().ScenarioPayloadTooLarge, match="pixel limit"):
        _run(app, "yolo26n-obb", _files(image=_file(payload=encoded.tobytes())))


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


@pytest.mark.parametrize(
    "form",
    [
        {"mode": "unknown", "points": "[[1, 2]]", "labels": "[1]"},
        {"precision": "fp16", "points": "[[1, 2]]", "labels": "[1]"},
        {"points": "[[-1, 2]]", "labels": "[1]"},
        {"points": "[[8, 2]]", "labels": "[1]"},
        {"box": "[0, 0, 9, 7]"},
        {"box": "[5, 5, 2, 2]"},
    ],
)
def test_segmentation_mode_precision_and_prompt_coordinates_are_validated(
    scenario_app, form,
):
    app, _headers, model_folder = scenario_app
    _register_model(
        app,
        model_folder,
        key="efficient-sam",
        task="interactive-segmentation",
        library="opencv-sam",
    )

    with pytest.raises(_dispatcher().ScenarioInputError):
        _run(app, "efficient-sam", _files(image=_file()), form)


def test_segmentation_prompt_count_is_bounded(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(
        app,
        model_folder,
        key="efficient-sam",
        task="interactive-segmentation",
        library="opencv-sam",
    )

    with pytest.raises(_dispatcher().ScenarioInputError, match="at most 2 prompt points"):
        _run(app, "efficient-sam", _files(image=_file()), {
            "points": "[[1, 1], [2, 2], [3, 3]]",
            "labels": "[1, 1, 0]",
        })


def test_registered_model_task_must_match_scenario_ability(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(app, model_folder, task="object-detection")

    with pytest.raises(_dispatcher().ScenarioInputError, match="does not match scenario"):
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

    with pytest.raises(_dispatcher().ScenarioInputError, match="library does not match scenario contract"):
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


def test_p2_plate_inference_rejects_the_generic_yolo26n_training_base(scenario_app):
    app, _headers, model_folder = scenario_app
    (model_folder / "yolo26n.pt").write_bytes(b"generic base")
    with app.app_context():
        db.session.add(AiModel(
            model_name="P2 scaffold",
            model_key="yolo26n-p2-plate",
            task="object-detection",
            library="ultralytics",
            file_path="models/yolo26n.pt",
            status="0",
        ))
        db.session.commit()

    with pytest.raises(
        _dispatcher().ScenarioInputError,
        match="plate-specific production manifest is missing or invalid",
    ):
        _run(app, "yolo26n-p2-plate", _files(image=_file()))


def test_segmentation_rejects_detector_confidence_as_an_unknown_field(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(
        app, model_folder, key="mobile-sam",
        task="interactive-segmentation", library="mobilesam",
    )

    with pytest.raises(_dispatcher().ScenarioInputError, match="unknown form field: conf"):
        _run(app, "mobile-sam", _files(image=_file()), {
            "mode": "auto", "conf": "0.5",
        })


def test_inpainting_requires_mask_and_rejects_unknown_fields(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(
        app, model_folder, key="inpainting-lama",
        task="image-inpainting", library="opencv-lama",
    )

    with pytest.raises(_dispatcher().ScenarioInputError, match="mask is required"):
        _run(app, "inpainting-lama", _files(image=_file()))
    with pytest.raises(_dispatcher().ScenarioInputError, match="unknown form field: conf"):
        _run(app, "inpainting-lama", _files(image=_file(), mask=_file("mask.png")), {
            "conf": "0.5",
        })


def test_classification_rejects_invalid_top_k(scenario_app):
    app, _headers, model_folder = scenario_app
    _register_model(
        app, model_folder, key="mobilenet-v2",
        task="image-classification", library="opencv-dnn",
    )

    with pytest.raises(_dispatcher().ScenarioInputError, match="topK must be an integer between 1 and 20"):
        _run(app, "mobilenet-v2", _files(image=_file()), {"topK": "0"})


def test_multimodal_grounding_requires_prompt(scenario_app, monkeypatch):
    app, _headers, model_folder = scenario_app
    key = "vlm-fo1-3b"
    # Directory-style weights: config + safetensors index.
    (model_folder / "config.json").write_text('{"model_type":"vlm"}', encoding="utf-8")
    (model_folder / "model.safetensors").write_bytes(b"x" * 100_001)
    with app.app_context():
        db.session.add(AiModel(
            model_name=key,
            model_key=key,
            task="object-detection",
            library="vlm-fo1",
            file_path="models",
            status="0",
        ))
        db.session.commit()
    monkeypatch.setattr(
        "services.model_scenario_contract.resolve_vlm_fo1_root",
        lambda: str(model_folder),
        raising=False,
    )
    monkeypatch.setattr(
        "services.vlm_fo1.resolve_vlm_fo1_root",
        lambda: str(model_folder),
    )

    with pytest.raises(_dispatcher().ScenarioInputError, match="prompt is required"):
        _run(app, key, _files(image=_file()), {"prompt": "   "})


def test_body_pose_forwards_conf_to_rtmlib(scenario_app, monkeypatch):
    app, _headers, model_folder = scenario_app
    key = "rtmo-s"
    _register_model(
        app, model_folder, key=key,
        task="pose-estimation", library="rtmlib",
    )
    calls = []

    def pose_call(model_key, path, raw, conf=0.25, draw=True):
        calls.append({"model_key": model_key, "path": path, "conf": conf, "draw": draw})
        return {
            "count": 1,
            "persons": [{"keypoints": [[1, 2, 0.9]]}],
            "imageBase64": None,
            "width": 2,
            "height": 2,
            "keypointCount": 17,
            "poseType": "body17",
        }

    monkeypatch.setattr("inference.estimate_pose_rtmlib", pose_call)
    payload = _run(app, key, _files(image=_file()), {"conf": "0.4"})

    assert payload["workbench"] == "body_pose"
    assert payload["result"]["count"] == 1
    assert calls and calls[0]["conf"] == 0.4
    assert calls[0]["model_key"] == key


def test_efficientsam_forwards_points_labels_and_box(scenario_app, monkeypatch):
    app, _headers, model_folder = scenario_app
    monkeypatch.setitem(app.config, "SCENARIO_MAX_PROMPTS", 3)
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


def test_efficientsam_selects_the_manifest_bound_int8_artifact(
    scenario_app, monkeypatch,
):
    app, _headers, model_folder = scenario_app
    weights = model_folder / "efficient-variants"
    weights.mkdir()
    artifacts = {}
    for precision, name in (
        ("fp32", "image_segmentation_efficientsam_ti_2025april.onnx"),
        ("int8", "image_segmentation_efficientsam_ti_2025april_int8.onnx"),
    ):
        artifact = weights / name
        artifact.write_bytes(precision.encode() * 50_001)
        artifacts[precision] = {
            "artifactFile": name,
            "artifactSha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
    (weights / "production-manifest.json").write_text(json.dumps({
        "modelKey": "efficient-sam", "task": "interactive-segmentation",
        "artifacts": artifacts,
    }), encoding="utf-8")
    with app.app_context():
        db.session.add(AiModel(
            model_name="efficient variants",
            model_key="efficient-sam",
            task="interactive-segmentation",
            library="opencv-sam",
            file_path="models/efficient-variants",
            status="0",
        ))
        db.session.commit()

    calls = []

    def segment_call(path, _raw, **kwargs):
        calls.append((path, kwargs))
        return {"detections": []}

    monkeypatch.setattr("inference.segment_image_efficientsam", segment_call)

    _run(app, "efficient-sam", _files(image=_file()), {
        "points": "[[1, 2]]",
        "labels": "[1]",
        "precision": "int8",
    })

    assert Path(calls[0][0]).name == "image_segmentation_efficientsam_ti_2025april_int8.onnx"
    assert calls[0][1]["precision"] == "int8"


def test_efficientsam_rejects_an_unpublished_precision(scenario_app, monkeypatch):
    app, _headers, model_folder = scenario_app
    _register_model(
        app, model_folder, key="efficient-sam",
        task="interactive-segmentation", library="opencv-sam",
    )
    monkeypatch.setattr(
        "inference.segment_image_efficientsam",
        lambda *_args, **_kwargs: pytest.fail("unpublished precision must not run"),
    )

    with pytest.raises(_dispatcher().ScenarioInputError, match="precision is not published"):
        _run(app, "efficient-sam", _files(image=_file()), {
            "points": "[[1, 2]]", "labels": "[1]", "precision": "int8",
        })


def test_segmentation_returns_area_metrics_computed_from_the_real_mask(
    scenario_app, monkeypatch,
):
    app, _headers, model_folder = scenario_app
    key = "efficient-sam"
    _register_model(
        app,
        model_folder,
        key=key,
        task="interactive-segmentation",
        library="opencv-sam",
    )
    mask = np.array([[0, 255], [255, 0]], dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", mask)
    assert ok
    mask_b64 = base64.b64encode(encoded.tobytes()).decode()
    monkeypatch.setattr(
        "inference.segment_image_efficientsam",
        lambda *_args, **_kwargs: {
            "width": 8,
            "height": 8,
            "detections": [{"className": "segment", "maskBase64": mask_b64}],
        },
    )

    result = _run(app, key, _files(image=_file()), {
        "points": "[[1, 1]]", "labels": "[1]", "precision": "fp32",
    })

    detection = result["result"]["detections"][0]
    assert detection["areaPixels"] == 2
    assert detection["areaRatio"] == pytest.approx(0.5)


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
    monkeypatch.setattr(_dispatcher(), "_get_obb_model", lambda _path: Model(), raising=False)
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
                xywhr=_Tensor([[3, 4, 4, 4, np.pi / 4]]),
                conf=_Tensor([0.91]),
                cls=_Tensor([0]),
            )
            return [SimpleNamespace(obb=obb, boxes=None, names=self.names, plot=lambda: image)]

    monkeypatch.setattr("inference._get_model", lambda _path: Model())
    monkeypatch.setattr(_dispatcher(), "_get_obb_model", lambda _path: Model(), raising=False)
    result = _run(app, key, _files(image=_file()), {"conf": "0.35", "imgsz": "736"})

    assert calls[0]["conf"] == 0.35
    assert calls[0]["imgsz"] == 736
    assert result["result"]["detections"] == [{
        "className": "vehicle", "classId": 0, "confidence": 0.91,
        "bbox": [1.0, 2.0, 5.0, 6.0],
        "quad": [[1.0, 2.0], [5.0, 2.0], [5.0, 6.0], [1.0, 6.0]],
        "angle": 45.0,
        "angleUnit": "degrees",
    }]
    assert "text" not in result["result"]


@pytest.mark.parametrize("extension", [".pt", ".onnx"])
def test_obb_uses_a_task_aware_loader_for_pt_and_onnx(monkeypatch, tmp_path, extension):
    dispatcher = _dispatcher()
    weight = tmp_path / f"model{extension}"
    weight.write_bytes(b"weight")
    calls = []

    class Model:
        names = {}

        def predict(self, image, **kwargs):
            return [SimpleNamespace(
                obb=SimpleNamespace(
                    xyxy=_Tensor([]), xyxyxyxy=_Tensor([]), xywhr=_Tensor([]),
                    conf=_Tensor([]), cls=_Tensor([]),
                ),
                names={},
                plot=lambda: image,
            )]

    def load(path, *, task):
        calls.append((path, task))
        return Model()

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=load))
    monkeypatch.setattr(
        "inference._get_model",
        lambda _path: pytest.fail("OBB must not use the task-agnostic shared loader"),
    )
    dispatcher._clear_obb_model_cache()
    dispatcher._predict_detection(
        str(weight), _png_bytes(), conf=0.4, imgsz=640, obb=True,
    )

    assert calls == [(str(weight.resolve()), "obb")]


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
        {
            "filename": "same.png", "similarity": 1.0, "distance": 0.0,
            "matched": True, "sourceIndex": 0, "rank": 1,
        },
        {
            "filename": "other.png", "similarity": 0.0, "distance": 1.0,
            "matched": False, "sourceIndex": 1, "rank": 2,
        },
    ]


def test_reid_uses_raw_similarity_for_decisions_then_stably_ranks_results(
    scenario_app, monkeypatch,
):
    app, _headers, model_folder = scenario_app
    key = "clip-reid-vehicle"
    _register_model(app, model_folder, key=key, task="vehicle-reid", library="clip-reid")
    monkeypatch.setattr(
        "services.vehicle_reid_feat.extract_vehicle_embedding",
        lambda *_args: (np.array([1.0, 0.0]), {"backend": "vehicle-onnx", "dim": 2}),
    )
    scores = iter((0.70003, 0.70004))
    monkeypatch.setattr("services.vehicle_reid_feat.cosine", lambda *_args: next(scores))

    result = _run(
        app,
        key,
        _files(query=_file("query.png"), gallery=[_file("low.png"), _file("high.png")]),
        {"threshold": "0.700035"},
    )

    assert result["result"]["matches"] == [
        {
            "filename": "high.png", "similarity": 0.7, "distance": 0.3,
            "matched": True, "sourceIndex": 1, "rank": 1,
        },
        {
            "filename": "low.png", "similarity": 0.7, "distance": 0.3,
            "matched": False, "sourceIndex": 0, "rank": 2,
        },
    ]


def test_reid_gallery_count_is_bounded_before_decoding(scenario_app):
    app, _headers, model_folder = scenario_app
    key = "clip-reid-vehicle"
    _register_model(app, model_folder, key=key, task="vehicle-reid", library="clip-reid")

    with pytest.raises(_dispatcher().ScenarioInputError, match="at most 2 gallery images"):
        _run(app, key, _files(
            query=_file("query.png"),
            gallery=[_file("one.png"), _file("two.png"), _file("three.png")],
        ))


def test_reid_decodes_and_embeds_each_gallery_image_incrementally(
    scenario_app, monkeypatch,
):
    app, _headers, model_folder = scenario_app
    key = "clip-reid-vehicle"
    _register_model(app, model_folder, key=key, task="vehicle-reid", library="clip-reid")
    events = []

    class RecordingStream(io.BytesIO):
        def __init__(self, label):
            super().__init__(_png_bytes())
            self.label = label

        def read(self, *args, **kwargs):
            events.append(f"read:{self.label}")
            return super().read(*args, **kwargs)

    files = _files(
        query=FileStorage(stream=RecordingStream("query"), filename="query.png"),
        gallery=[
            FileStorage(stream=RecordingStream("one"), filename="one.png"),
            FileStorage(stream=RecordingStream("two"), filename="two.png"),
        ],
    )

    def extract(_path, image):
        events.append("extract")
        return np.array([1.0, 0.0]), {"backend": "vehicle-onnx", "dim": 2}

    monkeypatch.setattr("services.vehicle_reid_feat.extract_vehicle_embedding", extract)
    _run(app, key, files)

    first_gallery_read = events.index("read:one")
    second_gallery_read = events.index("read:two")
    assert "extract" in events[first_gallery_read + 1:second_gallery_read]


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


def test_infer_route_returns_management_envelope_and_sanitizes_failures(
    scenario_app, monkeypatch, caplog,
):
    app, headers, model_folder = scenario_app
    _register_model(app, model_folder)
    monkeypatch.setattr(
        "routes.model_scenario.run_scenario",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret path")),
    )

    response = app.test_client().post(
        "/api/ai/model-scenarios/yolo26n-obb/infer",
        headers={**headers, "X-Request-Id": "scenario-failure-1"},
        data={"file": (io.BytesIO(_png_bytes()), "sample.png")},
    )

    assert response.status_code == 500
    assert response.get_json() == {"code": 500, "message": "inference failed", "data": None}
    assert response.headers["X-Request-Id"] == "scenario-failure-1"
    assert "scenario-failure-1" in caplog.text
    assert "secret path" not in caplog.text


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
    assert response.headers["X-Request-Id"]


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
    assert response.headers["X-Request-Id"]


def test_infer_route_preserves_request_too_large_as_413(scenario_app, monkeypatch):
    app, headers, _model_folder = scenario_app

    def too_large(*_args, **_kwargs):
        raise _dispatcher().ScenarioPayloadTooLarge(
            "image exceeds the scenario image size limit"
        )

    monkeypatch.setattr("routes.model_scenario.run_scenario", too_large)

    response = app.test_client().post(
        "/api/ai/model-scenarios/yolo26n-obb/infer",
        headers=headers,
        data={"file": (io.BytesIO(b"image"), "sample.png")},
    )

    assert response.status_code == 413
    assert response.get_json() == {
        "code": 413, "message": "image exceeds the scenario image size limit", "data": None,
    }
    assert response.headers["X-Request-Id"]


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ("/api/ai/model-scenarios?phase=1", "routes.model_scenario.list_scenario_groups"),
        ("/api/ai/model-scenarios?phase=1&grouped=0", "routes.model_scenario.list_scenarios"),
        ("/api/ai/model-scenarios/yolo26n-obb", "routes.model_scenario.get_scenario"),
    ],
)
def test_management_reads_log_and_sanitize_unexpected_failures(
    scenario_app, monkeypatch, caplog, path, target,
):
    app, headers, _model_folder = scenario_app
    monkeypatch.setattr(
        target,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("C:/secret/model.pt")),
    )

    response = app.test_client().get(
        path, headers={**headers, "X-Request-Id": "scenario-read-failure"},
    )

    assert response.status_code == 500
    assert response.get_json() == {
        "code": 500, "message": "model scenario lookup failed", "data": None,
    }
    assert response.headers["X-Request-Id"] == "scenario-read-failure"
    assert "scenario-read-failure" in caplog.text
    assert "secret/model.pt" not in caplog.text
