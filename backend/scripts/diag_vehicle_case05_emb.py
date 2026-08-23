"""用例05：比较 t=126/127 各检测 embedding 与 ref 的余弦。"""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.diag_vehicle_cross_cam_batch import ref_embedding, load_models, cosine, CASES, load_frame
from services.mtmc_engine import _detect, _crop
from services.vehicle_reid_feat import extract_vehicle_embedding
from app import create_app
from models import AiModel
from routes.mtmc import _abs_weight, _pick_model

name, t71, t81, pref = CASES[2]
models = load_models()
refs = ref_embedding(t71, t81, pref, models)

app = create_app()
with app.app_context():
    det = _abs_weight(AiModel.query.filter_by(model_key="yolo26n", status="0").first())
    vr = _abs_weight(_pick_model(None, keys=["transreid-vehicle"]))

P71 = os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "camera_192_168_8_71_20260820_094046.mp4")
P81 = os.path.join(ROOT, "..", "docs", "test_data", "video", "camera_recordings", "camera_192_168_8_81_20260820_094044.mp4")

for label, path, t, fps in [("71@126", P71, 126, 20), ("81@127", P81, 127, 25)]:
    f = load_frame(path, t, fps)
    dets = _detect(det, f, 0.28, [1, 2, 3, 5, 7])
    trucks = sorted([d for d in dets if d.get("className") in ("truck", "car")],
                    key=lambda x: -((x["bbox"][2]-x["bbox"][0])*(x["bbox"][3]-x["bbox"][1])))
    print(f"\n{label} dets={len(trucks)}")
    embs = []
    for i, d in enumerate(trucks[:5]):
        crop = _crop(f, d["bbox"])
        emb, _ = extract_vehicle_embedding(vr, crop)
        cref = cosine(emb, refs[71]["emb"])
        print(f"  #{i} {d.get('className')} conf={d['confidence']:.2f} cos_ref71={cref:.3f}")
        embs.append(emb)
    if embs:
        print(f"  best cos_ref71={cosine(embs[0], refs[71]['emb']):.3f} cos_ref81={cosine(embs[0], refs[81]['emb']):.3f}")

if embs:
    f71 = load_frame(P71, 126, 20)
    dets71 = _detect(det, f71, 0.28, [1, 2, 3, 5, 7])
    trucks71 = sorted(dets71, key=lambda x: -((x["bbox"][2]-x["bbox"][0])*(x["bbox"][3]-x["bbox"][1])))[:3]
    f81 = load_frame(P81, 127, 25)
    dets81 = _detect(det, f81, 0.28, [1, 2, 3, 5, 7])
    trucks81 = sorted(dets81, key=lambda x: -((x["bbox"][2]-x["bbox"][0])*(x["bbox"][3]-x["bbox"][1])))[:3]
    e71 = [extract_vehicle_embedding(vr, _crop(f71, d["bbox"]))[0] for d in trucks71]
    e81 = [extract_vehicle_embedding(vr, _crop(f81, d["bbox"]))[0] for d in trucks81]
    print("\nCross cosines (top dets 71 vs 81):")
    for i, a in enumerate(e71):
        for j, b in enumerate(e81):
            print(f"  71#{i} vs 81#{j}: {cosine(a,b):.3f}")
