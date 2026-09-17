from __future__ import annotations

import io
import base64

import pytest
from flask import Flask
from flask_jwt_extended import create_access_token

from extensions import db, jwt
from models import AiModel, Role, User
from routes import all_blueprints


@pytest.fixture
def squat_app(tmp_path):
    app = Flask("squat-api")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'squat.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="squat-test-secret",
        UPLOAD_FOLDER=str(tmp_path),
        MODEL_FOLDER=str(tmp_path / "models"),
        VIDEO_FOLDER=str(tmp_path / "videos"),
        OUTPUT_FOLDER=str(tmp_path / "outputs"),
        VIDEO_ALLOWED_EXT={".mp4", ".avi"},
        SQUAT_MAX_VIDEO_BYTES=1024,
    )
    db.init_app(app)
    jwt.init_app(app)
    for blueprint in all_blueprints:
        app.register_blueprint(blueprint)
    with app.app_context():
        db.create_all()
        role = Role(role_name="Admin", role_key="admin")
        user = User(username="squat-admin", nickname="Squat Admin", password_hash="unused")
        user.roles = [role]
        model_dir = tmp_path / "models"
        model_dir.mkdir()
        weight = model_dir / "pose.pt"
        weight.write_bytes(b"pose")
        model = AiModel(
            model_name="pose",
            model_key="yolo11n-pose",
            task="pose-estimation",
            library="ultralytics",
            file_path="models/pose.pt",
            status="0",
        )
        db.session.add_all([role, user, model])
        db.session.commit()
        token = create_access_token(identity=str(user.id))
        model_id = model.id
    yield app, {"Authorization": f"Bearer {token}"}, model_id, tmp_path
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _post_video(client, headers, model_id, **fields):
    data = {
        "file": (io.BytesIO(b"video"), "squats.mp4"),
        "modelId": str(model_id),
        **fields,
    }
    return client.post("/api/ai/squat/video", data=data, headers=headers)


def test_video_requires_authentication(squat_app):
    app, _headers, model_id, _tmp_path = squat_app
    response = _post_video(app.test_client(), {}, model_id)
    assert response.status_code == 401


def test_video_rejects_inverted_angle_thresholds(squat_app):
    app, headers, model_id, _tmp_path = squat_app
    response = _post_video(
        app.test_client(), headers, model_id,
        standingAngle="100", bottomAngle="160",
    )
    assert response.status_code == 400
    assert "standing" in response.json["message"]


def test_video_rejects_non_pose_model(squat_app):
    app, headers, _model_id, tmp_path = squat_app
    with app.app_context():
        model = AiModel(
            model_name="detect", model_key="yolo26n", task="object-detection",
            library="ultralytics", file_path="models/pose.pt", status="0",
        )
        db.session.add(model)
        db.session.commit()
        model_id = model.id
    response = _post_video(app.test_client(), headers, model_id)
    assert response.status_code == 400


def test_video_job_completes_and_output_name_is_restricted(squat_app, monkeypatch):
    app, headers, model_id, tmp_path = squat_app

    def fake_process(_estimator, _source, destination, _config, progress_cb=None):
        if progress_cb:
            progress_cb(2, 2)
        destination.write_bytes(b"annotated")
        return {"frames": 2, "count": 1}

    monkeypatch.setattr("services.squat_video.process_squat_video", fake_process)
    monkeypatch.setattr("routes.squat._start_worker", lambda target: target())
    client = app.test_client()
    response = _post_video(client, headers, model_id)
    assert response.status_code == 200
    job_id = response.json["data"]["jobId"]

    progress = client.get(f"/api/ai/squat/video-progress/{job_id}", headers=headers)
    assert progress.json["data"]["status"] == "done"
    assert progress.json["data"]["stats"]["count"] == 1
    output = progress.json["data"]["stats"]["output"]
    assert client.get(f"/api/ai/squat/output/{output}", headers=headers).data == b"annotated"
    assert client.get("/api/ai/squat/output/../secret.mp4", headers=headers).status_code in (400, 404)
    assert client.get("/api/ai/squat/output/not-squat.mp4", headers=headers).status_code == 400


def test_local_session_lifecycle(squat_app, monkeypatch):
    import cv2
    import numpy as np

    app, headers, model_id, _tmp_path = squat_app

    class EmptyEstimator:
        def __init__(self, *_args, **_kwargs):
            pass

        def infer(self, _frame):
            return []

    monkeypatch.setattr("routes.squat.PoseFrameEstimator", EmptyEstimator)
    client = app.test_client()
    created = client.post(
        "/api/ai/squat/sessions",
        json={"sourceType": "local", "modelId": model_id},
        headers=headers,
    )
    assert created.status_code == 200
    session_id = created.json["data"]["sessionId"]

    ok, encoded = cv2.imencode(".jpg", np.zeros((32, 32, 3), dtype=np.uint8))
    assert ok
    frame = client.post(
        f"/api/ai/squat/sessions/{session_id}/frames",
        data={
            "file": (io.BytesIO(encoded.tobytes()), "frame.jpg"),
            "sequence": "1",
            "capturedAt": "0.0",
        },
        headers=headers,
    )
    assert frame.status_code == 200
    assert base64.b64decode(frame.json["data"]["annotatedImageBase64"])
    assert client.get(f"/api/ai/squat/sessions/{session_id}", headers=headers).status_code == 200
    stopped = client.delete(f"/api/ai/squat/sessions/{session_id}", headers=headers)
    assert stopped.json["data"]["status"] == "stopped"
