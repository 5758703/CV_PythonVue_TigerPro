"""独立 Open API Gateway 进程（仅挂载 /openapi/* + 健康检查，不含控制台 RBAC）。

用法:
  cd backend
  python gateway_app.py
  # 生产: waitress-serve --listen=0.0.0.0:5002 gateway_app:app
"""
from flask import Flask, jsonify

from config import Config
from extensions import db, cors
from routes.openapi_v1 import openapi_v1_bp


def create_gateway_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    cors.init_app(app, resources={r"/openapi/*": {"origins": "*"}})
    app.register_blueprint(openapi_v1_bp)

    @app.get("/api/health")
    def health():
        return jsonify(code=0, message="ok", data={"mode": "gateway"})

    with app.app_context():
        import models  # noqa: F401
        db.create_all()

    return app


app = create_gateway_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False, threaded=True)
