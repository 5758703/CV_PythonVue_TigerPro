"""模型训练：数据集与训练任务。"""
import json
from datetime import datetime

from extensions import db


class TrainingDataset(db.Model):
    __tablename__ = "training_dataset"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    format = db.Column(db.String(24), default="auto")         # auto/voc/voc_standard/yolo/yolo_flat/import
    source_path = db.Column(db.String(500))                   # import 格式：本地数据集绝对路径
    class_names = db.Column(db.Text)                          # JSON 数组
    train_count = db.Column(db.Integer, default=0)
    val_count = db.Column(db.Integer, default=0)
    split_ratio = db.Column(db.Float, default=0.8)
    storage_path = db.Column(db.String(500))                  # uploads/datasets/<id>
    yaml_path = db.Column(db.String(500))                     # data.yaml 相对 uploads
    status = db.Column(db.String(16), default="draft")        # draft/ready/error
    description = db.Column(db.String(500))
    create_time = db.Column(db.DateTime, default=datetime.utcnow)
    update_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def class_list(self):
        if not self.class_names:
            return []
        try:
            return json.loads(self.class_names)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_class_list(self, names):
        self.class_names = json.dumps(names or [], ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "format": self.format,
            "sourcePath": self.source_path,
            "classNames": self.class_list(),
            "trainCount": self.train_count,
            "valCount": self.val_count,
            "splitRatio": self.split_ratio,
            "storagePath": self.storage_path,
            "yamlPath": self.yaml_path,
            "status": self.status,
            "description": self.description,
            "createTime": self.create_time.isoformat() if self.create_time else None,
            "updateTime": self.update_time.isoformat() if self.update_time else None,
        }


class TrainingJob(db.Model):
    __tablename__ = "training_job"

    id = db.Column(db.Integer, primary_key=True)
    job_name = db.Column(db.String(128), nullable=False)
    status = db.Column(db.String(16), default="pending")       # pending/running/done/failed/cancelled
    framework = db.Column(db.String(32), default="ultralytics")
    base_model = db.Column(db.String(128), default="yolov8n.pt")
    dataset_id = db.Column(db.Integer, db.ForeignKey("training_dataset.id"), index=True)
    hyperparams = db.Column(db.Text)                          # JSON
    current_epoch = db.Column(db.Integer, default=0)
    total_epochs = db.Column(db.Integer, default=100)
    progress = db.Column(db.Integer, default=0)               # 0-100
    metrics = db.Column(db.Text)                              # JSON: latest + history
    output_weight_path = db.Column(db.String(500))
    output_model_id = db.Column(db.Integer)                   # ai_model.id
    log_dir = db.Column(db.String(500))
    run_name = db.Column(db.String(128))
    error_message = db.Column(db.Text)
    create_time = db.Column(db.DateTime, default=datetime.utcnow)
    update_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    dataset = db.relationship("TrainingDataset", lazy="joined")

    def hyperparams_dict(self):
        if not self.hyperparams:
            return {}
        try:
            return json.loads(self.hyperparams)
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_hyperparams(self, hp):
        self.hyperparams = json.dumps(hp or {}, ensure_ascii=False)

    def metrics_dict(self):
        if not self.metrics:
            return {"latest": {}, "history": []}
        try:
            return json.loads(self.metrics)
        except (json.JSONDecodeError, TypeError):
            return {"latest": {}, "history": []}

    def set_metrics(self, m):
        self.metrics = json.dumps(m or {"latest": {}, "history": []}, ensure_ascii=False)

    def to_dict(self, detail=False):
        d = {
            "id": self.id,
            "jobName": self.job_name,
            "status": self.status,
            "framework": self.framework,
            "baseModel": self.base_model,
            "datasetId": self.dataset_id,
            "datasetName": self.dataset.name if self.dataset else None,
            "currentEpoch": self.current_epoch,
            "totalEpochs": self.total_epochs,
            "progress": self.progress,
            "latestMetrics": self.metrics_dict().get("latest", {}),
            "outputWeightPath": self.output_weight_path,
            "outputModelId": self.output_model_id,
            "logDir": self.log_dir,
            "runName": self.run_name,
            "errorMessage": self.error_message,
            "createTime": self.create_time.isoformat() if self.create_time else None,
            "updateTime": self.update_time.isoformat() if self.update_time else None,
        }
        if detail:
            d["hyperparams"] = self.hyperparams_dict()
            d["metricsHistory"] = self.metrics_dict().get("history", [])
        return d
