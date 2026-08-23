"""跨镜 MTMC 双视频评估：同步时间轴、生产引擎 tracklet 流程、输出对比报告。

用法（backend 目录）:
  python scripts/eval_mtmc_cross_cam.py
  python scripts/eval_mtmc_cross_cam.py --duration 60 --sample-fps 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import cv2

TARGET_WIDTH = 640


def resize_frame(frame, width: int = TARGET_WIDTH):
    h, w = frame.shape[:2]
    if w <= width:
        return frame
    scale = width / float(w)
    nh = max(1, int(round(h * scale)))
    return cv2.resize(frame, (width, nh), interpolation=cv2.INTER_AREA)


VIDEOS = [
    {
        "name": "cam71",
        "camera_id": 71,
        "path": os.path.join(
            ROOT, "..", "docs", "test_data", "video", "camera_recordings",
            "camera_192_168_8_71_20260820_094046.mp4",
        ),
    },
    {
        "name": "cam81",
        "camera_id": 81,
        "path": os.path.join(
            ROOT, "..", "docs", "test_data", "video", "camera_recordings",
            "camera_192_168_8_81_20260820_094044.mp4",
        ),
    },
]


@dataclass
class TrackRecord:
    object_type: str
    camera_id: int
    local_track_id: int
    global_id: str | None = None
    first_ts: float = 0.0
    last_ts: float = 0.0
    obs_count: int = 0


@dataclass
class EvalState:
    """跨镜评估统计。"""
    local_tracks: dict[tuple[str, int, int], TrackRecord] = field(default_factory=dict)
    global_cams: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))
    global_locals: dict[str, dict[int, set[int]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(set))
    )
    cross_events: list[dict] = field(default_factory=list)
    det_frames: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    det_counts: dict[int, list[int]] = field(default_factory=lambda: defaultdict(list))


def load_models():
    from app import create_app
    from models import AiModel
    from routes.mtmc import _abs_weight
    from services.vehicle_reid_feat import assets_ready

    app = create_app()
    with app.app_context():
        person_m = AiModel.query.filter_by(model_key="yolo26n", status="0").first()
        if person_m is None:
            person_m = AiModel.query.filter_by(
                model_key="winedarksea-yolo26n_person", status="0"
            ).first()
        vehicle_m = AiModel.query.filter_by(model_key="yolo26n", status="0").first()
        youtu_m = AiModel.query.filter_by(model_key="opencv-person-reid-youtu", status="0").first()
        strong_m = AiModel.query.filter_by(model_key="osnet-x1-0", status="0").first()
        if strong_m is None:
            strong_m = AiModel.query.filter_by(model_key="clip-reid-person", status="0").first()
        vreid_m = AiModel.query.filter_by(model_key="transreid-vehicle", status="0").first()
        det_person = _abs_weight(person_m)
        det_vehicle = _abs_weight(vehicle_m)
        youtu_root = _abs_weight(youtu_m)
        strong_root = _abs_weight(strong_m)
        vehicle_reid_root = _abs_weight(vreid_m)
        has_vehicle_reid = assets_ready(vehicle_reid_root)
        return {
            "det_person_path": det_person,
            "det_vehicle_path": det_vehicle,
            "youtu_root": youtu_root,
            "strong_reid_root": strong_root,
            "vehicle_reid_root": vehicle_reid_root,
            "has_vehicle_reid": has_vehicle_reid,
        }


def build_session(models: dict, sample_fps: float):
    from services.mtmc_associator import MtmcAssociator
    from services.mtmc_engine import CamState, MtmcConfig, MtmcSession
    from services.vehicle_reid_feat import assets_ready

    appear = 0.48
    v_appear = 0.48 if models.get("has_vehicle_reid") else max(0.62, appear + 0.14)
    cfg = MtmcConfig(
        camera_ids=[v["camera_id"] for v in VIDEOS],
        det_person_path=models["det_person_path"],
        det_vehicle_path=models["det_vehicle_path"],
        youtu_root=models["youtu_root"],
        strong_reid_root=models["strong_reid_root"],
        vehicle_reid_root=models["vehicle_reid_root"],
        enable_person=True,
        enable_vehicle=True,
        conf=0.28,
        sample_fps=sample_fps,
        appear_thresh=appear,
        vehicle_appear_thresh=0.0,
        confirm_thresh=appear,
        candidate_thresh=0.35,
        time_window_sec=120.0,
        persist_events=False,
        local_track_backend="bytetrack",
        mcbyte_decouple=True,
        lost_revive_sec=1.0,
    )
    associator = MtmcAssociator(
        appear_thresh=cfg.appear_thresh,
        vehicle_appear_thresh=v_appear,
        time_window_sec=cfg.time_window_sec,
        same_cam_reuse=True,
        same_cam_min_gap=max(0.35, (1.0 / sample_fps) * 0.85),
        lost_revive_sec=cfg.lost_revive_sec,
        local_sticky_sec=max(12.0, cfg.time_window_sec * 0.25),
        same_cam_appear_thresh=min(0.78, cfg.appear_thresh + 0.22),
        mcbyte_decouple=True,
        confirm_thresh=cfg.confirm_thresh,
        candidate_thresh=cfg.candidate_thresh,
        use_faiss_gallery=True,
    )
    session = MtmcSession("eval-cross-cam", cfg, associator, app=None)
    session.running = True
    for v in VIDEOS:
        session.cams[v["camera_id"]] = CamState(camera_id=v["camera_id"])
    return session


def open_captures():
    caps = {}
    meta = {}
    for v in VIDEOS:
        path = os.path.abspath(v["path"])
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        cap = cv2.VideoCapture(path)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 20.0)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        caps[v["camera_id"]] = cap
        meta[v["camera_id"]] = {
            "name": v["name"],
            "path": path,
            "fps": fps,
            "frames": frames,
            "duration_sec": frames / fps if fps > 0 else 0,
        }
    return caps, meta


def record_frame(session, eval_state: EvalState, cam_id: int, frame, frame_ts: float):
    from services.mtmc_engine import _process_frame

    cam_state = session.cams[cam_id]
    # 强制本帧处理（评估脚本自行节流）
    cam_state.last_process_at = 0.0
    _process_frame(session, cam_state, frame, {"seq": int(frame_ts * 1000)}, now=frame_ts)

    eval_state.det_frames[cam_id] += 1
    n_person = sum(1 for d in cam_state.last_dets if d.get("objectType") == "person")
    n_vehicle = sum(1 for d in cam_state.last_dets if d.get("objectType") == "vehicle")
    eval_state.det_counts[cam_id].append(n_person + n_vehicle)

    for d in cam_state.last_dets:
        otype = d.get("objectType") or "person"
        lid = int(d.get("localTrackId") or 0)
        gid = d.get("globalId")
        key = (otype, cam_id, lid)
        rec = eval_state.local_tracks.get(key)
        if rec is None:
            rec = TrackRecord(
                object_type=otype,
                camera_id=cam_id,
                local_track_id=lid,
                global_id=gid,
                first_ts=frame_ts,
                last_ts=frame_ts,
                obs_count=1,
            )
            eval_state.local_tracks[key] = rec
        else:
            rec.last_ts = frame_ts
            rec.obs_count += 1
            if gid:
                rec.global_id = gid
        if gid:
            eval_state.global_cams[gid].add(cam_id)
            eval_state.global_locals[gid][cam_id].add(lid)

    for row in session.cross_events:
        if row not in eval_state.cross_events:
            eval_state.cross_events.append(dict(row))


def finalize_builders(session, cam_id: int):
    from services.mtmc_engine import _finalize_removed_builders

    cam_state = session.cams[cam_id]
    _finalize_removed_builders(session, cam_state, "person", set())
    _finalize_removed_builders(session, cam_state, "vehicle", set())


def read_sample_frame(cap, step: int):
    """跳帧解码：grab 跳过中间帧，仅 decode 采样帧。"""
    if step > 1:
        for _ in range(step - 1):
            if not cap.grab():
                return False, None
    ok, frame = cap.read()
    return ok, frame


def process_video_fast(
    *,
    video: dict,
    cap,
    meta: dict,
    models: dict,
    associator,
    tracker_p,
    tracker_v,
    eval_state: EvalState,
    dur: float,
    sample_fps: float,
    base_ts: float,
    conf: float = 0.28,
):
    """高效跨镜评估：YOLO + ByteTrack + ReID + MtmcAssociator（与线上一致的核心关联逻辑）。"""
    from services.mtmc_engine import _detect, _crop
    from services.mtmc_local_track import create_local_tracker
    from services.strong_reid import extract_person_embedding
    from services.vehicle_reid_feat import extract_vehicle_embedding, fuse_plate_visual
    from services.reid_gallery import l2_normalize

    cid = video["camera_id"]
    fps = meta[cid]["fps"]
    step = max(1, int(round(fps / sample_fps)))
    max_frame = int(dur * fps)
    frame_idx = 0
    sample_no = 0
    det_path = models["det_person_path"]

    while frame_idx <= max_frame:
        ok, frame = read_sample_frame(cap, step)
        if not ok or frame is None:
            break
        frame_idx += step
        sample_no += 1
        now = base_ts + frame_idx / fps
        small = resize_frame(frame)

        raw_p = _detect(det_path, small, conf, [0])
        raw_v = _detect(det_path, small, conf, [1, 2, 3, 5, 7])
        tracks_p = tracker_p.update(raw_p, frame=small)
        tracks_v = tracker_v.update(raw_v, frame=small)

        eval_state.det_frames[cid] += 1
        eval_state.det_counts[cid].append(len(tracks_p) + len(tracks_v))

        # 同帧互斥：每采样帧重置（与 mtmc_engine 一致），不可跨帧累积
        claimed_p: set[str] = set()
        claimed_v: set[str] = set()

        for t in tracks_p:
            crop = _crop(small, t.bbox)
            if crop is None:
                continue
            try:
                emb, _ = extract_person_embedding(
                    crop,
                    youtu_root=models["youtu_root"],
                    strong_root=models["strong_reid_root"],
                )
                emb = l2_normalize(emb)
            except Exception:
                emb = None
            if emb is None:
                continue
            g = associator.associate(
                object_type="person",
                camera_id=cid,
                embedding=emb,
                local_track_id=int(t.track_id),
                exclude_gids=claimed_p,
                now=now,
            )
            claimed_p.add(g.global_id)
            cams_before = set(eval_state.global_cams.get(g.global_id, set()))
            _record_track(eval_state, "person", cid, int(t.track_id), g.global_id, now)
            if cid not in cams_before and len(eval_state.global_cams.get(g.global_id, set())) >= 2:
                other = next(c for c in eval_state.global_cams[g.global_id] if c != cid)
                eval_state.cross_events.append({
                    "globalId": g.global_id,
                    "objectType": "person",
                    "fromCameraId": other,
                    "toCameraId": cid,
                    "transitSec": round(now - base_ts, 2),
                    "ts": now,
                })

        for t in tracks_v:
            crop = _crop(small, t.bbox)
            if crop is None:
                continue
            emb, _ = extract_vehicle_embedding(models["vehicle_reid_root"], crop)
            fuse = fuse_plate_visual(plate=None, plate_score=0, emb_a=emb, emb_b=emb)
            g = associator.associate(
                object_type="vehicle",
                camera_id=cid,
                embedding=emb,
                identity_key=fuse.get("identityKey"),
                local_track_id=int(t.track_id),
                exclude_gids=claimed_v,
                now=now,
            )
            claimed_v.add(g.global_id)
            cams_before = set(eval_state.global_cams.get(g.global_id, set()))
            _record_track(eval_state, "vehicle", cid, int(t.track_id), g.global_id, now)
            if cid not in cams_before and len(eval_state.global_cams.get(g.global_id, set())) >= 2:
                other = next(c for c in eval_state.global_cams[g.global_id] if c != cid)
                eval_state.cross_events.append({
                    "globalId": g.global_id,
                    "objectType": "vehicle",
                    "fromCameraId": other,
                    "toCameraId": cid,
                    "transitSec": round(now - base_ts, 2),
                    "ts": now,
                })

        if sample_no % 30 == 0:
            print(
                f"  {video['name']} {frame_idx}/{max_frame} samples={sample_no}",
                flush=True,
            )

    return sample_no


def _record_track(eval_state: EvalState, otype: str, cam_id: int, lid: int, gid: str, ts: float):
    key = (otype, cam_id, lid)
    rec = eval_state.local_tracks.get(key)
    if rec is None:
        eval_state.local_tracks[key] = TrackRecord(
            object_type=otype,
            camera_id=cam_id,
            local_track_id=lid,
            global_id=gid,
            first_ts=ts,
            last_ts=ts,
            obs_count=1,
        )
    else:
        rec.last_ts = ts
        rec.obs_count += 1
        rec.global_id = gid
    if gid:
        eval_state.global_cams[gid].add(cam_id)
        eval_state.global_locals[gid][cam_id].add(lid)


def run_interleaved_eval(
    session, eval_state, caps, meta, models, dur, sample_fps, base_ts, t0: float,
):
    """按统一时间轴交错处理两路（在线 MTMC 时序，跨镜时间窗正确）。"""
    from services.mtmc_local_track import create_local_tracker
    from services.mtmc_engine import _detect, _crop
    from services.strong_reid import extract_person_embedding
    from services.vehicle_reid_feat import extract_vehicle_embedding, fuse_plate_visual
    from services.reid_gallery import l2_normalize

    trackers = {
        v["camera_id"]: (
            create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3),
            create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3),
        )
        for v in VIDEOS
    }
    frame_idx = {v["camera_id"]: 0 for v in VIDEOS}
    step = {v["camera_id"]: max(1, int(round(meta[v["camera_id"]]["fps"] / sample_fps))) for v in VIDEOS}
    max_frame = {v["camera_id"]: int(dur * meta[v["camera_id"]]["fps"]) for v in VIDEOS}
    total_steps = max(1, int(dur * sample_fps))

    for si in range(total_steps + 1):
        t = si / sample_fps
        if t > dur:
            break
        for v in VIDEOS:
            cid = v["camera_id"]
            target = min(si * step[cid], max_frame[cid])
            cap = caps[cid]
            cur = frame_idx[cid]
            while cur < target:
                if not cap.grab():
                    break
                cur += 1
            if cur > max_frame[cid]:
                frame_idx[cid] = cur
                continue
            ok, frame = cap.read()
            cur += 1
            frame_idx[cid] = cur
            if not ok or frame is None:
                continue
            now = base_ts + t
            small = resize_frame(frame)
            tp, tv = trackers[cid]
            raw_p = _detect(models["det_person_path"], small, 0.28, [0])
            raw_v = _detect(models["det_person_path"], small, 0.28, [1, 2, 3, 5, 7])
            tracks_p = tp.update(raw_p, frame=small)
            tracks_v = tv.update(raw_v, frame=small)
            eval_state.det_frames[cid] += 1
            eval_state.det_counts[cid].append(len(tracks_p) + len(tracks_v))
            claimed_p: set[str] = set()
            claimed_v: set[str] = set()
            for tr in tracks_p:
                crop = _crop(small, tr.bbox)
                if crop is None:
                    continue
                try:
                    emb, _ = extract_person_embedding(
                        crop, youtu_root=models["youtu_root"], strong_root=models["strong_reid_root"],
                    )
                    emb = l2_normalize(emb)
                except Exception:
                    continue
                cams_before = set(eval_state.global_cams.get("", set()))
                g = session.associator.associate(
                    object_type="person", camera_id=cid, embedding=emb,
                    local_track_id=int(tr.track_id), exclude_gids=claimed_p, now=now,
                )
                claimed_p.add(g.global_id)
                cams_before = set(eval_state.global_cams.get(g.global_id, set()))
                _record_track(eval_state, "person", cid, int(tr.track_id), g.global_id, now)
                if cid not in cams_before and len(eval_state.global_cams.get(g.global_id, set())) >= 2:
                    other = next(c for c in eval_state.global_cams[g.global_id] if c != cid)
                    eval_state.cross_events.append({
                        "globalId": g.global_id, "objectType": "person",
                        "fromCameraId": other, "toCameraId": cid,
                        "transitSec": round(t, 2), "ts": now,
                    })
            for tr in tracks_v:
                crop = _crop(small, tr.bbox)
                if crop is None:
                    continue
                emb, _ = extract_vehicle_embedding(models["vehicle_reid_root"], crop)
                fuse = fuse_plate_visual(plate=None, plate_score=0, emb_a=emb, emb_b=emb)
                cams_before = set(eval_state.global_cams.get("", set()))
                g = session.associator.associate(
                    object_type="vehicle", camera_id=cid, embedding=emb,
                    identity_key=fuse.get("identityKey"), local_track_id=int(tr.track_id),
                    exclude_gids=claimed_v, now=now,
                )
                claimed_v.add(g.global_id)
                cams_before = set(eval_state.global_cams.get(g.global_id, set()))
                _record_track(eval_state, "vehicle", cid, int(tr.track_id), g.global_id, now)
                if cid not in cams_before and len(eval_state.global_cams.get(g.global_id, set())) >= 2:
                    other = next(c for c in eval_state.global_cams[g.global_id] if c != cid)
                    eval_state.cross_events.append({
                        "globalId": g.global_id, "objectType": "vehicle",
                        "fromCameraId": other, "toCameraId": cid,
                        "transitSec": round(t, 2), "ts": now,
                    })
        if si % 20 == 0 and si > 0:
            print(f"  interleaved t={t:.0f}s/{dur:.0f}s elapsed={time.time()-t0:.0f}s", flush=True)


def run_eval(
    duration_sec: float,
    sample_fps: float,
    base_ts: float,
    mode: str = "fast",
    interleaved: bool = False,
) -> dict:
    from services.mtmc_local_track import create_local_tracker

    models = load_models()
    session = build_session(models, sample_fps)
    eval_state = EvalState()
    caps, meta = open_captures()

    min_dur = min(m["duration_sec"] for m in meta.values())
    dur = min(duration_sec, min_dur) if duration_sec > 0 else min_dur
    step = max(1, int(round(meta[VIDEOS[0]["camera_id"]]["fps"] / sample_fps)))

    print(f"模式: {mode}")
    print(f"模型: person_det={models['det_person_path']}")
    print(f"      vehicle_det={models['det_vehicle_path']}")
    print(f"      youtu={models['youtu_root']} strong={models['strong_reid_root']}")
    print(f"      vehicle_reid={models['vehicle_reid_root']} onnx={models['has_vehicle_reid']}")
    print(f"评估时长 {dur:.1f}s, 采样 {sample_fps} fps, step={step}, 交错={interleaved}")

    t0 = time.time()

    if mode == "engine":
        max_frame = int(dur * meta[VIDEOS[0]["camera_id"]]["fps"])
        total_steps = max(1, max_frame // step)
        readers: dict[int, tuple] = {}
        for v in VIDEOS:
            readers[v["camera_id"]] = (caps[v["camera_id"]], 0)
        processed_steps = 0
        while True:
            any_frame = False
            batch: dict[int, tuple] = {}
            for v in VIDEOS:
                cid = v["camera_id"]
                cap, fidx = readers[cid]
                if fidx > max_frame:
                    continue
                ok, frame = read_sample_frame(cap, step)
                if not ok or frame is None:
                    continue
                any_frame = True
                readers[cid] = (cap, fidx + step)
                ts = base_ts + fidx / meta[cid]["fps"]
                batch[cid] = (resize_frame(frame), ts)
            if not any_frame:
                break
            if not batch:
                continue
            for cid, (frame, fts) in batch.items():
                record_frame(session, eval_state, cid, frame, fts)
            processed_steps += 1
            if processed_steps % 10 == 0:
                pct = min(100.0, 100.0 * processed_steps / total_steps)
                print(f"  progress {pct:.0f}% elapsed={time.time()-t0:.0f}s", flush=True)
            if all(readers[v["camera_id"]][1] > max_frame for v in VIDEOS):
                break
        for v in VIDEOS:
            finalize_builders(session, v["camera_id"])
    elif interleaved:
        print("交错时间轴处理 cam71 + cam81 ...", flush=True)
        run_interleaved_eval(session, eval_state, caps, meta, models, dur, sample_fps, base_ts, t0)
    else:
        # 按视频顺序处理，共享 associator；视频时间轴对齐（同一起点 base_ts）
        for v in VIDEOS:
            cid = v["camera_id"]
            cap = caps[cid]
            tp = create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3)
            tv = create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3)
            print(f"处理 {v['name']} (cam{cid}) ...", flush=True)
            process_video_fast(
                video=v,
                cap=cap,
                meta=meta,
                models=models,
                associator=session.associator,
                tracker_p=tp,
                tracker_v=tv,
                eval_state=eval_state,
                dur=dur,
                sample_fps=sample_fps,
                base_ts=base_ts,
            )

    with session.associator._lock:
        for bkey, gid in session.associator._local_bind.items():
            otype, cid, lid = bkey
            _record_track(eval_state, otype, int(cid), int(lid), gid, base_ts)

    elapsed = time.time() - t0
    report = build_report(
        session, eval_state, meta, models, dur, sample_fps, elapsed,
        mode=mode, interleaved=interleaved,
    )
    for cap in caps.values():
        cap.release()
    return report


def build_report(
    session, eval_state: EvalState, meta, models, dur, sample_fps, elapsed,
    mode: str = "fast", interleaved: bool = False,
) -> dict:
    def summarize_type(object_type: str) -> dict:
        locals_by_cam: dict[int, list[TrackRecord]] = defaultdict(list)
        for rec in eval_state.local_tracks.values():
            if rec.object_type != object_type:
                continue
            locals_by_cam[rec.camera_id].append(rec)

        globals_by_cam: dict[int, set[str]] = defaultdict(set)
        for rec in eval_state.local_tracks.values():
            if rec.object_type != object_type or not rec.global_id:
                continue
            globals_by_cam[rec.camera_id].add(rec.global_id)

        cross_globals = []
        for gid, cams in eval_state.global_cams.items():
            g = session.associator.get_track(gid)
            if g is None or g.object_type != object_type:
                continue
            if len(cams) < 2:
                continue
            cam_locals = {
                int(c): sorted(eval_state.global_locals[gid][c])
                for c in sorted(cams)
            }
            cross_globals.append({
                "globalId": gid,
                "cameras": sorted(cams),
                "localTracksByCam": cam_locals,
                "displayName": g.display_name,
                "plate": g.plate,
                "hitCount": g.hit_count,
                "assocMode": g.last_assoc_mode,
            })
        cross_globals.sort(key=lambda x: (-len(x["cameras"]), x["globalId"]))

        cam_stats = {}
        for v in VIDEOS:
            cid = v["camera_id"]
            locs = locals_by_cam.get(cid, [])
            assigned = [r for r in locs if r.global_id]
            unassigned = [r for r in locs if not r.global_id]
            cam_stats[v["name"]] = {
                "cameraId": cid,
                "localTrackCount": len(locs),
                "globalIdCount": len(globals_by_cam.get(cid, set())),
                "assignedLocalTracks": len(assigned),
                "unassignedLocalTracks": len(unassigned),
                "assignmentRate": round(len(assigned) / max(1, len(locs)), 4),
                "avgDetsPerSampleFrame": round(
                    sum(eval_state.det_counts.get(cid, [])) / max(1, len(eval_state.det_counts.get(cid, []))),
                    2,
                ),
                "sampleFrames": eval_state.det_frames.get(cid, 0),
                "localTracks": [
                    {
                        "localTrackId": r.local_track_id,
                        "globalId": r.global_id,
                        "obsCount": r.obs_count,
                        "durationSec": round(r.last_ts - r.first_ts, 2),
                    }
                    for r in sorted(locs, key=lambda x: x.local_track_id)
                ],
            }

        all_globals = {
            gid for gid, g in session.associator.tracks.items()
            if g.object_type == object_type
        }
        only_cam71 = [
            gid for gid, cams in eval_state.global_cams.items()
            if gid in all_globals
            and session.associator.get_track(gid).object_type == object_type
            and cams == {71}
        ]
        only_cam81 = [
            gid for gid, cams in eval_state.global_cams.items()
            if gid in all_globals
            and session.associator.get_track(gid).object_type == object_type
            and cams == {81}
        ]

        return {
            "totalGlobalsInAssociator": len(all_globals),
            "crossCameraGlobalCount": len(cross_globals),
            "onlyCam71GlobalCount": len(only_cam71),
            "onlyCam81GlobalCount": len(only_cam81),
            "crossCameraGlobals": cross_globals,
            "candidates": [
                c for c in session.associator.list_candidates()
                if c.get("objectType") == object_type
            ],
            "byCamera": cam_stats,
        }

    person = summarize_type("person")
    vehicle = summarize_type("vehicle")

    return {
        "meta": {
            "durationSec": dur,
            "sampleFps": sample_fps,
            "elapsedSec": round(elapsed, 1),
            "videos": meta,
            "models": {k: v for k, v in models.items() if k != "has_vehicle_reid"},
            "hasVehicleReidOnnx": models["has_vehicle_reid"],
            "associatorVehicleAppearThresh": session.associator.vehicle_appear_thresh,
            "mode": mode,
            "interleaved": interleaved,
        },
        "person": person,
        "vehicle": vehicle,
        "crossEvents": eval_state.cross_events[-100:],
    }


def print_markdown(report: dict) -> str:
    lines = [
        "# 跨镜 MTMC 双视频评估报告",
        "",
        f"- 评估模式: **{report['meta'].get('mode', 'fast')}**",
        f"- 时间交错: **{report['meta'].get('interleaved', False)}**",
        f"- 评估时长: **{report['meta']['durationSec']:.1f}s**",
        f"- 采样率: **{report['meta']['sampleFps']} fps**",
        f"- 耗时: **{report['meta']['elapsedSec']}s**",
        f"- 车辆 ReID ONNX: **{report['meta']['hasVehicleReidOnnx']}**",
        f"- 车辆外观阈值: **{report['meta']['associatorVehicleAppearThresh']}**",
        "",
    ]

    for otype, title in (("person", "行人"), ("vehicle", "车辆")):
        block = report[otype]
        lines.append(f"## {title}")
        lines.append("")
        lines.append(
            f"| 指标 | cam71 | cam81 |"
        )
        lines.append("|------|-------|-------|")
        b71 = block["byCamera"]["cam71"]
        b81 = block["byCamera"]["cam81"]
        lines.append(
            f"| 局部轨迹数 | {b71['localTrackCount']} | {b81['localTrackCount']} |"
        )
        lines.append(
            f"| 分配 Global 数 | {b71['globalIdCount']} | {b81['globalIdCount']} |"
        )
        lines.append(
            f"| 已关联局部轨迹 | {b71['assignedLocalTracks']} | {b81['assignedLocalTracks']} |"
        )
        lines.append(
            f"| 未关联局部轨迹 | {b71['unassignedLocalTracks']} | {b81['unassignedLocalTracks']} |"
        )
        lines.append(
            f"| 关联率 | {b71['assignmentRate']:.1%} | {b81['assignmentRate']:.1%} |"
        )
        lines.append(
            f"| 平均每采样帧检测数 | {b71['avgDetsPerSampleFrame']} | {b81['avgDetsPerSampleFrame']} |"
        )
        lines.append("")
        lines.append(
            f"- 关联器内 Global 总数: **{block['totalGlobalsInAssociator']}**"
        )
        lines.append(
            f"- **跨镜成功关联 Global 数**: **{block['crossCameraGlobalCount']}**"
        )
        lines.append(
            f"- 仅 cam71 Global: {block['onlyCam71GlobalCount']}, 仅 cam81: {block['onlyCam81GlobalCount']}"
        )
        lines.append(
            f"- 候选对（待人工晋升）: {len(block['candidates'])}"
        )
        lines.append("")
        lines.append("### 跨镜 Global 对照（两路均出现同一 ID）")
        lines.append("")
        if not block["crossCameraGlobals"]:
            lines.append("_无跨镜 Global_")
        else:
            lines.append("| Global ID | cam71 local | cam81 local | 备注 |")
            lines.append("|-----------|-------------|-------------|------|")
            for row in block["crossCameraGlobals"][:50]:
                loc71 = row["localTracksByCam"].get(71, [])
                loc81 = row["localTracksByCam"].get(81, [])
                note = row.get("displayName") or row.get("plate") or row.get("assocMode") or ""
                lines.append(
                    f"| {row['globalId']} | {loc71} | {loc81} | {note} |"
                )
            if len(block["crossCameraGlobals"]) > 50:
                lines.append(f"| ... | 共 {len(block['crossCameraGlobals'])} 条 | | |")
        lines.append("")
        lines.append("### cam71 局部轨迹 → Global")
        lines.append("")
        lines.append("| local | global | 观测帧 | 持续(s) |")
        lines.append("|-------|--------|--------|---------|")
        for r in block["byCamera"]["cam71"]["localTracks"][:40]:
            lines.append(
                f"| {r['localTrackId']} | {r['globalId'] or '-'} | {r['obsCount']} | {r['durationSec']} |"
            )
        lines.append("")
        lines.append("### cam81 局部轨迹 → Global")
        lines.append("")
        lines.append("| local | global | 观测帧 | 持续(s) |")
        lines.append("|-------|--------|--------|---------|")
        for r in block["byCamera"]["cam81"]["localTracks"][:40]:
            lines.append(
                f"| {r['localTrackId']} | {r['globalId'] or '-'} | {r['obsCount']} | {r['durationSec']} |"
            )
        lines.append("")

    lines.append("## 跨镜事件（引擎记录）")
    lines.append("")
    if not report["crossEvents"]:
        lines.append("_无_")
    else:
        lines.append("| Global | 类型 | from→to | transit(s) |")
        lines.append("|--------|------|---------|------------|")
        for e in report["crossEvents"][:30]:
            lines.append(
                f"| {e.get('globalId')} | {e.get('objectType')} | "
                f"{e.get('fromCameraId')}→{e.get('toCameraId')} | {e.get('transitSec')} |"
            )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="MTMC 双视频跨镜评估")
    parser.add_argument("--mode", choices=("fast", "engine"), default="fast")
    parser.add_argument("--interleaved", action="store_true", help="按时间交错处理两路（更接近在线 MTMC）")
    parser.add_argument("--duration", type=float, default=0, help="评估秒数，0=全片")
    parser.add_argument("--sample-fps", type=float, default=2.0)
    parser.add_argument("--base-ts", type=float, default=1_700_000_000.0, help="模拟时间轴起点")
    parser.add_argument(
        "--out-json",
        default=os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "mtmc_eval_report.json"),
    )
    parser.add_argument(
        "--out-md",
        default=os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "mtmc_eval_report.md"),
    )
    args = parser.parse_args()

    report = run_eval(args.duration, args.sample_fps, args.base_ts, mode=args.mode, interleaved=args.interleaved)
    md = print_markdown(report)

    out_json = os.path.abspath(args.out_json)
    out_md = os.path.abspath(args.out_md)
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md)

    print(md)
    print(f"\n报告已写入:\n  {out_json}\n  {out_md}")


if __name__ == "__main__":
    main()
