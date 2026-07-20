"""检测告警：规则 + 事件。"""
import json
from datetime import datetime

from extensions import db


class AlertRule(db.Model):
    __tablename__ = "alert_rule"

    id = db.Column(db.Integer, primary_key=True)
    rule_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.String(500))
    rule_type = db.Column(db.String(32), nullable=False)  # class_presence | count_threshold | line_crossing | unmatched_face
    config_json = db.Column(db.Text, nullable=False, default="{}")
    severity = db.Column(db.String(16), default="medium")  # low | medium | high
    status = db.Column(db.String(1), default="1")  # 0启用 1停用（默认不启用）
    create_time = db.Column(db.DateTime, default=datetime.utcnow)
    update_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def config(self):
        try:
            return json.loads(self.config_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def to_dict(self):
        return {
            "id": self.id,
            "ruleKey": self.rule_key,
            "name": self.name,
            "description": self.description,
            "ruleType": self.rule_type,
            "config": self.config(),
            "severity": self.severity,
            "status": self.status,
            "createTime": self.create_time.isoformat() if self.create_time else None,
            "updateTime": self.update_time.isoformat() if self.update_time else None,
        }


class AlertEvent(db.Model):
    __tablename__ = "alert_event"

    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey("alert_rule.id", ondelete="SET NULL"), index=True)
    rule_key = db.Column(db.String(64), index=True)
    rule_name = db.Column(db.String(128))
    severity = db.Column(db.String(16), default="medium")
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.String(1000))
    source_type = db.Column(db.String(32), default="camera")  # camera | image | video
    source_key = db.Column(db.String(128), index=True)
    model_id = db.Column(db.Integer)
    payload_json = db.Column(db.Text)
    status = db.Column(db.String(1), default="0")  # 0未确认 1已确认
    create_time = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    rule = db.relationship("AlertRule", lazy="joined")

    def payload(self):
        try:
            return json.loads(self.payload_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def to_dict(self):
        return {
            "id": self.id,
            "ruleId": self.rule_id,
            "ruleKey": self.rule_key,
            "ruleName": self.rule_name,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "sourceType": self.source_type,
            "sourceKey": self.source_key,
            "modelId": self.model_id,
            "payload": self.payload(),
            "status": self.status,
            "createTime": self.create_time.isoformat() if self.create_time else None,
        }
