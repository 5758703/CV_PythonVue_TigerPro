"""统一异步任务状态（P1：MySQL 持久化，进程内缓存加速）。"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from extensions import db

_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}


def _row_to_dict(row) -> dict:
    return {
        "id": row.id,
        "appPk": row.app_pk,
        "appId": row.app_id,
        "capability": row.capability,
        "status": row.status,
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
    with _lock:
        _cache[job_id] = data
    return job_id


def update_job(job_id: str, **fields) -> bool:
    from models.open_job import OpenJob

    row = OpenJob.query.get(job_id)
    if row is None:
        return False
    if "status" in fields:
        row.status = fields["status"]
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
    with _lock:
        _cache[job_id] = data
    return True


def get_job(job_id: str) -> dict | None:
    from models.open_job import OpenJob

    with _lock:
        cached = _cache.get(job_id)
        if cached and cached.get("status") in ("succeeded", "failed"):
            return dict(cached)

    row = OpenJob.query.get(job_id)
    if row is None:
        return None
    data = _row_to_dict(row)
    with _lock:
        _cache[job_id] = data
    return data


def claim_next_job(capabilities: list[str] | None = None) -> dict | None:
    """Worker 抢占一条 queued 任务。"""
    from models.open_job import OpenJob
    from sqlalchemy import asc

    q = OpenJob.query.filter_by(status="queued")
    if capabilities:
        q = q.filter(OpenJob.capability.in_(capabilities))
    row = q.order_by(asc(OpenJob.create_time)).first()
    if row is None:
        return None
    row.status = "running"
    row.progress = max(float(row.progress or 0), 0.01)
    row.message = "running"
    db.session.commit()
    data = _row_to_dict(row)
    with _lock:
        _cache[row.id] = data
    return data


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
    return n
