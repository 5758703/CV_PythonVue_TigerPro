"""检查 t=28/29 黑 sedan 在交错 MTMC 流中的 Global ID 是否一致。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.eval_mtmc_cross_cam import (
    VIDEOS,
    EvalState,
    _record_track,
    _vehicle_fuse_from_track,
    build_session,
    load_models,
    open_captures,
    resize_frame,
)
from services.mtmc_engine import _detect, _crop
from services.mtmc_engine import _sort_vehicle_tracks_for_assoc
from services.mtmc_local_track import create_local_tracker


def main():
    models = load_models()
    session = build_session(models, 2.0)
    eval_state = EvalState()
    caps, meta = open_captures()
    det = models["det_person_path"]
    base_ts = 1.7e9
    dur = 35.0
    sample_fps = 2.0

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

    snap: dict[str, dict] = {}

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
            _, tv = trackers[cid]
            raw_v = _detect(det, small, 0.28, [1, 2, 3, 5, 7])
            tracks_v = tv.update(raw_v, frame=small)
            claimed_v: set[str] = set()
            for tr in _sort_vehicle_tracks_for_assoc(tracks_v, session.associator, cid, now):
                emb, fuse = _vehicle_fuse_from_track(tr, small, models)
                if emb is None:
                    continue
                g = session.associator.associate(
                    object_type="vehicle", camera_id=cid, embedding=emb,
                    identity_key=fuse.get("identityKey"), plate=fuse.get("plate"),
                    local_track_id=int(tr.track_id), exclude_gids=claimed_v, now=now,
                )
                claimed_v.add(g.global_id)
                _record_track(eval_state, "vehicle", cid, int(tr.track_id), g.global_id, now)

                # t=28 cam71 / t=29 cam81：记录最大 car
                want_t = 28.0 if cid == 71 else 29.0
                if abs(t - want_t) < 0.01:
                    area = (tr.bbox[2] - tr.bbox[0]) * (tr.bbox[3] - tr.bbox[1])
                    key = f"cam{cid}"
                    prev = snap.get(key)
                    if prev is None or area > prev["area"]:
                        snap[key] = {
                            "t": t, "local": int(tr.track_id), "global": g.global_id,
                            "area": area, "conf": tr.conf, "plate": fuse.get("plate"),
                        }

    for cap in caps.values():
        cap.release()

    print("=== t=28/29 largest car globals ===")
    for key in ("cam71", "cam81"):
        s = snap.get(key)
        if s:
            print(f"{key}: t={s['t']}s local=L{s['local']} global={s['global']} conf={s['conf']:.2f} plate={s['plate']!r}")
        else:
            print(f"{key}: no snapshot")

    g71 = snap.get("cam71", {}).get("global")
    g81 = snap.get("cam81", {}).get("global")
    if g71 and g81:
        print(f"SAME_GLOBAL={g71 == g81} ({g71} vs {g81})")
    else:
        print("SAME_GLOBAL=unknown (missing snapshot)")

    # 列出 t<=35 的跨镜 vehicle events
    print("\n=== vehicle cross events (t<=35) ===")
    for e in eval_state.cross_events:
        if e.get("objectType") == "vehicle" and e.get("transitSec", 99) <= 35:
            print(e)


if __name__ == "__main__":
    main()
