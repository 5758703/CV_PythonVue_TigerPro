"""行人重识别底库实体（与人脸底库完全独立）。

reid_person     登记人员
reid_embedding  外观特征向量（modality=appearance，与 model_key 绑定）
"""
from datetime import datetime

from extensions import db


class ReidPerson(db.Model):
    __tablename__ = "reid_person"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False, index=True)
    employee_no = db.Column(db.String(64), index=True)
    remark = db.Column(db.String(255))
    # 可选关联人脸底库人员，便于混合识别时统一展示身份
    face_person_id = db.Column(db.Integer, index=True)
    status = db.Column(db.String(1), default="0")  # 0启用 1停用
    create_time = db.Column(db.DateTime, default=datetime.utcnow)
    update_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    embeddings = db.relationship(
        "ReidEmbedding",
        backref="person",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def to_dict(self, with_embeddings=False):
        d = {
            "id": self.id,
            "name": self.name,
            "employeeNo": self.employee_no,
            "remark": self.remark,
            "facePersonId": self.face_person_id,
            "status": self.status,
            "embeddingCount": len(self.embeddings or []),
            "createTime": self.create_time.isoformat() if self.create_time else None,
            "updateTime": self.update_time.isoformat() if self.update_time else None,
        }
        if with_embeddings:
            d["embeddings"] = [e.to_dict() for e in (self.embeddings or [])]
        return d


class ReidEmbedding(db.Model):
    __tablename__ = "reid_embedding"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(
        db.Integer,
        db.ForeignKey("reid_person.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_key = db.Column(db.String(128), nullable=False, index=True)
    # Exact inference asset revision. NULL marks legacy rows and only matches a
    # versionless query; explicit versions are never mixed with legacy vectors.
    model_version = db.Column(db.String(255), nullable=True, index=True)
    # 模态：appearance=全身外观（Youtu ReID）；预留 face 等扩展
    modality = db.Column(db.String(32), nullable=False, default="appearance", index=True)
    dim = db.Column(db.Integer, default=768)
    vector = db.Column(db.LargeBinary, nullable=False)
    source_path = db.Column(db.String(500))
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "personId": self.person_id,
            "modelKey": self.model_key,
            "modelVersion": self.model_version,
            "modality": self.modality,
            "dim": self.dim,
            "sourcePath": self.source_path,
            "createTime": self.create_time.isoformat() if self.create_time else None,
        }
