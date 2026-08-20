"""跨镜 MTMC 引擎：一次拉流 → 检测 → 局部跟踪 → 强 ReID → 车牌融合 → 在线关联 → 叠加。

每会话 session_id 隔离；车辆复用 VehicleSession 语义（按 cam:session 隔离车牌投票/测速）。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
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


def _color_for(gid: str, palette) -> tuple:
    h = sum(ord(c) for c in (gid or ""))
    return palette[h % len(palette)]


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
    conf: float = 0.35
    sample_fps: float = 2.0
    meters_per_pixel: float = 0.05
    appear_thresh: float = 0.48
    time_window_sec: float = 90.0
    fuse_weight_strong: float = 0.65
    width: int = 640
    fps: int = 10
    persist_events: bool = True


@dataclass
class CamState:
    camera_id: int
    tracker_person: Any = None
    tracker_vehicle: Any = None
    vehicle_session_id: str = ""
    last_process_at: float = 0.0
    overlay_jpeg: bytes | None = None
    frame_seq: int = 0
    last_dets: list = field(default_factory=list)
    congestion: dict = field(default_factory=dict)


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

    def to_dict(self) -> dict:
        return {
            "sessionId": self.session_id,
            "running": self.running,
            "cameraIds": list(self.cfg.camera_ids),
            "enablePerson": self.cfg.enable_person,
            "enableVehicle": self.cfg.enable_vehicle,
            "createdAt": self.created_at,
            "stats": dict(self.stats),
            "globals": self.associator.snapshot(),
            "recentEvents": self.events[-50:],
            "recentPasses": self.passes[-50:],
            "cams": {
                str(cid): {
                    "frameSeq": st.frame_seq,
                    "detCount": len(st.last_dets),
                    "congestion": st.congestion,
                }
                for cid, st in self.cams.items()
            },
        }


_sessions: dict[str, MtmcSession] = {}
_sessions_lock = threading.Lock()


def get_session(session_id: str) -> MtmcSession | None:
    with _sessions_lock:
        return _sessions.get(session_id)


def list_sessions() -> list[dict]:
    with _sessions_lock:
        return [s.to_dict() for s in _sessions.values()]


def stop_session(session_id: str) -> bool:
    with _sessions_lock:
        s = _sessions.get(session_id)
    if not s:
        return False
    s._stop.set()
    s.running = False
    return True


def get_overlay_jpeg(session_id: str, camera_id: int) -> bytes | None:
    s = get_session(session_id)
    if not s:
        return None
    st = s.cams.get(int(camera_id))
    return st.overlay_jpeg if st else None


def _decode_jpeg(data: bytes):
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _detect(model_path: str | None, frame, conf: float, classes: list[int] | None):
    if not model_path:
        return []
    try:
        from inference import _get_model, _yolo_predict_kwargs
        model = _get_model(model_path)
        kw = _yolo_predict_kwargs(conf=conf, classes=classes)
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
        log.warning("mtmc detect failed: %s", e)
        return []


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


def _match_gallery(emb, model_key: str, threshold: float):
    try:
        from services.reid_gallery import match_embedding
        return match_embedding(emb, model_key, threshold=threshold)
    except Exception:  # noqa: BLE001
        return {"matched": False, "name": "未知", "personId": None, "score": 0.0}


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


def _draw_overlay(frame, items: list[dict], congestion: dict | None = None):
    """绘制检测框/轨迹/中文标签（PIL，避免 putText 显示 ???）。"""
    vis = frame.copy()
    for it in items:
        bbox = it.get("bbox") or []
        if len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox]
        ot = it.get("objectType") or "person"
        gid = it.get("globalId") or "?"
        color = _color_for(gid, _PERSON_COLORS if ot == "person" else _VEHICLE_COLORS)
        trail = it.get("trail") or []
        if len(trail) >= 2:
            pts = np.array([[int(p[0]), int(p[1])] for p in trail], dtype=np.int32)
            cv2.polylines(vis, [pts], False, color, 2, lineType=cv2.LINE_AA)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
        label = it.get("label") or gid
        # 标签画在框上方；空间不够则画在框内顶部
        ty = y1 - 22 if y1 >= 24 else y1 + 4
        vis = _draw_label_pil(vis, str(label), (x1, ty), color=color, font_size=16)
    if congestion:
        txt = f"拥堵:{congestion.get('label', '')} 车:{congestion.get('vehicleCount', 0)}"
        vis = _draw_label_pil(vis, txt, (8, 8), color=(0, 220, 255), font_size=18)
    ok, buf = cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    return buf.tobytes() if ok else None


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


def _process_frame(session: MtmcSession, cam_state: CamState, frame, hub_meta: dict):
    from services.mtmc_local_track import LocalTracker
    from services.strong_reid import extract_person_embedding
    from services.vehicle_reid_feat import extract_vehicle_embedding, fuse_plate_visual
    from services.vehicle_track import congestion_level, get_session as get_vsession
    from services.reid_gallery import l2_normalize

    cfg = session.cfg
    cam_id = cam_state.camera_id
    now = time.time()
    min_interval = 1.0 / max(0.2, float(cfg.sample_fps))
    if now - cam_state.last_process_at < min_interval:
        # 仍刷新 overlay 用上一帧结果画在新帧上
        if cam_state.last_dets:
            jpeg = _draw_overlay(frame, cam_state.last_dets, cam_state.congestion)
            if jpeg:
                cam_state.overlay_jpeg = jpeg
                cam_state.frame_seq += 1
        return
    cam_state.last_process_at = now

    if cam_state.tracker_person is None:
        cam_state.tracker_person = LocalTracker()
    if cam_state.tracker_vehicle is None:
        cam_state.tracker_vehicle = LocalTracker()

    items = []
    # ---- 人员 ----
    if cfg.enable_person and cfg.det_person_path:
        raw = _detect(cfg.det_person_path, frame, cfg.conf, [0])
        tracks = cam_state.tracker_person.update(raw)
        for t in tracks:
            crop = _crop(frame, t.bbox)
            if crop is None:
                continue
            try:
                emb, meta = extract_person_embedding(
                    crop,
                    youtu_root=cfg.youtu_root,
                    strong_root=cfg.strong_reid_root,
                    fuse_weight_strong=cfg.fuse_weight_strong,
                )
                emb = l2_normalize(emb)
            except Exception:  # noqa: BLE001
                emb, meta = None, {}
            gallery = {"matched": False, "name": None, "personId": None, "score": 0.0}
            if emb is not None and cfg.youtu_root:
                # 底库按 youtu model_key 匹配；强模型并联后仍可对 Youtu 空间做近似匹配
                try:
                    gallery = _match_gallery(emb, "opencv-person-reid-youtu", cfg.appear_thresh)
                except Exception:  # noqa: BLE001
                    pass
            g = session.associator.associate(
                object_type="person",
                camera_id=cam_id,
                embedding=emb,
                reid_person_id=gallery.get("personId") if gallery.get("matched") else None,
                display_name=gallery.get("name") if gallery.get("matched") else None,
                now=now,
            )
            if gallery.get("matched") and not g.display_name:
                g.display_name = gallery.get("name")
            name = g.display_name or "匿名"
            label = f"{g.global_id}|{name}"
            speed = _speed_from_trail(t.trail, cfg.meters_per_pixel, cfg.sample_fps)
            item = {
                "objectType": "person",
                "globalId": g.global_id,
                "localTrackId": t.track_id,
                "reidPersonId": g.reid_person_id,
                "displayName": name,
                "bbox": t.bbox,
                "trail": list(t.trail),
                "score": float(gallery.get("score") or 0),
                "speedKmh": speed,
                "label": label,
                "attrs": {"reidBackend": meta.get("backend"), "cameraId": cam_id},
            }
            items.append(item)
            session.stats["persons"] += 1
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
            if cfg.persist_events:
                _persist_event(session.app, row)

    # ---- 车辆 ----
    if cfg.enable_vehicle and cfg.det_vehicle_path:
        raw_v = _detect(cfg.det_vehicle_path, frame, cfg.conf, [1, 2, 3, 5, 7])
        tracks_v = cam_state.tracker_vehicle.update(raw_v)
        cong = congestion_level(len(tracks_v))
        cam_state.congestion = cong
        # VehicleSession 按 session 隔离
        if not cam_state.vehicle_session_id:
            cam_state.vehicle_session_id = f"{session.session_id}:cam{cam_id}"
        vsession = get_vsession(cam_state.vehicle_session_id)

        for t in tracks_v:
            crop = _crop(frame, t.bbox)
            if crop is None:
                continue
            emb, vmeta = extract_vehicle_embedding(cfg.vehicle_reid_root, crop)
            plate_text, plate_score = None, 0.0
            # 轻量车牌：复用 vehicle_track 启发式 + OCR（若配置）
            if cfg.ocr_fn is not None:
                try:
                    from services.vehicle_track import _pick_plate_bbox, _ocr_plate
                    pb = _pick_plate_bbox(t.bbox, frame, cfg.plate_model_path, 0.2)
                    if pb:
                        ocr = _ocr_plate(cfg.ocr_fn, frame, pb)
                        plate_text = ocr.get("text")
                        plate_score = float(ocr.get("score") or 0)
                        if plate_text:
                            vsession.plates[t.track_id] = {
                                "text": plate_text, "score": plate_score, "source": "mtmc",
                            }
                except Exception:  # noqa: BLE001
                    pass
            if not plate_text and t.track_id in vsession.plates:
                plate_text = vsession.plates[t.track_id].get("text")
                plate_score = float(vsession.plates[t.track_id].get("score") or 0)

            # 与已有全局车辆做视觉对比选最佳，再融合
            best_peer = None
            best_sim = -1.0
            with session.associator._lock:
                for gtrack in session.associator.tracks.values():
                    if gtrack.object_type != "vehicle" or gtrack.embedding is None:
                        continue
                    from services.vehicle_reid_feat import cosine as vcos
                    sim = vcos(emb, gtrack.embedding)
                    if sim > best_sim:
                        best_sim = sim
                        best_peer = gtrack.embedding
            fuse = fuse_plate_visual(
                plate=plate_text,
                plate_score=plate_score,
                emb_a=emb,
                emb_b=best_peer if best_peer is not None else emb,
            )
            g = session.associator.associate(
                object_type="vehicle",
                camera_id=cam_id,
                embedding=emb,
                identity_key=fuse["identityKey"],
                plate=fuse.get("plate"),
                visual_key=fuse.get("visualKey"),
                now=now,
            )
            speed = _speed_from_trail(t.trail, cfg.meters_per_pixel, cfg.sample_fps)
            if speed is not None:
                # 写入会话历史点
                cx = (t.bbox[0] + t.bbox[2]) * 0.5
                cy = (t.bbox[1] + t.bbox[3]) * 0.5
                hist = vsession.track_history.setdefault(t.track_id, [])
                hist.append((cx, cy, now))
                if len(hist) > 90:
                    vsession.track_history[t.track_id] = hist[-90:]

            plate_show = g.plate or fuse.get("plate") or "无牌"
            label = f"{g.global_id}|{plate_show}"
            item = {
                "objectType": "vehicle",
                "globalId": g.global_id,
                "localTrackId": t.track_id,
                "plate": g.plate or fuse.get("plate"),
                "identityKey": g.identity_key or fuse.get("identityKey"),
                "bbox": t.bbox,
                "trail": list(t.trail),
                "score": float(fuse.get("fuseScore") or 0),
                "plateScore": fuse.get("plateScore"),
                "visualScore": fuse.get("visualScore"),
                "fuseScore": fuse.get("fuseScore"),
                "speedKmh": speed,
                "congestion": cong,
                "label": label,
                "attrs": {"vehicleReid": vmeta.get("backend"), "cameraId": cam_id},
            }
            items.append(item)
            session.stats["vehicles"] += 1
            row = {"sessionId": session.session_id, "cameraId": cam_id, **item}
            with session._events_lock:
                session.events.append({**row, "ts": now})
                if len(session.events) > 500:
                    session.events = session.events[-400:]
            if cfg.persist_events:
                _persist_event(session.app, row)
                # 过车仅在新全局 ID 首见或换相机时落库，避免每帧刷写
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

    cam_state.last_dets = items
    jpeg = _draw_overlay(frame, items, cam_state.congestion)
    if jpeg:
        cam_state.overlay_jpeg = jpeg
        cam_state.frame_seq += 1
    session.stats["frames"] += 1


def _cam_worker(session: MtmcSession, camera_row, upload_folder: str):
    from services.camera_stream import ensure_shared_hub, _resolve_source

    cam_id = int(camera_row.id)
    cam_state = session.cams[cam_id]
    try:
        source = _resolve_source(camera_row, upload_folder)
    except Exception as e:  # noqa: BLE001
        log.error("mtmc resolve source cam=%s: %s", cam_id, e)
        session.stats["errors"] += 1
        return

    hub = ensure_shared_hub(
        cam_id, camera_row.source_type, source,
        session.cfg.width or camera_row.resolution or 640,
        session.cfg.fps or camera_row.fps or 10,
    )
    # 保持 hub 有订阅，避免空闲停掉
    sub = hub.subscribe_raw()
    last_seq = -1
    try:
        for jpeg, seq in sub:
            if session._stop.is_set():
                break
            if seq == last_seq:
                continue
            last_seq = seq
            frame = _decode_jpeg(jpeg)
            if frame is None:
                continue
            try:
                if session.app is not None:
                    with session.app.app_context():
                        _process_frame(session, cam_state, frame, {"seq": seq})
                else:
                    _process_frame(session, cam_state, frame, {"seq": seq})
            except Exception as e:  # noqa: BLE001
                session.stats["errors"] += 1
                log.warning("mtmc process cam=%s: %s", cam_id, e)
    finally:
        pass


def start_session(cfg: MtmcConfig, *, cameras: list, upload_folder: str, app=None, topology_edges=None) -> MtmcSession:
    from services.mtmc_associator import MtmcAssociator

    sid = uuid.uuid4().hex[:16]
    associator = MtmcAssociator(
        appear_thresh=cfg.appear_thresh,
        time_window_sec=cfg.time_window_sec,
    )
    if topology_edges:
        associator.set_topology(topology_edges)
    session = MtmcSession(sid, cfg, associator, app=app)
    for cam in cameras:
        cid = int(cam.id)
        session.cams[cid] = CamState(camera_id=cid)
    session.running = True
    with _sessions_lock:
        _sessions[sid] = session

    for cam in cameras:
        th = threading.Thread(
            target=_cam_worker,
            args=(session, cam, upload_folder),
            name=f"mtmc-{sid}-cam{cam.id}",
            daemon=True,
        )
        session._threads.append(th)
        th.start()
    return session
