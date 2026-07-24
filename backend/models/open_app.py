"""开放平台：应用、API Key、调用审计。"""
from datetime import datetime
import json

from extensions import db


class OpenApp(db.Model):
    __tablename__ = "open_app"

    id = db.Column(db.Integer, primary_key=True)
    app_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    status = db.Column(db.String(1), default="0")  # 0启用 1停用
    # JSON 数组字符串，如 ["vision:detect","face:recognize"]
    scopes = db.Column(db.Text, default="[]")
    qps_limit = db.Column(db.Integer, default=10)  # 每秒请求上限；0=不限
    daily_limit = db.Column(db.Integer, default=10000)  # 日调用上限；0=不限
    remark = db.Column(db.String(255))
    # 归属业务域（与 openapi_catalog 域 id 对齐，便于分类管理）
    domain_id = db.Column(db.String(64), index=True)
    # 大类：core / system / media / ai / platform
    category = db.Column(db.String(32), index=True)
    # P2 Webhook
    webhook_url = db.Column(db.String(500))
    webhook_secret = db.Column(db.String(128))
    webhook_events = db.Column(db.Text, default='["job.succeeded","job.failed"]')
    create_time = db.Column(db.DateTime, default=datetime.utcnow)
    update_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    keys = db.relationship(
        "OpenApiKey",
        backref="app",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def scope_list(self):
        try:
            raw = json.loads(self.scopes or "[]")
            return [str(x) for x in raw] if isinstance(raw, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def set_scopes(self, scopes):
        cleaned = sorted({str(s).strip() for s in (scopes or []) if str(s).strip()})
        self.scopes = json.dumps(cleaned, ensure_ascii=False)

    def webhook_event_list(self):
        try:
            raw = json.loads(self.webhook_events or "[]")
            return [str(x) for x in raw] if isinstance(raw, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def set_webhook_events(self, events):
        cleaned = sorted({str(s).strip() for s in (events or []) if str(s).strip()})
        self.webhook_events = json.dumps(cleaned, ensure_ascii=False)

    def to_dict(self, with_keys=False):
        d = {
            "id": self.id,
            "appId": self.app_id,
            "name": self.name,
            "status": self.status,
            "scopes": self.scope_list(),
            "qpsLimit": self.qps_limit,
            "dailyLimit": self.daily_limit,
            "remark": self.remark,
            "domainId": self.domain_id,
            "category": self.category,
            "webhookUrl": self.webhook_url,
            "webhookSecretSet": bool(self.webhook_secret),
            "webhookEvents": self.webhook_event_list(),
            "keyCount": len(self.keys or []),
            "createTime": self.create_time.isoformat() if self.create_time else None,
            "updateTime": self.update_time.isoformat() if self.update_time else None,
        }
        if with_keys:
            d["keys"] = [k.to_dict() for k in (self.keys or [])]
        return d


class OpenApiKey(db.Model):
    __tablename__ = "open_api_key"

    id = db.Column(db.Integer, primary_key=True)
    app_pk = db.Column(
        db.Integer,
        db.ForeignKey("open_app.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(64), default="default")
    key_prefix = db.Column(db.String(16), nullable=False, index=True)
    key_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    status = db.Column(db.String(1), default="0")
    expires_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "keyPrefix": self.key_prefix,
            "status": self.status,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "lastUsedAt": self.last_used_at.isoformat() if self.last_used_at else None,
            "createTime": self.create_time.isoformat() if self.create_time else None,
        }


class OpenApiCallLog(db.Model):
    __tablename__ = "open_api_call_log"

    id = db.Column(db.Integer, primary_key=True)
    app_pk = db.Column(db.Integer, db.ForeignKey("open_app.id", ondelete="SET NULL"), index=True)
    app_id = db.Column(db.String(64), index=True)
    request_id = db.Column(db.String(64), index=True)
    method = db.Column(db.String(16))
    path = db.Column(db.String(255))
    capability = db.Column(db.String(64))
    status_code = db.Column(db.Integer)
    biz_code = db.Column(db.Integer)
    latency_ms = db.Column(db.Integer)
    error_message = db.Column(db.String(500))
    create_time = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "appId": self.app_id,
            "requestId": self.request_id,
            "method": self.method,
            "path": self.path,
            "capability": self.capability,
            "statusCode": self.status_code,
            "bizCode": self.biz_code,
            "latencyMs": self.latency_ms,
            "errorMessage": self.error_message,
            "createTime": self.create_time.isoformat() if self.create_time else None,
        }
