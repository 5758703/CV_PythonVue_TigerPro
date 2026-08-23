"""模拟 MTMC 双视频：统计 local track 与 Global 分配。"""
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import cv2

from services.mtmc_associator import MtmcAssociator
from services.mtmc_engine import MtmcConfig, _detect, _crop
from services.mtmc_local_track import create_local_tracker
from services.vehicle_reid_feat import extract_vehicle_embedding, fuse_plate_visual
from services.strong_reid import extract_person_embedding
from services.reid_gallery import l2_normalize

VIDEOS = [
    ("cam71", os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "camera_192_168_8_71_20260820_094046.mp4")),
    ("cam81", os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "camera_192_168_8_81_20260820_094044.mp4")),
]


def find_model_path():
    from app import create_app
    from models import AiModel
    from routes.mtmc import _abs_weight

    app = create_app()
    with app.app_context():
        m = AiModel.query.filter_by(model_key="yolo26n", status="0").first()
        youtu = AiModel.query.filter_by(model_key="opencv-person-reid-youtu", status="0").first()
        return _abs_weight(m), _abs_weight(youtu)


def process_video(name, path, cam_id, model_path, youtu_root, assoc, tracker_p, tracker_v, claimed_p, claimed_v):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    step = max(1, int(round(fps / 2)))
    frame_idx = 0
    globals_p, globals_v = set(), set()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % step != 0:
            frame_idx += 1
            continue
        now = frame_idx / fps
        fh, fw = frame.shape[:2]
        # person
        for t in tracker_p.update(_detect(model_path, frame, 0.28, [0]), frame=frame):
            crop = _crop(frame, t.bbox)
            if crop is None:
                continue
            try:
                emb, _ = extract_person_embedding(crop, youtu_root=youtu_root, strong_root=None)
                emb = l2_normalize(emb)
            except Exception:
                emb = None
            if emb is None:
                continue
            g = assoc.associate(
                object_type="person", camera_id=cam_id, embedding=emb,
                local_track_id=int(t.track_id), exclude_gids=claimed_p, now=now,
            )
            claimed_p.add(g.global_id)
            globals_p.add(g.global_id)
        # vehicle
        for t in tracker_v.update(_detect(model_path, frame, 0.28, [1, 2, 3, 5, 7]), frame=frame):
            crop = _crop(frame, t.bbox)
            if crop is None:
                continue
            emb, _ = extract_vehicle_embedding(None, crop)
            fuse = fuse_plate_visual(plate=None, plate_score=0, emb_a=emb, emb_b=emb)
            g = assoc.associate(
                object_type="vehicle", camera_id=cam_id, embedding=emb,
                identity_key=fuse.get("identityKey"), local_track_id=int(t.track_id),
                exclude_gids=claimed_v, now=now,
            )
            claimed_v.add(g.global_id)
            globals_v.add(g.global_id)
        frame_idx += 1
        if frame_idx > fps * 30:
            break
    cap.release()
    print(f"{name}: person_globals={len(globals_p)} vehicle_globals={len(globals_v)}")
    return globals_p, globals_v


def main():
    model_path, youtu_root = find_model_path()
    print("model", model_path)
    assoc = MtmcAssociator(
        appear_thresh=0.48,
        vehicle_appear_thresh=0.62,
        confirm_thresh=0.48,
        candidate_thresh=0.35,
        time_window_sec=120,
    )
    tp = create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3)
    tv = create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3)
    claimed_p, claimed_v = set(), set()
    all_p, all_v = set(), set()
    for name, path in VIDEOS:
        if not os.path.isfile(path):
            print("missing", path)
            continue
        tp2 = create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3)
        tv2 = create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3)
        gp, gv = process_video(name, path, 71 if "71" in name else 81, model_path, youtu_root, assoc, tp2, tv2, claimed_p, claimed_v)
        all_p |= gp
        all_v |= gv
    print("TOTAL person_globals", len(all_p), "vehicle_globals", len(all_v))
    print("vehicle tracks in associator", sum(1 for g in assoc.tracks.values() if g.object_type == "vehicle"))


if __name__ == "__main__":
    main()
