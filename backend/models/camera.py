"""摄像头实体（table: camera）。

存放虚拟/网络摄像头元信息：本地视频(ffmpeg 模拟)或 rtsp 网络源。
"""
from datetime import datetime

from extensions import db


class Camera(db.Model):
    __tablename__ = "camera"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)              # 摄像头名称
    source_type = db.Column(db.String(16), default="file")       # file / rtsp
    source = db.Column(db.String(500))                            # 本地相对路径 或 rtsp:// URL
    location = db.Column(db.String(128))                          # 位置/备注
    resolution = db.Column(db.Integer, default=640)              # 输出宽(px)
    fps = db.Column(db.Integer, default=15)                      # 输出帧率
    status = db.Column(db.String(1), default="0")               # 0启用 1停用
    create_time = db.Column(db.DateTime, default=datetime.utcnow)
    update_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "sourceType": self.source_type,
            "source": self.source,
            "location": self.location,
            "resolution": self.resolution,
            "fps": self.fps,
            "status": self.status,
            "createTime": self.create_time.isoformat() if self.create_time else None,
            "updateTime": self.update_time.isoformat() if self.update_time else None,
        }
