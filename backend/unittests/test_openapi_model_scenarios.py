import io
import hashlib
import hmac
import mimetypes
import time
import uuid
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, quote

import pytest
from flask import Flask

from extensions import db
from models import (
    AiModel,
    OpenApiCallLog,
    OpenApiKey,
    OpenApp,
)
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
        SCENARIO_MAX_IMAGE_BYTES=1024,
        SCENARIO_MAX_PIXELS=100,
        SCENARIO_MAX_PROMPTS=2,
        SCENARIO_MAX_GALLERY_IMAGES=2,
        SCENARIO_MAX_MULTIPART_PARTS=8,
        SCENARIO_MAX_FILES=3,
        SCENARIO_MAX_REQUEST_BYTES=2048,
        OPENAPI_SIGNATURE_MAX_AGE_SECONDS=300,
        TRUST_PROXY=False,
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
        return {"X-App-Id": open_app.app_id, "X-Api-Key": raw_key, "_raw": raw_key}

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


def _normalized_query(path):
    query = path.partition("?")[2]
    pairs = parse_qsl(query, keep_blank_values=True)
    encoded = [(quote(k, safe="-._~"), quote(v, safe="-._~")) for k, v in pairs]
    return "&".join(f"{k}={v}" for k, v in sorted(encoded))


def _multipart_payload_hash(data):
    lines = []
    source_items = list((data or {}).items())
    # Werkzeug's multipart encoder emits ordinary fields before file fields.
    items = [item for item in source_items if not isinstance(item[1], tuple)]
    items += [item for item in source_items if isinstance(item[1], tuple)]
    for index, (field, value) in enumerate(items):
        if isinstance(value, tuple):
            stream = value[0]
            raw = stream.getvalue()
            filename = value[1]
            content_type = value[2] if len(value) > 2 else (
                mimetypes.guess_type(filename)[0] or "application/octet-stream"
            )
            lines.append(
                f"{index}:file:{quote(field, safe='')}:{quote(filename, safe='-._~')}:"
                f"{content_type.lower()}:{hashlib.sha256(raw).hexdigest()}"
            )
        else:
            lines.append(
                f"{index}:form:{quote(str(field), safe='')}={quote(str(value), safe='-._~')}"
            )
    canonical_payload = "\n".join(lines).encode()
    return hashlib.sha256(canonical_payload).hexdigest()


def _signed_headers(
    credentials,
    method,
    path,
    data=None,
    *,
    timestamp=None,
    nonce=None,
    signature=None,
):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    nonce = nonce or f"nonce-{uuid.uuid4().hex}"
    request_path = path.split("?", 1)[0]
    if data is not None:
        body_hash = _multipart_payload_hash(data)
    else:
        body_hash = hashlib.sha256(b"").hexdigest()
    canonical = (
        f"{method.upper()}\n{quote(request_path, safe='/-._~')}\n{_normalized_query(path)}\n"
        f"{timestamp}\n{nonce}\n{'multipart/form-data' if data is not None else ''}\n{body_hash}"
    )
    expected = hmac.new(
        credentials["_raw"].encode(), canonical.encode(), hashlib.sha256,
    ).hexdigest()
    return {
        "X-App-Id": credentials["X-App-Id"],
        "X-Api-Key": credentials["X-Api-Key"],
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature or expected,
    }


def test_scenario_endpoints_require_hmac_timestamp_and_nonce(openapi_app):
    app, read_headers, _infer_headers = openapi_app
    path = "/openapi/v1/model-scenarios"

    unsigned = app.test_client().get(path, headers={
        "X-App-Id": read_headers["X-App-Id"],
        "X-Api-Key": read_headers["X-Api-Key"],
    })

    payload = _assert_open_error(unsigned, 401, "signature")
    assert payload["message"] == "signed request headers are required"


def test_scenario_signature_rejects_tampering_and_expired_timestamps(openapi_app):
    app, read_headers, _infer_headers = openapi_app
    path = "/openapi/v1/model-scenarios"
    client = app.test_client()

    tampered = client.get(path, headers=_signed_headers(
        read_headers, "GET", path, signature="0" * 64,
    ))
    _assert_open_error(tampered, 401, "signature")

    expired = client.get(path, headers=_signed_headers(
        read_headers,
        "GET",
        path,
        timestamp=int(time.time()) - 301,
    ))
    expired_payload = _assert_open_error(expired, 401, "signature")
    assert expired_payload["message"] == "request timestamp is outside the allowed window"

    oversized_timestamp = client.get(path, headers=_signed_headers(
        read_headers,
        "GET",
        path,
        timestamp="9" * 5000,
    ))
    _assert_open_error(oversized_timestamp, 401, "signature")


def test_signature_covers_query_values_and_repeated_query_keys(openapi_app):
    app, read_headers, _ = openapi_app
    signed_path = "/openapi/v1/model-scenarios?phase=1&tag=b&tag=a"
    tampered_path = "/openapi/v1/model-scenarios?phase=2&tag=b&tag=a"
    response = app.test_client().get(
        tampered_path, headers=_signed_headers(read_headers, "GET", signed_path),
    )
    _assert_open_error(response, 401, "signature")


def test_signature_covers_multipart_order_filename_and_content_type(openapi_app):
    app, _, infer_headers = openapi_app
    path = "/openapi/v1/model-scenarios/clip-reid-vehicle/infer"
    signed = {
        "query": (io.BytesIO(b"query"), "query.jpg", "image/jpeg"),
        "gallery": (io.BytesIO(b"gallery"), "gallery.jpg", "image/jpeg"),
        "threshold": "0.7",
    }
    headers = _signed_headers(infer_headers, "POST", path, signed)
    tampered = {
        "gallery": (io.BytesIO(b"gallery"), "renamed.jpg", "image/jpeg"),
        "query": (io.BytesIO(b"query"), "query.jpg", "image/jpeg"),
        "threshold": "0.7",
    }
    response = app.test_client().post(path, data=tampered, headers=headers)
    _assert_open_error(response, 401, "signature")


def test_signed_request_rejects_content_length_unknown_file_and_excess_parts(openapi_app):
    app, _, infer_headers = openapi_app
    path = "/openapi/v1/model-scenarios/yolo26n-obb/infer"
    client = app.test_client()
    oversized = client.post(
        path,
        data=b"x" * 2049,
        content_type="application/octet-stream",
        headers={**_signed_headers(infer_headers, "POST", path), "Content-Length": "2049"},
    )
    _assert_open_error(oversized, 413, "request_too_large")

    unknown = {"leah": (io.BytesIO(b"x"), "x.jpg", "image/jpeg")}
    unknown_response = client.post(
        path, data=unknown, headers=_signed_headers(infer_headers, "POST", path, unknown),
    )
    _assert_open_error(unknown_response, 400, "validation")

    too_many = {f"field{i}": str(i) for i in range(8)}
    too_many["file"] = (io.BytesIO(b"x"), "x.jpg", "image/jpeg")
    too_many_response = client.post(
        path, data=too_many, headers=_signed_headers(infer_headers, "POST", path, too_many),
    )
    _assert_open_error(too_many_response, 413, "request_too_large")


def test_scenario_nonce_is_persistent_and_replay_safe_across_clients(openapi_app):
    app, read_headers, _infer_headers = openapi_app
    path = "/openapi/v1/model-scenarios"
    nonce = "nonce-persistent-replay-001"
    headers = _signed_headers(read_headers, "GET", path, nonce=nonce)

    first = app.test_client().get(path, headers=headers)
    replay = app.test_client().get(path, headers=headers)

    assert first.status_code == 200
    replay_payload = _assert_open_error(replay, 409, "replay")
    assert replay_payload["message"] == "request nonce has already been used"
    import models
    nonce_model = getattr(models, "OpenApiNonce", None)
    assert nonce_model is not None
    with app.app_context():
        assert nonce_model.query.filter_by(nonce=nonce).count() == 1


def test_expired_scenario_nonce_is_removed_before_the_value_is_reused(openapi_app):
    app, read_headers, _infer_headers = openapi_app
    path = "/openapi/v1/model-scenarios"
    nonce = "nonce-expired-reusable-001"
    import models
    nonce_model = getattr(models, "OpenApiNonce")
    with app.app_context():
        row = OpenApp.query.filter_by(app_id=read_headers["X-App-Id"]).one()
        db.session.add(nonce_model(
            app_pk=row.id,
            nonce=nonce,
            expires_at=datetime.utcnow() - timedelta(seconds=1),
        ))
        db.session.commit()

    response = app.test_client().get(
        path,
        headers=_signed_headers(read_headers, "GET", path, nonce=nonce),
    )

    assert response.status_code == 200
    with app.app_context():
        rows = nonce_model.query.filter_by(nonce=nonce).all()
        assert len(rows) == 1
        assert rows[0].expires_at > datetime.utcnow()


def test_scenario_ip_allowlist_ignores_forwarded_ip_until_proxy_trust_is_enabled(
    openapi_app,
):
    app, read_headers, _infer_headers = openapi_app
    assert hasattr(OpenApp, "ip_allowlist")
    path = "/openapi/v1/model-scenarios"
    with app.app_context():
        row = OpenApp.query.filter_by(app_id=read_headers["X-App-Id"]).one()
        row.ip_allowlist = '["203.0.113.0/24"]'
        db.session.commit()

    untrusted_proxy = app.test_client().get(
        path,
        headers={
            **_signed_headers(read_headers, "GET", path),
            "X-Forwarded-For": "203.0.113.9",
        },
        environ_base={"REMOTE_ADDR": "198.51.100.4"},
    )
    _assert_open_error(untrusted_proxy, 403, "ip_forbidden")

    app.config["TRUST_PROXY"] = True
    trusted_proxy = app.test_client().get(
        path,
        headers={
            **_signed_headers(read_headers, "GET", path),
            "X-Forwarded-For": "203.0.113.9, 198.51.100.4",
        },
        environ_base={"REMOTE_ADDR": "198.51.100.4"},
    )
    assert trusted_proxy.status_code == 200


def test_scenario_rate_limit_is_database_backed_and_returns_retry_after(
    openapi_app, monkeypatch,
):
    app, read_headers, _infer_headers = openapi_app
    path = "/openapi/v1/model-scenarios"
    fixed_time = int(time.time())
    monkeypatch.setattr("security_open.time.time", lambda: fixed_time)
    with app.app_context():
        row = OpenApp.query.filter_by(app_id=read_headers["X-App-Id"]).one()
        row.ip_allowlist = None
        row.qps_limit = 1
        row.daily_limit = 0
        db.session.commit()
        app_pk = row.id

    first = app.test_client().get(
        path,
        headers=_signed_headers(read_headers, "GET", path, timestamp=fixed_time),
    )
    limited = app.test_client().get(
        path,
        headers=_signed_headers(read_headers, "GET", path, timestamp=fixed_time),
    )

    assert first.status_code == 200
    _assert_open_error(limited, 429, "rate_limited")
    assert limited.headers["Retry-After"] == "1"
    import models
    rate_model = getattr(models, "OpenApiRateBucket", None)
    assert rate_model is not None
    with app.app_context():
        assert rate_model.query.filter_by(app_pk=app_pk, bucket_kind="second").count() == 1


def test_scenario_daily_limit_is_shared_and_returns_utc_reset_delay(
    openapi_app, monkeypatch,
):
    app, read_headers, _infer_headers = openapi_app
    path = "/openapi/v1/model-scenarios"
    fixed_time = 1_800_000_000
    monkeypatch.setattr("security_open.time.time", lambda: fixed_time)
    with app.app_context():
        row = OpenApp.query.filter_by(app_id=read_headers["X-App-Id"]).one()
        row.qps_limit = 0
        row.daily_limit = 1
        db.session.commit()
        app_pk = row.id

    first = app.test_client().get(
        path,
        headers=_signed_headers(read_headers, "GET", path, timestamp=fixed_time),
    )
    limited = app.test_client().get(
        path,
        headers=_signed_headers(read_headers, "GET", path, timestamp=fixed_time),
    )

    assert first.status_code == 200
    _assert_open_error(limited, 429, "rate_limited")
    assert 1 <= int(limited.headers["Retry-After"]) <= 86_400
    import models
    rate_model = getattr(models, "OpenApiRateBucket")
    with app.app_context():
        bucket = rate_model.query.filter_by(app_pk=app_pk, bucket_kind="day").one()
        assert bucket.count == 1
        log = OpenApiCallLog.query.filter_by(status_code=429).one()
        assert log.capability == "model-scenario:read"


def test_scenario_security_and_rate_failures_are_audited_without_sensitive_values(
    openapi_app,
):
    app, read_headers, _infer_headers = openapi_app
    path = "/openapi/v1/model-scenarios"
    request_id = "scenario-audit-001"
    signature = "f" * 64
    response = app.test_client().get(
        path,
        headers={
            **_signed_headers(read_headers, "GET", path, signature=signature),
            "X-Request-Id": request_id,
        },
    )
    assert response.status_code == 401

    with app.app_context():
        entry = OpenApiCallLog.query.filter_by(request_id=request_id).one()
        assert entry.capability == "model-scenario:read"
        assert entry.status_code == 401
        serialized = " ".join(str(value) for value in (
            entry.app_id,
            entry.request_id,
            entry.path,
            entry.capability,
            entry.error_message,
        ))
        assert read_headers["_raw"] not in serialized
        assert signature not in serialized


@pytest.mark.parametrize("failure_point", ["nonce", "rate"])
def test_scenario_security_database_failures_use_open_error(
    openapi_app, monkeypatch, failure_point,
):
    app, read_headers, _ = openapi_app
    path = "/openapi/v1/model-scenarios"
    target = "security_open._remember_nonce" if failure_point == "nonce" else "security_open._check_shared_rate_limit"
    monkeypatch.setattr(target, lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db offline")))
    response = app.test_client().get(
        path, headers=_signed_headers(read_headers, "GET", path),
    )
    payload = _assert_open_error(response, 500, "internal")
    assert "db offline" not in payload["message"]


def test_audit_database_failure_does_not_replace_open_response(openapi_app, monkeypatch):
    app, read_headers, _ = openapi_app
    path = "/openapi/v1/model-scenarios"
    monkeypatch.setattr(
        "security_open.OpenApiCallLog",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("audit database offline")),
    )
    response = app.test_client().get(
        path, headers=_signed_headers(read_headers, "GET", path, signature="0" * 64),
    )
    payload = _assert_open_error(response, 401, "signature")
    assert "audit" not in payload["message"]


def test_read_scope_lists_and_gets_public_scenarios_but_cannot_infer(openapi_app):
    app, read_headers, _infer_headers = openapi_app
    client = app.test_client()

    listing_path = "/openapi/v1/model-scenarios?phase=1"
    listing = client.get(
        listing_path,
        headers=_signed_headers(read_headers, "GET", listing_path),
    )
    assert listing.status_code == 200
    list_payload = listing.get_json()
    assert list_payload["code"] == 0
    assert len(list_payload["data"]) == 9
    assert list_payload["data"][0]["modelKey"] == "efficient-sam"
    assert all("model" not in item for item in list_payload["data"])

    detail_path = "/openapi/v1/model-scenarios/yolo26n-obb"
    detail = client.get(
        detail_path, headers=_signed_headers(read_headers, "GET", detail_path),
    )
    assert detail.status_code == 200
    detail_payload = detail.get_json()
    assert detail_payload["code"] == 0
    assert detail_payload["data"]["modelKey"] == "yolo26n-obb"
    assert detail_payload["data"]["configured"] is True
    assert "model" not in detail_payload["data"]
    assert "secret/internal" not in detail.get_data(as_text=True)
    assert "private.example" not in detail.get_data(as_text=True)

    infer_path = "/openapi/v1/model-scenarios/yolo26n-obb/infer"
    denied_data = {"file": (io.BytesIO(b"image"), "sample.png")}
    denied = client.post(
        infer_path,
        headers=_signed_headers(read_headers, "POST", infer_path, denied_data),
        data=denied_data,
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
    path = "/openapi/v1/model-scenarios/yolo26n-obb"
    response = app.test_client().get(
        path, headers=_signed_headers(read_headers, "GET", path),
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert set(data) == {
        "phase", "order", "modelKey", "name", "category", "ability",
        "workbenchType", "project", "description", "workflow", "outputs",
        "metrics", "risks", "defaults", "input", "adapter", "published",
        "apiEnabled", "apiPath", "configured", "enabled", "weightsPresent",
        "runtimeAvailable", "ready", "apiReady", "reason",
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
    path = "/openapi/v1/model-scenarios/yolo26n-obb/infer"
    request_data = {
        "file": (io.BytesIO(b"image"), "sample.png"),
        "conf": "0.4",
    }
    response = app.test_client().post(
        path,
        headers=_signed_headers(infer_headers, "POST", path, request_data),
        data=request_data,
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

    unknown_path = "/openapi/v1/model-scenarios/not-registered"
    unknown = client.get(
        unknown_path,
        headers=_signed_headers(read_headers, "GET", unknown_path),
    )
    unknown_payload = _assert_open_error(unknown, 404, "not_found")
    assert unknown_payload["message"] == "model scenario not found"

    def unavailable(*_args, **_kwargs):
        raise ScenarioInputError("model weights are missing")

    monkeypatch.setattr("routes.openapi_v1.run_scenario", unavailable, raising=False)
    infer_path = "/openapi/v1/model-scenarios/yolo26n-obb/infer"
    unavailable_data = {"file": (io.BytesIO(b"image"), "sample.png")}
    unavailable_response = client.post(
        infer_path,
        headers=_signed_headers(infer_headers, "POST", infer_path, unavailable_data),
        data=unavailable_data,
    )
    unavailable_payload = _assert_open_error(unavailable_response, 400, "validation")
    assert unavailable_payload["message"] == "model weights are missing"

    def malformed(*_args, **_kwargs):
        raise ScenarioInputError("conf must be a number between 0 and 1")

    monkeypatch.setattr("routes.openapi_v1.run_scenario", malformed, raising=False)
    malformed_data = {
        "file": (io.BytesIO(b"image"), "sample.png"), "conf": "wrong",
    }
    malformed_response = client.post(
        infer_path,
        headers=_signed_headers(infer_headers, "POST", infer_path, malformed_data),
        data=malformed_data,
    )
    malformed_payload = _assert_open_error(malformed_response, 400, "validation")
    assert malformed_payload["message"] == "conf must be a number between 0 and 1"


def test_infer_preserves_file_limit_and_sanitizes_runtime_failures(
    openapi_app, monkeypatch,
):
    app, _read_headers, infer_headers = openapi_app
    client = app.test_client()

    infer_path = "/openapi/v1/model-scenarios/yolo26n-obb/infer"
    import services.model_scenario_inference as dispatcher
    payload_error = getattr(dispatcher, "ScenarioPayloadTooLarge", None)
    assert payload_error is not None
    monkeypatch.setattr(
        "routes.openapi_v1.run_scenario",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            payload_error("image exceeds the scenario image size limit")
        ),
    )
    too_large_data = {"file": (io.BytesIO(b"x" * 1025), "sample.png")}
    too_large = client.post(
        infer_path,
        headers=_signed_headers(infer_headers, "POST", infer_path, too_large_data),
        data=too_large_data,
    )
    too_large_payload = _assert_open_error(too_large, 413, "request_too_large")
    assert too_large_payload["message"] == "image exceeds the scenario image size limit"

    def runtime_failure(*_args, **_kwargs):
        raise RuntimeError("C:/secret/models/yolo26n-obb.pt provider failure")

    monkeypatch.setattr("routes.openapi_v1.run_scenario", runtime_failure, raising=False)
    failed_data = {"file": (io.BytesIO(b"image"), "sample.png")}
    failed = client.post(
        infer_path,
        headers=_signed_headers(infer_headers, "POST", infer_path, failed_data),
        data=failed_data,
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
    response = app.test_client().get(
        path, headers=_signed_headers(read_headers, "GET", path),
    )

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
    path = "/openapi/v1/model-scenarios/yolo26n-obb"
    response = app.test_client().get(
        path, headers=_signed_headers(read_headers, "GET", path),
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
    for operation in (collection, detail, infer):
        assert operation["x-signature-required"] is True
        assert "429" in operation["responses"]
        assert "Retry-After" in operation["responses"]["429"]["headers"]
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
    assert form_schema["properties"]["precision"]["enum"] == ["fp32", "int8"]
    response_example = infer["responses"]["200"]["content"]["application/json"]["example"]
    assert response_example["code"] == 0
    assert response_example["data"]["modelKey"] == "yolo26n-obb"
    assert response_example["data"]["result"]["detections"] == []
