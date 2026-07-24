"""开放平台异步任务（跨进程共享，落库）。"""
from datetime import datetime
import json

from extensions import db


class OpenJob(db.Model):
    __tablename__ = "open_job"

    id = db.Column(db.String(64), primary_key=True)  # uuid hex
    app_pk = db.Column(db.Integer, db.ForeignKey("open_app.id", ondelete="SET NULL"), index=True)
    app_id = db.Column(db.String(64), index=True)
    capability = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(db.String(32), default="queued", index=True)  # queued|running|succeeded|failed
    progress = db.Column(db.Float, default=0.0)
    message = db.Column(db.String(500), default="")
    error = db.Column(db.Text)
    # JSON
    meta_json = db.Column(db.Text, default="{}")
    result_json = db.Column(db.Text)
    input_uri = db.Column(db.String(500))  # object store 相对/绝对路径
    webhook_delivered = db.Column(db.String(1), default="0")
    create_time = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    update_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def meta(self):
        try:
            return json.loads(self.meta_json or "{}") or {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def set_meta(self, obj):
        self.meta_json = json.dumps(obj or {}, ensure_ascii=False, default=str)

    def result(self):
        if not self.result_json:
            return None
        try:
            return json.loads(self.result_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def set_result(self, obj):
        self.result_json = json.dumps(obj, ensure_ascii=False, default=str) if obj is not None else None

    def to_public(self):
        return {
            "id": self.id,
            "capability": self.capability,
            "status": self.status,
            "progress": self.progress,
            "message": self.message or "",
            "result": self.result(),
            "error": self.error,
            "createdAt": self.create_time.timestamp() if self.create_time else None,
            "updatedAt": self.update_time.timestamp() if self.update_time else None,
        }
