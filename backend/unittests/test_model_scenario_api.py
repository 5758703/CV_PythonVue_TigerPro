from __future__ import annotations

import builtins
import hashlib
import json
import sys
from pathlib import Path

import pytest
from flask import Flask
from flask_jwt_extended import create_access_token

from config import Config
from extensions import db, jwt
from models import AiModel, Role, User
from routes import all_blueprints
from services import model_scenario_readiness as readiness


@pytest.fixture
def scenario_api_client(tmp_path, monkeypatch):
    """An isolated management app with the project blueprints registered."""
    monkeypatch.setattr(Config, "MODEL_FOLDER", str(tmp_path / "models"))
    app = Flask("model-scenario-api")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'scenario-api.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="scenario-api-test-secret",
        MODEL_FOLDER=str(tmp_path / "models"),
    )
    db.init_app(app)
    jwt.init_app(app)
    for blueprint in all_blueprints:
        app.register_blueprint(blueprint)

    with app.app_context():
        db.create_all()
        admin_role = Role(role_name="Admin", role_key="admin")
        admin = User(username="scenario-admin", nickname="Scenario Admin")
        admin.set_password("not-used")
        admin.roles = [admin_role]
        db.session.add_all([admin_role, admin])
        db.session.commit()
        token = create_access_token(identity=str(admin.id))

    yield app.test_client(), {"Authorization": f"Bearer {token}"}, tmp_path

    with app.app_context():
        db.session.remove()
        db.drop_all()


def _model(
    *, key: str, library: str, file_path: str | None,
    task: str = "object-detection", status: str = "0",
) -> AiModel:
    return AiModel(
        model_name=f"Configured {key}",
        model_key=key,
        task=task,
        library=library,
        file_path=file_path,
        status=status,
    )


def _assert_envelope(response, status_code=200):
    assert response.status_code == status_code
    payload = response.get_json()
    assert set(payload) == {"code", "message", "data"}
    return payload


def _model_folder(client) -> Path:
    return Path(client.application.config["MODEL_FOLDER"])


def test_phase_one_catalog_returns_nine_entries_and_requires_authentication(scenario_api_client):
    """Removing the registered catalog route must reject anonymous catalog access."""
    client, headers, _tmp_path = scenario_api_client

    assert client.get("/api/ai/model-scenarios?phase=1").status_code == 401

    payload = _assert_envelope(client.get("/api/ai/model-scenarios?phase=1", headers=headers))
    assert payload["code"] == 0
    assert len(payload["data"]) == 9
    assert {entry["modelKey"] for entry in payload["data"]} == {
        "efficient-sam",
        "mobile-sam",
        "clip-reid-vehicle",
        "keremberke-yolov5m-license-plate",
        "keremberke-yolov5n-license-plate",
        "transreid-vehicle",
        "vehicle-vit-reid",
        "yolo26n-obb",
        "yolo26n-p2-plate",
    }


def test_detail_joins_the_exact_registered_model_key(scenario_api_client, monkeypatch):
    """A catalog detail must use its own key, not a similarly named database row."""
    client, headers, tmp_path = scenario_api_client
    weights = _model_folder(client)
    weights.mkdir()
    (weights / "obb.pt").write_bytes(b"weight")

    with client.application.app_context():
        db.session.add_all([
            _model(
                key="yolo26n-obb", task="obb", library="ultralytics",
                file_path="models/obb.pt",
            ),
            _model(
                key="yolo26n-obb-shadow", task="obb", library="ultralytics",
                file_path="missing.pt",
            ),
        ])
        db.session.commit()
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())

    payload = _assert_envelope(client.get("/api/ai/model-scenarios/yolo26n-obb", headers=headers))
    detail = payload["data"]
    assert detail["modelKey"] == "yolo26n-obb"
    assert detail["model"]["modelKey"] == "yolo26n-obb"
    assert detail["configured"] is True
    assert detail["enabled"] is True
    assert detail["weightsPresent"] is True
    assert detail["runtimeAvailable"] is True
    assert detail["ready"] is True
    assert detail["apiReady"] is True
    assert detail["reason"] is None


def test_unknown_catalog_key_is_not_found(scenario_api_client):
    """A non-catalog key must not be represented as a readiness result."""
    client, headers, _tmp_path = scenario_api_client

    payload = _assert_envelope(
        client.get("/api/ai/model-scenarios/not-a-registered-model", headers=headers),
        status_code=404,
    )
    assert payload["code"] == 404
    assert payload["data"] is None


@pytest.mark.parametrize(
    ("key", "library", "file_path", "status", "expected"),
    [
        (
            "mobile-sam", "mobilesam", "mobile.pt", "1",
            {"enabled": False, "weightsPresent": True, "runtimeAvailable": True, "reason": "model is disabled"},
        ),
        (
            "transreid-vehicle", "transreid", "missing.onnx", "0",
            {"enabled": True, "weightsPresent": False, "runtimeAvailable": True, "reason": "model weights are missing"},
        ),
        (
            "vehicle-vit-reid", "vit-reid", "vehicle.onnx", "0",
            {"enabled": True, "weightsPresent": True, "runtimeAvailable": False, "reason": "runtime library is unavailable"},
        ),
    ],
)
def test_readiness_exposes_boolean_checks_and_the_blocking_reason(
    scenario_api_client, monkeypatch, key, library, file_path, status, expected,
):
    """Removing any readiness prerequisite must leave a truthful, explicit state."""
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client)
    weights.mkdir()
    if expected["weightsPresent"]:
        (weights / file_path).write_bytes(b"x" * 100_001)

    monkeypatch.setattr(
        readiness,
        "_find_module_spec",
        lambda module: None if key == "vehicle-vit-reid" and module == "onnxruntime" else object(),
    )

    with client.application.app_context():
        task = "interactive-segmentation" if key == "mobile-sam" else "vehicle-reid"
        db.session.add(_model(
            key=key, task=task, library=library, file_path=file_path, status=status,
        ))
        db.session.commit()

    payload = _assert_envelope(client.get(f"/api/ai/model-scenarios/{key}", headers=headers))
    state = payload["data"]
    assert state["configured"] is True
    assert state["ready"] is False
    for field, value in expected.items():
        assert state[field] == value


def test_library_alias_probes_its_controlled_runtime_module(scenario_api_client, monkeypatch):
    """A clip-reid registration must probe onnxruntime, never its database alias."""
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client) / "clip-reid"
    weights.mkdir(parents=True)
    (weights / "clip_vehicle_reid.onnx").write_bytes(b"x" * 100_001)
    monkeypatch.setattr(
        readiness,
        "_find_module_spec",
        lambda module: object() if module == "onnxruntime" else None,
        raising=False,
    )

    with client.application.app_context():
        db.session.add(_model(
            key="clip-reid-vehicle", task="vehicle-reid",
            library="clip-reid", file_path="clip-reid",
        ))
        db.session.commit()

    payload = _assert_envelope(client.get("/api/ai/model-scenarios/clip-reid-vehicle", headers=headers))
    assert payload["data"]["weightsPresent"] is True
    assert payload["data"]["runtimeAvailable"] is True
    assert payload["data"]["ready"] is True
    assert payload["data"]["apiReady"] is True


@pytest.mark.parametrize(
    ("key", "library", "folder", "asset_name", "blocked_module"),
    [
        (
            "clip-reid-vehicle", "clip-reid", "clip-reid", "clip_vehicle_reid.onnx",
            "services.vehicle_reid_feat",
        ),
        (
            "efficient-sam", "opencv-sam", "efficient-sam",
            "image_segmentation_efficientsam_ti_2025april.onnx", "efficient_sam_dnn",
        ),
    ],
)
def test_missing_optional_asset_adapter_returns_not_ready_detail(
    scenario_api_client, monkeypatch, key, library, folder, asset_name, blocked_module,
):
    """A missing optional runtime module must not turn directory readiness into a 500."""
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client) / folder
    weights.mkdir(parents=True)
    (weights / asset_name).write_bytes(b"x" * 100_001)
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: None)

    with client.application.app_context():
        task = "interactive-segmentation" if key == "efficient-sam" else "vehicle-reid"
        db.session.add(_model(
            key=key, task=task, library=library, file_path=folder,
        ))
        db.session.commit()

    original_import = builtins.__import__

    def reject_optional_asset_adapter(name, *args, **kwargs):
        if name == blocked_module:
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_optional_asset_adapter)
    payload = _assert_envelope(client.get(f"/api/ai/model-scenarios/{key}", headers=headers))
    assert payload["data"]["weightsPresent"] is True
    assert payload["data"]["runtimeAvailable"] is False
    assert payload["data"]["ready"] is False
    expected_reason = (
        "production manifest is missing or invalid"
        if key == "efficient-sam" else "runtime library is unavailable"
    )
    assert payload["data"]["reason"] == expected_reason


def test_runtime_probe_does_not_import_a_dotted_business_parent(tmp_path, monkeypatch):
    """A dotted runtime name must not execute the parent package during readiness."""
    package_name = "scenario_readiness_probe_parent"
    marker_name = "_scenario_readiness_probe_parent_loaded"
    package_dir = tmp_path / package_name
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(
        f"import builtins\nbuiltins.{marker_name} = True\n",
        encoding="utf-8",
    )
    (package_dir / "runtime.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(builtins, marker_name, False, raising=False)
    monkeypatch.delitem(sys.modules, package_name, raising=False)
    monkeypatch.delitem(sys.modules, f"{package_name}.runtime", raising=False)

    assert readiness._runtime_available(f"{package_name}.runtime") is False
    assert getattr(builtins, marker_name) is False


def test_empty_weight_directory_is_not_ready(scenario_api_client):
    """An empty configured directory must not be treated as a model asset."""
    client, headers, _tmp_path = scenario_api_client
    (_model_folder(client) / "empty-assets").mkdir(parents=True)

    with client.application.app_context():
        db.session.add(_model(
            key="vehicle-vit-reid", task="vehicle-reid", library="vit-reid",
            file_path="empty-assets",
        ))
        db.session.commit()

    payload = _assert_envelope(client.get("/api/ai/model-scenarios/vehicle-vit-reid", headers=headers))
    assert payload["data"]["weightsPresent"] is False
    assert payload["data"]["ready"] is False
    assert payload["data"]["reason"] == "model weights are missing"


def test_weight_path_uses_the_current_application_model_folder(scenario_api_client, monkeypatch):
    """A deployment-specific MODEL_FOLDER must override the process-level default."""
    client, headers, tmp_path = scenario_api_client
    active_folder = tmp_path / "deployment-models"
    active_folder.mkdir()
    (active_folder / "obb.pt").write_bytes(b"weight")
    client.application.config["MODEL_FOLDER"] = str(active_folder)

    with client.application.app_context():
        db.session.add(_model(
            key="yolo26n-obb", task="obb", library="ultralytics", file_path="obb.pt",
        ))
        db.session.commit()
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())

    payload = _assert_envelope(client.get("/api/ai/model-scenarios/yolo26n-obb", headers=headers))
    assert payload["data"]["weightsPresent"] is True
    assert payload["data"]["ready"] is True


@pytest.mark.parametrize(
    ("key", "task", "library", "suffix", "reason"),
    [
        (
            "yolo26n-obb", "object-detection", "ultralytics", ".pt",
            "registered model task does not match scenario contract",
        ),
        (
            "yolo26n-obb", "obb", "os", ".pt",
            "registered model library does not match scenario contract",
        ),
        (
            "yolo26n-obb", "obb", "ultralytics", ".weights",
            "model weights are incompatible with scenario runtime",
        ),
    ],
)
def test_readiness_enforces_the_same_exact_contract_as_inference(
    scenario_api_client, monkeypatch, key, task, library, suffix, reason,
):
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client)
    weights.mkdir()
    (weights / f"asset{suffix}").write_bytes(b"weight")
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())

    with client.application.app_context():
        db.session.add(_model(
            key=key, task=task, library=library, file_path=f"asset{suffix}",
        ))
        db.session.commit()

    detail = _assert_envelope(
        client.get(f"/api/ai/model-scenarios/{key}", headers=headers),
    )["data"]
    assert detail["ready"] is False
    assert detail["apiReady"] is False
    assert detail["reason"] == reason


def test_p2_plate_generic_training_base_is_never_reported_api_ready(
    scenario_api_client, monkeypatch,
):
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client)
    weights.mkdir()
    (weights / "yolo26n.pt").write_bytes(b"generic base")
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())

    with client.application.app_context():
        db.session.add(_model(
            key="yolo26n-p2-plate", task="object-detection",
            library="ultralytics", file_path="yolo26n.pt",
        ))
        db.session.commit()

    detail = _assert_envelope(client.get(
        "/api/ai/model-scenarios/yolo26n-p2-plate", headers=headers,
    ))["data"]
    assert detail["weightsPresent"] is True
    assert detail["apiReady"] is False
    assert detail["ready"] is False
    assert detail["reason"] == "plate-specific production manifest is missing or invalid"


def test_p2_plate_valid_production_manifest_enables_the_verified_artifact(
    scenario_api_client, monkeypatch,
):
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client)
    weights.mkdir()
    artifact = weights / "p2-plate.pt"
    artifact.write_bytes(b"trained")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (weights / "production-manifest.json").write_text(
        '{"modelKey":"yolo26n-p2-plate","task":"object-detection",'
        '"trainingComplete":true,"classes":["license_plate"],'
        f'"artifactFile":"p2-plate.pt","artifactSha256":"{digest}"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())
    with client.application.app_context():
        db.session.add(_model(
            key="yolo26n-p2-plate", task="object-detection",
            library="ultralytics", file_path="p2-plate.pt",
        ))
        db.session.commit()

    detail = _assert_envelope(client.get(
        "/api/ai/model-scenarios/yolo26n-p2-plate", headers=headers,
    ))["data"]
    assert detail["apiReady"] is True
    assert detail["reason"] is None


@pytest.mark.parametrize(
    "manifest_update",
    [
        {"artifactFile": None},
        {"artifactSha256": None},
        {"artifactFile": "../p2-plate.pt"},
        {"artifactFile": "other.pt"},
        {"artifactSha256": "0" * 64},
        {"artifactSha256": "not-a-sha256"},
    ],
)
def test_p2_manifest_must_bind_the_exact_artifact_and_hash(
    scenario_api_client, monkeypatch, manifest_update,
):
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client)
    weights.mkdir()
    artifact = weights / "p2-plate.pt"
    artifact.write_bytes(b"trained")
    manifest = {
        "modelKey": "yolo26n-p2-plate",
        "task": "object-detection",
        "trainingComplete": True,
        "classes": ["license_plate"],
        "artifactFile": artifact.name,
        "artifactSha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    manifest.update(manifest_update)
    (weights / "production-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())
    with client.application.app_context():
        db.session.add(_model(
            key="yolo26n-p2-plate", task="object-detection",
            library="ultralytics", file_path=artifact.name,
        ))
        db.session.commit()

    detail = _assert_envelope(client.get(
        "/api/ai/model-scenarios/yolo26n-p2-plate", headers=headers,
    ))["data"]
    assert detail["apiReady"] is False
    assert detail["reason"] == "plate-specific production manifest is missing or invalid"


def test_p2_directory_with_multiple_compatible_weights_is_ambiguous(
    scenario_api_client, monkeypatch,
):
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client) / "p2"
    weights.mkdir(parents=True)
    for name in ("one.pt", "two.pt"):
        (weights / name).write_bytes(name.encode())
    digest = hashlib.sha256((weights / "one.pt").read_bytes()).hexdigest()
    (weights / "production-manifest.json").write_text(json.dumps({
        "modelKey": "yolo26n-p2-plate", "task": "object-detection",
        "trainingComplete": True, "classes": ["license_plate"],
        "artifactFile": "one.pt", "artifactSha256": digest,
    }), encoding="utf-8")
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())
    with client.application.app_context():
        db.session.add(_model(
            key="yolo26n-p2-plate", task="object-detection",
            library="ultralytics", file_path="p2",
        ))
        db.session.commit()

    detail = _assert_envelope(client.get(
        "/api/ai/model-scenarios/yolo26n-p2-plate", headers=headers,
    ))["data"]
    assert detail["apiReady"] is False
    assert detail["reason"] == "model weight directory is ambiguous"


def test_p2_plate_renamed_base_requires_a_production_manifest(
    scenario_api_client, monkeypatch,
):
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client)
    weights.mkdir()
    (weights / "custom-trained-looking.pt").write_bytes(b"unverified")
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())

    with client.application.app_context():
        db.session.add(_model(
            key="yolo26n-p2-plate", task="object-detection",
            library="ultralytics", file_path="custom-trained-looking.pt",
        ))
        db.session.commit()

    detail = _assert_envelope(client.get(
        "/api/ai/model-scenarios/yolo26n-p2-plate", headers=headers,
    ))["data"]
    assert detail["apiReady"] is False
    assert detail["reason"] == "plate-specific production manifest is missing or invalid"


def test_efficientsam_rejects_an_arbitrary_large_onnx_file(
    scenario_api_client, monkeypatch,
):
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client)
    weights.mkdir()
    (weights / "unrelated-large-model.onnx").write_bytes(b"x" * 100_001)
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())

    with client.application.app_context():
        db.session.add(_model(
            key="efficient-sam", task="interactive-segmentation",
            library="opencv-sam", file_path="unrelated-large-model.onnx",
        ))
        db.session.commit()

    detail = _assert_envelope(client.get(
        "/api/ai/model-scenarios/efficient-sam", headers=headers,
    ))["data"]
    assert detail["apiReady"] is False
    assert detail["reason"] == "model weights are incompatible with scenario runtime"


def test_efficientsam_requires_a_hash_bound_production_manifest(
    scenario_api_client, monkeypatch,
):
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client)
    weights.mkdir()
    artifact = weights / "image_segmentation_efficientsam_ti_2025april.onnx"
    artifact.write_bytes(b"x" * 100_001)
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())
    with client.application.app_context():
        db.session.add(_model(
            key="efficient-sam", task="interactive-segmentation",
            library="opencv-sam", file_path=artifact.name,
        ))
        db.session.commit()

    missing = _assert_envelope(client.get(
        "/api/ai/model-scenarios/efficient-sam", headers=headers,
    ))["data"]
    assert missing["apiReady"] is False
    assert missing["reason"] == "production manifest is missing or invalid"

    (weights / "production-manifest.json").write_text(json.dumps({
        "modelKey": "efficient-sam", "task": "interactive-segmentation",
        "artifactFile": artifact.name,
        "artifactSha256": hashlib.sha256(artifact.read_bytes()).hexdigest().upper(),
    }), encoding="utf-8")
    ready = _assert_envelope(client.get(
        "/api/ai/model-scenarios/efficient-sam", headers=headers,
    ))["data"]
    assert ready["apiReady"] is True
    assert ready["supportedPrecisions"] == ["fp32"]


def test_efficientsam_dual_manifest_publishes_both_precisions(
    scenario_api_client, monkeypatch,
):
    client, headers, _tmp_path = scenario_api_client
    weights = _model_folder(client) / "efficient-dual"
    weights.mkdir(parents=True)
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
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())
    with client.application.app_context():
        db.session.add(_model(
            key="efficient-sam", task="interactive-segmentation",
            library="opencv-sam", file_path="efficient-dual",
        ))
        db.session.commit()

    detail = _assert_envelope(client.get(
        "/api/ai/model-scenarios/efficient-sam", headers=headers,
    ))["data"]
    assert detail["apiReady"] is True
    assert detail["supportedPrecisions"] == ["fp32", "int8"]

    artifacts["int8"]["artifactSha256"] = "0" * 64
    (weights / "production-manifest.json").write_text(json.dumps({
        "modelKey": "efficient-sam", "task": "interactive-segmentation",
        "artifacts": artifacts,
    }), encoding="utf-8")
    invalid = _assert_envelope(client.get(
        "/api/ai/model-scenarios/efficient-sam", headers=headers,
    ))["data"]
    assert invalid["apiReady"] is False
    assert invalid["reason"] == "production manifest is missing or invalid"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("published", False, "scenario is not published"),
        ("apiEnabled", False, "scenario API is disabled"),
        ("adapter", "wrong-adapter", "scenario adapter is not supported"),
    ],
)
def test_readiness_enforces_explicit_publication_and_adapter_contract(
    scenario_api_client, monkeypatch, field, value, reason,
):
    _client, _headers, _tmp_path = scenario_api_client
    weights = _model_folder(_client)
    weights.mkdir()
    (weights / "obb.pt").write_bytes(b"weight")
    monkeypatch.setattr(readiness, "_find_module_spec", lambda _module: object())

    with _client.application.app_context():
        db.session.add(_model(
            key="yolo26n-obb", task="obb", library="ultralytics", file_path="obb.pt",
        ))
        db.session.commit()
        from services.model_scenarios import get_scenario
        scenario = get_scenario("yolo26n-obb")
        scenario[field] = value
        detail = readiness.scenario_with_readiness(scenario)

    assert detail["apiReady"] is False
    assert detail["ready"] is False
    assert detail["reason"] == reason
