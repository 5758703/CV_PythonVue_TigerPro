"""调试用例 05/06：目标时刻全部 vehicle track 及 Global 分布。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.diag_vehicle_cross_cam_batch import CASES, ref_embedding, load_models, cosine
from scripts.eval_mtmc_cross_cam import build_session, open_captures, resize_frame, _vehicle_fuse_from_track
from services.mtmc_engine import _detect, _sort_vehicle_tracks_for_assoc, supplement_orphan_vehicle_dets
from services.mtmc_local_track import create_local_tracker

from services.vehicle_reid_feat import infer_vehicle_class

VEHICLE_CLS = [1, 2, 3, 5, 7]

def run_case(case_idx: int):
    name, t71, t81, pref = CASES[case_idx]
    models = load_models()
    refs = ref_embedding(t71, t81, pref, models)
    t_start = max(0.0, min(t71, t81) - 25.0)
    dur = max(t71, t81) + 5.0

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

    total = int((dur - t_start) * 2) + 1
    rows_by_t: dict[float, dict] = {}

    for si in range(total):
        t = t_start + si / 2.0
        if t > dur:
            break
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
            raw = _detect(det, small, 0.28, VEHICLE_CLS)
            tracks = trackers[cid].update(raw, frame=small)
            sh, sw = small.shape[:2]
            tracks = supplement_orphan_vehicle_dets(tracks, raw, frame_w=sw, frame_h=sh)
            claimed = set()
            tt = t71 if cid == 71 else t81
            if abs(t - tt) > 0.01:
                continue
            ref = refs[cid]["emb"]
            bucket = rows_by_t.setdefault(tt, {71: [], 81: []})
            for tr in _sort_vehicle_tracks_for_assoc(tracks, session.associator, cid, now):
                emb, fuse = _vehicle_fuse_from_track(tr, small, models)
                if emb is None:
                    continue
                sh, sw = small.shape[:2]
                vcls = infer_vehicle_class(
                    getattr(tr, "class_name", None), tr.bbox, frame_h=sh, frame_w=sw,
                )
                g = session.associator.associate(
                    object_type="vehicle", camera_id=cid, embedding=emb,
                    identity_key=fuse.get("identityKey"), plate=fuse.get("plate"),
                    vehicle_class=vcls,
                    local_track_id=int(tr.track_id), exclude_gids=claimed, now=now,
                )
                claimed.add(g.global_id)
                bucket[cid].append({
                    "local": int(tr.track_id),
                    "global": g.global_id,
                    "mode": session.associator.last_mode.value,
                    "cos": cosine(emb, ref),
                    "conf": tr.conf,
                    "cls": vcls or getattr(tr, "class_name", None),
                    "plate": fuse.get("plate"),
                })

    for cap in caps.values():
        cap.release()

    print(f"\n{'='*60}\n{name}  t71={t71} t81={t81}\n{'='*60}")
    for tt in sorted(rows_by_t.keys()):
        for cid in (71, 81):
            print(f"\n--- cam{cid} t={tt}s ---")
            for r in sorted(rows_by_t[tt][cid], key=lambda x: -x["cos"]):
                mark = " ***" if r["cos"] > 0.88 else ""
                print(
                    f"  L{r['local']:2d} {r['global']} mode={r['mode']:8s} "
                    f"cos={r['cos']:.3f} conf={r['conf']:.2f} cls={r.get('cls')!r} plate={r['plate']!r}{mark}"
                )
        g71 = {r["global"] for r in rows_by_t[tt][71]}
        g81 = {r["global"] for r in rows_by_t[tt][81]}
        shared = g71 & g81
        print(f"\nshared globals: {shared or '(none)'}")
        for gid in shared:
            c71 = max(r["cos"] for r in rows_by_t[tt][71] if r["global"] == gid)
            c81 = max(r["cos"] for r in rows_by_t[tt][81] if r["global"] == gid)
            print(f"  {gid}: cam71 cos={c71:.3f} cam81 cos={c81:.3f}")


if __name__ == "__main__":
    for idx in (2, 3):
        run_case(idx)
