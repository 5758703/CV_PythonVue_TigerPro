"""诊断行人难例 03/06/07/08/09：半幅检测数、最佳配对 cos、isolated。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.diag_person_cross_cam_batch import (
    PERSON_CASES,
    PERSON_SCREENSHOTS,
    _imread,
    _person_embeddings_from_half,
    cosine,
    isolated_test,
    load_models,
    ref_from_screenshot,
)

HARD = [2, 5, 6, 7, 8]  # 03,06,07,08,09


def main():
    models = load_models()
    print(f"screenshots={len(PERSON_SCREENSHOTS)}")
    for i in HARD:
        name, t71, t81 = PERSON_CASES[i]
        path = PERSON_SCREENSHOTS[i] if i < len(PERSON_SCREENSHOTS) else None
        print(f"\n=== {i} {name} t71={t71} t81={t81} ===")
        print(f"  file={os.path.basename(path) if path else None}")
        if not path:
            continue
        img = _imread(path)
        if img is None:
            print("  READ_FAIL")
            continue
        h, w = img.shape[:2]
        for cid, half in ((71, img[:, : w // 2]), (81, img[:, w // 2 :])):
            pool = _person_embeddings_from_half(half, models)
            confs = [round(float(p["conf"]), 2) for p in pool]
            print(f"  cam{cid} n={len(pool)} confs={confs}")
        refs = ref_from_screenshot(i, models)
        if refs.get(71) and refs.get(81):
            c = cosine(refs[71]["emb"], refs[81]["emb"])
            iso = isolated_test(refs)
            print(f"  best_pair cos={c:.3f} isolated={iso['ok']} g71={iso.get('g71')} g81={iso.get('g81')}")
        else:
            print("  NO_REF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
