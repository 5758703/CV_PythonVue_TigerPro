from flask import Flask, jsonify
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.exceptions import BadRequest, Forbidden

from config import Config
from extensions import db, cors, jwt
from routes import all_blueprints


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    cors.init_app(app, resources={
        r"/api/*": {"origins": "*"},
        r"/openapi/*": {"origins": "*"},
    })
    jwt.init_app(app)

    @app.errorhandler(BadRequest)
    @app.errorhandler(Forbidden)
    def _permission_input_error(error):
        db.session.rollback()
        return jsonify(code=error.code, message=error.description), error.code

    for bp in all_blueprints:
        app.register_blueprint(bp)

    @app.get("/api/health")
    def health():
        return jsonify(code=0, message="ok")

    # JWT 异常 -> 统一 JSON
    @jwt.unauthorized_loader
    def _missing_token(reason):
        return jsonify(code=401, message="缺少或无效的令牌"), 401

    @jwt.invalid_token_loader
    def _invalid_token(reason):
        
        return jsonify(code=401, message="令牌无效"), 401

    @jwt.expired_token_loader
    def _expired_token(header, payload):
        return jsonify(code=401, message="登录已过期，请重新登录"), 401

    @app.errorhandler(RequestEntityTooLarge)
    def _payload_too_large(_e):
        limit_mb = app.config.get("MAX_CONTENT_LENGTH", 0) // (1024 * 1024)
        return jsonify(
            code=413,
            message=f"上传内容过大（上限约 {limit_mb}MB）。大体积视频请改用「服务器路径」模式，"
            f"或在 .env 中提高 MAX_CONTENT_LENGTH_MB",
        ), 413

    with app.app_context():
        # 确保 ORM 模型（含人脸/行人底库）在 create_all 前完成注册
        import models  # noqa: F401
        db.create_all()
        _migrate(db)
        from seed import init_seed
        from services.organization_types import migrate_type_catalog
        migrate_type_catalog()
        init_seed()
        from services.superadmin import ensure_single_superadmin
        ensure_single_superadmin()
        from services.organization_migration import migrate_legacy_organization_auth
        migrate_legacy_organization_auth()

    return app


def _migrate(db):
    """轻量迁移：为已存在的表补充新增列（create_all 不改已有表）。"""
    from schema_migrations import migrate_schema
    migrate_schema(db)


app = create_app()


def _spawn_admin_job_worker():
    """随 app.py 拉起管理任务 worker（视频检测/转换/训练等依赖队列）。

    仅 ``python app.py`` 入口调用；pytest / create_app 不会启动。
    设置环境变量 ``TIGERPRO_SKIP_ADMIN_WORKER=1`` 可跳过（例如已由外部脚本托管）。
    """
    import atexit
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path

    if os.environ.get("TIGERPRO_SKIP_ADMIN_WORKER", "").strip().lower() in ("1", "true", "yes"):
        print("[admin-worker] skipped (TIGERPRO_SKIP_ADMIN_WORKER)", flush=True)
        return None

    script = Path(__file__).resolve().parent / "scripts" / "admin_job_worker.py"
    if not script.is_file():
        print(f"[warn] admin job worker missing: {script}", flush=True)
        return None

    kwargs = {
        "args": [sys.executable, str(script)],
        "cwd": str(script.parent.parent),
    }
    if sys.platform == "win32":
        # 避免额外弹出控制台窗口
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.Popen(**kwargs)
    time.sleep(0.8)
    if proc.poll() is not None:
        print(
            f"[warn] admin job worker exited immediately (code={proc.returncode}); "
            "video/convert/training jobs will stay queued",
            flush=True,
        )
        return None

    def _stop():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()

    atexit.register(_stop)
    print(f"[admin-worker] spawned pid={proc.pid}", flush=True)
    return proc


if __name__ == "__main__":
    _spawn_admin_job_worker()
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)
