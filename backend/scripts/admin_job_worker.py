"""Process persistent management tasks: run alongside the Flask server.

Usage: cd backend && python scripts/admin_job_worker.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def process_job(app, job: dict) -> None:
    from extensions import db
    from models.training import TrainingJob
    from routes import ai_model as model_routes
    from services import admin_jobs
    from services.training import run_training_worker, run_validate_worker

    job_id = job["id"]
    cap = job["capability"]
    args = (job.get("meta") or {}).get("args") or []
    handlers = {
        "admin:model-convert": model_routes._convert_worker,
        "admin:model-segment-video": model_routes._segment_worker,
        "admin:model-detect-video": model_routes._video_worker,
        "admin:model-pose-video": model_routes._pose_worker,
        "admin:model-track-video": model_routes._track_worker,
        "admin:model-talking-head": model_routes._talker_worker,
    }
    try:
        if cap in handlers:
            handlers[cap](job_id, *args)
        elif cap == "admin:training-run":
            training_id = int(args[0])
            run_training_worker(app, training_id)
            db.session.expire_all()
            row = db.session.get(TrainingJob, training_id)
            if row and row.status == "done":
                admin_jobs.complete(job_id, trainingJobId=training_id)
            else:
                admin_jobs.fail(job_id, row.error_message if row else "训练任务不存在")
        elif cap == "admin:training-validate":
            metrics = run_validate_worker(app, int(args[0]))
            if metrics is None:
                admin_jobs.fail(job_id, "验证失败")
            else:
                admin_jobs.complete(job_id, result=metrics)
        else:
            raise ValueError(f"Unsupported management task: {cap}")
        state = admin_jobs.state(job_id)
        if state and state["status"] == "running":
            admin_jobs.fail(job_id, "worker returned without a terminal result")
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Management task %s failed", job_id)
        admin_jobs.fail(job_id, str(exc))


def main() -> None:
    parser = argparse.ArgumentParser(description="TigerPro management job worker")
    parser.add_argument("--interval", type=float, default=1.5)
    parser.add_argument("--cleanup-days", type=int, default=7)
    args = parser.parse_args()

    from app import app
    from services import admin_jobs, job_store

    print("[admin-worker] started", flush=True)
    loops = 0
    with app.app_context():
        while True:
            job_store.recover_stale_jobs(admin_jobs.CAPABILITIES)
            job = job_store.claim_next_job(admin_jobs.CAPABILITIES)
            if job:
                with job_store.lease_heartbeat(app, job):
                    process_job(app, job)
            else:
                time.sleep(args.interval)
            loops += 1
            if args.cleanup_days > 0 and loops % 200 == 0:
                job_store.cleanup_old_jobs(args.cleanup_days)


if __name__ == "__main__":
    main()
