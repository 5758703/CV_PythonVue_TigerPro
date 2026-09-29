"""Database-backed asynchronous jobs with atomic worker claims and leases."""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from extensions import db

_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}
_CACHE_LIMIT = 256


def _remember(job_id: str, data: dict) -> None:
    with _lock:
        _cache.pop(job_id, None)
        _cache[job_id] = data
        while len(_cache) > _CACHE_LIMIT:
            _cache.pop(next(iter(_cache)))


def _row_to_dict(row) -> dict:
    return {
        "id": row.id,
        "appPk": row.app_pk,
        "appId": row.app_id,
        "capability": row.capability,
        "status": row.status,
        "workerId": row.worker_id,
        "leaseExpiresAt": row.lease_expires_at.timestamp() if row.lease_expires_at else None,
        "progress": float(row.progress or 0),
        "message": row.message or "",
        "result": row.result(),
        "error": row.error,
        "meta": row.meta(),
        "inputUri": row.input_uri,
        "webhookDelivered": row.webhook_delivered,
        "createdAt": row.create_time.timestamp() if row.create_time else time.time(),
        "updatedAt": row.update_time.timestamp() if row.update_time else time.time(),
    }


def create_job(
    capability: str,
    meta: dict | None = None,
    *,
    app_pk: int | None = None,
    app_id: str | None = None,
    input_uri: str | None = None,
) -> str:
    from models.open_job import OpenJob

    job_id = uuid.uuid4().hex
    row = OpenJob(
        id=job_id,
        app_pk=app_pk,
        app_id=app_id,
        capability=capability,
        status="queued",
        progress=0.0,
        message="",
        input_uri=input_uri,
    )
    row.set_meta(meta or {})
    db.session.add(row)
    db.session.commit()
    data = _row_to_dict(row)
    _remember(job_id, data)
    return job_id


def update_job(job_id: str, **fields) -> bool:
    from models.open_job import OpenJob

    row = (db.session.query(OpenJob).filter(OpenJob.id == job_id)
           .with_for_update().populate_existing().first())
    if row is None:
        return False
    if row.status in ("succeeded", "failed") and set(fields) != {"webhook_delivered"}:
        return False
    if "status" in fields:
        row.status = fields["status"]
        if row.status in ("succeeded", "failed"):
            row.lease_expires_at = None
    if "progress" in fields:
        row.progress = float(fields["progress"])
    if "message" in fields:
        row.message = (fields["message"] or "")[:500]
    if "error" in fields:
        row.error = fields["error"]
    if "result" in fields:
        row.set_result(fields["result"])
    if "meta" in fields:
        row.set_meta(fields["meta"])
    if "input_uri" in fields or "inputUri" in fields:
        row.input_uri = fields.get("input_uri") or fields.get("inputUri")
    if "webhook_delivered" in fields:
        row.webhook_delivered = fields["webhook_delivered"]
    db.session.commit()
    data = _row_to_dict(row)
    _remember(job_id, data)
    return True


def get_job(job_id: str) -> dict | None:
    from models.open_job import OpenJob

    row = OpenJob.query.get(job_id)
    if row is None:
        with _lock:
            _cache.pop(job_id, None)
        return None
    data = _row_to_dict(row)
    _remember(job_id, data)
    return data


def claim_next_job(capabilities: list[str] | None = None, *, lease_seconds: int = 90) -> dict | None:
    """Atomically claim one queued row across processes."""
    from models.open_job import OpenJob
    from sqlalchemy import asc

    for _ in range(16):
        q = db.session.query(OpenJob.id).filter(OpenJob.status == "queued")
        if capabilities:
            q = q.filter(OpenJob.capability.in_(capabilities))
        candidate = q.order_by(asc(OpenJob.create_time), asc(OpenJob.id)).first()
        if candidate is None:
            return None
        worker_id = uuid.uuid4().hex
        now = datetime.utcnow()
        updated = (db.session.query(OpenJob)
                   .filter(OpenJob.id == candidate.id, OpenJob.status == "queued")
                   .update({
                       OpenJob.status: "running",
                       OpenJob.progress: 0.01,
                       OpenJob.message: "running",
                       OpenJob.worker_id: worker_id,
                       OpenJob.lease_expires_at: now + timedelta(seconds=max(1, lease_seconds)),
                       OpenJob.update_time: now,
                   }, synchronize_session=False))
        if not updated:
            db.session.rollback()
            continue
        db.session.commit()
        row = db.session.get(OpenJob, candidate.id)
        data = _row_to_dict(row)
        _remember(row.id, data)
        return data
    return None


def heartbeat(job_id: str, worker_id: str, *, lease_seconds: int = 90) -> bool:
    from models.open_job import OpenJob

    now = datetime.utcnow()
    updated = (db.session.query(OpenJob)
               .filter(OpenJob.id == job_id, OpenJob.status == "running",
                       OpenJob.worker_id == worker_id)
               .update({
                   OpenJob.lease_expires_at: now + timedelta(seconds=max(1, lease_seconds)),
                   OpenJob.update_time: now,
               }, synchronize_session=False))
    db.session.commit()
    return bool(updated)


def cancel_queued_job(job_id: str, reason: str = "cancelled") -> bool:
    """Cancel only before a worker claims the task."""
    from models.open_job import OpenJob

    changed = (db.session.query(OpenJob)
               .filter(OpenJob.id == job_id, OpenJob.status == "queued")
               .update({OpenJob.status: "failed", OpenJob.error: reason,
                        OpenJob.message: reason, OpenJob.update_time: datetime.utcnow()},
                       synchronize_session=False))
    db.session.commit()
    with _lock:
        _cache.pop(job_id, None)
    return bool(changed)


def recover_stale_jobs(capabilities: list[str] | None = None) -> int:
    """Mark crashed worker jobs failed; callers may submit a new job explicitly."""
    from models.open_job import OpenJob
    from sqlalchemy import or_

    q = db.session.query(OpenJob).filter(
        OpenJob.status == "running",
        or_(OpenJob.lease_expires_at.is_(None),
            OpenJob.lease_expires_at < datetime.utcnow()),
    )
    if capabilities:
        q = q.filter(OpenJob.capability.in_(capabilities))
    count = q.update({
        OpenJob.status: "failed",
        OpenJob.message: "worker lease expired",
        OpenJob.error: "worker lease expired; submit a new job to retry",
        OpenJob.lease_expires_at: None,
        OpenJob.update_time: datetime.utcnow(),
    }, synchronize_session=False)
    db.session.commit()
    return count


@contextmanager
def lease_heartbeat(app, job: dict, *, interval_seconds: int = 15):
    """Keep a claimed job live while its worker performs long inference."""
    stopped = threading.Event()

    def _run():
        while not stopped.wait(interval_seconds):
            try:
                with app.app_context():
                    if not heartbeat(job["id"], job["workerId"]):
                        return
            except Exception:  # noqa: BLE001 - next lease expiry makes failure observable
                app.logger.exception("Could not renew job lease %s", job["id"])

    thread = threading.Thread(target=_run, name=f"job-lease-{job['id'][:8]}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=2)


def public_job(job: dict) -> dict:
    return {
        "id": job["id"],
        "capability": job.get("capability"),
        "status": job.get("status"),
        "progress": job.get("progress"),
        "message": job.get("message") or "",
        "result": job.get("result"),
        "error": job.get("error"),
        "createdAt": job.get("createdAt"),
        "updatedAt": job.get("updatedAt"),
    }


def cleanup_old_jobs(days: int = 7) -> int:
    from datetime import datetime, timedelta
    from models.open_job import OpenJob

    cutoff = datetime.utcnow() - timedelta(days=days)
    q = OpenJob.query.filter(
        OpenJob.create_time < cutoff,
        OpenJob.status.in_(["succeeded", "failed"]),
    )
    n = q.count()
    q.delete(synchronize_session=False)
    db.session.commit()
    with _lock:
        for job_id, data in list(_cache.items()):
            if data.get("status") in ("succeeded", "failed") and data.get("createdAt", 0) < cutoff.timestamp():
                _cache.pop(job_id, None)
    return n
