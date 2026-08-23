"""单独跑某一用例 flow（默认 case 06）。"""
import sys, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from scripts.diag_vehicle_cross_cam_batch import CASES, ref_embedding, flow_test, load_models, cosine

idx = int(sys.argv[1]) if len(sys.argv) > 1 else 3
name, t71, t81, pref = CASES[idx]
models = load_models()
refs = ref_embedding(t71, t81, pref, models)
print(f"{name} visual_cosine={cosine(refs[71]['emb'], refs[81]['emb']):.4f}")
t_start = max(0.0, min(t71, t81) - 25.0)
flow = flow_test(t71, t81, refs, max(t71, t81) + 5.0, t_start=t_start)
print(flow)
