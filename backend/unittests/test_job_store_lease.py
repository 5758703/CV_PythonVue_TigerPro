"""Durable worker-claim behavior, including crashed worker recovery."""

from datetime import datetime, timedelta
import sqlite3

import pytest
from flask import Flask
from sqlalchemy import inspect

from extensions import db
from models.open_app import OpenApp  # noqa: F401 - OpenJob foreign key
from models.open_job import OpenJob
from services import job_store


@pytest.fixture(scope="module")
def job_app(tmp_path_factory):
    path = tmp_path_factory.mktemp("job-store") / "jobs.db"
    app = Flask("job-store-test")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_claim_records_lease_and_excludes_other_workers(job_app):
    with job_app.app_context():
        job_id = job_store.create_job("vision:detect")
        claimed = job_store.claim_next_job(["vision:detect"])
        assert claimed["id"] == job_id
        assert claimed["status"] == "running"
        assert claimed["workerId"]
        assert claimed["leaseExpiresAt"] > datetime.utcnow().timestamp()
        assert job_store.claim_next_job(["vision:detect"]) is None


def test_expired_claim_becomes_observable_failure_and_is_not_replayed(job_app):
    with job_app.app_context():
        job_id = job_store.create_job("vision:detect")
        job_store.claim_next_job(["vision:detect"])
        row = db.session.get(OpenJob, job_id)
        row.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        assert job_store.recover_stale_jobs(["vision:detect"]) == 1
        recovered = job_store.get_job(job_id)
        assert recovered["status"] == "failed"
        assert "worker" in recovered["error"].lower()
        assert job_store.claim_next_job(["vision:detect"]) is None


def test_heartbeat_extends_active_claim(job_app):
    with job_app.app_context():
        job_id = job_store.create_job("vision:detect")
        claimed = job_store.claim_next_job(["vision:detect"])
        old_expiry = claimed["leaseExpiresAt"]
        assert job_store.heartbeat(job_id, claimed["workerId"], lease_seconds=300)
        assert job_store.get_job(job_id)["leaseExpiresAt"] > old_expiry


def test_cleanup_removes_terminal_job_from_process_cache(job_app):
    with job_app.app_context():
        job_id = job_store.create_job("vision:detect")
        job_store.update_job(job_id, status="succeeded")
        row = db.session.get(OpenJob, job_id)
        row.create_time = datetime.utcnow() - timedelta(days=10)
        db.session.commit()
        assert job_store.get_job(job_id)
        assert job_store.cleanup_old_jobs(7) >= 1
        assert job_store.get_job(job_id) is None


def test_late_worker_cannot_overwrite_expired_failure(job_app):
    with job_app.app_context():
        job_id = job_store.create_job("vision:detect")
        job_store.claim_next_job(["vision:detect"])
        row = db.session.get(OpenJob, job_id)
        row.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        assert job_store.recover_stale_jobs(["vision:detect"]) == 1
        assert not job_store.update_job(job_id, status="succeeded", result={"late": True})
        assert job_store.get_job(job_id)["status"] == "failed"


def test_legacy_running_job_without_lease_is_recovered(job_app):
    with job_app.app_context():
        job_id = job_store.create_job("vision:detect")
        job_store.claim_next_job(["vision:detect"])
        row = db.session.get(OpenJob, job_id)
        row.lease_expires_at = None
        db.session.commit()
        assert job_store.recover_stale_jobs(["vision:detect"]) == 1
        assert job_store.get_job(job_id)["status"] == "failed"


def test_existing_database_receives_queue_and_training_columns(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE open_job (id VARCHAR(64) PRIMARY KEY, status VARCHAR(32))")
        connection.execute("CREATE TABLE training_job (id INTEGER PRIMARY KEY, status VARCHAR(16))")
    app = Flask("legacy-queue-migration")
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{path}",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        from schema_migrations import migrate_schema
        migrate_schema(db)
        migrate_schema(db)
        inspector = inspect(db.engine)
        assert {"worker_id", "lease_expires_at"} <= {
            col["name"] for col in inspector.get_columns("open_job")
        }
        assert {"worker_job_id", "validation_job_id"} <= {
            col["name"] for col in inspector.get_columns("training_job")
        }
