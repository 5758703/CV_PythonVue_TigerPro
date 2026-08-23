"""诊断 t=65s 两路同一绿牌车跨镜关联。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import cv2

from app import create_app
from models import AiModel
from routes.mtmc import _abs_weight, _build_ocr_fn, _pick_model
from services.mtmc_engine import _detect, _crop
from services.vehicle_reid_feat import extract_vehicle_embedding, fuse_plate_visual, cosine
from services.vehicle_track import _plate_candidates, _ocr_plate
from services.mtmc_associator import MtmcAssociator

P71 = os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "camera_192_168_8_71_20260820_094046.mp4")
P81 = os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "camera_192_168_8_81_20260820_094044.mp4")
T_SEC = 65.0


def load_frame(path: str, t: float, fps: float):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ok, f = cap.read()
    cap.release()
    if not ok:
        return None
    h, w = f.shape[:2]
    return cv2.resize(f, (640, max(1, int(h * 640 / w))))


def best_car(dets, frame, vr, plate_path, ocr_fn):
    cars = [d for d in dets if d.get("className") == "car"]
    if not cars:
        cars = dets
    if not cars:
        return None
    d = max(cars, key=lambda x: (x["bbox"][2] - x["bbox"][0]) * (x["bbox"][3] - x["bbox"][1]))
    crop = _crop(frame, d["bbox"])
    emb, _ = extract_vehicle_embedding(vr, crop)
    plate, ps = None, 0.0
    if ocr_fn and plate_path:
        for pb, _src, _q, warp in _plate_candidates(d["bbox"], frame, plate_path, 0.2):
            ocr = _ocr_plate(ocr_fn, frame, pb, warped=warp)
            if ocr.get("text"):
                plate = ocr.get("text")
                ps = float(ocr.get("score") or 0)
                break
    fuse = fuse_plate_visual(plate=plate, plate_score=ps, emb_a=emb, emb_b=emb)
    return {"bbox": d["bbox"], "conf": d["confidence"], "emb": emb, "plate": plate, "plateScore": ps, "fuse": fuse}


def main():
    app = create_app()
    with app.app_context():
        det = _abs_weight(AiModel.query.filter_by(model_key="yolo26n", status="0").first())
        vr = _abs_weight(_pick_model(None, keys=["transreid-vehicle"]))
        plate_m = _pick_model(None, keys=["yolo26s-plate-pose", "yolo26n-plate"])
        plate_path = _abs_weight(plate_m)
        ocr_fn = _build_ocr_fn(None, None)
        print("plate_model:", plate_path)
        print("ocr_fn:", ocr_fn is not None)

    f71 = load_frame(P71, T_SEC, 20.0)
    f81 = load_frame(P81, T_SEC, 25.0)
    d71 = _detect(det, f71, 0.28, [1, 2, 3, 5, 7])
    d81 = _detect(det, f81, 0.28, [1, 2, 3, 5, 7])
    c71 = best_car(d71, f71, vr, plate_path, ocr_fn)
    c81 = best_car(d81, f81, vr, plate_path, ocr_fn)

    for tag, c in ("cam71", c71), ("cam81", c81):
        if not c:
            print(tag, "no vehicle")
            continue
        print(
            tag,
            f"conf={c['conf']:.2f}",
            f"plate={c['plate']!r}",
            f"plateScore={c['plateScore']:.2f}",
            f"identityKey={c['fuse'].get('identityKey')}",
        )

    if c71 and c81:
        sim = cosine(c71["emb"], c81["emb"])
        print(f"visual_cosine={sim:.4f}")
        print(f"plates_equal={c71['plate'] and c81['plate'] and c71['plate']==c81['plate']}")

    now = 1_700_000_065.0
    assoc = MtmcAssociator(appear_thresh=0.48, vehicle_appear_thresh=0.48, confirm_thresh=0.48, time_window_sec=120)
    g1 = assoc.associate(
        object_type="vehicle", camera_id=71, embedding=c71["emb"],
        identity_key=c71["fuse"].get("identityKey"), plate=c71["plate"],
        local_track_id=1, exclude_gids=set(), now=now,
    )
    print("cam71 ->", g1.global_id, "plate=", g1.plate, "mode=", g1.last_assoc_mode)
    g2 = assoc.associate(
        object_type="vehicle", camera_id=81, embedding=c81["emb"],
        identity_key=c81["fuse"].get("identityKey"), plate=c81["plate"],
        local_track_id=3, exclude_gids=set(), now=now + 0.01,
    )
    print("cam81 ->", g2.global_id, "plate=", g2.plate, "mode=", g2.last_assoc_mode)
    print("SAME_GLOBAL=", g1.global_id == g2.global_id)
    if assoc.last_evidence:
        ev = assoc.last_evidence
        print("last_evidence:", ev.decision, "reid=", ev.reid_score, "final=", ev.final_score)


if __name__ == "__main__":
    main()
