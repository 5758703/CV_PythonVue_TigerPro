"""AI 检测模型实体（table: ai_model）。

存放 YOLO 等目标检测模型的元信息与本地权重路径，供
图片 / 视频 / 摄像头检测模块按需加载。
"""
from datetime import datetime

from extensions import db


class AiModel(db.Model):
    __tablename__ = "ai_model"

    id = db.Column(db.Integer, primary_key=True)
    model_name = db.Column(db.String(128), nullable=False)        # 模型名称
    category = db.Column(db.String(64), index=True)               # 模型分类
    model_key = db.Column(db.String(64), unique=True, index=True) # 唯一标识
    # HF 任务类型：object-detection / text-classification / image-classification ...
    task = db.Column(db.String(64), default="object-detection", index=True)
    # 推理库：ultralytics / transformers
    library = db.Column(db.String(32), default="ultralytics")
    version = db.Column(db.String(32), default="v1")
    source_url = db.Column(db.String(500))                        # 来源（HuggingFace 等）
    file_path = db.Column(db.String(500))                         # 本地权重相对路径
    file_size = db.Column(db.BigInteger, default=0)              # 字节
    description = db.Column(db.String(500))
    status = db.Column(db.String(1), default="0")                # 0启用 1停用
    create_time = db.Column(db.DateTime, default=datetime.utcnow)
    update_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def _hub_label(url):
        """从来源 URL 推断下载源：huggingface / modelscope / other。"""
        if not url:
            return "other"
        u = url.lower()
        if "modelscope" in u:
            return "modelscope"
        if "huggingface" in u or "hf.co" in u:
            return "huggingface"
        return "other"

    def to_dict(self):
        return {
            "id": self.id,
            "modelName": self.model_name,
            "category": self.category,
            "modelKey": self.model_key,
            "task": self.task,
            "library": self.library,
            "version": self.version,
            "sourceUrl": self.source_url,
            "hub": self._hub_label(self.source_url),
            "filePath": self.file_path,
            "fileSize": self.file_size,
            "description": self.description,
            "status": self.status,
            "createTime": self.create_time.isoformat() if self.create_time else None,
            "updateTime": self.update_time.isoformat() if self.update_time else None,
        }
