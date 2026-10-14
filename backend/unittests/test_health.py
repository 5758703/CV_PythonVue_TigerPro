"""GET /api/health 健康检查接口单测（不加载重模型 / 不依赖 MySQL）。

import app 会连带导入 routes（cv2/numpy/inference 等重依赖），这里在导入前
用空壳模块占位，并把数据库指向 sqlite 内存库，避免拉起 MySQL / 推理栈。
"""
import sys
import types

for _heavy in ("cv2", "numpy", "inference", "ultralytics", "torch", "pymysql"):
    if _heavy not in sys.modules:
        sys.modules[_heavy] = types.ModuleType(_heavy)

import config

config.Config.SQLALCHEMY_DATABASE_URI = "sqlite://"

from app import app as app  # noqa: E402,F401  模块级 create_app() 已在此执行

app.config["TESTING"] = True
client = app.test_client()


def test_health_returns_200_and_status_ok():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload is not None
    assert payload["status"] == "ok"


def test_health_keeps_legacy_fields():
    resp = client.get("/api/health")
    payload = resp.get_json()
    assert payload["code"] == 0
    assert payload["message"] == "ok"


def test_health_content_type_json():
    resp = client.get("/api/health")
    assert resp.content_type.startswith("application/json")
