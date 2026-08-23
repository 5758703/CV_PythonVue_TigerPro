"""按参考 bbox IoU 定位 t=28/29 黑 sedan 的 local/global。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.diag_vehicle_t28 import P71, P81, load_frame
from scripts.eval_mtmc_cross_cam import (
    EvalState,
    _record_track,
    _vehicle_fuse_from_track,
    build_session,
    load_models,
    open_captures,
    resize_frame,
)
from services.mtmc_engine import _detect
from services.mtmc_local_track import create_local_tracker

REF71 = [315.7, 169.4, 470.9, 264.5]
REF81 = [459.8, 290.1, 639.5, 359.1]


def iou(a, b):
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    aa = (a[2] - a[0]) * (a[3] - a[1])
    bb = (b[2] - b[0]) * (b[3] - b[1])
    return inter / max(aa + bb - inter, 1e-6)


def main():
    models = load_models()
    session = build_session(models, 2.0)
    caps, meta = open_captures()
    det = models["det_person_path"]
    base = 1.7e9
    trackers = {
        71: create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3),
        81: create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3),
    }
    fi = {71: 0, 81: 0}
    step = {71: 10, 81: 12}
    mf = {71: 700, 81: 875}
    snap = {}

    for si in range(61):
        t = si / 2.0
        for cid in (71, 81):
            cap = caps[cid]
            target = min(si * step[cid], mf[cid])
            cur = fi[cid]
            while cur < target:
                cap.grab()
                cur += 1
            if cur > mf[cid]:
                fi[cid] = cur
                continue
            ok, frame = cap.read()
            cur += 1
            fi[cid] = cur
            if not ok:
                continue
            small = resize_frame(frame)
            tracks = trackers[cid].update(
                _detect(det, small, 0.28, [1, 2, 3, 5, 7]), frame=small,
            )
            claimed = set()
            ref = REF71 if cid == 71 else REF81
            tt = 28.0 if cid == 71 else 29.0
            for tr in tracks:
                emb, fuse = _vehicle_fuse_from_track(tr, small, models)
                if emb is None:
                    continue
                g = session.associator.associate(
                    object_type="vehicle", camera_id=cid, embedding=emb,
                    identity_key=fuse.get("identityKey"), plate=fuse.get("plate"),
                    local_track_id=int(tr.track_id), exclude_gids=claimed, now=base + t,
                )
                claimed.add(g.global_id)
                if abs(t - tt) < 0.01:
                    row = (int(tr.track_id), g.global_id, tr.conf, iou(tr.bbox, ref))
                    prev = snap.get(cid)
                    if prev is None or row[3] > prev[3]:
                        snap[cid] = row

    for cap in caps.values():
        cap.release()

    for cid in (71, 81):
        if cid not in snap:
            print(f"cam{cid}: no match")
            continue
        lid, gid, conf, ov = snap[cid]
        print(f"cam{cid}: L{lid} {gid} conf={conf:.2f} iou_ref={ov:.3f}")

    if 71 in snap and 81 in snap:
        print(f"SAME_GLOBAL={snap[71][1] == snap[81][1]}")


if __name__ == "__main__":
    main()
