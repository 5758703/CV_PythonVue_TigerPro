"""快速跑 9 组行人 isolated 关联。"""
import sys
import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from scripts.diag_person_cross_cam_batch import (
    PERSON_CASES, ref_from_screenshot, load_models, isolated_test, cosine,
)

models = load_models()
passed = 0
for i, (name, _, _) in enumerate(PERSON_CASES):
    refs = ref_from_screenshot(i, models)
    if not (refs.get(71) and refs.get(81)):
        print(i, name, "NO_REF")
        continue
    c = cosine(refs[71]["emb"], refs[81]["emb"])
    ok = isolated_test(refs)["ok"]
    passed += int(ok)
    print(f"{i} {name} cos={c:.3f} isolated={'PASS' if ok else 'FAIL'}")
print(f"isolated total {passed}/{len(PERSON_CASES)}")
