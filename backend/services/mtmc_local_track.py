"""单路局部 Tracklet：IoU 轻量跟踪 + ByteTrack 适配（roboflow/trackers）。

默认仍使用 LocalTracker；可通过 create_local_tracker(backend=\"bytetrack\") 切换。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

TrackerBackend = Literal["iou", "bytetrack"]


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def _center(b):
    return ((b[0] + b[2]) * 0.5, (b[1] + b[3]) * 0.5)


@dataclass
class Tracklet:
    track_id: int
    bbox: list[float]
    class_name: str = "person"
    conf: float = 0.0
    age: int = 0
    hits: int = 1
    time_since_update: int = 0
    embedding: Any = None
    trail: list[tuple[float, float]] = field(default_factory=list)
    attrs: dict = field(default_factory=dict)


class LocalTracker:
    """每摄像头独立的 IoU 局部跟踪器（原有实现）。"""

    def __init__(self, *, iou_thresh: float = 0.3, max_age: int = 30, trail_len: int = 40):
        self.iou_thresh = float(iou_thresh)
        self.max_age = int(max_age)
        self.trail_len = int(trail_len)
        self._next_id = 1
        self.tracks: dict[int, Tracklet] = {}

    def update(self, detections: list[dict]) -> list[Tracklet]:
        """detections: [{bbox, confidence, className, ...}]"""
        for t in self.tracks.values():
            t.time_since_update += 1
            t.age += 1

        unmatched_dets = set(range(len(detections)))
        unmatched_trks = set(self.tracks.keys())
        pairs: list[tuple[float, int, int]] = []
        for ti, trk in self.tracks.items():
            for di, det in enumerate(detections):
                score = _iou(trk.bbox, det["bbox"])
                if score >= self.iou_thresh:
                    pairs.append((score, ti, di))
        pairs.sort(reverse=True)
        used_t, used_d = set(), set()
        for score, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            unmatched_trks.discard(ti)
            unmatched_dets.discard(di)
            det = detections[di]
            trk = self.tracks[ti]
            trk.bbox = [float(v) for v in det["bbox"]]
            trk.conf = float(det.get("confidence") or 0)
            trk.class_name = str(det.get("className") or trk.class_name)
            trk.time_since_update = 0
            trk.hits += 1
            cx, cy = _center(trk.bbox)
            trk.trail.append((cx, cy))
            if len(trk.trail) > self.trail_len:
                trk.trail = trk.trail[-self.trail_len :]

        for di in unmatched_dets:
            det = detections[di]
            tid = self._next_id
            self._next_id += 1
            bbox = [float(v) for v in det["bbox"]]
            cx, cy = _center(bbox)
            self.tracks[tid] = Tracklet(
                track_id=tid,
                bbox=bbox,
                class_name=str(det.get("className") or "object"),
                conf=float(det.get("confidence") or 0),
                trail=[(cx, cy)],
            )

        dead = [tid for tid, t in self.tracks.items() if t.time_since_update > self.max_age]
        for tid in dead:
            self.tracks.pop(tid, None)

        return [t for t in self.tracks.values() if t.time_since_update == 0]


class ByteTrackLocalTracker:
    """ByteTrack 适配层：与 LocalTracker 相同输入/输出，底层使用 roboflow/trackers。"""

    def __init__(
        self,
        *,
        iou_thresh: float = 0.3,
        max_age: int = 30,
        trail_len: int = 40,
        track_activation_threshold: float = 0.25,
        frame_rate: int = 30,
    ):
        try:
            import supervision as sv  # noqa: F401
            from trackers import ByteTrackTracker
        except ImportError as e:
            raise ImportError(
                "ByteTrack 需要 pip install trackers supervision"
            ) from e

        self.trail_len = int(trail_len)
        self.max_age = int(max_age)
        self._trails: dict[int, list[tuple[float, float]]] = {}
        self._hits: dict[int, int] = {}
        self._class_names: dict[int, str] = {}
        self._tracker = ByteTrackTracker(
            lost_track_buffer=max_age,
            minimum_iou_threshold=iou_thresh,
            track_activation_threshold=track_activation_threshold,
            minimum_consecutive_frames=1,
            frame_rate=frame_rate,
        )

    def _match_class_name(self, bbox: list[float], detections: list[dict]) -> str:
        best, best_iou = "object", 0.0
        for det in detections:
            score = _iou(bbox, det["bbox"])
            if score > best_iou:
                best_iou = score
                best = str(det.get("className") or "object")
        return best

    def _to_sv_detections(self, detections: list[dict]):
        import supervision as sv

        if not detections:
            return sv.Detections.empty()
        xyxy = np.asarray([d["bbox"] for d in detections], dtype=np.float32)
        conf = np.asarray([float(d.get("confidence") or 0) for d in detections], dtype=np.float32)
        class_id = np.asarray([hash(str(d.get("className") or "object")) % 1000 for d in detections], dtype=int)
        return sv.Detections(xyxy=xyxy, confidence=conf, class_id=class_id)

    def update(self, detections: list[dict]) -> list[Tracklet]:
        tracked = self._tracker.update(self._to_sv_detections(detections))
        active_ids: set[int] = set()
        out: list[Tracklet] = []

        if tracked.tracker_id is None or len(tracked) == 0:
            stale = [tid for tid in self._trails if tid not in active_ids]
            for tid in stale:
                self._trails.pop(tid, None)
                self._hits.pop(tid, None)
                self._class_names.pop(tid, None)
            return out

        for i in range(len(tracked)):
            raw_tid = int(tracked.tracker_id[i])
            if raw_tid < 0:
                continue
            tid = raw_tid + 1
            active_ids.add(tid)
            bbox = [float(v) for v in tracked.xyxy[i].tolist()]
            conf = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
            cls = self._match_class_name(bbox, detections) if detections else self._class_names.get(tid, "object")
            self._class_names[tid] = cls
            self._hits[tid] = self._hits.get(tid, 0) + 1
            cx, cy = _center(bbox)
            trail = self._trails.setdefault(tid, [])
            trail.append((cx, cy))
            if len(trail) > self.trail_len:
                self._trails[tid] = trail[-self.trail_len :]
            out.append(
                Tracklet(
                    track_id=tid,
                    bbox=bbox,
                    class_name=cls,
                    conf=conf,
                    age=self._hits[tid],
                    hits=self._hits[tid],
                    time_since_update=0,
                    trail=list(self._trails[tid]),
                )
            )

        stale = [tid for tid in list(self._trails) if tid not in active_ids]
        for tid in stale:
            self._trails.pop(tid, None)
            self._hits.pop(tid, None)
            self._class_names.pop(tid, None)
        return out


def create_local_tracker(
    backend: TrackerBackend = "iou",
    *,
    iou_thresh: float = 0.3,
    max_age: int = 30,
    trail_len: int = 40,
    **kwargs,
) -> LocalTracker | ByteTrackLocalTracker:
    """工厂：backend=iou（默认）| bytetrack。"""
    if backend == "bytetrack":
        return ByteTrackLocalTracker(
            iou_thresh=iou_thresh,
            max_age=max_age,
            trail_len=trail_len,
            **kwargs,
        )
    return LocalTracker(iou_thresh=iou_thresh, max_age=max_age, trail_len=trail_len)


def bytetrack_available() -> bool:
    try:
        import supervision  # noqa: F401
        import trackers  # noqa: F401
        return True
    except ImportError:
        return False
