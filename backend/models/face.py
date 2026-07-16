"""人脸底库实体。

face_person     登记人员
face_embedding  人员特征向量（与模型 pack 绑定，换模型需重提特征）
"""
from datetime import datetime

from extensions import db


class FacePerson(db.Model):
    __tablename__ = "face_person"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False, index=True)
    employee_no = db.Column(db.String(64), index=True)  # 工号/编号（可选）
    remark = db.Column(db.String(255))
    status = db.Column(db.String(1), default="0")  # 0启用 1停用
    create_time = db.Column(db.DateTime, default=datetime.utcnow)
    update_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    embeddings = db.relationship(
        "FaceEmbedding",
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
            "status": self.status,
            "embeddingCount": len(self.embeddings or []),
            "createTime": self.create_time.isoformat() if self.create_time else None,
            "updateTime": self.update_time.isoformat() if self.update_time else None,
        }
        if with_embeddings:
            d["embeddings"] = [e.to_dict() for e in (self.embeddings or [])]
        return d


class FaceEmbedding(db.Model):
    __tablename__ = "face_embedding"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(
        db.Integer,
        db.ForeignKey("face_person.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_key = db.Column(db.String(128), nullable=False, index=True)  # 与 AiModel.model_key 绑定
    dim = db.Column(db.Integer, default=512)
    vector = db.Column(db.LargeBinary, nullable=False)  # float32 bytes
    source_path = db.Column(db.String(500))  # 登记图相对路径（可选）
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "personId": self.person_id,
            "modelKey": self.model_key,
            "dim": self.dim,
            "sourcePath": self.source_path,
            "createTime": self.create_time.isoformat() if self.create_time else None,
        }
