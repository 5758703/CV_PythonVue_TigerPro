"""Flow 到指定时刻，打印 cam81 全部 vehicle track + raw det。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.diag_vehicle_cross_cam_batch import load_models, CASES
from scripts.eval_mtmc_cross_cam import build_session, open_captures, resize_frame
from services.mtmc_engine import _detect
from services.mtmc_local_track import create_local_tracker

case_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 2
name, t71, t81, _ = CASES[case_idx]
t_target = float(sys.argv[2]) if len(sys.argv) > 2 else t81
cid = 81

models = load_models()
build_session(models, 2.0)
caps, meta = open_captures()
det = models["det_person_path"]
tracker = create_local_tracker("bytetrack", max_age=30, iou_thresh=0.3)
t_start = max(0.0, min(t71, t81) - 25.0)
dur = t_target + 1.0
fi = 0
cap = caps[cid]
tf = int(t_start * meta[cid]["fps"])
cur = 0
while cur < tf:
    cap.grab()
    cur += 1
fi = cur
step = max(1, int(round(meta[cid]["fps"] / 2.0)))
total = int((dur - t_start) * 2) + 1
for si in range(total):
    t = t_start + si / 2.0
    target = min(int(t * meta[cid]["fps"]), int(dur * meta[cid]["fps"]))
    while fi < target:
        if not cap.grab():
            break
        fi += 1
    ok, frame = cap.read()
    fi += 1
    if not ok:
        continue
    small = resize_frame(frame)
    h, w = small.shape[:2]
    dets = _detect(det, small, 0.28, [1, 2, 3, 5, 7])
    tracks = tracker.update(dets, frame=small)
    if abs(t - t_target) > 0.01:
        continue
    print(f"{name} cam{cid} t={t:.1f}s")
    for d in sorted(dets, key=lambda x: -((x["bbox"][2] - x["bbox"][0]) * (x["bbox"][3] - x["bbox"][1]))):
        b = d["bbox"]
        ar = (b[2] - b[0]) * (b[3] - b[1]) / (w * h)
        print(f"  det cls={d.get('className')} conf={d['confidence']:.2f} area={ar:.3f}")
    for tr in tracks:
        b = tr.bbox
        ar = (b[2] - b[0]) * (b[3] - b[1]) / (w * h)
        print(f"  track L{tr.track_id} cls={getattr(tr, 'class_name', None)} conf={tr.conf:.2f} area={ar:.3f} new={getattr(tr, 'is_new', False)}")
    break
cap.release()
caps[71].release()
