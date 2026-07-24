"""开放 Job Worker：轮询 open_job 队列并执行能力任务。

用法:
  cd backend
  python scripts/open_job_worker.py
  # 或: .\\.venv\\Scripts\\python.exe scripts/open_job_worker.py
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
    from services import job_store
    from services.object_store import get_object_store
    from services import openapi_handlers as handlers
    from services.webhook import deliver_webhook
    from models.open_app import OpenApp
    from services import metrics_registry as metrics

    job_id = job["id"]
    cap = job.get("capability") or ""
    meta = job.get("meta") or {}
    try:
        if cap == "vision:detect":
            uri = job.get("inputUri")
            if not uri:
                raise ValueError("缺少 inputUri")
            image_bytes = get_object_store().get_bytes(uri)
            result = handlers.run_vision_detect(
                model_id=int(meta.get("modelId") or 0),
                image_bytes=image_bytes,
                conf=float(meta.get("conf") or 0.25),
                draw=bool(meta.get("draw", True)),
            )
            # 控制结果体积：去掉超大 base64 可选
            if isinstance(result, dict) and meta.get("dropImage") and "imageBase64" in result:
                result = {**result, "imageBase64": None}
            job_store.update_job(
                job_id, status="succeeded", progress=1.0, message="done", result=result
            )
            event = "job.succeeded"
        else:
            raise ValueError(f"worker 暂不支持 capability={cap}")
    except Exception as exc:  # noqa: BLE001
        job_store.update_job(
            job_id, status="failed", progress=1.0, message="failed", error=str(exc)
        )
        event = "job.failed"
        metrics.incr("tigerpro_open_jobs_failed", capability=cap)
    else:
        metrics.incr("tigerpro_open_jobs_succeeded", capability=cap)

    # Webhook
    app_pk = job.get("appPk")
    if app_pk:
        open_app = OpenApp.query.get(app_pk)
        if open_app:
            fresh = job_store.get_job(job_id) or {}
            ok = deliver_webhook(open_app, event, job_store.public_job(fresh))
            if ok:
                job_store.update_job(job_id, webhook_delivered="1")


def main():
    parser = argparse.ArgumentParser(description="TigerPro Open Job Worker")
    parser.add_argument("--interval", type=float, default=1.5, help="空闲轮询秒数")
    parser.add_argument("--cleanup-days", type=int, default=7, help="清理终态任务天数，0=不清理")
    args = parser.parse_args()

    from app import create_app
    from services import job_store

    flask_app = create_app()
    print("[open-worker] started", flush=True)
    loops = 0
    with flask_app.app_context():
        while True:
            job = job_store.claim_next_job(["vision:detect"])
            if job:
                print(f"[open-worker] claim {job['id']} {job.get('capability')}", flush=True)
                process_job(flask_app, job)
            else:
                time.sleep(args.interval)
            loops += 1
            if args.cleanup_days > 0 and loops % 200 == 0:
                n = job_store.cleanup_old_jobs(args.cleanup_days)
                if n:
                    print(f"[open-worker] cleaned {n} old jobs", flush=True)


if __name__ == "__main__":
    main()
