"""MTMC Tracklet 聚合：关键帧质量筛选 + 加权 embedding。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# person 3~8 帧，vehicle 3~10 帧（文档 §6.2）
_TOPK_BY_TYPE = {"person": 8, "vehicle": 10}
_MIN_AREA_RATIO = 0.002  # bbox 过小则丢弃


_KEYFRAME_MIN_INTERVAL_SEC = 0.75
_KEYFRAME_MAX_INTERVAL_SEC = 3.0
_KEYFRAME_QUALITY_GAIN = 0.08


def _l2(v: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(a))
    return a if n < eps else a / n


def frame_quality(
    bbox: list[float],
    conf: float,
    frame_h: int,
    frame_w: int,
) -> float:
    """bbox 面积 + 检测置信度 → 质量分 [0,1]。"""
    if len(bbox) < 4 or frame_h <= 0 or frame_w <= 0:
        return 0.0
    x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    frame_area = float(frame_h * frame_w)
    area_ratio = area / max(frame_area, 1.0)
    if area_ratio < _MIN_AREA_RATIO:
        return 0.0
    # 面积占比上限 25%，与置信度加权
    area_score = min(1.0, area_ratio / 0.25)
    return float(max(0.0, min(1.0, float(conf or 0) * (0.25 + 0.75 * area_score))))


@dataclass
class TrackletObservation:
    ts: float
    bbox: list[float]
    conf: float
    quality: float
    embedding: np.ndarray | None = None
    model_key: str | None = None
    model_version: str | None = None
    embedding_spaces: dict[tuple[str, int, str | None], np.ndarray] = field(default_factory=dict)
    plate: str | None = None
    plate_score: float = 0.0
    identity_key: str | None = None
    visual_key: str | None = None
    fuse_score: float = 0.0
    meta: dict = field(default_factory=dict)


@dataclass
class TrackletBuilder:
    """单路 local_track 的观测累积器。"""

    tracklet_id: str
    session_id: str
    camera_id: int
    object_type: str  # person|vehicle
    local_track_id: int
    observations: list[TrackletObservation] = field(default_factory=list)
    assigned_global_id: str | None = None
    start_ts: float = 0.0
    end_ts: float = 0.0
    trail: list[tuple[float, float]] = field(default_factory=list)
    last_embedding_sample_at: float | None = None
    last_embedding_sample_quality: float = 0.0
    sampled_view_tokens: set[str] = field(default_factory=set)

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        camera_id: int,
        object_type: str,
        local_track_id: int,
        now: float | None = None,
    ) -> TrackletBuilder:
        ts = float(now if now is not None else time.time())
        tid = f"TL-{object_type[:1]}-{camera_id}-{local_track_id}-{uuid.uuid4().hex[:10]}"
        return cls(
            tracklet_id=tid,
            session_id=session_id,
            camera_id=camera_id,
            object_type=object_type,
            local_track_id=int(local_track_id),
            start_ts=ts,
            end_ts=ts,
        )

    def should_sample_embedding(self, now: float, quality: float, view_token: str | None = None) -> bool:
        """Reserve a keyframe when its time, quality, or view adds evidence."""
        ts = float(now)
        q = max(0.0, min(1.0, float(quality or 0.0)))
        view = str(view_token) if view_token else None
        last = self.last_embedding_sample_at
        unseen_view = view is not None and view not in self.sampled_view_tokens
        should_sample = (
            last is None
            or (ts - last) >= _KEYFRAME_MAX_INTERVAL_SEC
            or ((ts - last) >= _KEYFRAME_MIN_INTERVAL_SEC
                and q >= self.last_embedding_sample_quality + _KEYFRAME_QUALITY_GAIN)
            or unseen_view
        )
        if should_sample:
            self.last_embedding_sample_at = ts
            self.last_embedding_sample_quality = q
            if view is not None:
                self.sampled_view_tokens.add(view)
        return should_sample

    def add_observation(
        self,
        *,
        bbox: list[float],
        conf: float,
        frame_h: int,
        frame_w: int,
        embedding: np.ndarray | None = None,
        embedding_spaces: dict[str, np.ndarray] | None = None,
        embedding_space_versions: dict[str, str | None] | None = None,
        model_key: str | None = None,
        model_version: str | None = None,
        plate: str | None = None,
        plate_score: float = 0.0,
        identity_key: str | None = None,
        visual_key: str | None = None,
        fuse_score: float = 0.0,
        trail: list[tuple[float, float]] | None = None,
        meta: dict | None = None,
        now: float | None = None,
    ) -> float:
        ts = float(now if now is not None else time.time())
        q = frame_quality(bbox, conf, frame_h, frame_w)
        emb = None
        if embedding is not None:
            emb = _l2(np.asarray(embedding, dtype=np.float32))
        spaces: dict[tuple[str, int, str | None], np.ndarray] = {}
        for key, value in (embedding_spaces or {}).items():
            vector = _l2(np.asarray(value, dtype=np.float32).reshape(-1))
            version = (embedding_space_versions or {}).get(key, model_version)
            spaces[(str(key), int(vector.size), str(version) if version else None)] = vector
        if emb is not None and not spaces:
            key = str(model_key or f"legacy:{self.object_type}")
            spaces[(key, int(emb.size), str(model_version) if model_version else None)] = emb
        self.observations.append(
            TrackletObservation(
                ts=ts,
                bbox=[float(v) for v in bbox[:4]],
                conf=float(conf or 0),
                quality=q,
                embedding=emb,
                model_key=str(model_key) if model_key else None,
                model_version=str(model_version) if model_version else None,
                embedding_spaces=spaces,
                plate=plate,
                plate_score=float(plate_score or 0),
                identity_key=identity_key,
                visual_key=visual_key,
                fuse_score=float(fuse_score or 0),
                meta=dict(meta or {}),
            )
        )
        self.end_ts = ts
        if not self.start_ts:
            self.start_ts = ts
        if trail:
            self.trail = list(trail)
        return q

    def best_observation(self) -> TrackletObservation | None:
        keyed = [o for o in self.observations if o.quality > 0]
        if not keyed:
            return self.observations[-1] if self.observations else None
        return max(keyed, key=lambda o: o.quality)

    def ready_for_tentative(self, min_quality: float = 0.08) -> bool:
        """至少一帧带 embedding 且质量达标，可做首次关联。"""
        return any(
            o.embedding is not None and o.quality >= min_quality
            for o in self.observations
        )

    def aggregate_embedding_spaces(self) -> dict[tuple[str, int, str | None], np.ndarray]:
        """Aggregate only observations from the exact same model space."""
        groups: dict[tuple[str, int, str | None], list[TrackletObservation]] = {}
        for observation in self.observations:
            spaces = observation.embedding_spaces
            if not spaces and observation.embedding is not None:
                vector = np.asarray(observation.embedding, dtype=np.float32).reshape(-1)
                key = observation.model_key or f"legacy:{self.object_type}"
                spaces = {(key, int(vector.size), observation.model_version): vector}
            for space, vector in spaces.items():
                groups.setdefault(space, []).append(
                    TrackletObservation(
                        ts=observation.ts, bbox=observation.bbox, conf=observation.conf,
                        quality=observation.quality, embedding=vector,
                    )
                )
        return {space: self._aggregate_space(observations) for space, observations in groups.items()}

    def _aggregate_space(self, observations: list[TrackletObservation]) -> np.ndarray:
        keyed = [(o.quality, o.embedding) for o in observations if o.embedding is not None and o.quality > 0]
        if not keyed:
            keyed = [(o.quality, o.embedding) for o in observations if o.embedding is not None]
        if not keyed:
            raise ValueError("cannot aggregate an empty model space")
        keyed.sort(key=lambda x: -x[0])
        top_k = _TOPK_BY_TYPE.get(self.object_type, 8)
        top = keyed[:top_k]
        # Reject a stray crop from another nearby target before averaging.  The
        # medoid represents the most coherent appearance within this tracklet.
        if len(top) >= 3:
            vecs = [_l2(np.asarray(emb, dtype=np.float32).reshape(-1)) for _, emb in top]
            dim = int(vecs[0].size)
            if any(vec.size != dim for vec in vecs):
                raise ValueError("model-space aggregation received mixed dimensions")
            mat = np.stack(vecs, axis=0)
            sims = mat @ mat.T
            medoid = int(np.argmax(np.median(sims, axis=1)))
            keep_at = 0.30 if self.object_type == "vehicle" else 0.38
            keep = [i for i, sim in enumerate(sims[medoid]) if float(sim) >= keep_at]
            if len(keep) >= 2:
                top = [top[i] for i in keep]
        weights = np.asarray([max(q, 1e-6) for q, _ in top], dtype=np.float32)
        weights = weights / weights.sum()
        dim = int(top[0][1].size)
        out = np.zeros(dim, dtype=np.float32)
        for w, (_, emb) in zip(weights, top):
            e = np.asarray(emb, dtype=np.float32).reshape(-1)
            if e.size != dim:
                raise ValueError("model-space aggregation received mixed dimensions")
            out += float(w) * e
        return _l2(out)

    def aggregate_embedding(
        self,
        model_key: str | None = None,
        model_version: str | None = None,
    ) -> np.ndarray | None:
        """Compatibility view of the best single isolated model space."""
        spaces = self.aggregate_embedding_spaces()
        if not spaces:
            return None
        if model_key is not None:
            for (key, _dim, version), embedding in spaces.items():
                if key == model_key and version == model_version:
                    return embedding
            return None
        return next(iter(spaces.values()))

    def aggregate_plate(self) -> tuple[str | None, float]:
        """多帧车牌投票（取最高分）。"""
        best_text, best_score = None, 0.0
        for o in self.observations:
            if o.plate and float(o.plate_score or 0) >= best_score:
                best_text, best_score = o.plate, float(o.plate_score)
        return best_text, best_score

    def aggregate_identity(self) -> dict[str, Any]:
        best = self.best_observation()
        plate, plate_score = self.aggregate_plate()
        return {
            "plate": plate,
            "plateScore": plate_score,
            "identityKey": best.identity_key if best else None,
            "visualKey": best.visual_key if best else None,
            "fuseScore": max((o.fuse_score for o in self.observations), default=0.0),
        }

    def summary(self) -> dict:
        emb = self.aggregate_embedding()
        qualities = [o.quality for o in self.observations]
        return {
            "trackletId": self.tracklet_id,
            "sessionId": self.session_id,
            "cameraId": self.camera_id,
            "objectType": self.object_type,
            "localTrackId": self.local_track_id,
            "globalId": self.assigned_global_id,
            "startTs": self.start_ts,
            "endTs": self.end_ts,
            "durationSec": max(0.0, self.end_ts - self.start_ts),
            "observationCount": len(self.observations),
            "keyframeCount": sum(1 for o in self.observations if o.embedding is not None),
            "avgQuality": round(float(np.mean(qualities)), 4) if qualities else 0.0,
            "embeddingDim": int(emb.size) if emb is not None else 0,
            "trail": [[float(x), float(y)] for x, y in self.trail],
        }
