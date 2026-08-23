"""L3/L4 跨镜误合并诊断：计算 t=27 两路 embedding 余弦。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.eval_mtmc_cross_cam import load_models, open_captures, resize_frame, _vehicle_fuse_from_track
from services.mtmc_engine import _detect
from services.mtmc_local_track import create_local_tracker
from services.vehicle_reid_feat import cosine
import cv2

P71 = os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "camera_192_168_8_71_20260820_094046.mp4")
P81 = os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "camera_192_168_8_81_20260820_094044.mp4")


def frame_at(path, t, fps):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ok, f = cap.read()
    cap.release()
    h, w = f.shape[:2]
    return cv2.resize(f, (640, max(1, int(h * 640 / w))))


def main():
    models = load_models()
    det = models["det_person_path"]
    f71 = frame_at(P71, 27.0, 20.0)
    f81 = frame_at(P81, 27.0, 25.0)
    for tag, f in ("71", f71), ("81", f81):
        tr = create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3)
        # warm up a few frames
        for _ in range(54):
            tr.update(_detect(det, f, 0.28, [1, 2, 3, 5, 7]), frame=f)
        tracks = tr.update(_detect(det, f, 0.28, [1, 2, 3, 5, 7]), frame=f)
        print(f"cam{tag} tracks:", [(t.track_id, round(t.conf, 2)) for t in tracks])

    # run interleaved to t=27 and capture L3/L4 embeddings
    from scripts.eval_mtmc_cross_cam import build_session, EvalState, _record_track
    session = build_session(models, 2.0)
    caps, meta = open_captures()
    trackers = {71: create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3),
                81: create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3)}
    fi = {71: 0, 81: 0}
    step = {71: 10, 81: 12}
    emb_snap = {}
    for si in range(55):
        t = si / 2.0
        for cid in (71, 81):
            cap = caps[cid]
            target = min(si * step[cid], int(35 * meta[cid]["fps"]))
            cur = fi[cid]
            while cur < target:
                cap.grab()
                cur += 1
            ok, frame = cap.read()
            cur += 1
            fi[cid] = cur
            if not ok:
                continue
            small = resize_frame(frame)
            tracks = trackers[cid].update(_detect(det, small, 0.28, [1, 2, 3, 5, 7]), frame=small)
            claimed = set()
            for tr in tracks:
                e, fuse = _vehicle_fuse_from_track(tr, small, models)
                if e is None:
                    continue
                session.associator.associate(
                    object_type="vehicle", camera_id=cid, embedding=e,
                    identity_key=fuse.get("identityKey"), plate=fuse.get("plate"),
                    local_track_id=int(tr.track_id), exclude_gids=claimed, now=1.7e9 + t,
                )
                claimed.add(session.associator.last_evidence.target_global_id if session.associator.last_evidence else "")
                if abs(t - 27.0) < 0.01 and int(tr.track_id) in (3, 4, 5):
                    emb_snap[(cid, int(tr.track_id))] = e
    for cap in caps.values():
        cap.release()

    if (71, 3) in emb_snap and (81, 4) in emb_snap:
        print(f"L3/L4 cosine={cosine(emb_snap[(71,3)], emb_snap[(81,4)]):.4f}")
    if (71, 5) in emb_snap and (81, 4) in emb_snap:
        print(f"L5/L4 cosine={cosine(emb_snap[(71,5)], emb_snap[(81,4)]):.4f}")
    if (71, 5) in emb_snap and (71, 3) in emb_snap:
        print(f"L5/L3 cosine={cosine(emb_snap[(71,5)], emb_snap[(71,3)]):.4f}")


if __name__ == "__main__":
    main()
