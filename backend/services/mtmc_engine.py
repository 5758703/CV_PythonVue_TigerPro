"""跨镜 MTMC 引擎：一次拉流 → 检测 → 局部跟踪 → 强 ReID → 车牌融合 → 在线关联 → 叠加。

每会话 session_id 隔离；车辆复用 VehicleSession 语义（按 cam:session 隔离车牌投票/测速）。
"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable

import cv2
import numpy as np

log = logging.getLogger(__name__)

_PERSON_COLORS = [
    (80, 200, 0), (255, 160, 0), (60, 160, 230), (80, 80, 245),
    (222, 84, 146), (0, 200, 200), (180, 105, 255), (194, 194, 19),
]
_VEHICLE_COLORS = [
    (40, 180, 255), (0, 140, 255), (30, 200, 120), (200, 100, 40),
]
# COCO 检测类别：行人 class=0；骑车人常被标为 bicycle(1)/motorcycle(3)，归入车辆分支
_PERSON_DET_CLASSES = [0]
_VEHICLE_DET_CLASSES = [1, 2, 3, 5, 7]


def _intersection_over_smaller(a, b) -> float:
    ax1, ay1, ax2, ay2 = [float(v) for v in a]
    bx1, by1, bx2, by2 = [float(v) for v in b]
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    ba = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / max(1.0, min(aa, ba))


def supplement_rider_person_dets(
    persons: list[dict],
    vehicles: list[dict],
    *,
    frame_w: int,
    frame_h: int,
) -> list[dict]:
    """Recover riders that YOLO labels only as bicycle/motorcycle.

    The proxy covers the body above the two-wheeler and is emitted only when no
    real person detection already occupies that region.  Cars and trucks never
    create a person proxy.
    """
    out = list(persons or [])
    for vehicle in vehicles or []:
        cls_id = int(vehicle.get("classId", -1))
        cls_name = str(vehicle.get("className") or "").strip().lower()
        if cls_id not in (1, 3) and cls_name not in {"bicycle", "motorcycle", "bike", "motorbike"}:
            continue
        bbox = vehicle.get("bbox") or []
        if len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
        bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
        proxy = [
            max(0.0, x1 + 0.06 * bw),
            max(0.0, y1 - 0.95 * bh),
            min(float(frame_w), x2 - 0.06 * bw),
            min(float(frame_h), y1 + 0.62 * bh),
        ]
        if proxy[2] <= proxy[0] or proxy[3] <= proxy[1]:
            continue
        if any(_intersection_over_smaller(proxy, p.get("bbox") or [0, 0, 0, 0]) >= 0.38 for p in out):
            continue
        out.append({
            "bbox": [round(v, 1) for v in proxy],
            "confidence": round(max(0.12, float(vehicle.get("confidence") or 0) * 0.72), 4),
            "classId": 0,
            "className": "rider",
            "riderProxy": True,
            "sourceVehicleClass": cls_name,
        })
    return out


def _color_for(gid: str, palette) -> tuple:
    h = sum(ord(c) for c in (gid or ""))
    return palette[h % len(palette)]


@dataclass
class VirtualVideoSource:
    """本地视频上传模式：无需预建摄像头，会话内临时虚拟镜头。"""
    id: int
    name: str
    abs_path: str
    source_type: str = "file"
    source: str = ""
    resolution: int = 640
    fps: int = 10
    original_filename: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "sourceType": self.source_type,
            "originalFilename": self.original_filename or os.path.basename(self.abs_path or self.source or ""),
        }


_VIRTUAL_CAM_ID_SEQ = 910_000
_virtual_cam_lock = threading.Lock()


def next_virtual_cam_id() -> int:
    global _VIRTUAL_CAM_ID_SEQ
    with _virtual_cam_lock:
        _VIRTUAL_CAM_ID_SEQ += 1
        return _VIRTUAL_CAM_ID_SEQ


@dataclass
class MtmcConfig:
    camera_ids: list[int]
    det_person_path: str | None = None
    det_vehicle_path: str | None = None
    youtu_root: str | None = None
    strong_reid_root: str | None = None
    vehicle_reid_root: str | None = None
    plate_model_path: str | None = None
    ocr_fn: Callable[[bytes], dict] | None = None
    enable_person: bool = True
    enable_vehicle: bool = True
    conf: float = 0.28
    sample_fps: float = 4.0
    meters_per_pixel: float = 0.05
    appear_thresh: float = 0.48
    vehicle_appear_thresh: float = 0.0
    confirm_thresh: float = 0.0
    candidate_thresh: float = 0.0
    use_faiss_gallery: bool = True
    gallery_model_key: str | None = None
    time_window_sec: float = 90.0
    fuse_weight_strong: float = 0.65
    width: int = 960
    fps: int = 10
    persist_events: bool = False
    reid_budget: int = 2
    person_reid_budget: int | None = None
    vehicle_reid_budget: int | None = None
    plate_budget: int = 1
    # 局部跟踪：bytetrack（默认）| botsort | iou
    local_track_backend: str = "bytetrack"
    local_track_max_age: int = 30
    local_track_iou_thresh: float = 0.3
    # McByte++：CMC 仅云台/抖动时开；Mask 默认关（SAM/Cutie 太重）
    enable_cmc: bool = False
    enable_mask_cue: bool = False
    lost_revive_sec: float = 1.0
    mcbyte_decouple: bool = True
    # 实时检测测试：仅 YOLO 画框，不做 Tracklet / ReID / 跨镜关联
    detect_only: bool = False


@dataclass
class CamState:
    camera_id: int
    tracker_person: Any = None
    tracker_vehicle: Any = None
    vehicle_session_id: str = ""
    last_process_at: float = 0.0
    playback_started_at: float = 0.0
    playback_last_at: float = 0.0
    overlay_jpeg: bytes | None = None
    frame_seq: int = 0
    last_dets: list = field(default_factory=list)
    # 当前帧会随采样清空；会话结果按目标保留并持续更新，供每路卡片展示。
    session_dets: dict = field(default_factory=dict)
    state_lock: Any = field(default_factory=threading.RLock, repr=False)
    lifecycle_lock: Any = field(default_factory=threading.RLock, repr=False)
    builders_flushed: bool = False
    congestion: dict = field(default_factory=dict)
    person_builders: dict = field(default_factory=dict)
    vehicle_builders: dict = field(default_factory=dict)
    last_error: str | None = None
    last_persist_at: float = 0.0
    plate_cache: dict = field(default_factory=dict)
    raw_jpeg: bytes | None = None
    fast_preview: bool = False
    stream_fps: float = 0.0
    detect_fps: float = 0.0
    _publish_times: list = field(default_factory=list, repr=False)
    _detect_times: list = field(default_factory=list, repr=False)


def _rolling_fps(times: list, now: float | None = None, window: float = 2.0) -> float:
    """根据时间戳滑动窗口估算实时 FPS。"""
    ts = float(now if now is not None else time.time())
    times.append(ts)
    cutoff = ts - window
    while times and times[0] < cutoff:
        times.pop(0)
    if len(times) < 2:
        return 0.0
    span = times[-1] - times[0]
    if span <= 1e-6:
        return 0.0
    return round((len(times) - 1) / span, 1)


def _mark_playback(cam_state: CamState, now: float | None = None):
    """记录该路视频实际收到帧的播放时间，不受检测/ReID耗时影响。"""
    ts = float(now if now is not None else time.time())
    if cam_state.playback_started_at <= 0:
        cam_state.playback_started_at = ts
    cam_state.playback_last_at = max(ts, cam_state.playback_started_at)


def _playback_seconds(cam_state: CamState) -> float:
    if cam_state.playback_started_at <= 0 or cam_state.playback_last_at <= 0:
        return 0.0
    return max(0.0, cam_state.playback_last_at - cam_state.playback_started_at)


def _public_live_det(d: dict) -> dict:
    """Compact current-frame detection for session snapshot / UI (no full trail)."""
    attrs = d.get("attrs") or {}
    trail = d.get("trail") or []
    tip = trail[-1] if trail else None
    public = {
        "objectType": d.get("objectType"),
        "globalId": d.get("globalId"),
        "localTrackId": d.get("localTrackId"),
        "trackletId": d.get("trackletId"),
        "label": d.get("label"),
        "bbox": d.get("bbox"),
        "score": d.get("score"),
        "displayName": d.get("displayName"),
        "reidPersonId": d.get("reidPersonId"),
        "plate": d.get("plate"),
        "identityKey": d.get("identityKey"),
        "plateScore": d.get("plateScore"),
        "visualScore": d.get("visualScore"),
        "fuseScore": d.get("fuseScore"),
        "speedKmh": d.get("speedKmh"),
        "assocMode": attrs.get("assocMode"),
        "trailTip": tip,
    }
    if d.get("lastSeenAt") is not None:
        public["lastSeenAt"] = d.get("lastSeenAt")
    return public


def _record_session_dets(cam_state: "CamState", items: list[dict], now: float | None = None):
    """按摄像头保留会话内目标；同一 local/global 持续更新而不是逐帧清空。"""
    with cam_state.state_lock:
        _record_session_dets_unlocked(cam_state, items, now)


def _record_session_dets_unlocked(cam_state: "CamState", items: list[dict], now: float | None = None):
    seen_at = float(now if now is not None else time.time())
    confirmed_kinds = {
        str(item.get("objectType") or "object")
        for item in (items or [])
        if not bool((item.get("attrs") or {}).get("detectOnly"))
    }
    if confirmed_kinds:
        stale_provisional = [
            key for key, row in cam_state.session_dets.items()
            if str(row.get("objectType") or "object") in confirmed_kinds
            and bool((row.get("attrs") or {}).get("detectOnly"))
        ]
        for key in stale_provisional:
            cam_state.session_dets.pop(key, None)
    for item in items or []:
        kind = str(item.get("objectType") or "object")
        local_id = item.get("localTrackId")
        global_id = item.get("globalId")
        # 目标从 local 晋升为 global 时，移除该 local 的旧临时项。
        if local_id is not None:
            local_key = f"{kind}:local:{local_id}"
            if global_id:
                cam_state.session_dets.pop(local_key, None)
        key = f"{kind}:global:{global_id}" if global_id else f"{kind}:local:{local_id}"
        row = dict(item)
        row["lastSeenAt"] = seen_at
        cam_state.session_dets[key] = row
    # 防止超长会话无限增长；保留最近更新的 200 个目标。
    if len(cam_state.session_dets) > 200:
        newest = sorted(
            cam_state.session_dets.items(),
            key=lambda pair: float(pair[1].get("lastSeenAt") or 0),
            reverse=True,
        )[:200]
        cam_state.session_dets = dict(reversed(newest))


def _session_det_snapshot(cam_state: "CamState") -> list[dict]:
    with cam_state.state_lock:
        return list(cam_state.session_dets.values())


def _session_det_count(cam_state: "CamState") -> int:
    with cam_state.state_lock:
        return len(cam_state.session_dets)


class MtmcSession:
    def __init__(self, session_id: str, cfg: MtmcConfig, associator, app=None):
        self.session_id = session_id
        self.cfg = cfg
        self.associator = associator
        self.app = app
        self.created_at = time.time()
        self.running = False
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._candidate_lock = threading.RLock()
        self._gid_alias: dict[str, str] = {}
        self._finalization_lock = threading.Lock()
        self._stop_finalized = False
        self._stop_finalizer_started = False
        self._stop_finalization_done = threading.Event()
        self.cams: dict[int, CamState] = {}
        self.events: list[dict] = []
        self.passes: list[dict] = []
        self._events_lock = threading.Lock()
        self.stats = {
            "frames": 0,
            "persons": 0,
            "vehicles": 0,
            "errors": 0,
        }
        self.runtime_status: dict[str, dict] = {}
        self.runtime_status_lock = threading.Lock()
        self.cross_events: list[dict] = []
        self._global_last_cam: dict[str, int] = {}
        self._global_last_seen_ts: dict[str, float] = {}
        self.source_mode: str = "camera"  # camera | upload
        self.kind: str = "detect" if cfg.detect_only else "mtmc"
        self.video_sources: dict[int, VirtualVideoSource] = {}
        self.upload_dir: str | None = None

    def cam_label(self, cam_id: int) -> str:
        vs = self.video_sources.get(int(cam_id))
        if vs:
            return vs.name or vs.original_filename or f"视频#{cam_id}"
        return f"Cam #{cam_id}"

    def to_dict(self) -> dict:
        with self.runtime_status_lock:
            runtime_snapshot = copy.deepcopy(self.runtime_status)
        return {
            "sessionId": self.session_id,
            "running": self.running,
            "kind": self.kind,
            "detectOnly": bool(self.cfg.detect_only),
            "sourceMode": self.source_mode,
            "cameraIds": list(self.cfg.camera_ids),
            "videoSources": [v.to_dict() for v in self.video_sources.values()],
            "enablePerson": self.cfg.enable_person,
            "enableVehicle": self.cfg.enable_vehicle,
            "localTrackBackend": self.cfg.local_track_backend,
            "enableCmc": self.cfg.enable_cmc,
            "persistEvents": self.cfg.persist_events,
            "mcbyteDecouple": self.cfg.mcbyte_decouple,
            "confirmThresh": self.cfg.confirm_thresh or self.cfg.appear_thresh,
            "candidateThresh": self.cfg.candidate_thresh or max(0.2, self.cfg.appear_thresh * 0.82),
            "useFaissGallery": self.cfg.use_faiss_gallery,
            "candidates": self.associator.list_candidates(),
            "crossEvents": self.cross_events[-50:],
            "createdAt": self.created_at,
            "stats": dict(self.stats),
            "runtime": runtime_snapshot,
            "globals": self.associator.snapshot(),
            "recentEvents": self.events[-50:],
            "recentPasses": self.passes[-50:],
            "cams": {
                str(cid): {
                    "frameSeq": st.frame_seq,
                    "streamFps": float(getattr(st, "stream_fps", 0) or 0),
                    "detectFps": float(getattr(st, "detect_fps", 0) or 0),
                    "detCount": _session_det_count(st),
                    "currentDetCount": len(st.last_dets),
                    "congestion": st.congestion,
                    "updatedAt": st.last_process_at,
                    "playbackStartedAt": st.playback_started_at or None,
                    "playbackSeconds": round(_playback_seconds(st), 1),
                    "lastError": getattr(st, "last_error", None),
                    "detections": [_public_live_det(d) for d in _session_det_snapshot(st)],
                }
                for cid, st in self.cams.items()
            },
        }


_sessions: dict[str, MtmcSession] = {}
_sessions_lock = threading.Lock()
_detect_fail_logged: set[str] = set()
_detect_model_locks: dict[str, threading.Lock] = {}
_detect_model_locks_guard = threading.Lock()


def get_session(session_id: str) -> MtmcSession | None:
    with _sessions_lock:
        return _sessions.get(session_id)


def list_sessions() -> list[dict]:
    with _sessions_lock:
        return [s.to_dict() for s in _sessions.values()]


def _finish_stopped_session_locked(session: MtmcSession) -> bool:
    if getattr(session, "_stop_finalized", False):
        return True
    for cam_state in list(session.cams.values()):
        _flush_camera_tracklets(session, cam_state)
    upload_dir = getattr(session, "upload_dir", None)
    if upload_dir and os.path.isdir(upload_dir):
        try:
            import shutil
            shutil.rmtree(upload_dir, ignore_errors=True)
        except Exception as e:  # noqa: BLE001
            log.debug("cleanup mtmc upload dir failed: %s", e)
    session._stop_finalized = True
    done = getattr(session, "_stop_finalization_done", None)
    if done is not None:
        done.set()
    return True


def _post_worker_finalizer(session: MtmcSession) -> None:
    """Daemon coordinator used when a session worker requests its own stop."""
    for worker in list(getattr(session, "_threads", ())):
        if worker is threading.current_thread():
            continue
        worker.join()
    with session._finalization_lock:
        if any(
            callable(getattr(worker, "is_alive", None)) and worker.is_alive()
            for worker in session._threads
        ):
            return
        _finish_stopped_session_locked(session)


def _schedule_post_worker_finalizer(session: MtmcSession) -> None:
    if getattr(session, "_stop_finalizer_started", False):
        return
    session._stop_finalizer_started = True
    threading.Thread(
        target=_post_worker_finalizer,
        args=(session,),
        name=f"mtmc-{session.session_id}-finalizer",
        daemon=True,
    ).start()


def stop_session(session_id: str) -> bool:
    with _sessions_lock:
        s = _sessions.get(session_id)
    if not s:
        return False
    finalization_lock = getattr(s, "_finalization_lock", None)
    if finalization_lock is None:
        finalization_lock = threading.Lock()
        s._finalization_lock = finalization_lock
        s._stop_finalized = False
    with finalization_lock:
        if getattr(s, "_stop_finalized", False):
            return True
        s._stop.set()
        s.running = False
        current = threading.current_thread()
        workers = list(getattr(s, "_threads", ()))
        # A worker cannot wait for itself. Schedule a coordinator before it
        # exits so no external retry is needed to clean uploads safely.
        if any(worker is current for worker in workers):
            _schedule_post_worker_finalizer(s)
            return True
        for worker in workers:
            worker.join(timeout=5.0)
        if any(callable(getattr(worker, "is_alive", None)) and worker.is_alive() for worker in workers):
            return False
        return _finish_stopped_session_locked(s)


def _resolve_cam_source(camera_row, upload_folder: str) -> str:
    st = (getattr(camera_row, "source_type", None) or "file").strip().lower()
    if st in ("rtsp", "device"):
        src = (getattr(camera_row, "source", None) or getattr(camera_row, "abs_path", None) or "").strip()
        if not src:
            raise ValueError(f"缺少 {st} 地址")
        return src
    abs_path = getattr(camera_row, "abs_path", None)
    if abs_path and os.path.isfile(abs_path):
        return abs_path
    from services.camera_stream import _resolve_source
    return _resolve_source(camera_row, upload_folder)


def resolve_overlay_source(session: MtmcSession | None, cam_id: int, upload_folder: str):
    """解析 MJPEG 拉流源：DB 摄像头或上传视频虚拟镜头。"""
    if session:
        vs = session.video_sources.get(int(cam_id))
        if vs is not None:
            if vs.source_type in ("rtsp", "device"):
                src = vs.source
            else:
                src = vs.abs_path
            return vs, src, vs.resolution or 960, vs.fps or 10
    from models import Camera
    cam = Camera.query.get(int(cam_id))
    if cam is None:
        return None, None, 640, 10
    try:
        source = _resolve_cam_source(cam, upload_folder)
    except (ValueError, FileNotFoundError, OSError):
        return cam, None, cam.resolution or 640, cam.fps or 10
    return cam, source, cam.resolution or 640, cam.fps or 10


def _auto_topology_edges(cam_ids: list[int]) -> list[dict]:
    """上传双视频模式：默认全互通、重叠视野 minTransitSec=0。"""
    edges: list[dict] = []
    for i, a in enumerate(cam_ids):
        for b in cam_ids[i + 1 :]:
            edges.append({
                "fromCameraId": int(a),
                "toCameraId": int(b),
                "minTransitSec": 0,
                "maxTransitSec": 120,
                "weight": 1,
                "edgeType": "overlap",
            })
            edges.append({
                "fromCameraId": int(b),
                "toCameraId": int(a),
                "minTransitSec": 0,
                "maxTransitSec": 120,
                "weight": 1,
                "edgeType": "overlap",
            })
    return edges


def load_database_topology() -> list[dict]:
    """Return enabled topology rows in the API's wire format."""
    from models.mtmc import CameraTopology

    return [
        row.to_dict()
        for row in CameraTopology.query.filter_by(status="0").order_by(CameraTopology.id.asc()).all()
    ]


def get_overlay_jpeg(session_id: str, camera_id: int) -> bytes | None:
    s = get_session(session_id)
    if not s:
        return None
    st = s.cams.get(int(camera_id))
    return st.overlay_jpeg if st else None


def get_raw_jpeg(session_id: str, camera_id: int) -> bytes | None:
    s = get_session(session_id)
    if not s:
        return None
    st = s.cams.get(int(camera_id))
    return st.raw_jpeg if st else None


def _decode_jpeg(data: bytes):
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _read_image_bgr(path: str):
    """读取图片为 BGR；Windows 下支持中文/特殊字符路径。"""
    if not path or not os.path.isfile(path):
        return None
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is not None:
            return img
    except OSError:
        pass
    return cv2.imread(path)


def _hub_stream_params(session: MtmcSession, camera_row) -> tuple[int, int]:
    """与 overlay 流一致的 hub 宽高/FPS，避免 cam_worker 与预览各用一套 hub。"""
    width = int(session.cfg.width or getattr(camera_row, "resolution", None) or 960)
    # MJPEG 在浏览器端解码开销明显高于 H.264。跨镜页面同时展示多路时，
    # 12 FPS 已足够保持监控预览流畅，也能避免原始 25/30 FPS 把 CPU 和带宽占满。
    fps = min(12, int(session.cfg.fps or getattr(camera_row, "fps", None) or 10))
    return width, fps


def _cam_worker_static_image(session: MtmcSession, cam_state: CamState, source_path: str):
    """静态图片：直接 cv2 读图循环检测，不依赖 ffmpeg MJPEG（避免 hub 断流后 worker 退出）。"""
    frame = _read_image_bgr(source_path)
    if frame is None:
        log.error("mtmc image load failed cam=%s path=%s", cam_state.camera_id, source_path)
        cam_state.last_error = f"图片读取失败：{os.path.basename(source_path)}"
        session.stats["errors"] += 1
        return
    if session.cfg.detect_only:
        frame = _resize_max_side(frame, 720)
    interval = 1.0 / max(0.2, float(session.cfg.sample_fps))
    seq = 0
    while not session._stop.is_set():
        try:
            _process_frame(session, cam_state, frame, {"seq": seq, "staticImage": True})
        except Exception as e:  # noqa: BLE001
            session.stats["errors"] += 1
            cam_state.last_error = str(e)
            log.warning("mtmc image process cam=%s: %s", cam_state.camera_id, e)
            try:
                _publish_overlay(cam_state, frame, cam_state.last_dets, cam_state.congestion)
            except Exception:  # noqa: BLE001
                pass
        seq += 1
        session._stop.wait(interval)


def _open_video_capture(path: str):
    """打开本地视频；中文路径失败时走 ASCII 副本。"""
    if not path or not os.path.isfile(path):
        return None
    cap = cv2.VideoCapture(path)
    if cap.isOpened():
        return cap
    cap.release()
    from services.camera_stream import ensure_ffmpeg_readable_path

    alt = ensure_ffmpeg_readable_path(path)
    if alt and alt != path:
        cap = cv2.VideoCapture(alt)
        if cap.isOpened():
            return cap
        cap.release()
    return None


def _resize_max_side(frame, max_side: int = 720):
    """预览/叠加缩小最长边，降低双路 JPEG 编码成本。"""
    if frame is None or max_side <= 0:
        return frame
    h, w = frame.shape[:2]
    m = max(int(h), int(w))
    if m <= max_side:
        return frame
    scale = float(max_side) / float(m)
    nw = max(2, int(w * scale) // 2 * 2)
    nh = max(2, int(h * scale) // 2 * 2)
    return cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)


def _cam_worker_local_file(session: MtmcSession, cam_state: CamState, source_path: str):
    """本地视频：OpenCV 循环读帧检测，不依赖 ffmpeg hub（竖屏/中文路径下 hub 经常无帧）。"""
    cap = _open_video_capture(source_path)
    if cap is None:
        log.error("mtmc video open failed cam=%s path=%s", cam_state.camera_id, source_path)
        cam_state.last_error = f"视频打开失败：{os.path.basename(source_path)}"
        session.stats["errors"] += 1
        return
    src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    if src_fps <= 1e-3 or src_fps > 120:
        src_fps = float(session.cfg.fps or 25)
    frame_interval = 1.0 / max(1.0, src_fps)
    sample_fps = max(0.2, float(session.cfg.sample_fps))
    sample_stride = max(1, int(round(src_fps / sample_fps)))
    detect_only = bool(session.cfg.detect_only)
    display_side = 720 if detect_only else 960
    seq = 0
    frame_idx = 0
    next_tick = time.monotonic()
    try:
        while not session._stop.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = cap.read()
                if not ok or frame is None:
                    cam_state.last_error = "视频无可用帧"
                    session.stats["errors"] += 1
                    break
                frame_idx = 0
                next_tick = time.monotonic()
            frame_idx += 1
            _mark_playback(cam_state)
            frame = _resize_max_side(frame, display_side)
            try:
                if frame_idx == 1 or (frame_idx % sample_stride == 0):
                    _process_frame(session, cam_state, frame, {"seq": seq, "localFile": True})
                else:
                    _publish_overlay(cam_state, frame, cam_state.last_dets, cam_state.congestion)
            except Exception as e:  # noqa: BLE001
                session.stats["errors"] += 1
                cam_state.last_error = str(e)
                log.warning("mtmc file process cam=%s: %s", cam_state.camera_id, e)
                try:
                    _publish_overlay(cam_state, frame, cam_state.last_dets, cam_state.congestion)
                except Exception:  # noqa: BLE001
                    pass
            seq += 1
            next_tick += frame_interval
            wait_s = next_tick - time.monotonic()
            if wait_s > 0:
                session._stop.wait(wait_s)
            elif wait_s < -0.04:
                # 检测/编码落后时丢帧，保持接近原视频节拍，避免一顿一顿追帧
                skip = min(int((-wait_s) / frame_interval), 24)
                for _ in range(skip):
                    if not cap.grab():
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        frame_idx = 0
                        break
                    frame_idx += 1
                next_tick = time.monotonic()
    finally:
        cap.release()


def _detect(model_path: str | None, frame, conf: float, classes: list[int] | None):
    if not model_path:
        return []
    path = model_path
    if not os.path.isfile(path):
        if path not in _detect_fail_logged:
            _detect_fail_logged.add(path)
            log.error("mtmc detect model not found: %s", path)
        return []
    try:
        from inference import _get_model, _yolo_predict_kwargs
        model = _get_model(path)
        kw = _yolo_predict_kwargs(conf=conf, classes=classes, imgsz=640)
        # 同一 YOLO 实例由多摄像头线程共享。Ultralytics predictor 内部状态
        # 不是可重入的，并发调用会出现随机的 "bn"/predictor 初始化异常。
        with _detect_model_locks_guard:
            predict_lock = _detect_model_locks.setdefault(os.path.abspath(path), threading.Lock())
        with predict_lock:
            r = model.predict(frame, **kw)[0]
        out = []
        if r.boxes is None:
            return out
        names = r.names or {}
        for b in r.boxes:
            cls_id = int(b.cls[0])
            out.append({
                "bbox": [round(float(v), 1) for v in b.xyxy[0].tolist()],
                "confidence": round(float(b.conf[0]), 4),
                "classId": cls_id,
                "className": str(names.get(cls_id, cls_id)),
            })
        return out
    except Exception as e:  # noqa: BLE001
        key = f"{path}:{type(e).__name__}:{e}"
        if key not in _detect_fail_logged:
            _detect_fail_logged.add(key)
            log.error("mtmc detect failed path=%s: %s", path, e)
        # 不再把模型初始化/推理故障伪装成“本帧没有目标”。上层 worker 会
        # 记录 errors 和 lastError，前端摄像头标题栏可直接显示真实原因。
        raise RuntimeError(f"检测模型执行失败: {e}") from e


_PV_CLASSES = [0, 1, 2, 3, 5, 7]


def _detect_person_vehicle(cfg: MtmcConfig, frame):
    """人员+车辆一次 YOLO，避免每帧两次推理。"""
    person_conf = min(float(cfg.conf), 0.18) if cfg.enable_person else float(cfg.conf)
    vehicle_conf = float(cfg.conf)
    if (
        cfg.enable_person and cfg.enable_vehicle
        and cfg.det_person_path and cfg.det_vehicle_path
        and cfg.det_person_path == cfg.det_vehicle_path
    ):
        raw = _detect(cfg.det_person_path, frame, min(person_conf, vehicle_conf), _PV_CLASSES)
        persons = [d for d in raw if int(d.get("classId", -1)) == 0]
        vehicles = [d for d in raw if int(d.get("classId", -1)) in (1, 2, 3, 5, 7)]
        persons = supplement_rider_person_dets(
            persons, vehicles, frame_w=frame.shape[1], frame_h=frame.shape[0],
        )
        return persons, vehicles
    persons = []
    vehicles = []
    if cfg.enable_person and cfg.det_person_path:
        persons = _detect(cfg.det_person_path, frame, person_conf, _PERSON_DET_CLASSES)
    if cfg.enable_vehicle and cfg.det_vehicle_path:
        vehicles = _detect(cfg.det_vehicle_path, frame, vehicle_conf, _VEHICLE_DET_CLASSES)
    if cfg.enable_person and vehicles:
        persons = supplement_rider_person_dets(
            persons, vehicles, frame_w=frame.shape[1], frame_h=frame.shape[0],
        )
    return persons, vehicles


def _detect_items_from_raw(raw_p: list[dict], raw_v: list[dict]) -> list[dict]:
    """纯检测框，不经过 Tracklet / 跟踪器。"""
    items = []
    for i, det in enumerate(raw_p or []):
        bbox = [float(v) for v in (det.get("bbox") or [])[:4]]
        if len(bbox) < 4:
            continue
        conf = float(det.get("confidence") or det.get("score") or 0)
        items.append({
            "objectType": "person",
            "globalId": None,
            "localTrackId": i + 1,
            "bbox": bbox,
            "trail": [],
            "score": conf,
            "label": f"人 {conf:.2f}",
            "attrs": {"className": det.get("className") or "person", "detectOnly": True},
        })
    for i, det in enumerate(raw_v or []):
        bbox = [float(v) for v in (det.get("bbox") or [])[:4]]
        if len(bbox) < 4:
            continue
        conf = float(det.get("confidence") or det.get("score") or 0)
        cls = str(det.get("className") or "车")
        items.append({
            "objectType": "vehicle",
            "globalId": None,
            "localTrackId": i + 1,
            "bbox": bbox,
            "trail": [],
            "score": conf,
            "label": f"{cls} {conf:.2f}",
            "attrs": {"className": cls, "detectOnly": True},
        })
    return items


def _tracks_or_raw(tracker, raw: list[dict], frame, *, id_base: int = 800001):
    """跟踪器空结果时仍用原始检测框出叠加，避免画面无框。"""
    from services.mtmc_local_track import Tracklet

    tracks = tracker.update(raw, frame=frame) if tracker is not None else []
    if tracks or not raw:
        return list(tracks)
    extras = []
    for i, det in enumerate(raw):
        bbox = [float(v) for v in (det.get("bbox") or [])[:4]]
        if len(bbox) < 4:
            continue
        cx, cy = (bbox[0] + bbox[2]) * 0.5, (bbox[1] + bbox[3]) * 0.5
        extras.append(
            Tracklet(
                track_id=id_base + i,
                bbox=bbox,
                class_name=str(det.get("className") or "object"),
                conf=float(det.get("confidence") or 0),
                is_new=True,
                trail=[(cx, cy)],
                attrs={"rawFallback": True},
            )
        )
    return extras


def _crop(img, bbox, pad=0.05):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox]
    bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
    px, py = bw * pad, bh * pad
    x1 = max(0, int(x1 - px))
    y1 = max(0, int(y1 - py))
    x2 = min(w, int(x2 + px))
    y2 = min(h, int(y2 + py))
    if x2 <= x1 or y2 <= y1:
        return None
    return img[y1:y2, x1:x2].copy()


def _gallery_model_keys(cfg: MtmcConfig, meta_backend: str | None = None) -> list[str]:
    keys: list[str] = []
    if cfg.gallery_model_key:
        keys.append(cfg.gallery_model_key)
    backend = (meta_backend or "").lower()
    if cfg.strong_reid_root or "strong" in backend:
        keys.extend(["osnet-x1-0", "clip-reid-person", "fastreid-osnet"])
    if cfg.youtu_root or "youtu" in backend:
        keys.append("opencv-person-reid-youtu")
    if not keys:
        keys.append("opencv-person-reid-youtu")
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def normalize_fuse_weight_strong(value, default: float = 0.65) -> float:
    """Preserve an explicit zero while keeping the public configuration bounded."""
    raw = default if value is None else value
    try:
        parsed = float(raw)
        if not np.isfinite(parsed):
            return float(default)
        return float(np.clip(parsed, 0.0, 1.0))
    except (TypeError, ValueError):
        return float(default)


def _reid_score_weights(cfg: MtmcConfig, embeddings: dict[str, np.ndarray]) -> dict[str, float]:
    """Map the configured Strong/Youtu split onto the spaces actually available."""
    strong_keys = [key for key in embeddings if key != "opencv-person-reid-youtu"]
    youtu_keys = [key for key in embeddings if key == "opencv-person-reid-youtu"]
    weights: dict[str, float] = {}
    if len(embeddings) == 1:
        return {next(iter(embeddings)): 1.0}
    strong_weight = normalize_fuse_weight_strong(cfg.fuse_weight_strong)
    if strong_keys:
        per_strong = strong_weight / len(strong_keys)
        weights.update({key: per_strong for key in strong_keys})
    if youtu_keys:
        per_youtu = (1.0 - strong_weight) / len(youtu_keys)
        weights.update({key: per_youtu for key in youtu_keys})
    return weights


def _match_gallery(
    embeddings: dict[str, np.ndarray],
    threshold: float,
    *,
    score_weights: dict[str, float] | None = None,
    model_versions_by_space: dict[str, str | None] | None = None,
):
    errors_by_model_key: dict[str, list[str]] = {}
    try:
        from services.reid_gallery import match_embedding, match_embedding_faiss
    except Exception as exc:  # noqa: BLE001
        return {
            "matched": False, "name": "未知", "personId": None, "score": 0.0,
            "modelKey": None, "ready": False, "degraded": True,
            "errorsByModelKey": {"runtime": [str(exc)]},
        }
    from services.strong_reid import fuse_similarity_scores

    rows_by_person: dict[tuple, dict] = {}
    for key, emb in embeddings.items():
        version = (model_versions_by_space or {}).get(key)
        try:
            if version is None:
                row = match_embedding_faiss(emb, key, threshold=threshold)
            else:
                row = match_embedding_faiss(emb, key, threshold=threshold, model_version=version)
        except Exception as faiss_error:  # noqa: BLE001
            errors_by_model_key.setdefault(key, []).append(str(faiss_error))
            try:
                if version is None:
                    row = match_embedding(emb, key, threshold=threshold)
                else:
                    row = match_embedding(emb, key, threshold=threshold, model_version=version)
            except Exception as gallery_error:  # noqa: BLE001
                errors_by_model_key.setdefault(key, []).append(str(gallery_error))
                continue
        person_key = (
            row.get("candidatePersonId", row.get("personId")),
            row.get("candidateFacePersonId", row.get("facePersonId")),
            row.get("candidateName", row.get("name")),
        )
        if person_key[0] is None and person_key[1] is None:
            continue
        grouped = rows_by_person.setdefault(person_key, {"row": row, "scores": {}})
        grouped["scores"][key] = float(row.get("score") or 0.0)
    best = {"matched": False, "name": "未知", "personId": None, "score": 0.0, "modelKey": None}
    for person_key, grouped in rows_by_person.items():
        scores = grouped["scores"]
        fused = fuse_similarity_scores(scores, score_weights or {key: 1.0 for key in scores})
        if fused is None or fused < float(threshold) or fused <= float(best.get("score") or 0):
            continue
        row = grouped["row"]
        best = {
            **row,
            "personId": person_key[0],
            "facePersonId": person_key[1],
            "name": person_key[2] or "未知",
            "score": float(fused),
            "matched": True,
            "modelKey": max(scores, key=scores.get),
            "scoreByModelKey": dict(scores),
        }
    failed_spaces = sum(len(errors) >= 2 for errors in errors_by_model_key.values())
    best.update({
        "ready": len(embeddings) > failed_spaces,
        "degraded": bool(errors_by_model_key),
        "errorsByModelKey": errors_by_model_key,
    })
    return best


def _runtime_status_lock(session):
    lock = getattr(session, "runtime_status_lock", None)
    if lock is None:
        lock = threading.Lock()
        session.runtime_status_lock = lock
    return lock


def _record_gallery_failure(
    session, meta: dict, error: Exception, *, camera_id=None, errors_by_space=None, detail: dict | None = None,
) -> None:
    detail = {"ready": False, "degraded": True, "error": str(error), **(detail or {})}
    if errors_by_space:
        detail["errorsByModelKey"] = copy.deepcopy(errors_by_space)
    meta["gallery"] = detail
    with _runtime_status_lock(session):
        runtime = getattr(session, "runtime_status", None)
        if runtime is None:
            runtime = {}
            session.runtime_status = runtime
        previous = dict(runtime.get("gallery") or {})
        errors_by_camera = dict(previous.get("errorsByCamera") or {})
        errors_by_runtime_space = copy.deepcopy(previous.get("errorsBySpace") or {})
        if camera_id is not None:
            errors_by_camera[str(camera_id)] = str(error)
            if errors_by_space:
                errors_by_runtime_space[str(camera_id)] = copy.deepcopy(errors_by_space)
        runtime["gallery"] = {
            **detail,
            "errorCount": int(previous.get("errorCount") or 0) + 1,
            **({"errorsByCamera": errors_by_camera} if errors_by_camera else {}),
            **({"errorsBySpace": errors_by_runtime_space} if errors_by_runtime_space else {}),
        }
    log.warning("mtmc_gallery_degraded error=%s", error)


def _record_gallery_ready(session, meta: dict, *, camera_id=None) -> None:
    detail = {"ready": True, "degraded": False, "error": None}
    meta["gallery"] = detail
    with _runtime_status_lock(session):
        runtime = getattr(session, "runtime_status", None)
        if runtime is None:
            runtime = {}
            session.runtime_status = runtime
        previous = dict(runtime.get("gallery") or {})
        errors_by_camera = dict(previous.get("errorsByCamera") or {})
        errors_by_runtime_space = copy.deepcopy(previous.get("errorsBySpace") or {})
        if camera_id is not None:
            errors_by_camera.pop(str(camera_id), None)
            errors_by_runtime_space.pop(str(camera_id), None)
        error_count = int(previous.get("errorCount") or 0)
        degraded = bool(errors_by_camera)
        runtime["gallery"] = {
            "ready": True,
            "degraded": degraded,
            "error": previous.get("error") if degraded else None,
            "errorCount": error_count,
            **({"errorsByCamera": errors_by_camera} if errors_by_camera else {}),
            **({"errorsBySpace": errors_by_runtime_space} if errors_by_runtime_space else {}),
        }


def _speed_from_trail(trail, meters_per_pixel: float, fps: float) -> float | None:
    if not trail or len(trail) < 2 or meters_per_pixel <= 0 or fps <= 0:
        return None
    (x0, y0), (x1, y1) = trail[-2], trail[-1]
    dist_px = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    mps = dist_px * meters_per_pixel * fps
    return round(mps * 3.6, 1)


_hud_font_cache: dict[int, Any] = {}


def _hud_font(size: int = 18):
    """加载支持中文的 TrueType 字体（cv2.putText 无法渲染 CJK）。"""
    if size in _hud_font_cache:
        return _hud_font_cache[size]
    from PIL import ImageFont
    win = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        os.path.join(win, "Fonts", "msyh.ttc"),
        os.path.join(win, "Fonts", "msyhbd.ttc"),
        os.path.join(win, "Fonts", "simhei.ttf"),
        os.path.join(win, "Fonts", "simsun.ttc"),
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    font = None
    for path in candidates:
        if os.path.isfile(path):
            try:
                font = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default()
    _hud_font_cache[size] = font
    return font


def _draw_label_pil(img_bgr, text: str, origin, *, color=(0, 200, 80), font_size=18):
    """在 BGR 图上用 PIL 绘制中英文标签。"""
    if not text:
        return img_bgr
    from PIL import Image, ImageDraw
    font = _hud_font(font_size)
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    x, y = int(origin[0]), int(origin[1])
    bbox = draw.textbbox((x, y), text, font=font)
    pad = 3
    # color 入参为 BGR，转 RGB 填充底
    fill = (max(0, color[2] - 40), max(0, color[1] - 40), max(0, color[0] - 40))
    draw.rectangle(
        [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
        fill=fill,
    )
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def _draw_overlay(frame, items: list[dict], congestion: dict | None = None, jpeg_quality: int | None = None):
    """绘制检测框/轨迹/中文标签。PIL 只转一次，保证实时叠加不卡。"""
    vis = frame.copy()
    labels = []
    for it in items:
        bbox = it.get("bbox") or []
        if len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox]
        ot = it.get("objectType") or "person"
        gid = it.get("globalId") or str(it.get("localTrackId") or "?")
        color = _color_for(str(gid), _PERSON_COLORS if ot == "person" else _VEHICLE_COLORS)
        trail = it.get("trail") or []
        if len(trail) >= 2:
            pts = np.array([[int(p[0]), int(p[1])] for p in trail], dtype=np.int32)
            cv2.polylines(vis, [pts], False, color, 2, lineType=cv2.LINE_AA)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
        label = it.get("label") or gid
        ty = y1 - 22 if y1 >= 24 else y1 + 4
        labels.append((str(label), (x1, ty), color, 16))
    n_p = sum(1 for it in items if it.get("objectType") == "person")
    n_v = sum(1 for it in items if it.get("objectType") == "vehicle")
    hud = f"检出 人:{n_p} 车:{n_v}"
    if congestion:
        hud += f"  拥堵:{congestion.get('label', '')}"
    labels.append((hud, (8, 8), (0, 220, 255), 18))
    if labels:
        from PIL import Image, ImageDraw
        pil = Image.fromarray(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil)
        for text, origin, color, font_size in labels:
            font = _hud_font(font_size)
            x, y = int(origin[0]), int(origin[1])
            bbox = draw.textbbox((x, y), text, font=font)
            pad = 3
            fill = (max(0, color[2] - 40), max(0, color[1] - 40), max(0, color[0] - 40))
            draw.rectangle(
                [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
                fill=fill,
            )
            draw.text((x, y), text, font=font, fill=(255, 255, 255))
        vis = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
    quality = 70 if jpeg_quality is None else int(jpeg_quality)
    ok, buf = cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buf.tobytes() if ok else None


def _publish_overlay(cam_state: CamState, frame, items, congestion=None):
    fast = bool(getattr(cam_state, "fast_preview", False))
    quality = 52 if fast else 70
    preview = _resize_max_side(frame, 720 if fast else 960)
    ok_raw, raw_buf = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if ok_raw:
        cam_state.raw_jpeg = raw_buf.tobytes()
    jpeg = _draw_overlay(preview, items or [], congestion, jpeg_quality=quality)
    if jpeg:
        cam_state.overlay_jpeg = jpeg
    elif ok_raw:
        # 画框失败时至少推原帧，避免预览长期空白
        cam_state.overlay_jpeg = cam_state.raw_jpeg
    if ok_raw or jpeg:
        cam_state.frame_seq += 1
        cam_state.stream_fps = _rolling_fps(cam_state._publish_times)
    cam_state.last_dets = list(items or [])


def _persist_event(app, row: dict):
    if app is None:
        return
    try:
        with app.app_context():
            from extensions import db
            from models.mtmc import MtmcTrackEvent
            ev = MtmcTrackEvent(
                session_id=row["sessionId"],
                camera_id=row["cameraId"],
                object_type=row["objectType"],
                global_id=row["globalId"],
                local_track_id=row.get("localTrackId"),
                reid_person_id=row.get("reidPersonId"),
                display_name=row.get("displayName"),
                plate=row.get("plate"),
                identity_key=row.get("identityKey"),
                score=float(row.get("score") or 0),
                speed_kmh=row.get("speedKmh"),
                congestion=(row.get("congestion") or {}).get("label") if isinstance(row.get("congestion"), dict) else row.get("congestion"),
                bbox_json=json.dumps(row.get("bbox") or []),
                trail_json=json.dumps(row.get("trail") or []),
                attrs_json=json.dumps(row.get("attrs") or {}),
            )
            db.session.add(ev)
            db.session.commit()
    except Exception as e:  # noqa: BLE001
        log.debug("persist event failed: %s", e)


def _persist_pass(app, row: dict):
    if app is None:
        return
    try:
        with app.app_context():
            from extensions import db
            from models.mtmc import MtmcVehiclePass
            p = MtmcVehiclePass(
                session_id=row["sessionId"],
                camera_id=row["cameraId"],
                global_id=row["globalId"],
                identity_key=row.get("identityKey"),
                plate=row.get("plate"),
                plate_score=row.get("plateScore"),
                visual_score=row.get("visualScore"),
                fuse_score=row.get("fuseScore"),
                speed_kmh=row.get("speedKmh"),
                congestion=(row.get("congestion") or {}).get("label") if isinstance(row.get("congestion"), dict) else row.get("congestion"),
                local_track_id=row.get("localTrackId"),
            )
            db.session.add(p)
            db.session.commit()
    except Exception as e:  # noqa: BLE001
        log.debug("persist pass failed: %s", e)


def _get_tracklet_builder(
    cam_state: CamState,
    *,
    session_id: str,
    object_type: str,
    local_track_id: int,
    now: float,
):
    from services.mtmc_tracklet import TrackletBuilder

    pool = cam_state.person_builders if object_type == "person" else cam_state.vehicle_builders
    builder = pool.get(int(local_track_id))
    if builder is None:
        builder = TrackletBuilder.create(
            session_id=session_id,
            camera_id=cam_state.camera_id,
            object_type=object_type,
            local_track_id=int(local_track_id),
            now=now,
        )
        pool[int(local_track_id)] = builder
    return builder


def _maybe_cross_camera_event(session: MtmcSession, builder, g, now: float, *, evidence=None):
    """P2：同一 Global 跨相机切换时写入轻量跨镜事件。"""
    if not session.cfg.persist_events:
        return
    gid = g.global_id
    cur_cam = int(builder.camera_id)
    prev_cam = session._global_last_cam.get(gid)
    prev_ts = session._global_last_seen_ts.get(gid, now)
    decision = evidence.decision if evidence else None
    if prev_cam is not None and int(prev_cam) != cur_cam:
        transit = float(now - prev_ts)
        row = {
            "sessionId": session.session_id,
            "globalId": gid,
            "objectType": builder.object_type,
            "fromCameraId": int(prev_cam),
            "toCameraId": cur_cam,
            "transitSec": round(transit, 2),
            "displayName": g.display_name,
            "plate": g.plate,
            "decision": decision,
            "eventTime": now,
        }
        session.cross_events.append(row)
        if len(session.cross_events) > 200:
            session.cross_events = session.cross_events[-200:]
        from services.mtmc_persist import persist_cross_camera_event

        persist_cross_camera_event(
            session.app,
            session_id=session.session_id,
            global_id=gid,
            object_type=builder.object_type,
            from_camera_id=int(prev_cam),
            to_camera_id=cur_cam,
            transit_sec=transit,
            display_name=g.display_name,
            plate=g.plate,
            decision=decision,
            attrs={"trackletId": builder.tracklet_id},
            event_time=None,
        )
    session._global_last_cam[gid] = cur_cam
    session._global_last_seen_ts[gid] = now


def _canonical_gid_locked(session: MtmcSession, global_id: str | None) -> str | None:
    gid = global_id
    seen: set[str] = set()
    while gid and gid not in seen:
        seen.add(gid)
        next_gid = session._gid_alias.get(gid)
        if next_gid is None or next_gid == gid:
            break
        gid = next_gid
    return gid


def _canonical_association_locked(session: MtmcSession, builder, g, prev_global_id, evidence):
    gid = _canonical_gid_locked(session, g.global_id)
    canonical_track = session.associator.get_track(gid) if gid else None
    if canonical_track is not None:
        g = canonical_track
    builder.assigned_global_id = gid
    prev_global_id = _canonical_gid_locked(session, prev_global_id)
    if evidence is not None:
        evidence = replace(
            evidence,
            target_global_id=_canonical_gid_locked(session, evidence.target_global_id) or g.global_id,
            source_global_id=_canonical_gid_locked(session, evidence.source_global_id),
            candidate_global_id=_canonical_gid_locked(session, evidence.candidate_global_id),
        )
        if evidence.candidate_global_id == evidence.target_global_id:
            evidence = replace(
                evidence,
                decision="long_term",
                candidate_global_id=None,
            )
    return g, prev_global_id, evidence


def _record_association(
    session: MtmcSession,
    builder,
    g,
    *,
    prev_global_id: str | None,
    persist_tracklet_row: bool = False,
    evidence=None,
):
    from services.mtmc_persist import (
        persist_association_edge,
        persist_candidate_pair,
        persist_global_identity,
        persist_tracklet,
    )

    with session._candidate_lock:
        g, prev_global_id, evidence = _canonical_association_locked(
            session, builder, g, prev_global_id, evidence,
        )
        decision = evidence.decision if evidence else "NEW"
        if prev_global_id and prev_global_id != g.global_id:
            decision = "REFINE"
        if session.cfg.persist_events:
            persist_global_identity(session.app, g)
            persist_association_edge(
                session.app,
                session_id=session.session_id,
                tracklet_id=builder.tracklet_id,
                object_type=builder.object_type,
                decision=decision,
                target_global_id=g.global_id,
                source_global_id=prev_global_id,
                scores=evidence.to_scores() if evidence else {},
                evidence=evidence.to_dict() if evidence else {},
                policy_version=evidence.policy_version if evidence else "mtmc_v2",
            )
            if evidence and evidence.decision == "candidate" and evidence.candidate_global_id:
                persist_candidate_pair(
                    session.app,
                    session_id=session.session_id,
                    global_id=g.global_id,
                    candidate_global_id=evidence.candidate_global_id,
                    object_type=builder.object_type,
                    camera_id=builder.camera_id,
                    tracklet_id=builder.tracklet_id,
                    final_score=evidence.final_score,
                    reid_score=evidence.reid_score,
                    evidence=evidence.to_dict(),
                )
            if persist_tracklet_row:
                persist_tracklet(session.app, builder, global_id=g.global_id)
        _maybe_cross_camera_event(session, builder, g, time.time(), evidence=evidence)
        return g


def _associate_tracklet(
    session: MtmcSession,
    builder,
    *,
    embedding,
    embedding_spaces=None,
    association_model_key=None,
    score_weights=None,
    reid_person_id=None,
    display_name=None,
    identity_key=None,
    plate=None,
    visual_key=None,
    vehicle_class=None,
    color_sig=None,
    exclude_gids: set,
    now: float,
    force: bool = False,
):
    prev_gid = builder.assigned_global_id
    ex = set(exclude_gids or ())
    # 仅当粘性绑定仍指向本 local、且未被同帧其它目标占用时，才复用缓存 GID
    if prev_gid and not force and prev_gid not in ex:
        sticky = session.associator.peek_sticky(
            object_type=builder.object_type,
            camera_id=builder.camera_id,
            local_track_id=int(builder.local_track_id),
            now=now,
        )
        if sticky == prev_gid:
            g = session.associator.get_track(prev_gid)
            if g is not None:
                return g
        # 同镜 takeover 后 _local_bind 已清、但 TrackletBuilder 仍缓存旧 GID → 必须重关联
        builder.assigned_global_id = None
        prev_gid = None
    elif prev_gid and (force or prev_gid in ex):
        builder.assigned_global_id = None
        prev_gid = None

    best_observation = builder.best_observation()
    result = session.associator.associate_batch([{
        "object_type": builder.object_type,
        "camera_id": builder.camera_id,
        "embedding": embedding,
        "embedding_spaces": embedding_spaces,
        "association_model_key": association_model_key,
        "score_weights": score_weights,
        "reid_person_id": reid_person_id,
        "identity_key": identity_key,
        "plate": plate,
        "visual_key": visual_key,
        "vehicle_class": vehicle_class,
        "color_sig": color_sig,
        "display_name": display_name,
        "local_track_id": int(builder.local_track_id),
        "exclude_gids": ex,
        "now": now,
        "force_long_term": force,
        "observation_quality": (best_observation.quality if best_observation is not None else None),
    }])[0]
    g = getattr(result, "global_track", result)
    builder.assigned_global_id = g.global_id
    g = _record_association(
        session, builder, g, prev_global_id=prev_gid, persist_tracklet_row=False,
        evidence=getattr(result, "evidence", None),
    )
    return g


def _associate_prepared_tracklets(session, prepared: list[dict]) -> dict:
    """Submit all prepared same-frame associations as one batch and map results."""
    if not prepared:
        return {}
    results = session.associator.associate_batch([
        dict(item["association"]) for item in prepared
    ])
    assigned = {}
    for item, result in zip(prepared, results):
        global_track = getattr(result, "global_track", result)
        builder = item.get("builder")
        if builder is not None:
            builder.assigned_global_id = global_track.global_id
        item["evidence"] = getattr(result, "evidence", None)
        assigned[item["key"]] = global_track
    return assigned


class _FrameAssociationCollector:
    """Collect non-sticky same-frame observations before mutating MTMC state."""

    def __init__(self, session, now: float):
        self.session = session
        self.now = now
        self.pending: dict[str, list[dict]] = {"person": [], "vehicle": []}

    def enqueue(self, builder, associate_kwargs: dict) -> None:
        best = builder.best_observation()
        self.pending[builder.object_type].append({
            "key": int(builder.local_track_id),
            "builder": builder,
            "association": {
                "object_type": builder.object_type,
                "camera_id": builder.camera_id,
                "local_track_id": int(builder.local_track_id),
                "exclude_gids": set(),
                "now": self.now,
                "observation_quality": best.quality if best is not None else None,
                **associate_kwargs,
            },
        })

    def flush(self, object_type: str, items: list[dict]) -> None:
        prepared = self.pending[object_type]
        self.pending[object_type] = []
        assigned = _associate_prepared_tracklets(self.session, prepared)
        for record in prepared:
            builder = record["builder"]
            g = assigned.get(record["key"])
            if g is None:
                continue
            g = _record_association(
                self.session, builder, g, prev_global_id=None,
                persist_tracklet_row=False, evidence=record.get("evidence"),
            )
            resolved_item = None
            for item in items:
                if (
                    item.get("objectType") == object_type
                    and int(item.get("localTrackId") or -1) == int(builder.local_track_id)
                ):
                    item["globalId"] = g.global_id
                    item.setdefault("attrs", {})["assocMode"] = g.last_assoc_mode
                    if object_type == "person":
                        item["reidPersonId"] = g.reid_person_id
                        item["displayName"] = g.display_name or item.get("displayName") or "匿名"
                        item["label"] = f"{g.global_id}|{item['displayName']}"
                    else:
                        item["plate"] = g.plate or item.get("plate")
                        item["identityKey"] = g.identity_key or item.get("identityKey")
                        item["label"] = f"{g.global_id}|{item.get('plate') or '无牌'}"
                    resolved_item = item
                    break
            if resolved_item is not None:
                row = {
                    "sessionId": self.session.session_id,
                    "cameraId": builder.camera_id,
                    **resolved_item,
                    "congestion": resolved_item.get("congestion"),
                }
                with self.session._events_lock:
                    self.session.events.append({**row, "ts": self.now})
                    if len(self.session.events) > 500:
                        self.session.events = self.session.events[-400:]
                cam_state = self.session.cams.get(int(builder.camera_id))
                if (
                    cam_state is not None
                    and self.session.cfg.persist_events
                    and self.now - float(cam_state.last_persist_at or 0) >= 1.0
                ):
                    _persist_event(self.session.app, row)
                    cam_state.last_persist_at = self.now
                if object_type == "vehicle" and self.session.cfg.persist_events:
                    pass_key = f"{g.global_id}:{builder.camera_id}"
                    seen = getattr(self.session, "_pass_seen", None)
                    if seen is None:
                        self.session._pass_seen = set()
                        seen = self.session._pass_seen
                    if pass_key not in seen:
                        seen.add(pass_key)
                        pass_row = {
                            "sessionId": self.session.session_id,
                            "cameraId": builder.camera_id,
                            "globalId": g.global_id,
                            "identityKey": resolved_item.get("identityKey"),
                            "plate": resolved_item.get("plate"),
                            "plateScore": resolved_item.get("plateScore"),
                            "visualScore": resolved_item.get("visualScore"),
                            "fuseScore": resolved_item.get("fuseScore"),
                            "speedKmh": resolved_item.get("speedKmh"),
                            "congestion": resolved_item.get("congestion"),
                            "localTrackId": builder.local_track_id,
                        }
                        with self.session._events_lock:
                            self.session.passes.append({**pass_row, "ts": self.now})
                            if len(self.session.passes) > 300:
                                self.session.passes = self.session.passes[-200:]
                        _persist_pass(self.session.app, pass_row)


def _resolve_overlay_global(
    session: MtmcSession,
    builder,
    *,
    sticky_gid: str | None,
    claimed: set,
    now: float,
    associate_kwargs: dict,
    collector=None,
):
    """同帧 Global 独占：仅信任未占用的 sticky；否则带 exclude_gids 重关联。

    同镜 takeover 只会清 associator._local_bind，不会清 TrackletBuilder.assigned_global_id。
    若仍走「缓存 GID」捷径，同一帧会出现多个框共用一个 V######。
    """
    if sticky_gid and sticky_gid not in claimed:
        g = session.associator.get_track(sticky_gid)
        if g is not None:
            builder.assigned_global_id = g.global_id
            return g
    if not builder.ready_for_tentative(min_quality=0.08):
        return None
    # 粘性丢失或已被同帧占用 → 丢弃可能过期的 assigned，强制走 associate
    if sticky_gid is None or sticky_gid in claimed:
        builder.assigned_global_id = None
    elif builder.assigned_global_id and builder.assigned_global_id in claimed:
        builder.assigned_global_id = None
    if collector is not None:
        collector.enqueue(builder, associate_kwargs)
        return None
    return _associate_tracklet(
        session,
        builder,
        exclude_gids=claimed,
        now=now,
        **associate_kwargs,
    )


def _finalize_tracklet_locked(session: MtmcSession, builder, *, exclude_gids: set | None = None):
    """局部轨迹结束：聚合 embedding 后做最终关联并落库 tracklet。"""
    spaces = builder.aggregate_embedding_spaces()
    association_model_key = None
    for observation in reversed(builder.observations):
        association_model_key = (observation.meta or {}).get("reidModelKey")
        if association_model_key:
            break
    emb = builder.aggregate_embedding(association_model_key)
    identity = builder.aggregate_identity()
    if builder.object_type == "vehicle":
        from services.vehicle_reid_feat import aggregate_vehicle_plate_votes, fuse_plate_visual

        plate, plate_score = aggregate_vehicle_plate_votes(
            (observation.plate, observation.plate_score)
            for observation in builder.observations
        )
        identity.update(fuse_plate_visual(
            plate=plate, plate_score=plate_score, emb_a=emb,
        ))
    prev_gid = builder.assigned_global_id
    ex = set(exclude_gids or ())
    kwargs = dict(
        embedding=emb,
        embedding_spaces=spaces,
        association_model_key=association_model_key,
        exclude_gids=ex,
        now=builder.end_ts or time.time(),
        force=True,
    )
    if builder.object_type == "person":
        g = _associate_tracklet(
            session,
            builder,
            reid_person_id=None,
            display_name=None,
            **kwargs,
        )
    else:
        g = _associate_tracklet(
            session,
            builder,
            identity_key=identity.get("identityKey"),
            plate=identity.get("plate"),
            visual_key=identity.get("visualKey"),
            **kwargs,
        )
    if session.cfg.persist_events:
        from services.mtmc_persist import persist_tracklet
        persist_tracklet(session.app, builder, global_id=g.global_id)
    return g


def _finalize_tracklet(session: MtmcSession, builder, *, exclude_gids: set | None = None):
    """Serialize final association and tracklet persistence with promotion."""
    with session._candidate_lock:
        return _finalize_tracklet_locked(session, builder, exclude_gids=exclude_gids)


def _finalize_removed_builders(
    session: MtmcSession,
    cam_state: CamState,
    object_type: str,
    removed_local_ids: set[int] | None = None,
    *,
    now: float | None = None,
    timeout_sec: float | None = None,
):
    pool = cam_state.person_builders if object_type == "person" else cam_state.vehicle_builders
    stale = {int(tid) for tid in (removed_local_ids or set())}
    if now is not None and timeout_sec is not None:
        stale.update(
            int(tid) for tid, builder in pool.items()
            if float(now) - float(builder.end_ts or now) >= float(timeout_sec)
        )
    finalized: set[int] = set()
    for tid in stale:
        builder = pool.pop(tid, None)
        if builder is None or not builder.observations:
            continue
        try:
            _finalize_tracklet(session, builder, exclude_gids=set())
            finalized.add(int(tid))
        except Exception as e:  # noqa: BLE001
            log.debug("finalize tracklet failed cam=%s %s#%s: %s", cam_state.camera_id, object_type, tid, e)
    return finalized


def _release_finalized_locals(session: MtmcSession, cam_state: CamState, object_type: str, local_ids: set[int]) -> None:
    if local_ids:
        session.associator.release_local(object_type, cam_state.camera_id, local_ids)


def _flush_camera_tracklets(session: MtmcSession, cam_state: CamState) -> None:
    """Finalize a camera tail once, serialized with frame processing and shutdown."""
    with cam_state.lifecycle_lock:
        if cam_state.builders_flushed:
            return
        for object_type, pool in (
            ("person", cam_state.person_builders),
            ("vehicle", cam_state.vehicle_builders),
        ):
            finalized = _finalize_removed_builders(
                session, cam_state, object_type, set(pool),
            )
            _release_finalized_locals(session, cam_state, object_type, finalized)
        cam_state.builders_flushed = True


def _pop_removed_track_ids(tracker) -> set[int]:
    """Consume explicit tracker expiry notifications without changing update callers."""
    pop_removed = getattr(tracker, "pop_removed_track_ids", None)
    if not callable(pop_removed):
        return set()
    return {int(track_id) for track_id in pop_removed()}


def _reid_budget_for(cfg: MtmcConfig, object_type: str) -> int:
    configured = getattr(cfg, f"{object_type}_reid_budget", None)
    return max(0, int(cfg.reid_budget if configured is None else configured))


def _track_view_token(track) -> str | None:
    attrs = getattr(track, "attrs", None) or {}
    return attrs.get("viewToken") or attrs.get("view_token")


def _sort_tracks_for_reid(
    session, cam_state: CamState, object_type: str, tracks, *, frame_h: int = 0, frame_w: int = 0,
):
    """Spend each per-class budget on fresh, expiring, candidate, then better views."""
    pool = cam_state.person_builders if object_type == "person" else cam_state.vehicle_builders
    candidate_ids = {
        int(row.get("localTrackId"))
        for row in session.associator.list_candidates()
        if row.get("objectType") == object_type and int(row.get("cameraId") or -1) == cam_state.camera_id
        and row.get("localTrackId") is not None
    }
    from services.mtmc_tracklet import frame_quality

    def key(track):
        builder = pool.get(int(track.track_id))
        has_embedding = bool(builder and any(
            observation.embedding is not None or observation.embedding_spaces
            for observation in builder.observations
        ))
        unsampled_new = not has_embedding
        near_removal = int(getattr(track, "time_since_update", 0) or 0) >= max(1, int(session.cfg.local_track_max_age) - 1)
        candidate = int(track.track_id) in candidate_ids
        bbox = getattr(track, "bbox", [])
        conf = float(getattr(track, "conf", 0.0) or 0.0)
        quality = frame_quality(bbox, conf, frame_h, frame_w) if frame_h and frame_w else conf
        quality_improvement = bool(
            builder and quality >= builder.last_embedding_sample_quality + 0.08
        )
        return (
            0 if unsampled_new else 1,
            0 if near_removal else 1,
            0 if candidate else 1,
            0 if quality_improvement else 1,
            -quality,
            int(track.track_id),
        )

    return sorted(tracks, key=key)


def _bbox_area(bbox) -> float:
    if not bbox or len(bbox) < 4:
        return 0.0
    return max(0.0, float(bbox[2]) - float(bbox[0])) * max(0.0, float(bbox[3]) - float(bbox[1]))


def _bbox_iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = (float(v) for v in a[:4])
    bx1, by1, bx2, by2 = (float(v) for v in b[:4])
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def supplement_orphan_vehicle_dets(
    tracks,
    raw_dets: list[dict],
    *,
    frame_w: int,
    frame_h: int,
    iou_thresh: float = 0.22,
    min_conf: float = 0.42,
    min_area_ratio: float = 0.055,
):
    """ByteTrack 漏跟时，为大号/货车 orphan 检测补虚拟 track（仅当帧关联）。"""
    from services.mtmc_local_track import Tracklet

    if not raw_dets:
        return tracks
    frame_area = max(float(frame_w * frame_h), 1.0)
    matched: set[int] = set()
    for tr in tracks:
        for i, det in enumerate(raw_dets):
            if _bbox_iou(tr.bbox, det.get("bbox") or []) >= iou_thresh:
                matched.add(i)
    extras = []
    eid = 900001
    for i, det in enumerate(raw_dets):
        if i in matched:
            continue
        conf = float(det.get("confidence") or 0)
        if conf < min_conf:
            continue
        bbox = [float(v) for v in (det.get("bbox") or [])[:4]]
        if len(bbox) < 4:
            continue
        area_ratio = _bbox_area(bbox) / frame_area
        cls = str(det.get("className") or "object").strip().lower()
        if cls not in ("truck", "bus"):
            continue
        if area_ratio < min_area_ratio:
            continue
        cx, cy = (bbox[0] + bbox[2]) * 0.5, (bbox[1] + bbox[3]) * 0.5
        extras.append(
            Tracklet(
                track_id=eid,
                bbox=bbox,
                class_name=str(det.get("className") or "object"),
                conf=conf,
                is_new=True,
                trail=[(cx, cy)],
                attrs={"orphanDet": True},
            )
        )
        eid += 1
    return list(tracks) + extras


def _sort_vehicle_tracks_for_assoc(tracks, associator, camera_id: int, now: float):
    """未绑定 Global 的 local 优先关联；同优先级时大框优先（跨镜货车漏跟补救）。"""

    def _key(tr):
        sticky = associator.peek_sticky(
            object_type="vehicle",
            camera_id=camera_id,
            local_track_id=int(tr.track_id),
            now=now,
        )
        return (
            0 if sticky is None else 1,
            -_bbox_area(getattr(tr, "bbox", None)),
            -float(getattr(tr, "conf", 0) or 0),
        )

    return sorted(tracks, key=_key)


def _enforce_unique_camera_global_ids(items: list[dict]) -> list[dict]:
    """Guarantee one visible owner for each Global ID in a camera frame."""
    owners: dict[tuple[str, str], tuple[int, float]] = {}
    for idx, item in enumerate(items):
        gid = item.get("globalId")
        if not gid:
            continue
        key = (str(item.get("objectType") or ""), str(gid))
        confidence = max(
            float(item.get("fuseScore") or 0),
            float(item.get("score") or 0),
            float(item.get("plateScore") or 0),
        )
        previous = owners.get(key)
        if previous is None:
            owners[key] = (idx, confidence)
            continue
        loser_idx = idx
        if confidence > previous[1]:
            loser_idx = previous[0]
            owners[key] = (idx, confidence)
        loser = items[loser_idx]
        loser["globalId"] = None
        loser["reidPersonId"] = None
        loser.setdefault("attrs", {})["duplicateGlobalIdSuppressed"] = str(gid)
        local_id = loser.get("localTrackId")
        kind = "person" if loser.get("objectType") == "person" else "vehicle"
        loser["label"] = f"{kind} L{local_id}"
    return items


def _make_local_tracker(cfg: MtmcConfig):
    """按配置创建单路局部跟踪器；ByteTrack/BoT-SORT 不可用时回退 IoU。"""
    from services.mtmc_local_track import bytetrack_available, botsort_available, create_local_tracker

    backend = (cfg.local_track_backend or "bytetrack").strip().lower()
    if backend not in ("iou", "bytetrack", "botsort"):
        log.warning("unknown local_track_backend=%s, use bytetrack", backend)
        backend = "bytetrack"
    if backend == "botsort" and not botsort_available():
        log.warning("BoT-SORT unavailable, fallback to ByteTrack")
        backend = "bytetrack"
    if backend == "bytetrack" and not bytetrack_available():
        log.warning("ByteTrack deps missing (trackers/supervision), fallback to IoU LocalTracker")
        backend = "iou"
        cfg.local_track_backend = "iou"
    else:
        cfg.local_track_backend = backend
    sample_fps = max(0.2, float(cfg.sample_fps))
    # 与 MTMC 采样率对齐，避免 ByteTrack 按 30FPS 预测导致低采样下轨迹永不激活
    frame_rate = max(2, int(round(sample_fps)))
    track_act = min(0.25, max(0.12, float(cfg.conf) * 0.75))
    return create_local_tracker(
        backend,  # type: ignore[arg-type]
        max_age=int(cfg.local_track_max_age or 30),
        iou_thresh=float(cfg.local_track_iou_thresh or 0.3),
        enable_cmc=bool(cfg.enable_cmc),
        enable_mask_cue=bool(cfg.enable_mask_cue),
        frame_rate=frame_rate,
        track_activation_threshold=track_act,
    )


def _process_frame(session: MtmcSession, cam_state: CamState, frame, hub_meta: dict, now: float | None = None):
    with cam_state.lifecycle_lock:
        if session._stop.is_set() and cam_state.builders_flushed:
            return
        return _process_frame_locked(session, cam_state, frame, hub_meta, now=now)


def _process_frame_locked(session: MtmcSession, cam_state: CamState, frame, hub_meta: dict, now: float | None = None):
    cfg = session.cfg
    cam_id = cam_state.camera_id
    now = float(now if now is not None else time.time())
    min_interval = 1.0 / max(0.2, float(cfg.sample_fps))
    if now - cam_state.last_process_at < min_interval:
        _publish_overlay(cam_state, frame, cam_state.last_dets, cam_state.congestion)
        return
    cam_state.last_process_at = now
    fh, fw = frame.shape[:2]
    cam_state.last_error = None

    if cfg.detect_only:
        raw_p, raw_v = _detect_person_vehicle(cfg, frame)
        items = _detect_items_from_raw(
            raw_p if cfg.enable_person else [],
            raw_v if cfg.enable_vehicle else [],
        )
        session.stats["persons"] += sum(1 for it in items if it.get("objectType") == "person")
        session.stats["vehicles"] += sum(1 for it in items if it.get("objectType") == "vehicle")
        _record_session_dets(cam_state, items, now)
        _publish_overlay(cam_state, frame, items, None)
        session.stats["frames"] += 1
        cam_state.detect_fps = _rolling_fps(cam_state._detect_times, now)
        return

    from services.strong_reid import extract_person_embeddings, color_signature
    from services.mtmc_tracklet import frame_quality
    from services.vehicle_reid_feat import extract_vehicle_embedding, fuse_plate_visual, infer_vehicle_class
    from services.vehicle_track import congestion_level, get_session as get_vsession
    from services.reid_gallery import l2_normalize

    if cam_state.tracker_person is None:
        cam_state.tracker_person = _make_local_tracker(cfg)
    if cam_state.tracker_vehicle is None:
        cam_state.tracker_vehicle = _make_local_tracker(cfg)

    items = []
    collector = _FrameAssociationCollector(session, now)
    claimed_person: set[str] = set()
    claimed_vehicle: set[str] = set()
    person_reid_left = _reid_budget_for(cfg, "person")
    vehicle_reid_left = _reid_budget_for(cfg, "vehicle")
    plate_left = max(0, int(cfg.plate_budget or 0))
    raw_p, raw_v = _detect_person_vehicle(cfg, frame)
    # “命中”表示检测器命中，必须在耗时的 ReID/车牌/关联前统计；否则首帧
    # ReID 尚未完成时页面会错误地长期显示人员 0。
    session.stats["persons"] += len(raw_p) if cfg.enable_person else 0
    session.stats["vehicles"] += len(raw_v) if cfg.enable_vehicle else 0
    session.stats["frames"] += 1
    cam_state.detect_fps = _rolling_fps(cam_state._detect_times, now)
    preliminary = _detect_items_from_raw(
        raw_p if cfg.enable_person else [],
        raw_v if cfg.enable_vehicle else [],
    )
    _record_session_dets(cam_state, preliminary, now)
    _publish_overlay(cam_state, frame, preliminary, cam_state.congestion)
    # ---- 人员 ----
    if cfg.enable_person and cfg.det_person_path:
        tracks = _tracks_or_raw(cam_state.tracker_person, raw_p, frame, id_base=800001)
        tracks = _sort_tracks_for_reid(session, cam_state, "person", tracks, frame_h=fh, frame_w=fw)
        for t in tracks:
            crop = _crop(frame, t.bbox)
            is_rider = str(getattr(t, "class_name", "")).lower() == "rider"
            builder = _get_tracklet_builder(
                cam_state,
                session_id=session.session_id,
                object_type="person",
                local_track_id=int(t.track_id),
                now=now,
            )
            if crop is None:
                items.append({
                    "objectType": "person",
                    "globalId": None,
                    "localTrackId": t.track_id,
                    "trackletId": builder.tracklet_id,
                    "displayName": "匿名",
                    "bbox": t.bbox,
                    "trail": list(t.trail),
                    "score": float(t.conf or 0),
                    "label": f"人 L{t.track_id}",
                    "attrs": {"cameraId": cam_id, "className": getattr(t, "class_name", "person")},
                })
                continue
            sticky_gid = session.associator.peek_sticky(
                object_type="person",
                camera_id=cam_id,
                local_track_id=int(t.track_id),
                now=now,
            )
            quality = frame_quality(t.bbox, t.conf, fh, fw)
            need_reid = person_reid_left > 0 and builder.should_sample_embedding(
                now, quality, view_token=_track_view_token(t),
            )
            emb, meta = None, {}
            embeddings: dict[str, np.ndarray] = {}
            c_sig = None
            gallery = {"matched": False, "name": None, "personId": None, "score": 0.0}
            if need_reid:
                person_reid_left -= 1
                try:
                    embeddings, meta = extract_person_embeddings(
                        crop,
                        youtu_root=cfg.youtu_root,
                        strong_root=cfg.strong_reid_root,
                    )
                    embeddings = {key: l2_normalize(value) for key, value in embeddings.items()}
                    model_key = meta.get("bestModelKey")
                    if model_key in embeddings:
                        emb = embeddings[model_key]
                    c_sig = color_signature(crop)
                except Exception as e:  # noqa: BLE001
                    emb, embeddings = None, {}
                    meta = {"backends": {"runtime": {"ready": False, "error": str(e)}}}
                if embeddings:
                    try:
                        gallery_embeddings = embeddings
                        if cfg.gallery_model_key:
                            gallery_embeddings = {
                                cfg.gallery_model_key: embeddings[cfg.gallery_model_key]
                            } if cfg.gallery_model_key in embeddings else {}
                        if cfg.gallery_model_key and not gallery_embeddings:
                            selected_space = str(cfg.gallery_model_key)
                            error = RuntimeError(f"selected gallery space unavailable: {selected_space}")
                            detail = {
                                "code": "selected_space_unavailable",
                                "selectedModelKey": selected_space,
                                "availableModelSpaces": sorted(embeddings),
                            }
                            _record_gallery_failure(
                                session, meta, error, camera_id=cam_id,
                                errors_by_space={selected_space: ["selected_space_unavailable"]}, detail=detail,
                            )
                            gallery = {"matched": False, "name": None, "personId": None, "score": 0.0, **detail,
                                       "ready": False, "degraded": True}
                        else:
                            gallery = _match_gallery(
                                gallery_embeddings,
                                cfg.appear_thresh,
                                score_weights=_reid_score_weights(cfg, gallery_embeddings),
                                model_versions_by_space={
                                    key: value for key, value in (meta.get("modelVersionsBySpace") or {}).items()
                                    if key in gallery_embeddings
                                },
                            )
                            gallery_errors = gallery.get("errorsByModelKey") or {}
                            if gallery_errors:
                                error = RuntimeError("; ".join(
                                    f"{key}: {', '.join(errors)}"
                                    for key, errors in gallery_errors.items()
                                ))
                                _record_gallery_failure(
                                    session, meta, error, camera_id=cam_id,
                                    errors_by_space=gallery_errors,
                                )
                            else:
                                _record_gallery_ready(session, meta, camera_id=cam_id)
                    except Exception as e:  # noqa: BLE001
                        _record_gallery_failure(session, meta, e, camera_id=cam_id)
            builder.add_observation(
                bbox=t.bbox,
                conf=t.conf,
                frame_h=fh,
                frame_w=fw,
                embedding=emb,
                embedding_spaces=embeddings,
                embedding_space_versions=meta.get("modelVersionsBySpace"),
                model_key=meta.get("associationModelKey"),
                visual_key="rider" if is_rider else None,
                trail=list(t.trail),
                meta={"reidBackend": meta.get("backend"), "reidModelKey": meta.get("associationModelKey")},
                now=now,
            )
            agg_spaces = builder.aggregate_embedding_spaces()
            agg_emb = builder.aggregate_embedding(meta.get("associationModelKey"))
            if agg_emb is None:
                agg_emb = emb
            g = _resolve_overlay_global(
                session,
                builder,
                sticky_gid=sticky_gid,
                claimed=claimed_person,
                now=now,
                collector=collector,
                associate_kwargs={
                    "embedding": agg_emb,
                    "embedding_spaces": agg_spaces,
                    "association_model_key": meta.get("associationModelKey"),
                    "score_weights": _reid_score_weights(cfg, embeddings),
                    "reid_person_id": gallery.get("personId") if gallery.get("matched") else None,
                    "display_name": gallery.get("name") if gallery.get("matched") else None,
                    "color_sig": c_sig,
                    "visual_key": "rider" if is_rider else None,
                },
            )
            if g is not None:
                claimed_person.add(g.global_id)
                if gallery.get("matched") and not g.display_name:
                    g.display_name = gallery.get("name")
                name = g.display_name or "匿名"
                label = f"{g.global_id}|{name}"
            else:
                label = f"人 L{t.track_id}"
                name = "匿名"
            speed = _speed_from_trail(t.trail, cfg.meters_per_pixel, cfg.sample_fps)
            item = {
                "objectType": "person",
                "globalId": g.global_id if g is not None else None,
                "localTrackId": t.track_id,
                "trackletId": builder.tracklet_id,
                "reidPersonId": g.reid_person_id if g is not None else None,
                "displayName": name,
                "bbox": t.bbox,
                "trail": list(t.trail),
                "score": float(gallery.get("score") or 0),
                "speedKmh": speed,
                "label": label,
                "attrs": {
                    "reidBackend": meta.get("backend"),
                    "reidReadiness": meta.get("backends"),
                    "availableModelSpaces": meta.get("availableModelSpaces", []),
                    "associationModelKey": meta.get("associationModelKey"),
                    "galleryModelKey": gallery.get("modelKey"),
                    "galleryStatus": meta.get("gallery"),
                    "cameraId": cam_id,
                    "assocMode": getattr(g, "last_assoc_mode", None) if g else None,
                    "reidSkipped": not need_reid,
                    "trackletId": builder.tracklet_id,
                },
            }
            items.append(item)
            if g is not None:
                row = {
                    "sessionId": session.session_id,
                    "cameraId": cam_id,
                    **item,
                    "congestion": None,
                }
                with session._events_lock:
                    session.events.append({**row, "ts": now})
                    if len(session.events) > 500:
                        session.events = session.events[-400:]
                if cfg.persist_events and (now - float(cam_state.last_persist_at or 0)) >= 1.0:
                    _persist_event(session.app, row)
                    cam_state.last_persist_at = now
        collector.flush("person", items)
        finalized = _finalize_removed_builders(
            session, cam_state, "person", _pop_removed_track_ids(cam_state.tracker_person),
            now=now, timeout_sec=cfg.lost_revive_sec,
        )
        _release_finalized_locals(session, cam_state, "person", finalized)

    # ---- 车辆 ----
    if cfg.enable_vehicle and cfg.det_vehicle_path:
        tracks_v = _tracks_or_raw(cam_state.tracker_vehicle, raw_v, frame, id_base=810001)
        tracks_v = supplement_orphan_vehicle_dets(
            tracks_v, raw_v, frame_w=fw, frame_h=fh,
        )
        cong = congestion_level(len(tracks_v))
        cam_state.congestion = cong
        if not cam_state.vehicle_session_id:
            cam_state.vehicle_session_id = f"{session.session_id}:cam{cam_id}"
        vsession = get_vsession(cam_state.vehicle_session_id)

        tracks_v = _sort_vehicle_tracks_for_assoc(tracks_v, session.associator, cam_id, now)
        for t in _sort_tracks_for_reid(
            session, cam_state, "vehicle", tracks_v, frame_h=fh, frame_w=fw,
        ):
            crop = _crop(frame, t.bbox)
            builder = _get_tracklet_builder(
                cam_state,
                session_id=session.session_id,
                object_type="vehicle",
                local_track_id=int(t.track_id),
                now=now,
            )
            if crop is None:
                cls = getattr(t, "class_name", None) or "车"
                items.append({
                    "objectType": "vehicle",
                    "globalId": None,
                    "localTrackId": t.track_id,
                    "trackletId": builder.tracklet_id,
                    "bbox": t.bbox,
                    "trail": list(t.trail),
                    "score": float(t.conf or 0),
                    "label": f"{cls} L{t.track_id}",
                    "attrs": {"cameraId": cam_id, "className": cls},
                })
                continue
            sticky_gid = session.associator.peek_sticky(
                object_type="vehicle",
                camera_id=cam_id,
                local_track_id=int(t.track_id),
                now=now,
            )
            quality = frame_quality(t.bbox, t.conf, fh, fw)
            need_reid = vehicle_reid_left > 0 and builder.should_sample_embedding(
                now, quality, view_token=_track_view_token(t),
            )
            emb, vmeta = None, {}
            plate_text, plate_score = None, 0.0
            fuse = {
                "identityKey": None, "plate": None, "visualKey": None,
                "fuseScore": 0, "plateScore": 0, "visualScore": 0,
            }
            cached_plate = cam_state.plate_cache.get(int(t.track_id)) or {}
            if cached_plate.get("text"):
                plate_text = cached_plate.get("text")
                plate_score = float(cached_plate.get("score") or 0)
            if need_reid:
                vehicle_reid_left -= 1
                emb, vmeta = extract_vehicle_embedding(cfg.vehicle_reid_root, crop)
                do_ocr = cfg.ocr_fn is not None and plate_left > 0 and not plate_text
                if do_ocr:
                    plate_left -= 1
                    try:
                        from services.vehicle_track import _plate_candidates, _ocr_plate
                        for pb, _src, _q, warp in _plate_candidates(
                            t.bbox, frame, cfg.plate_model_path, 0.2,
                        ):
                            ocr = _ocr_plate(cfg.ocr_fn, frame, pb, warped=warp)
                            plate_text = ocr.get("text")
                            plate_score = float(ocr.get("score") or 0)
                            if plate_text:
                                vsession.plates[t.track_id] = {
                                    "text": plate_text, "score": plate_score, "source": "mtmc",
                                }
                                cam_state.plate_cache[int(t.track_id)] = {
                                    "text": plate_text, "score": plate_score,
                                }
                                break
                    except Exception:  # noqa: BLE001
                        pass
                if not plate_text and t.track_id in vsession.plates:
                    plate_text = vsession.plates[t.track_id].get("text")
                    plate_score = float(vsession.plates[t.track_id].get("score") or 0)

                candidate_prototype = session.associator.vehicle_candidate_prototype(
                    camera_id=cam_id,
                    embedding=emb,
                    vehicle_class=infer_vehicle_class(
                        getattr(t, "class_name", None), t.bbox, frame_h=fh, frame_w=fw,
                    ),
                    now=now,
                )
                fuse = fuse_plate_visual(
                    plate=plate_text,
                    plate_score=plate_score,
                    emb_a=emb,
                    emb_b=candidate_prototype,
                )
            elif t.track_id in vsession.plates:
                plate_text = vsession.plates[t.track_id].get("text")
                plate_score = float(vsession.plates[t.track_id].get("score") or 0)
                fuse = {"plate": plate_text, "plateScore": plate_score, "identityKey": None,
                        "visualKey": None, "fuseScore": 0, "visualScore": 0}

            builder.add_observation(
                bbox=t.bbox,
                conf=t.conf,
                frame_h=fh,
                frame_w=fw,
                embedding=emb,
                plate=fuse.get("plate") or plate_text,
                plate_score=float(fuse.get("plateScore") or plate_score or 0),
                identity_key=fuse.get("identityKey"),
                visual_key=fuse.get("visualKey"),
                fuse_score=float(fuse.get("fuseScore") or 0),
                trail=list(t.trail),
                meta={"vehicleReid": vmeta.get("backend")},
                now=now,
            )
            agg_emb = builder.aggregate_embedding()
            if agg_emb is None:
                agg_emb = emb
            g = _resolve_overlay_global(
                session,
                builder,
                sticky_gid=sticky_gid,
                claimed=claimed_vehicle,
                now=now,
                collector=collector,
                associate_kwargs={
                    "embedding": agg_emb,
                    "identity_key": fuse.get("identityKey"),
                    "plate": fuse.get("plate") or plate_text,
                    "visual_key": fuse.get("visualKey"),
                    "vehicle_class": infer_vehicle_class(
                        getattr(t, "class_name", None),
                        t.bbox,
                        frame_h=fh,
                        frame_w=fw,
                    ),
                },
            )
            if g is not None:
                claimed_vehicle.add(g.global_id)
                plate_show = g.plate or fuse.get("plate") or plate_text or "无牌"
                cls = getattr(t, "class_name", None) or "车"
                label = f"{g.global_id}|{plate_show}"
            else:
                plate_show = fuse.get("plate") or plate_text or "无牌"
                cls = getattr(t, "class_name", None) or "车"
                label = f"{cls} L{t.track_id}|{plate_show}"
            speed = _speed_from_trail(t.trail, cfg.meters_per_pixel, cfg.sample_fps)
            if speed is not None and g is not None:
                cx = (t.bbox[0] + t.bbox[2]) * 0.5
                cy = (t.bbox[1] + t.bbox[3]) * 0.5
                hist = vsession.track_history.setdefault(t.track_id, [])
                hist.append((cx, cy, now))
                if len(hist) > 90:
                    vsession.track_history[t.track_id] = hist[-90:]

            item = {
                "objectType": "vehicle",
                "globalId": g.global_id if g is not None else None,
                "localTrackId": t.track_id,
                "trackletId": builder.tracklet_id,
                "plate": (g.plate if g else None) or fuse.get("plate") or plate_text,
                "identityKey": (g.identity_key if g else None) or fuse.get("identityKey"),
                "bbox": t.bbox,
                "trail": list(t.trail),
                "score": float(fuse.get("fuseScore") or 0),
                "plateScore": fuse.get("plateScore"),
                "visualScore": fuse.get("visualScore"),
                "fuseScore": fuse.get("fuseScore"),
                "speedKmh": speed,
                "congestion": cong,
                "label": label,
                "attrs": {
                    "vehicleReid": vmeta.get("backend"),
                    "cameraId": cam_id,
                    "assocMode": getattr(g, "last_assoc_mode", None) if g else None,
                    "reidSkipped": not need_reid,
                    "trackletId": builder.tracklet_id,
                },
            }
            items.append(item)
            if g is not None:
                row = {"sessionId": session.session_id, "cameraId": cam_id, **item}
                with session._events_lock:
                    session.events.append({**row, "ts": now})
                    if len(session.events) > 500:
                        session.events = session.events[-400:]
                if cfg.persist_events and (now - float(cam_state.last_persist_at or 0)) >= 1.0:
                    _persist_event(session.app, row)
                    cam_state.last_persist_at = now
                    pass_key = f"{g.global_id}:{cam_id}"
                    seen = getattr(session, "_pass_seen", None)
                    if seen is None:
                        session._pass_seen = set()
                        seen = session._pass_seen
                    if pass_key not in seen:
                        seen.add(pass_key)
                        pass_row = {
                            "sessionId": session.session_id,
                            "cameraId": cam_id,
                            "globalId": g.global_id,
                            "identityKey": item.get("identityKey"),
                            "plate": item.get("plate"),
                            "plateScore": item.get("plateScore"),
                            "visualScore": item.get("visualScore"),
                            "fuseScore": item.get("fuseScore"),
                            "speedKmh": speed,
                            "congestion": cong,
                            "localTrackId": t.track_id,
                        }
                        with session._events_lock:
                            session.passes.append({**pass_row, "ts": now})
                            if len(session.passes) > 300:
                                session.passes = session.passes[-200:]
                        _persist_pass(session.app, pass_row)
        collector.flush("vehicle", items)
        finalized = _finalize_removed_builders(
            session, cam_state, "vehicle", _pop_removed_track_ids(cam_state.tracker_vehicle),
            now=now, timeout_sec=cfg.lost_revive_sec,
        )
        _release_finalized_locals(session, cam_state, "vehicle", finalized)

    _enforce_unique_camera_global_ids(items)
    _record_session_dets(cam_state, items, now)
    _publish_overlay(cam_state, frame, items, cam_state.congestion)


def _cam_worker(session: MtmcSession, camera_row, upload_folder: str):
    cam_state = session.cams[int(camera_row.id)]
    try:
        _cam_worker_run(session, camera_row, upload_folder)
    finally:
        _flush_camera_tracklets(session, cam_state)


def _cam_worker_run(session: MtmcSession, camera_row, upload_folder: str):
    from services.camera_stream import ensure_shared_hub

    cam_id = int(camera_row.id)
    cam_state = session.cams[cam_id]
    source_type = (getattr(camera_row, "source_type", None) or "file").strip().lower()
    try:
        source = _resolve_cam_source(camera_row, upload_folder)
    except Exception as e:  # noqa: BLE001
        log.error("mtmc resolve source cam=%s: %s", cam_id, e)
        session.stats["errors"] += 1
        return

    if source_type == "image":
        _cam_worker_static_image(session, cam_state, source)
        return
    if source_type == "file":
        _cam_worker_local_file(session, cam_state, source)
        return

    width, fps = _hub_stream_params(session, camera_row)
    hub = ensure_shared_hub(cam_id, source_type, source, width, fps)
    sample_interval = 1.0 / max(0.2, float(session.cfg.sample_fps))
    next_sample_at = 0.0
    # hub epoch 变化（ffmpeg 重启）后重新订阅，避免 worker 永久退出
    while not session._stop.is_set():
        last_seq = -1
        try:
            for jpeg, seq in hub.subscribe_raw():
                if session._stop.is_set():
                    break
                if seq == last_seq:
                    continue
                last_seq = seq
                _mark_playback(cam_state)
                # RTSP/device 分支之前会对源流的每一帧执行完整推理，sampleFps
                # 没有生效。两路 25 FPS 视频因此可能触发每秒 50 次推理并造成积压。
                # 在 JPEG 解码之前节流，只处理最新采样帧，预览仍由共享 hub 流畅输出。
                now = time.monotonic()
                if now < next_sample_at:
                    # 首帧尚未产出时先推无框预览，避免画面空白；之后由流层重推最近 overlay
                    if cam_state.overlay_jpeg is None:
                        try:
                            frame_keep = _decode_jpeg(jpeg)
                            if frame_keep is not None:
                                _publish_overlay(cam_state, frame_keep, [], None)
                        except Exception:  # noqa: BLE001
                            pass
                    continue
                next_sample_at = now + sample_interval
                frame = _decode_jpeg(jpeg)
                if frame is None:
                    continue
                try:
                    _process_frame(session, cam_state, frame, {"seq": seq})
                except Exception as e:  # noqa: BLE001
                    session.stats["errors"] += 1
                    cam_state.last_error = str(e)
                    log.warning("mtmc process cam=%s: %s", cam_id, e)
                    try:
                        _publish_overlay(cam_state, frame, cam_state.last_dets, cam_state.congestion)
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as e:  # noqa: BLE001
            log.warning("mtmc hub subscribe cam=%s: %s", cam_id, e)
        if session._stop.is_set():
            break
        session._stop.wait(0.3)


def start_session(
    cfg: MtmcConfig,
    *,
    cameras: list | None = None,
    video_sources: dict[int, VirtualVideoSource] | None = None,
    upload_folder: str,
    app=None,
    topology_edges=None,
    upload_dir: str | None = None,
) -> MtmcSession:
    from services.mtmc_associator import MtmcAssociator
    from services.vehicle_reid_feat import assets_ready

    sid = uuid.uuid4().hex[:16]
    # same_cam_min_gap：略小于采样周期，保证同帧互斥，又允许目标短暂丢失后同镜续接
    sample_gap = 1.0 / max(0.2, float(cfg.sample_fps))
    v_appear = float(cfg.vehicle_appear_thresh or 0)
    if v_appear <= 0:
        if assets_ready(cfg.vehicle_reid_root):
            v_appear = float(cfg.appear_thresh)
        else:
            v_appear = max(0.62, float(cfg.appear_thresh) + 0.14)
    associator = MtmcAssociator(
        appear_thresh=cfg.appear_thresh,
        vehicle_appear_thresh=v_appear,
        time_window_sec=cfg.time_window_sec,
        same_cam_reuse=True,
        same_cam_min_gap=max(0.35, sample_gap * 0.85),
        lost_revive_sec=float(cfg.lost_revive_sec or max(1.0, sample_gap * 1.5)),
        local_sticky_sec=max(12.0, cfg.time_window_sec * 0.25),
        same_cam_appear_thresh=min(0.78, float(cfg.appear_thresh) + 0.22),
        mcbyte_decouple=bool(cfg.mcbyte_decouple),
        confirm_thresh=cfg.confirm_thresh or None,
        candidate_thresh=cfg.candidate_thresh or None,
        use_faiss_gallery=bool(cfg.use_faiss_gallery),
        gallery_model_key=cfg.gallery_model_key,
    )
    if topology_edges is not None:
        associator.set_topology(topology_edges)
    session = MtmcSession(sid, cfg, associator, app=app)
    session.source_mode = "upload" if video_sources else "camera"
    if video_sources:
        types = {vs.source_type for vs in video_sources.values()}
        if types == {"image"}:
            session.source_mode = "image"
        elif "rtsp" in types:
            session.source_mode = "stream"
        elif "device" in types:
            session.source_mode = "device"
    session.video_sources = dict(video_sources or {})
    session.upload_dir = upload_dir
    cam_rows = list(cameras or []) or list((video_sources or {}).values())
    for cam in cam_rows:
        cid = int(cam.id)
        session.cams[cid] = CamState(camera_id=cid, fast_preview=bool(cfg.detect_only))
    session.running = True
    with _sessions_lock:
        _sessions[sid] = session

    for cam in cam_rows:
        th = threading.Thread(
            target=_cam_worker,
            args=(session, cam, upload_folder),
            name=f"mtmc-{sid}-cam{cam.id}",
            daemon=True,
        )
        session._threads.append(th)
        th.start()
    return session


def _replace_live_global_id(session: MtmcSession, old_gid: str, new_gid: str) -> None:
    """Rekey output caches after a successfully persisted promotion."""
    for collection in (session.events, session.passes, session.cross_events):
        for row in collection:
            if row.get("globalId") == old_gid:
                row["globalId"] = new_gid
    if old_gid in session._global_last_cam:
        session._global_last_cam[new_gid] = session._global_last_cam.pop(old_gid)
    if old_gid in session._global_last_seen_ts:
        session._global_last_seen_ts[new_gid] = session._global_last_seen_ts.pop(old_gid)
    for cam_state in session.cams.values():
        with cam_state.state_lock:
            for row in cam_state.last_dets:
                if row.get("globalId") == old_gid:
                    row["globalId"] = new_gid
            updated = {}
            for key, row in cam_state.session_dets.items():
                if row.get("globalId") == old_gid:
                    row["globalId"] = new_gid
                    key = key.replace(f"global:{old_gid}", f"global:{new_gid}")
                updated[key] = row
            cam_state.session_dets = updated


def promote_candidate(session_id: str, global_id: str, candidate_global_id: str) -> dict:
    s = get_session(session_id)
    if not s:
        return {"ok": False, "message": "session not found"}
    from services.mtmc_persist import resolve_candidate_pair

    with s._candidate_lock:
        keep = s.associator.get_track(candidate_global_id)
        drop = s.associator.get_track(global_id)
        if keep is None or drop is None or keep.object_type != drop.object_type:
            return {"ok": False, "message": "merge unavailable"}
        if not resolve_candidate_pair(
            s.app,
            session_id=session_id,
            global_id=global_id,
            candidate_global_id=candidate_global_id,
            status="promoted",
        ):
            return {"ok": False, "message": "persistent promotion failed"}
        s._gid_alias[global_id] = candidate_global_id
        g = s.associator.merge_globals(candidate_global_id, global_id)
        if g is None:
            return {"ok": False, "message": "in-memory merge failed"}
        s.associator.resolve_live_candidate(global_id, candidate_global_id, "promoted")
        _replace_live_global_id(s, global_id, candidate_global_id)
        return {"ok": True, "globalId": g.global_id, "mergedFrom": global_id}


def reject_candidate(session_id: str, global_id: str, candidate_global_id: str) -> dict:
    s = get_session(session_id)
    if not s:
        return {"ok": False, "message": "session not found"}
    from services.mtmc_persist import resolve_candidate_pair

    with s._candidate_lock:
        ok = resolve_candidate_pair(
            s.app,
            session_id=session_id,
            global_id=global_id,
            candidate_global_id=candidate_global_id,
            status="rejected",
        )
        if ok:
            s.associator.resolve_live_candidate(global_id, candidate_global_id, "rejected")
        return {"ok": ok, "globalId": global_id, "candidateGlobalId": candidate_global_id}
