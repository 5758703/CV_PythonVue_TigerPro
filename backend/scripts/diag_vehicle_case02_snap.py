"""用例 02 目标时刻全部 vehicle track：Global / cos_ref / class。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.diag_vehicle_cross_cam_batch import CASES, load_models, ref_embedding, cosine
from scripts.eval_mtmc_cross_cam import (
    build_session,
    open_captures,
    resize_frame,
    _vehicle_fuse_from_track,
)
from services.mtmc_engine import (
    _detect,
    _sort_vehicle_tracks_for_assoc,
    supplement_orphan_vehicle_dets,
)
from services.mtmc_local_track import create_local_tracker
from services.vehicle_reid_feat import infer_vehicle_class

VEHICLE_CLS = [1, 2, 3, 5, 7]


def main():
    name, t71, t81, pref = CASES[0]
    models = load_models()
    refs = ref_embedding(t71, t81, pref, models)
    print(f"{name} ref_cos={cosine(refs[71]['emb'], refs[81]['emb']):.4f}")
    t_start = max(0.0, min(t71, t81) - 25.0)
    dur = max(t71, t81) + 2.0
    session = build_session(models, 2.0)
    caps, meta = open_captures()
    det = models["det_person_path"]
    trackers = {
        71: create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3),
        81: create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3),
    }
    fi = {71: 0, 81: 0}
    base = 1.7e9
    for cid in (71, 81):
        cap = caps[cid]
        tf = int(t_start * meta[cid]["fps"])
        cur = 0
        while cur < tf:
            cap.grab()
            cur += 1
        fi[cid] = cur

    snap = {71: [], 81: []}
    total = int((dur - t_start) * 2) + 1
    for si in range(total):
        t = t_start + si / 2.0
        for cid in (71, 81):
            cap = caps[cid]
            target = min(int(t * meta[cid]["fps"]), int(dur * meta[cid]["fps"]))
            cur = fi[cid]
            while cur < target:
                if not cap.grab():
                    break
                cur += 1
            ok, frame = cap.read()
            cur += 1
            fi[cid] = cur
            if not ok:
                continue
            now = base + t
            small = resize_frame(frame)
            sh, sw = small.shape[:2]
            raw = _detect(det, small, 0.28, VEHICLE_CLS)
            tracks = trackers[cid].update(raw, frame=small)
            tracks = supplement_orphan_vehicle_dets(tracks, raw, frame_w=sw, frame_h=sh)
            claimed = set()
            tt = t71 if cid == 71 else t81
            if abs(t - tt) > 0.01:
                continue
            ref = refs[cid]["emb"]
            for tr in _sort_vehicle_tracks_for_assoc(tracks, session.associator, cid, now):
                emb, fuse = _vehicle_fuse_from_track(tr, small, models)
                if emb is None:
                    continue
                vcls = infer_vehicle_class(
                    getattr(tr, "class_name", None), tr.bbox, frame_h=sh, frame_w=sw,
                )
                g = session.associator.associate(
                    object_type="vehicle",
                    camera_id=cid,
                    embedding=emb,
                    identity_key=fuse.get("identityKey"),
                    plate=fuse.get("plate"),
                    vehicle_class=vcls,
                    local_track_id=int(tr.track_id),
                    exclude_gids=claimed,
                    now=now,
                )
                claimed.add(g.global_id)
                ev = session.associator.last_evidence
                snap[cid].append({
                    "L": int(tr.track_id),
                    "G": g.global_id,
                    "mode": session.associator.last_mode.value,
                    "cos": cosine(emb, ref),
                    "cls": vcls,
                    "conf": tr.conf,
                    "reid": getattr(ev, "reid_score", None) if ev else None,
                    "final": getattr(ev, "final_score", None) if ev else None,
                    "plate": fuse.get("plate"),
                })

    for cid in (71, 81):
        print(f"\n--- cam{cid} ---")
        for r in sorted(snap[cid], key=lambda x: -x["cos"]):
            mark = " ***" if r["cos"] >= 0.85 else ""
            print(
                f"  L{r['L']:2d} {r['G']} mode={r['mode']:8s} cos={r['cos']:.3f} "
                f"cls={r['cls']} conf={r['conf']:.2f} reid={r['reid']} final={r['final']} "
                f"plate={r['plate']!r}{mark}"
            )
    shared = {r["G"] for r in snap[71]} & {r["G"] for r in snap[81]}
    print(f"\nshared={shared or '(none)'}")
    for cap in caps.values():
        cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
