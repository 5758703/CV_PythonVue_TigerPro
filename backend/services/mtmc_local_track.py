"""单路局部 Tracklet：ByteTrack / BoT-SORT(+CMC) / IoU。

McByte++ 分层：
- 检测：YOLO 等（引擎）
- 短时：Kalman + IoU（ByteTrack/BoT-SORT）；CMC 仅在 enable_cmc 且传入 frame 时启用
- Mask：可选 MaskCue（默认关闭；完整 SAM/Cutie 成本高，监控墙 2FPS 不建议默认开）
- 长时认人：OSNet 在 MtmcAssociator 新生 track 时调用（本模块不负责）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

TrackerBackend = Literal["iou", "bytetrack", "botsort"]

# ByteTrack/BoT-SORT 未激活轨迹（tracker_id<0）使用 900001+ 段，避免与正式 track 冲突
_TENTATIVE_ID_BASE = 900_000


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
    is_new: bool = False  # 本帧新确认的轨迹（供引擎触发长时 ReID）


class MaskCueHelper:
    """短时疑难匹配的 Mask 钩子（McByte 风格，默认空实现）。

    完整版需 SAM 初始化 + Cutie/XMem 传播；默认关闭以免拖垮 MTMC 采样。
    子类可覆盖 `boost_pair(track_bbox, det_bbox) -> float` 给 IoU 加分。
    """

    def __init__(self, enabled: bool = False):
        self.enabled = bool(enabled)

    def prepare(self, frame, tracklets: list[Tracklet]) -> None:
        return None

    def boost_pair(self, track_bbox: list[float], det_bbox: list[float]) -> float:
        return 0.0


class LocalTracker:
    """每摄像头独立的 IoU 局部跟踪器。"""

    def __init__(
        self,
        *,
        iou_thresh: float = 0.3,
        max_age: int = 30,
        trail_len: int = 40,
        mask_cue: MaskCueHelper | None = None,
    ):
        self.iou_thresh = float(iou_thresh)
        self.max_age = int(max_age)
        self.trail_len = int(trail_len)
        self.mask_cue = mask_cue or MaskCueHelper(False)
        self._next_id = 1
        self.tracks: dict[int, Tracklet] = {}
        self._seen_ids: set[int] = set()

    def update(self, detections: list[dict], frame=None) -> list[Tracklet]:
        if self.mask_cue.enabled and frame is not None:
            self.mask_cue.prepare(frame, list(self.tracks.values()))

        for t in self.tracks.values():
            t.time_since_update += 1
            t.age += 1
            t.is_new = False

        unmatched_dets = set(range(len(detections)))
        unmatched_trks = set(self.tracks.keys())
        pairs: list[tuple[float, int, int]] = []
        for ti, trk in self.tracks.items():
            for di, det in enumerate(detections):
                score = _iou(trk.bbox, det["bbox"])
                if self.mask_cue.enabled:
                    score += self.mask_cue.boost_pair(trk.bbox, det["bbox"])
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
            is_new = tid not in self._seen_ids
            self._seen_ids.add(tid)
            self.tracks[tid] = Tracklet(
                track_id=tid,
                bbox=bbox,
                class_name=str(det.get("className") or "object"),
                conf=float(det.get("confidence") or 0),
                trail=[(cx, cy)],
                is_new=is_new,
            )

        dead = [tid for tid, t in self.tracks.items() if t.time_since_update > self.max_age]
        for tid in dead:
            self.tracks.pop(tid, None)

        return [t for t in self.tracks.values() if t.time_since_update == 0]


class _SvTrackerAdapter:
    """ByteTrack / BoT-SORT 共用适配逻辑。"""

    def __init__(
        self,
        tracker,
        *,
        trail_len: int = 40,
        pass_frame: bool = False,
        mask_cue: MaskCueHelper | None = None,
        iou_thresh: float = 0.3,
    ):
        self._tracker = tracker
        self.trail_len = int(trail_len)
        self.pass_frame = bool(pass_frame)
        self.mask_cue = mask_cue or MaskCueHelper(False)
        self.iou_thresh = float(iou_thresh)
        self._trails: dict[int, list[tuple[float, float]]] = {}
        self._hits: dict[int, int] = {}
        self._class_names: dict[int, str] = {}
        self._seen_ids: set[int] = set()
        self._tentative_bbox: dict[int, list[float]] = {}
        self._next_tentative = 0

    def _promote_tentative_to_confirmed(self, bbox: list[float], confirmed_tid: int) -> int:
        """未激活→激活：若 IoU 命中临时轨迹则沿用临时 id，保证 MTMC sticky 连续。"""
        best_tid, best_iou = None, 0.0
        match_thresh = max(0.15, self.iou_thresh * 0.5)
        for tid, prev in self._tentative_bbox.items():
            score = _iou(prev, bbox)
            if score > best_iou and score >= match_thresh:
                best_iou, best_tid = score, tid
        if best_tid is not None:
            self._tentative_bbox[best_tid] = bbox
            return best_tid
        return confirmed_tid

    def _assign_tentative_id(self, bbox: list[float]) -> int:
        """未激活检测：IoU 续接临时 local id，供 MTMC 低采样率下仍能出框。"""
        best_tid, best_iou = None, 0.0
        match_thresh = max(0.15, self.iou_thresh * 0.5)
        for tid, prev in self._tentative_bbox.items():
            score = _iou(prev, bbox)
            if score > best_iou and score >= match_thresh:
                best_iou, best_tid = score, tid
        if best_tid is not None:
            self._tentative_bbox[best_tid] = bbox
            return best_tid
        self._next_tentative += 1
        tid = _TENTATIVE_ID_BASE + self._next_tentative
        self._tentative_bbox[tid] = bbox
        return tid

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

    def update(self, detections: list[dict], frame=None) -> list[Tracklet]:
        if self.mask_cue.enabled and frame is not None:
            self.mask_cue.prepare(frame, [])
        if self.pass_frame:
            tracked = self._tracker.update(self._to_sv_detections(detections), frame=frame)
        else:
            tracked = self._tracker.update(self._to_sv_detections(detections))
        active_ids: set[int] = set()
        active_tentative: set[int] = set()
        out: list[Tracklet] = []

        if tracked.tracker_id is None or len(tracked) == 0:
            for tid in list(self._trails):
                self._trails.pop(tid, None)
                self._hits.pop(tid, None)
                self._class_names.pop(tid, None)
            self._tentative_bbox.clear()
            return out

        for i in range(len(tracked)):
            raw_tid = int(tracked.tracker_id[i])
            bbox = [float(v) for v in tracked.xyxy[i].tolist()]
            conf = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
            tentative = raw_tid < 0
            if tentative:
                tid = self._assign_tentative_id(bbox)
                active_tentative.add(tid)
            else:
                tid = self._promote_tentative_to_confirmed(bbox, raw_tid + 1)
                if tid >= _TENTATIVE_ID_BASE:
                    active_tentative.add(tid)
            active_ids.add(tid)
            cls = self._match_class_name(bbox, detections) if detections else self._class_names.get(tid, "object")
            self._class_names[tid] = cls
            self._hits[tid] = self._hits.get(tid, 0) + 1
            is_new = tid not in self._seen_ids
            self._seen_ids.add(tid)
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
                    is_new=is_new,
                    attrs={
                        "cmc": bool(self.pass_frame and frame is not None),
                        "tentative": tentative,
                    },
                )
            )

        stale = [tid for tid in list(self._trails) if tid not in active_ids]
        for tid in stale:
            self._trails.pop(tid, None)
            self._hits.pop(tid, None)
            self._class_names.pop(tid, None)
        stale_tent = [tid for tid in list(self._tentative_bbox) if tid not in active_tentative]
        for tid in stale_tent:
            self._tentative_bbox.pop(tid, None)
        return out


class ByteTrackLocalTracker(_SvTrackerAdapter):
    """ByteTrack：Kalman + 高低分 IoU（短时主路径）。"""

    def __init__(
        self,
        *,
        iou_thresh: float = 0.3,
        max_age: int = 30,
        trail_len: int = 40,
        track_activation_threshold: float = 0.25,
        frame_rate: int = 30,
        mask_cue: MaskCueHelper | None = None,
        **_kwargs,
    ):
        try:
            from trackers import ByteTrackTracker
        except ImportError as e:
            raise ImportError("ByteTrack 需要 pip install trackers supervision") from e
        tracker = ByteTrackTracker(
            lost_track_buffer=max_age,
            minimum_iou_threshold=iou_thresh,
            track_activation_threshold=track_activation_threshold,
            minimum_consecutive_frames=1,
            frame_rate=frame_rate,
        )
        super().__init__(
            tracker,
            trail_len=trail_len,
            pass_frame=False,
            mask_cue=mask_cue,
            iou_thresh=iou_thresh,
        )


class BotSortLocalTracker(_SvTrackerAdapter):
    """BoT-SORT：短时跟踪 + 可选 CMC（固定摄像头建议 enable_cmc=False）。"""

    def __init__(
        self,
        *,
        iou_thresh: float = 0.3,
        max_age: int = 30,
        trail_len: int = 40,
        track_activation_threshold: float = 0.25,
        frame_rate: int = 30,
        enable_cmc: bool = False,
        cmc_method: str = "sparseOptFlow",
        mask_cue: MaskCueHelper | None = None,
        **_kwargs,
    ):
        try:
            from trackers import BoTSORTTracker
        except ImportError as e:
            raise ImportError("BoT-SORT 需要 pip install trackers supervision") from e
        tracker = BoTSORTTracker(
            lost_track_buffer=max_age,
            track_activation_threshold=track_activation_threshold,
            minimum_consecutive_frames=1,
            minimum_iou_threshold_first_assoc=max(0.1, float(iou_thresh) - 0.1),
            frame_rate=float(frame_rate),
            enable_cmc=bool(enable_cmc),
            cmc_method=cmc_method,  # type: ignore[arg-type]
        )
        super().__init__(
            tracker,
            trail_len=trail_len,
            pass_frame=bool(enable_cmc),
            mask_cue=mask_cue,
            iou_thresh=iou_thresh,
        )


def create_local_tracker(
    backend: TrackerBackend = "bytetrack",
    *,
    iou_thresh: float = 0.3,
    max_age: int = 30,
    trail_len: int = 40,
    enable_cmc: bool = False,
    enable_mask_cue: bool = False,
    **kwargs,
) -> LocalTracker | ByteTrackLocalTracker | BotSortLocalTracker:
    """工厂：bytetrack（默认）| botsort | iou。"""
    mask = MaskCueHelper(enabled=enable_mask_cue)
    if backend == "iou":
        return LocalTracker(
            iou_thresh=iou_thresh, max_age=max_age, trail_len=trail_len, mask_cue=mask,
        )
    if backend == "botsort":
        return BotSortLocalTracker(
            iou_thresh=iou_thresh,
            max_age=max_age,
            trail_len=trail_len,
            enable_cmc=enable_cmc,
            mask_cue=mask,
            **kwargs,
        )
    return ByteTrackLocalTracker(
        iou_thresh=iou_thresh,
        max_age=max_age,
        trail_len=trail_len,
        mask_cue=mask,
        **kwargs,
    )


def bytetrack_available() -> bool:
    try:
        import supervision  # noqa: F401
        import trackers  # noqa: F401
        return True
    except ImportError:
        return False


def botsort_available() -> bool:
    try:
        from trackers import BoTSORTTracker  # noqa: F401
        return True
    except ImportError:
        return False
