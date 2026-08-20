"""在线 MTMC 关联器：外观相似 + 时间窗 + 相机拓扑约束 → 稳定 global_id。"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np


def _l2(v: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(a))
    return a if n < eps else a / n


def _cos(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return -1.0
    x, y = _l2(a), _l2(b)
    dim = max(x.size, y.size)
    xa = np.zeros(dim, dtype=np.float32)
    ya = np.zeros(dim, dtype=np.float32)
    xa[: x.size] = x
    ya[: y.size] = y
    return float(np.dot(xa, ya))


@dataclass
class GlobalTrack:
    global_id: str
    object_type: str  # person|vehicle
    embedding: np.ndarray | None = None
    camera_id: int | None = None
    last_seen: float = field(default_factory=time.time)
    first_seen: float = field(default_factory=time.time)
    reid_person_id: int | None = None
    face_person_id: int | None = None
    display_name: str | None = None
    plate: str | None = None
    identity_key: str | None = None
    visual_key: str | None = None
    hit_count: int = 1
    trail_by_cam: dict[int, list] = field(default_factory=dict)


class MtmcAssociator:
    """跨摄像头全局关联。"""

    def __init__(
        self,
        *,
        appear_thresh: float = 0.48,
        time_window_sec: float = 90.0,
        topology: dict[tuple[int, int], tuple[float, float]] | None = None,
        same_cam_reuse: bool = True,
    ):
        self.appear_thresh = float(appear_thresh)
        self.time_window_sec = float(time_window_sec)
        # (from,to) -> (min_sec, max_sec)
        self.topology = topology or {}
        self.same_cam_reuse = bool(same_cam_reuse)
        self._lock = threading.Lock()
        self.tracks: dict[str, GlobalTrack] = {}
        self._seq = 0

    def set_topology(self, edges: list[dict]):
        topo = {}
        for e in edges or []:
            a = int(e.get("fromCameraId") or e.get("from_camera_id") or 0)
            b = int(e.get("toCameraId") or e.get("to_camera_id") or 0)
            if a and b:
                topo[(a, b)] = (
                    float(e.get("minTransitSec") or e.get("min_transit_sec") or 0),
                    float(e.get("maxTransitSec") or e.get("max_transit_sec") or self.time_window_sec),
                )
                # 无向也允许反向（对称默认）
                topo[(b, a)] = topo[(a, b)]
        with self._lock:
            self.topology = topo

    def _new_gid(self, object_type: str) -> str:
        self._seq += 1
        prefix = "P" if object_type == "person" else "V"
        return f"{prefix}{self._seq:06d}-{uuid.uuid4().hex[:6]}"

    def _topology_ok(self, prev_cam: int | None, cur_cam: int, dt: float) -> float:
        """返回拓扑权重 [0,1]；无拓扑时仅用时间窗。"""
        if prev_cam is None or prev_cam == cur_cam:
            return 1.0 if dt <= self.time_window_sec else 0.0
        key = (int(prev_cam), int(cur_cam))
        if key in self.topology:
            lo, hi = self.topology[key]
            if dt < lo or dt > hi:
                return 0.0
            return 1.0
        # 无边：允许但降权
        if dt > self.time_window_sec:
            return 0.0
        return 0.55

    def associate(
        self,
        *,
        object_type: str,
        camera_id: int,
        embedding: np.ndarray | None,
        identity_key: str | None = None,
        plate: str | None = None,
        reid_person_id: int | None = None,
        face_person_id: int | None = None,
        display_name: str | None = None,
        visual_key: str | None = None,
        now: float | None = None,
    ) -> GlobalTrack:
        now = float(now if now is not None else time.time())
        with self._lock:
            # 过期清理
            dead = [
                gid for gid, g in self.tracks.items()
                if now - g.last_seen > self.time_window_sec * 2
            ]
            for gid in dead:
                self.tracks.pop(gid, None)

            best_gid = None
            best_score = -1.0

            for gid, g in self.tracks.items():
                if g.object_type != object_type:
                    continue
                dt = now - g.last_seen
                topo_w = self._topology_ok(g.camera_id, camera_id, dt)
                if topo_w <= 0:
                    continue
                if g.camera_id == camera_id and not self.same_cam_reuse:
                    continue

                score = 0.0
                # 车辆：identity_key / plate 强约束
                if object_type == "vehicle":
                    if identity_key and g.identity_key and identity_key == g.identity_key:
                        score = 0.99
                    elif plate and g.plate and plate == g.plate:
                        score = 0.92
                    else:
                        score = _cos(embedding, g.embedding)
                        if score < self.appear_thresh:
                            continue
                else:
                    # 已知人员直接锚定
                    if reid_person_id and g.reid_person_id and reid_person_id == g.reid_person_id:
                        score = 0.99
                    else:
                        score = _cos(embedding, g.embedding)
                        if score < self.appear_thresh:
                            continue
                score *= topo_w
                if score > best_score:
                    best_score = score
                    best_gid = gid

            if best_gid is None:
                gid = self._new_gid(object_type)
                g = GlobalTrack(
                    global_id=gid,
                    object_type=object_type,
                    embedding=_l2(embedding) if embedding is not None else None,
                    camera_id=camera_id,
                    last_seen=now,
                    first_seen=now,
                    reid_person_id=reid_person_id,
                    face_person_id=face_person_id,
                    display_name=display_name,
                    plate=plate,
                    identity_key=identity_key,
                    visual_key=visual_key,
                )
                self.tracks[gid] = g
                return g

            g = self.tracks[best_gid]
            g.last_seen = now
            g.camera_id = camera_id
            g.hit_count += 1
            if embedding is not None:
                if g.embedding is None:
                    g.embedding = _l2(embedding)
                else:
                    # EMA 更新外观
                    a, b = _l2(g.embedding), _l2(embedding)
                    dim = max(a.size, b.size)
                    aa = np.zeros(dim, dtype=np.float32)
                    bb = np.zeros(dim, dtype=np.float32)
                    aa[: a.size] = a
                    bb[: b.size] = b
                    g.embedding = _l2(0.7 * aa + 0.3 * bb)
            if reid_person_id:
                g.reid_person_id = reid_person_id
            if face_person_id:
                g.face_person_id = face_person_id
            if display_name:
                g.display_name = display_name
            if plate:
                g.plate = plate
            if identity_key:
                g.identity_key = identity_key
            if visual_key:
                g.visual_key = visual_key
            return g

    def snapshot(self) -> list[dict]:
        with self._lock:
            out = []
            for g in self.tracks.values():
                out.append({
                    "globalId": g.global_id,
                    "objectType": g.object_type,
                    "cameraId": g.camera_id,
                    "reidPersonId": g.reid_person_id,
                    "facePersonId": g.face_person_id,
                    "displayName": g.display_name,
                    "plate": g.plate,
                    "identityKey": g.identity_key,
                    "visualKey": g.visual_key,
                    "hitCount": g.hit_count,
                    "lastSeen": g.last_seen,
                    "firstSeen": g.first_seen,
                })
            return out
