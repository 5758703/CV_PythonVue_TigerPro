"""快速重测失败用例 02/05/06。"""
import sys, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from scripts.diag_vehicle_cross_cam_batch import CASES, ref_embedding, isolated_test, flow_test, load_models, cosine

FAIL_CASES = [c for c in CASES if c[0].startswith(("02", "05", "06"))]
models = load_models()
for name, t71, t81, pref in FAIL_CASES:
    print(f"\n=== {name} ===")
    refs = ref_embedding(t71, t81, pref, models)
    if refs.get(71) and refs.get(81):
        print(f"visual_cosine={cosine(refs[71]['emb'], refs[81]['emb']):.4f}")
    iso = isolated_test(refs)
    t_start = max(0.0, min(t71, t81) - 25.0)
    flow = flow_test(t71, t81, refs, max(t71, t81) + 5.0, t_start=t_start)
    ok = iso.get("ok") and flow.get("ok")
    print(f"isolated={'PASS' if iso.get('ok') else 'FAIL'} flow={'PASS' if flow.get('ok') else 'FAIL'} => {'PASS' if ok else 'FAIL'}")
    print(iso)
    print(flow)
