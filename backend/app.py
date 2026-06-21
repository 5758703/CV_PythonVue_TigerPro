from flask import Flask, jsonify

from config import Config
from extensions import db, cors, jwt
from routes import all_blueprints


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})
    jwt.init_app(app)

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

    with app.app_context():
        db.create_all()
        _migrate(db)
        from seed import init_seed
        init_seed()

    return app


def _migrate(db):
    """轻量迁移：为已存在的表补充新增列（create_all 不改已有表）。"""
    from sqlalchemy import inspect, text

    insp = inspect(db.engine)
    if "ai_model" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("ai_model")}
    adds = []
    if "task" not in cols:
        adds.append("ADD COLUMN task VARCHAR(64) DEFAULT 'object-detection'")
    if "library" not in cols:
        adds.append("ADD COLUMN library VARCHAR(32) DEFAULT 'ultralytics'")
    if adds:
        with db.engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE ai_model {', '.join(adds)}"))


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
