"""快速验证难例 isolated（视频+截图 ref）。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.diag_person_cross_cam_batch import (
    PERSON_CASES,
    cosine,
    isolated_test,
    load_models,
    ref_from_screenshot,
    ref_from_video,
)

HARD = [0, 2, 5, 6, 7, 8]  # 含 01 对照 + 难例


def main():
    models = load_models()
    passed = 0
    for i in HARD:
        name, t71, t81 = PERSON_CASES[i]
        refs = ref_from_screenshot(i, models)
        src = "shot"
        if not refs.get(71) or not refs.get(81):
            refs = ref_from_video(t71, t81, models, conf=0.12)
            src = "video"
        if not refs.get(71) or not refs.get(81):
            print(f"{i} {name} NO_REF")
            continue
        c = cosine(refs[71]["emb"], refs[81]["emb"])
        iso = isolated_test(refs)
        ok = bool(iso.get("ok"))
        passed += int(ok)
        print(f"{i} {name} src={src} cos={c:.3f} isolated={'PASS' if ok else 'FAIL'}")
    print(f"hard isolated {passed}/{len(HARD)}")
    return 0 if passed == len(HARD) else 1


if __name__ == "__main__":
    raise SystemExit(main())
