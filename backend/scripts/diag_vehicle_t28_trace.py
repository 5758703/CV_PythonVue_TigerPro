"""追踪 t=20~35s 车辆 local/global 绑定，定位黑 sedan 跨镜失败原因。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import cv2
import numpy as np

from scripts.diag_vehicle_t28 import P71, P81, analyze_car, load_frame
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
from services.mtmc_engine import _detect, _crop, _sort_vehicle_tracks_for_assoc
from services.mtmc_local_track import create_local_tracker
from services.vehicle_reid_feat import cosine


def ref_emb():
    from app import create_app
    from models import AiModel
    from routes.mtmc import _abs_weight, _build_ocr_fn, _pick_model
    app = create_app()
    with app.app_context():
        det = _abs_weight(AiModel.query.filter_by(model_key="yolo26n", status="0").first())
        vr = _abs_weight(_pick_model(None, keys=["transreid-vehicle"]))
        plate_path = _abs_weight(_pick_model(None, keys=["yolo26s-plate-pose", "yolo26n-plate"]))
        ocr_fn = _build_ocr_fn(None, None)
    f71 = load_frame(P71, 28.0, 20.0)
    f81 = load_frame(P81, 29.0, 25.0)
    d71 = _detect(det, f71, 0.28, [1, 2, 3, 5, 7])
    d81 = _detect(det, f81, 0.28, [1, 2, 3, 5, 7])
    c71 = analyze_car(d71, f71, vr, plate_path, ocr_fn)
    c81 = analyze_car(d81, f81, vr, plate_path, ocr_fn)
    return c71["emb"], c81["emb"]


def main():
    ref71, ref81 = ref_emb()
    print(f"ref visual_cosine={cosine(ref71, ref81):.4f}")

    models = load_models()
    session = build_session(models, 2.0)
    eval_state = EvalState()
    caps, meta = open_captures()
    det = models["det_person_path"]
    base_ts = 1.7e9
    dur = 35.0
    sample_fps = 2.0

    trackers = {
        v["camera_id"]: create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3)
        for v in VIDEOS
    }
    frame_idx = {v["camera_id"]: 0 for v in VIDEOS}
    step = {v["camera_id"]: max(1, int(round(meta[v["camera_id"]]["fps"] / sample_fps))) for v in VIDEOS}
    max_frame = {v["camera_id"]: int(dur * meta[v["camera_id"]]["fps"]) for v in VIDEOS}
    total_steps = max(1, int(dur * sample_fps))

    bind_log: list[tuple] = []

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
            tv = trackers[cid]
            raw_v = _detect(det, small, 0.28, [1, 2, 3, 5, 7])
            tracks_v = tv.update(raw_v, frame=small)
            claimed_v: set[str] = set()
            for tr in _sort_vehicle_tracks_for_assoc(tracks_v, session.associator, cid, now):
                emb, fuse = _vehicle_fuse_from_track(tr, small, models)
                if emb is None:
                    continue
                mode_before = session.associator.last_mode
                g = session.associator.associate(
                    object_type="vehicle", camera_id=cid, embedding=emb,
                    identity_key=fuse.get("identityKey"), plate=fuse.get("plate"),
                    local_track_id=int(tr.track_id), exclude_gids=claimed_v, now=now,
                )
                claimed_v.add(g.global_id)
                _record_track(eval_state, "vehicle", cid, int(tr.track_id), g.global_id, now)

                ref = ref71 if cid == 71 else ref81
                cos_ref = cosine(emb, ref)
                if 26 <= t <= 32:
                    bind_log.append((
                        t, cid, int(tr.track_id), g.global_id,
                        session.associator.last_mode.value if session.associator.last_mode else "?",
                        tr.conf, cos_ref,
                    ))

    for cap in caps.values():
        cap.release()

    print("\n=== tracks t=26~32 (cos_ref vs t=28/29 ref) ===")
    for row in bind_log:
        t, cid, lid, gid, mode, conf, cos_ref = row
        mark = " ***" if cos_ref > 0.85 else ""
        print(f"t={t:4.1f} cam{cid} L{lid:2d} {gid} mode={mode:8s} conf={conf:.2f} cos_ref={cos_ref:.3f}{mark}")

    # 找 cos_ref 最高的 cam71 / cam81 在 t=28/29
    for cid, tt in ((71, 28.0), (81, 29.0)):
        rows = [r for r in bind_log if r[1] == cid and abs(r[0] - tt) < 0.01]
        if not rows:
            print(f"cam{cid} t={tt}: no tracks")
            continue
        best = max(rows, key=lambda r: r[6])
        print(f"\ncam{cid} t={tt} best_match: L{best[2]} {best[3]} cos_ref={best[6]:.3f}")

    g71 = max([r for r in bind_log if r[1] == 71 and abs(r[0] - 28) < 0.01], key=lambda r: r[6], default=None)
    g81 = max([r for r in bind_log if r[1] == 81 and abs(r[0] - 29) < 0.01], key=lambda r: r[6], default=None)
    if g71 and g81:
        print(f"\nSAME_GLOBAL (by cos_ref)={g71[3] == g81[3]} ({g71[3]} vs {g81[3]})")


if __name__ == "__main__":
    main()
