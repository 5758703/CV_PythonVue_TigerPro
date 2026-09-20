from flask import Flask, jsonify
from werkzeug.exceptions import RequestEntityTooLarge

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

    for bp in all_blueprints:
        app.register_blueprint(bp)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", code=0, message="ok")

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
        init_seed()

    return app


def _migrate(db):
    """轻量迁移：为已存在的表补充新增列（create_all 不改已有表）。"""
    from schema_migrations import migrate_schema
    migrate_schema(db)


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True, threaded=True)
