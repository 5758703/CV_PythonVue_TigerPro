"""Print detection/track bbox area at a timestamp."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.diag_vehicle_cross_cam_batch import load_models, load_frame, P81
from scripts.eval_mtmc_cross_cam import resize_frame
from services.mtmc_engine import _detect
from services.mtmc_local_track import create_local_tracker

t = float(sys.argv[1]) if len(sys.argv) > 1 else 127.0
models = load_models()
det = models["det_person_path"]
frame = load_frame(P81, t, 25.0)
small = resize_frame(frame)
h, w = small.shape[:2]
dets = _detect(det, small, 0.28, [1, 2, 3, 5, 7])
tr = create_local_tracker("bytetrack")
tracks = tr.update(dets, frame=small)
print(f"cam81 t={t}s frame={w}x{h}")
for d in sorted(dets, key=lambda x: -((x["bbox"][2] - x["bbox"][0]) * (x["bbox"][3] - x["bbox"][1]))):
    b = d["bbox"]
    ar = (b[2] - b[0]) * (b[3] - b[1]) / (w * h)
    print(f"  det cls={d.get('className')} conf={d['confidence']:.2f} area={ar:.3f}")
for t0 in tracks:
    b = t0.bbox
    ar = (b[2] - b[0]) * (b[3] - b[1]) / (w * h)
    cls = getattr(t0, "class_name", None)
    print(f"  track L{t0.track_id} cls={cls} conf={t0.conf:.2f} area={ar:.3f}")
