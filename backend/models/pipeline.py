"""边缘 AI 视频分析流水线：定义 / 版本 / 运行记录。"""
from __future__ import annotations

import json
from datetime import datetime

from extensions import db


class AiPipeline(db.Model):
    __tablename__ = "ai_pipeline"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.String(500))
    status = db.Column(db.String(1), default="0")  # 0启用 1停用
    current_version = db.Column(db.Integer, default=1)
    create_by = db.Column(db.Integer)
    create_time = db.Column(db.DateTime, default=datetime.utcnow)
    update_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions = db.relationship(
        "AiPipelineVersion",
        back_populates="pipeline",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    runs = db.relationship(
        "AiPipelineRun",
        back_populates="pipeline",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def to_dict(self, with_dag: bool = False):
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "currentVersion": self.current_version,
            "createBy": self.create_by,
            "createTime": self.create_time.isoformat() if self.create_time else None,
            "updateTime": self.update_time.isoformat() if self.update_time else None,
        }
        if with_dag:
            ver = (
                AiPipelineVersion.query.filter_by(
                    pipeline_id=self.id, version=self.current_version
                ).first()
            )
            d["dag"] = ver.dag() if ver else None
            d["versionId"] = ver.id if ver else None
        return d


class AiPipelineVersion(db.Model):
    __tablename__ = "ai_pipeline_version"

    id = db.Column(db.Integer, primary_key=True)
    pipeline_id = db.Column(
        db.Integer, db.ForeignKey("ai_pipeline.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version = db.Column(db.Integer, nullable=False, default=1)
    dag_json = db.Column(db.Text, nullable=False, default="{}")
    remark = db.Column(db.String(255))
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    pipeline = db.relationship("AiPipeline", back_populates="versions")

    __table_args__ = (
        db.UniqueConstraint("pipeline_id", "version", name="uk_pipeline_version"),
    )

    def dag(self) -> dict:
        try:
            return json.loads(self.dag_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def to_dict(self):
        return {
            "id": self.id,
            "pipelineId": self.pipeline_id,
            "version": self.version,
            "dag": self.dag(),
            "remark": self.remark,
            "createTime": self.create_time.isoformat() if self.create_time else None,
        }


class AiPipelineRun(db.Model):
    __tablename__ = "ai_pipeline_run"

    id = db.Column(db.Integer, primary_key=True)
    run_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    pipeline_id = db.Column(
        db.Integer, db.ForeignKey("ai_pipeline.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id = db.Column(db.Integer, db.ForeignKey("ai_pipeline_version.id", ondelete="SET NULL"))
    camera_id = db.Column(db.Integer, index=True)
    state = db.Column(db.String(16), default="created")  # created|running|stopped|error
    error_message = db.Column(db.String(1000))
    metrics_json = db.Column(db.Text, default="{}")
    started_at = db.Column(db.DateTime)
    stopped_at = db.Column(db.DateTime)
    create_time = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    pipeline = db.relationship("AiPipeline", back_populates="runs")
    version = db.relationship("AiPipelineVersion")

    def metrics(self) -> dict:
        try:
            return json.loads(self.metrics_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def to_dict(self):
        return {
            "id": self.id,
            "runKey": self.run_key,
            "pipelineId": self.pipeline_id,
            "versionId": self.version_id,
            "cameraId": self.camera_id,
            "state": self.state,
            "errorMessage": self.error_message,
            "metrics": self.metrics(),
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "stoppedAt": self.stopped_at.isoformat() if self.stopped_at else None,
            "createTime": self.create_time.isoformat() if self.create_time else None,
        }
