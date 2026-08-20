"""跨摄像头 MTMC 实体：相机拓扑、全局身份、轨迹事件、过车记录。"""
from __future__ import annotations

from datetime import datetime

from extensions import db


class CameraTopology(db.Model):
    """相机拓扑边：from_cam → to_cam 的通行时间窗约束。"""
    __tablename__ = "camera_topology"

    id = db.Column(db.Integer, primary_key=True)
    from_camera_id = db.Column(db.Integer, nullable=False, index=True)
    to_camera_id = db.Column(db.Integer, nullable=False, index=True)
    min_transit_sec = db.Column(db.Float, default=0.0)
    max_transit_sec = db.Column(db.Float, default=120.0)
    weight = db.Column(db.Float, default=1.0)
    remark = db.Column(db.String(255))
    status = db.Column(db.String(1), default="0")
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "fromCameraId": self.from_camera_id,
            "toCameraId": self.to_camera_id,
            "minTransitSec": self.min_transit_sec,
            "maxTransitSec": self.max_transit_sec,
            "weight": self.weight,
            "remark": self.remark,
            "status": self.status,
            "createTime": self.create_time.isoformat() if self.create_time else None,
        }


class MtmcGlobalPerson(db.Model):
    """匿名/已知人员全局 ID。"""
    __tablename__ = "mtmc_global_person"

    id = db.Column(db.Integer, primary_key=True)
    global_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    reid_person_id = db.Column(db.Integer, index=True)  # 映射业务底库
    face_person_id = db.Column(db.Integer, index=True)
    display_name = db.Column(db.String(128))
    status = db.Column(db.String(1), default="0")
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "globalId": self.global_id,
            "reidPersonId": self.reid_person_id,
            "facePersonId": self.face_person_id,
            "displayName": self.display_name,
            "status": self.status,
            "firstSeenAt": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "lastSeenAt": self.last_seen_at.isoformat() if self.last_seen_at else None,
        }


class MtmcGlobalVehicle(db.Model):
    """车辆全局身份：车牌 + 视觉 ReID 组合。"""
    __tablename__ = "mtmc_global_vehicle"

    id = db.Column(db.Integer, primary_key=True)
    global_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    plate = db.Column(db.String(32), index=True)
    visual_key = db.Column(db.String(64), index=True)
    identity_key = db.Column(db.String(128), index=True)  # plate|visual
    status = db.Column(db.String(1), default="0")
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "globalId": self.global_id,
            "plate": self.plate,
            "visualKey": self.visual_key,
            "identityKey": self.identity_key,
            "status": self.status,
            "firstSeenAt": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "lastSeenAt": self.last_seen_at.isoformat() if self.last_seen_at else None,
        }


class MtmcTrackEvent(db.Model):
    """跨镜轨迹事件（人员/车辆）。"""
    __tablename__ = "mtmc_track_event"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), nullable=False, index=True)
    camera_id = db.Column(db.Integer, nullable=False, index=True)
    object_type = db.Column(db.String(16), nullable=False, index=True)  # person|vehicle
    global_id = db.Column(db.String(64), nullable=False, index=True)
    local_track_id = db.Column(db.Integer)
    reid_person_id = db.Column(db.Integer)
    display_name = db.Column(db.String(128))
    plate = db.Column(db.String(32))
    identity_key = db.Column(db.String(128))
    score = db.Column(db.Float, default=0.0)
    speed_kmh = db.Column(db.Float)
    congestion = db.Column(db.String(32))
    bbox_json = db.Column(db.Text)  # [x1,y1,x2,y2]
    trail_json = db.Column(db.Text)  # [[x,y],...]
    attrs_json = db.Column(db.Text)
    event_time = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        import json
        def _loads(s):
            if not s:
                return None
            try:
                return json.loads(s)
            except Exception:  # noqa: BLE001
                return None
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "cameraId": self.camera_id,
            "objectType": self.object_type,
            "globalId": self.global_id,
            "localTrackId": self.local_track_id,
            "reidPersonId": self.reid_person_id,
            "displayName": self.display_name,
            "plate": self.plate,
            "identityKey": self.identity_key,
            "score": self.score,
            "speedKmh": self.speed_kmh,
            "congestion": self.congestion,
            "bbox": _loads(self.bbox_json),
            "trail": _loads(self.trail_json),
            "attrs": _loads(self.attrs_json),
            "eventTime": self.event_time.isoformat() if self.event_time else None,
        }


class MtmcVehiclePass(db.Model):
    """跨镜过车记录（挂载在车辆全局身份上）。"""
    __tablename__ = "mtmc_vehicle_pass"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), nullable=False, index=True)
    camera_id = db.Column(db.Integer, nullable=False, index=True)
    global_id = db.Column(db.String(64), nullable=False, index=True)
    identity_key = db.Column(db.String(128), index=True)
    plate = db.Column(db.String(32), index=True)
    plate_score = db.Column(db.Float)
    visual_score = db.Column(db.Float)
    fuse_score = db.Column(db.Float)
    speed_kmh = db.Column(db.Float)
    congestion = db.Column(db.String(32))
    local_track_id = db.Column(db.Integer)
    snapshot_path = db.Column(db.String(500))
    pass_time = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "cameraId": self.camera_id,
            "globalId": self.global_id,
            "identityKey": self.identity_key,
            "plate": self.plate,
            "plateScore": self.plate_score,
            "visualScore": self.visual_score,
            "fuseScore": self.fuse_score,
            "speedKmh": self.speed_kmh,
            "congestion": self.congestion,
            "localTrackId": self.local_track_id,
            "snapshotPath": self.snapshot_path,
            "passTime": self.pass_time.isoformat() if self.pass_time else None,
        }
