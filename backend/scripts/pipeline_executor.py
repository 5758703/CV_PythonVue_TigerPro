"""边缘 Pipeline Executor：独立进程运行同一 Runtime（Mode B 骨架）。

用法:
  cd backend
  python scripts/pipeline_executor.py --dag examples/pipeline_rtsp_yolo_overlay.json
  python scripts/pipeline_executor.py --pipeline-id 1
  python scripts/pipeline_executor.py --dag ... --run-key plrun_demo

Ctrl+C 停止并写回 AiPipelineRun metrics。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="TigerPro Edge Pipeline Executor")
    parser.add_argument("--dag", help="本地 DAG JSON 路径")
    parser.add_argument("--pipeline-id", type=int, help="从 DB 加载流水线当前版本")
    parser.add_argument("--run-key", default="", help="可选固定 runKey")
    parser.add_argument("--phase", type=int, default=None)
    parser.add_argument("--name", default="executor-run", help="无 pipeline-id 时写入 DB 的名称")
    args = parser.parse_args()

    if not args.dag and not args.pipeline_id:
        parser.error("需要 --dag 或 --pipeline-id")

    from app import create_app
    from extensions import db
    from models.pipeline import AiPipeline, AiPipelineRun, AiPipelineVersion
    from services import pipeline_runtime
    from services.pipeline_schema import dag_required_phase, parse_dag_json, validate_dag

    app = create_app()
    dag = None
    pipeline_id = 0
    version_id = None

    with app.app_context():
        if args.pipeline_id:
            pl = AiPipeline.query.get(int(args.pipeline_id))
            if not pl:
                print("FAIL: pipeline not found", args.pipeline_id)
                return 1
            ver = AiPipelineVersion.query.filter_by(
                pipeline_id=pl.id, version=pl.current_version
            ).first()
            if not ver:
                print("FAIL: no version")
                return 1
            dag = ver.dag()
            pipeline_id = pl.id
            version_id = ver.id
        else:
            with open(args.dag, "r", encoding="utf-8") as f:
                dag = parse_dag_json(json.load(f))
            pl = AiPipeline(
                name=args.name,
                description="executor CLI",
                status="0",
                current_version=1,
            )
            db.session.add(pl)
            db.session.flush()
            phase = args.phase if args.phase is not None else max(1, dag_required_phase(dag))
            validate_dag(dag, phase=phase)
            ver = AiPipelineVersion(
                pipeline_id=pl.id,
                version=1,
                dag_json=json.dumps(dag, ensure_ascii=False),
                remark="executor",
            )
            db.session.add(ver)
            db.session.commit()
            pipeline_id = pl.id
            version_id = ver.id

        phase = args.phase if args.phase is not None else max(1, dag_required_phase(dag))
        norm = validate_dag(dag, phase=phase)
        sess = pipeline_runtime.start_run(
            app=app,
            pipeline_id=pipeline_id,
            version_id=version_id,
            dag=dag,
            run_key=(args.run_key or "").strip() or None,
            phase=phase,
            executor_mode="cli",
        )
        row = AiPipelineRun(
            run_key=sess.run_key,
            pipeline_id=pipeline_id,
            version_id=version_id,
            camera_id=norm["cameraId"],
            state="running",
            metrics_json="{}",
        )
        from datetime import datetime

        row.started_at = datetime.utcnow()
        db.session.add(row)
        db.session.commit()
        print("STARTED", sess.run_key, "mode", norm.get("mode"), "camera", norm["cameraId"])

    stop = {"flag": False}

    def _sig(*_):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        while not stop["flag"]:
            live = pipeline_runtime.get_session(sess.run_key)
            if not live or not live.running:
                print("worker exited", live.error if live else "")
                break
            time.sleep(0.5)
    finally:
        pipeline_runtime.stop_run(sess.run_key)
        with app.app_context():
            pipeline_runtime.persist_run_stopped(app, sess.run_key, state="stopped")
        print("STOPPED", sess.run_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
