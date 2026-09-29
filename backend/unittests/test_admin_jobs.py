"""Admin task status survives process-local cache loss."""

import pytest
from flask import Flask
from flask_jwt_extended import create_access_token

from extensions import db, jwt
from models import Role, User
from models.open_app import OpenApp  # noqa: F401
from models.open_job import OpenJob  # noqa: F401
from models.training import TrainingDataset, TrainingJob
from routes.training import training_bp
from services import admin_jobs, job_store


@pytest.fixture(scope="module")
def admin_job_app(tmp_path_factory):
    path = tmp_path_factory.mktemp("admin-jobs") / "jobs.db"
    app = Flask("admin-jobs-test")
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=f"sqlite:///{path}",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      JWT_SECRET_KEY="test-only-secret", UPLOAD_FOLDER=str(path.parent / "uploads"))
    db.init_app(app)
    jwt.init_app(app)
    app.register_blueprint(training_bp)
    with app.app_context():
        db.create_all()
        admin = User(username="admin-queue", roles=[Role(role_name="Admin", role_key="admin")])
        admin.set_password("test-password")
        db.session.add(admin)
        db.session.commit()
        token = create_access_token(identity=str(admin.id))
    yield app, token
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_enqueued_task_and_progress_survive_cache_loss(admin_job_app):
    app, _ = admin_job_app
    with app.app_context():
        job_id = admin_jobs.enqueue("admin:model-convert", args=["source.pt", "onnx"], model_id=7)
        assert admin_jobs.state(job_id, model_id=7)["status"] == "queued"
        job_store._cache.clear()
        claimed = job_store.claim_next_job(["admin:model-convert"])
        assert claimed["id"] == job_id
        assert claimed["meta"]["args"] == ["source.pt", "onnx"]
        admin_jobs.progress(job_id, 3, 10)
        job_store._cache.clear()
        assert admin_jobs.state(job_id, model_id=7)["processed"] == 3
        admin_jobs.complete(job_id, output="model.onnx")
        job_store._cache.clear()
        assert admin_jobs.state(job_id, model_id=7) == {
            "status": "done", "processed": 3, "total": 10, "output": "model.onnx",
        }


def test_failed_task_is_visible_after_restart(admin_job_app):
    app, _ = admin_job_app
    with app.app_context():
        job_id = admin_jobs.enqueue("admin:model-convert", args=[], model_id=8)
        job_store.claim_next_job(["admin:model-convert"])
        admin_jobs.fail(job_id, "conversion failed")
        job_store._cache.clear()
        state = admin_jobs.state(job_id, model_id=8)
        assert state["status"] == "error"
        assert state["error"] == "conversion failed"
        assert admin_jobs.state(job_id, model_id=9) is None


def test_worker_processes_queued_conversion_and_persists_result(admin_job_app, monkeypatch):
    from scripts.admin_job_worker import process_job
    from services import model_convert

    monkeypatch.setattr(model_convert, "convert_file", lambda *_args, **_kwargs: {
        "outputName": "converted.onnx", "output": "/models/converted.onnx",
        "outputSize": 42, "isDir": False,
    })
    app, _ = admin_job_app
    with app.app_context():
        job_id = admin_jobs.enqueue(
            "admin:model-convert", args=["source.pt", "onnx", "/models", {}], model_id=9,
        )
        claimed = job_store.claim_next_job(["admin:model-convert"])
        process_job(app, claimed)
        job_store._cache.clear()
        result = admin_jobs.state(job_id, model_id=9)
        assert result["status"] == "done"
        assert result["output"] == "converted.onnx"


def test_training_start_persists_queue_and_rejects_duplicate(admin_job_app):
    app, token = admin_job_app
    with app.app_context():
        dataset = TrainingDataset(name="ready", status="ready")
        job = TrainingJob(job_name="queued training", dataset=dataset, status="pending")
        db.session.add(job)
        db.session.commit()
        job_id = job.id
    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"/api/ai/training/jobs/{job_id}/start"
    assert client.post(url, headers=headers).status_code == 200
    assert client.post(url, headers=headers).status_code == 400
    with app.app_context():
        row = db.session.get(TrainingJob, job_id)
        assert admin_jobs.state(row.worker_job_id)["status"] == "queued"


def test_cancelling_queued_training_removes_runnable_job(admin_job_app):
    app, token = admin_job_app
    with app.app_context():
        dataset = TrainingDataset(name="ready-2", status="ready")
        job = TrainingJob(job_name="cancel queued", dataset=dataset, status="pending")
        db.session.add(job)
        db.session.commit()
        job_id = job.id
    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(f"/api/ai/training/jobs/{job_id}/start", headers=headers).status_code == 200
    assert client.post(f"/api/ai/training/jobs/{job_id}/cancel", headers=headers).status_code == 200
    with app.app_context():
        row = db.session.get(TrainingJob, job_id)
        assert admin_jobs.state(row.worker_job_id)["status"] == "error"
        assert db.session.get(OpenJob, row.worker_job_id).status == "failed"


def test_training_validation_progress_survives_worker_completion(admin_job_app, monkeypatch):
    from scripts.admin_job_worker import process_job
    from services import training

    app, token = admin_job_app
    with app.app_context():
        dataset = TrainingDataset(name="validation-ready", status="ready")
        job = TrainingJob(job_name="validation", dataset=dataset, status="done",
                          output_weight_path="models/best.pt")
        db.session.add(job)
        db.session.commit()
        job_id = job.id
    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"/api/ai/training/jobs/{job_id}/validate"
    assert client.post(url, headers=headers).status_code == 200
    assert client.post(url, headers=headers).status_code == 400
    progress_url = f"/api/ai/training/jobs/{job_id}/validate-progress"
    assert client.get(progress_url, headers=headers).get_json()["data"]["status"] == "queued"
    monkeypatch.setattr(training, "run_validate_worker", lambda *_args: {"mAP50": 0.9})
    with app.app_context():
        claimed = job_store.claim_next_job(["admin:training-validate"])
        process_job(app, claimed)
        db.session.remove()
    state = client.get(progress_url, headers=headers).get_json()["data"]
    assert state["status"] == "done"
    assert state["result"] == {"mAP50": 0.9}
