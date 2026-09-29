"""Persistent management task queue and legacy progress response adapter."""
from __future__ import annotations

import threading
import time

from services import job_store


CAPABILITIES = [
    "admin:model-convert",
    "admin:model-segment-video",
    "admin:model-detect-video",
    "admin:model-pose-video",
    "admin:model-track-video",
    "admin:model-talking-head",
    "admin:training-run",
    "admin:training-validate",
]

_write_times: dict[str, float] = {}
_write_lock = threading.Lock()


def enqueue(capability: str, *, args: list, model_id: int | None = None,
            display: dict | None = None) -> str:
    if capability not in CAPABILITIES:
        raise ValueError(f"Unsupported management task: {capability}")
    return job_store.create_job(
        capability, meta={"args": args, "modelId": model_id, "display": display or {}},
    )


def state(job_id: str, *, model_id: int | None = None) -> dict | None:
    job = job_store.get_job(job_id)
    if not job or job["capability"] not in CAPABILITIES:
        return None
    meta = job.get("meta") or {}
    if model_id is not None and meta.get("modelId") != model_id:
        return None
    status = {"queued": "queued", "running": "running",
              "succeeded": "done", "failed": "error"}.get(job["status"], "error")
    result = job.get("result") or {}
    return {"processed": 0, "total": 0,
            **(meta.get("display") or {}), **result, "status": status,
            **({"error": job["error"]} if job.get("error") else {})}


def progress(job_id: str, processed: int, total: int) -> None:
    now = time.monotonic()
    with _write_lock:
        if len(_write_times) > 512:
            for old_job_id, written_at in list(_write_times.items()):
                if now - written_at > 300:
                    _write_times.pop(old_job_id, None)
        if processed < total and now - _write_times.get(job_id, 0) < 0.5:
            return
        _write_times[job_id] = now
    current = state(job_id) or {}
    current.pop("status", None)
    job_store.update_job(
        job_id, result={**current, "processed": processed, "total": total},
        progress=min(0.99, processed / total) if total else 0.01,
    )


def complete(job_id: str, **result) -> None:
    current = state(job_id) or {}
    current.pop("status", None)
    job_store.update_job(
        job_id, status="succeeded", progress=1.0, message="done",
        result={**current, **result},
    )
    with _write_lock:
        _write_times.pop(job_id, None)


def fail(job_id: str, error: str) -> None:
    job_store.update_job(job_id, status="failed", message="failed", error=error)
    with _write_lock:
        _write_times.pop(job_id, None)
