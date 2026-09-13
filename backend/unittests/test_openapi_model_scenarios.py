import io

import pytest
from flask import Flask

from extensions import db
from models import AiModel, OpenApiKey, OpenApp
from routes.openapi_v1 import openapi_v1_bp
from security_open import hash_api_key, key_prefix
from services.model_scenario_inference import ScenarioInputError


@pytest.fixture
def openapi_app():
    app = Flask("openapi-model-scenarios")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MODEL_FOLDER="backend/.task4-models-not-present",
        MAX_CONTENT_LENGTH=2048,
    )
    db.init_app(app)
    app.register_blueprint(openapi_v1_bp)

    def add_credentials(name, scopes):
        raw_key = f"tp_live_{name}_scenario_test_key"
        open_app = OpenApp(
            app_id=f"app-{name}",
            name=name,
            status="0",
            qps_limit=0,
            daily_limit=0,
        )
        open_app.set_scopes(scopes)
        db.session.add(open_app)
        db.session.flush()
        db.session.add(OpenApiKey(
            app_pk=open_app.id,
            name="test",
            key_prefix=key_prefix(raw_key),
            key_hash=hash_api_key(raw_key),
            status="0",
        ))
        db.session.commit()
        return {"X-App-Id": open_app.app_id, "X-Api-Key": raw_key}

    with app.app_context():
        db.create_all()
        read_headers = add_credentials("reader", ["model-scenario:read"])
        infer_headers = add_credentials("runner", ["model-scenario:infer"])
        db.session.add(AiModel(
            model_name="Private OBB runtime",
            model_key="yolo26n-obb",
            task="obb",
            library="ultralytics",
            source_url="https://private.example/models/yolo26n-obb",
            file_path="secret/internal/yolo26n-obb.pt",
            status="0",
        ))
        db.session.commit()

    yield app, read_headers, infer_headers

    with app.app_context():
        db.session.remove()
        db.drop_all()


def _assert_open_error(response, status, err_type):
    assert response.status_code == status
    payload = response.get_json()
    assert payload["code"] == status
    assert payload["error"] == {"type": err_type, "message": payload["message"]}
    assert payload["requestId"]
    assert response.headers["X-Request-Id"] == payload["requestId"]
    return payload


def test_read_scope_lists_and_gets_public_scenarios_but_cannot_infer(openapi_app):
    app, read_headers, _infer_headers = openapi_app
    client = app.test_client()

    listing = client.get("/openapi/v1/model-scenarios?phase=1", headers=read_headers)
    assert listing.status_code == 200
    list_payload = listing.get_json()
    assert list_payload["code"] == 0
    assert len(list_payload["data"]) == 9
    assert list_payload["data"][0]["modelKey"] == "efficient-sam"
    assert all("model" not in item for item in list_payload["data"])

    detail = client.get(
        "/openapi/v1/model-scenarios/yolo26n-obb", headers=read_headers,
    )
    assert detail.status_code == 200
    detail_payload = detail.get_json()
    assert detail_payload["code"] == 0
    assert detail_payload["data"]["modelKey"] == "yolo26n-obb"
    assert detail_payload["data"]["configured"] is True
    assert "model" not in detail_payload["data"]
    assert "secret/internal" not in detail.get_data(as_text=True)
    assert "private.example" not in detail.get_data(as_text=True)

    denied = client.post(
        "/openapi/v1/model-scenarios/yolo26n-obb/infer",
        headers=read_headers,
        data={"file": (io.BytesIO(b"image"), "sample.png")},
    )
    denied_payload = _assert_open_error(denied, 403, "forbidden")
    assert "model-scenario:infer" in denied_payload["message"]


def test_public_scenario_shape_is_allowlisted_and_uses_the_real_infer_path(
    openapi_app, monkeypatch,
):
    app, read_headers, _infer_headers = openapi_app
    import routes.openapi_v1 as openapi_routes

    real_readiness = openapi_routes.scenario_with_readiness

    def readiness_with_future_management_field(scenario):
        data = real_readiness(scenario)
        data["futureManagementSecret"] = "C:/secret/future-admin-value"
        return data

    monkeypatch.setattr(
        openapi_routes,
        "scenario_with_readiness",
        readiness_with_future_management_field,
    )
    response = app.test_client().get(
        "/openapi/v1/model-scenarios/yolo26n-obb", headers=read_headers,
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert set(data) == {
        "phase", "order", "modelKey", "name", "category", "ability",
        "workbenchType", "project", "description", "workflow", "outputs",
        "metrics", "risks", "defaults", "input", "apiPath", "configured",
        "enabled", "weightsPresent", "runtimeAvailable", "ready", "reason",
    }
    assert data["apiPath"] == (
        "/openapi/v1/model-scenarios/yolo26n-obb/infer"
    )
    assert "future-admin-value" not in response.get_data(as_text=True)


def test_infer_scope_dispatches_to_shared_scenario_runner(openapi_app, monkeypatch):
    app, _read_headers, infer_headers = openapi_app
    captured = {}
    normalized = {
        "modelKey": "yolo26n-obb",
        "workbench": "obb_detection",
        "elapsedMs": 7,
        "result": {"detections": [], "count": 0},
    }

    def fake_run(model_key, files, form):
        captured.update(
            model_key=model_key,
            filename=files["file"].filename,
            conf=form["conf"],
        )
        return normalized

    monkeypatch.setattr("routes.openapi_v1.run_scenario", fake_run, raising=False)
    response = app.test_client().post(
        "/openapi/v1/model-scenarios/yolo26n-obb/infer",
        headers=infer_headers,
        data={
            "file": (io.BytesIO(b"image"), "sample.png"),
            "conf": "0.4",
            "modelPath": "C:/attacker/model.pt",
            "library": "attacker-runtime",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"] == 0
    assert payload["data"] == normalized
    assert payload["requestId"]
    assert captured == {
        "model_key": "yolo26n-obb",
        "filename": "sample.png",
        "conf": "0.4",
    }


def test_unknown_unavailable_and_malformed_requests_use_open_errors(
    openapi_app, monkeypatch,
):
    app, read_headers, infer_headers = openapi_app
    client = app.test_client()

    unknown = client.get(
        "/openapi/v1/model-scenarios/not-registered", headers=read_headers,
    )
    unknown_payload = _assert_open_error(unknown, 404, "not_found")
    assert unknown_payload["message"] == "model scenario not found"

    def unavailable(*_args, **_kwargs):
        raise ScenarioInputError("model weights are missing")

    monkeypatch.setattr("routes.openapi_v1.run_scenario", unavailable, raising=False)
    unavailable_response = client.post(
        "/openapi/v1/model-scenarios/yolo26n-obb/infer",
        headers=infer_headers,
        data={"file": (io.BytesIO(b"image"), "sample.png")},
    )
    unavailable_payload = _assert_open_error(unavailable_response, 400, "validation")
    assert unavailable_payload["message"] == "model weights are missing"

    def malformed(*_args, **_kwargs):
        raise ScenarioInputError("conf must be a number between 0 and 1")

    monkeypatch.setattr("routes.openapi_v1.run_scenario", malformed, raising=False)
    malformed_response = client.post(
        "/openapi/v1/model-scenarios/yolo26n-obb/infer",
        headers=infer_headers,
        data={"file": (io.BytesIO(b"image"), "sample.png"), "conf": "wrong"},
    )
    malformed_payload = _assert_open_error(malformed_response, 400, "validation")
    assert malformed_payload["message"] == "conf must be a number between 0 and 1"


def test_infer_preserves_file_limit_and_sanitizes_runtime_failures(
    openapi_app, monkeypatch,
):
    app, _read_headers, infer_headers = openapi_app
    client = app.test_client()

    too_large = client.post(
        "/openapi/v1/model-scenarios/yolo26n-obb/infer",
        headers=infer_headers,
        data={"file": (io.BytesIO(b"x" * 2049), "sample.png")},
    )
    too_large_payload = _assert_open_error(too_large, 413, "request_too_large")
    assert too_large_payload["message"] == "request entity too large"

    def runtime_failure(*_args, **_kwargs):
        raise RuntimeError("C:/secret/models/yolo26n-obb.pt provider failure")

    monkeypatch.setattr("routes.openapi_v1.run_scenario", runtime_failure, raising=False)
    failed = client.post(
        "/openapi/v1/model-scenarios/yolo26n-obb/infer",
        headers=infer_headers,
        data={"file": (io.BytesIO(b"image"), "sample.png")},
    )
    failed_payload = _assert_open_error(failed, 500, "inference")
    assert failed_payload["message"] == "inference failed"
    assert "secret" not in failed.get_data(as_text=True)


@pytest.mark.parametrize("path", [
    "/openapi/v1/model-scenarios",
    "/openapi/v1/model-scenarios/yolo26n-obb",
])
def test_scenario_reads_sanitize_unexpected_readiness_failures(
    openapi_app, monkeypatch, path,
):
    app, read_headers, _infer_headers = openapi_app

    def readiness_failure(*_args, **_kwargs):
        raise RuntimeError("C:/secret/models/yolo26n-obb.pt database failure")

    monkeypatch.setattr("routes.openapi_v1.scenario_with_readiness", readiness_failure)
    response = app.test_client().get(path, headers=read_headers)

    payload = _assert_open_error(response, 500, "internal")
    assert payload["message"] == "model scenario lookup failed"
    assert "secret" not in response.get_data(as_text=True)


def test_scenario_detail_sanitizes_unexpected_registry_failure(
    openapi_app, monkeypatch,
):
    app, read_headers, _infer_headers = openapi_app

    def registry_failure(*_args, **_kwargs):
        raise RuntimeError("D:/secret/catalog/database.sqlite failure")

    monkeypatch.setattr("routes.openapi_v1.get_scenario", registry_failure)
    response = app.test_client().get(
        "/openapi/v1/model-scenarios/yolo26n-obb", headers=read_headers,
    )

    payload = _assert_open_error(response, 500, "internal")
    assert payload["message"] == "model scenario lookup failed"
    assert "secret" not in response.get_data(as_text=True)


def test_openapi_json_documents_scenario_paths_scopes_and_multipart_fields(openapi_app):
    app, _read_headers, _infer_headers = openapi_app
    spec = app.test_client().get("/openapi/v1/openapi.json").get_json()

    collection = spec["paths"]["/model-scenarios"]["get"]
    detail = spec["paths"]["/model-scenarios/{modelKey}"]["get"]
    infer = spec["paths"]["/model-scenarios/{modelKey}/infer"]["post"]
    assert collection["x-required-scope"] == "model-scenario:read"
    assert detail["x-required-scope"] == "model-scenario:read"
    assert infer["x-required-scope"] == "model-scenario:infer"
    assert "500" in collection["responses"]
    assert "500" in detail["responses"]
    list_example = collection["responses"]["200"]["content"]["application/json"]["example"]
    assert list_example["data"][0]["apiPath"] == (
        "/openapi/v1/model-scenarios/yolo26n-obb/infer"
    )

    form_schema = infer["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert {frozenset(option["required"]) for option in form_schema["oneOf"]} == {
        frozenset(("file",)),
        frozenset(("query", "gallery")),
    }
    assert {
        "file", "query", "gallery", "points", "labels", "box",
        "mode", "precision", "conf", "imgsz", "threshold",
    } <= set(form_schema["properties"])
    response_example = infer["responses"]["200"]["content"]["application/json"]["example"]
    assert response_example["code"] == 0
    assert response_example["data"]["modelKey"] == "yolo26n-obb"
    assert response_example["data"]["result"]["detections"] == []
