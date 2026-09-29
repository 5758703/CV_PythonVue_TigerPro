"""Public statistics retain their meaning when aggregation moves to SQL."""

from flask import Flask

from extensions import db
from models import AiModel
from routes.portal import portal_bp


def test_portal_summary_counts_only_enabled_models(tmp_path):
    app = Flask("portal-aggregation")
    app.config.update(TESTING=True,
                      SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'portal.db'}",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    app.register_blueprint(portal_bp)
    with app.app_context():
        db.create_all()
        db.session.add_all([
            AiModel(model_name="detect-a", task="object-detection", category="CV",
                    file_path="models/a.pt", status="0"),
            AiModel(model_name="detect-b", task="object-detection", category="CV", status="0"),
            AiModel(model_name="ocr", task="optical-character-recognition",
                    category="Text", status="0"),
            AiModel(model_name="disabled", task="pose-estimation", category="CV", status="1"),
        ])
        db.session.commit()
        data = app.test_client().get("/api/portal/summary").get_json()["data"]
        assert data["modelTotal"] == 3
        assert data["readyCount"] == 1
        assert data["taskKinds"] == 2
        assert data["categoryKinds"] == 2
        assert {item["name"]: item["value"] for item in data["taskDistribution"]} == {
            "目标检测": 2, "文字识别": 1,
        }
        assert {item["name"]: item["value"] for item in data["categoryRanking"]} == {
            "CV": 2, "Text": 1,
        }
