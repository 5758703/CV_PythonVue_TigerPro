"""诊断 t=28/29s 两路同一黑 sedan 跨镜关联。"""
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


def load_frame(path: str, t: float, fps: float):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ok, f = cap.read()
    cap.release()
    if not ok:
        return None
    h, w = f.shape[:2]
    return cv2.resize(f, (640, max(1, int(h * 640 / w))))


def analyze_car(dets, frame, vr, plate_path, ocr_fn, pick="largest"):
    cars = [d for d in dets if d.get("className") == "car"] or dets
    if not cars:
        return None
    if pick == "largest":
        d = max(cars, key=lambda x: (x["bbox"][2] - x["bbox"][0]) * (x["bbox"][3] - x["bbox"][1]))
    else:
        d = max(cars, key=lambda x: x["confidence"])
    crop = _crop(frame, d["bbox"])
    emb, _ = extract_vehicle_embedding(vr, crop)
    plate, ps = None, 0.0
    if ocr_fn and plate_path:
        for pb, src, _q, warp in _plate_candidates(d["bbox"], frame, plate_path, 0.15):
            ocr = _ocr_plate(ocr_fn, frame, pb, warped=warp)
            txt = ocr.get("text")
            if txt:
                plate, ps = txt, float(ocr.get("score") or 0)
                print(f"    plate cand {src}: {plate!r} score={ps:.2f}")
    fuse = fuse_plate_visual(plate=plate, plate_score=ps, emb_a=emb, emb_b=emb)
    return {"bbox": d["bbox"], "conf": d["confidence"], "emb": emb, "plate": plate, "plateScore": ps, "fuse": fuse}


def main():
    app = create_app()
    with app.app_context():
        det = _abs_weight(AiModel.query.filter_by(model_key="yolo26n", status="0").first())
        vr = _abs_weight(_pick_model(None, keys=["transreid-vehicle"]))
        plate_path = _abs_weight(_pick_model(None, keys=["yolo26s-plate-pose", "yolo26n-plate"]))
        ocr_fn = _build_ocr_fn(None, None)

    t71, t81 = 28.0, 29.0
    f71 = load_frame(P71, t71, 20.0)
    f81 = load_frame(P81, t81, 25.0)
    d71 = _detect(det, f71, 0.28, [1, 2, 3, 5, 7])
    d81 = _detect(det, f81, 0.28, [1, 2, 3, 5, 7])
    print(f"cam71 t={t71}s dets={len(d71)}")
    c71 = analyze_car(d71, f71, vr, plate_path, ocr_fn)
    print(f"cam81 t={t81}s dets={len(d81)}")
    c81 = analyze_car(d81, f81, vr, plate_path, ocr_fn)

    for tag, c in ("cam71", c71), ("cam81", c81):
        if not c:
            print(tag, "no car")
            continue
        print(tag, f"conf={c['conf']:.2f} bbox={[round(x,1) for x in c['bbox']]} plate={c['plate']!r} ik={c['fuse'].get('identityKey')}")

    if c71 and c81:
        print(f"visual_cosine={cosine(c71['emb'], c81['emb']):.4f}")

    now = 1_700_000_028.0
    assoc = MtmcAssociator(appear_thresh=0.48, vehicle_appear_thresh=0.48, confirm_thresh=0.48, time_window_sec=120)
    g1 = assoc.associate(
        object_type="vehicle", camera_id=71, embedding=c71["emb"],
        identity_key=c71["fuse"].get("identityKey"), plate=c71["plate"],
        local_track_id=1, exclude_gids=set(), now=now,
    )
    g2 = assoc.associate(
        object_type="vehicle", camera_id=81, embedding=c81["emb"],
        identity_key=c81["fuse"].get("identityKey"), plate=c81["plate"],
        local_track_id=3, exclude_gids=set(), now=now + 1.0,
    )
    print("cam71 ->", g1.global_id, g2.global_id == g1.global_id and "MATCH" or "cam81 ->", g2.global_id, "mode=", g2.last_assoc_mode)
    if assoc.last_evidence:
        print("evidence reid=", assoc.last_evidence.reid_score)


if __name__ == "__main__":
    main()
