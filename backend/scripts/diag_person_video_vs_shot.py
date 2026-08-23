"""对比截图配对 vs 视频帧配对的行人 cos。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from scripts.diag_person_cross_cam_batch import (
    PERSON_CASES,
    P71,
    P81,
    cosine,
    load_frame,
    load_models,
    ref_from_screenshot,
)
from services.mtmc_engine import _crop, _detect
from services.reid_gallery import l2_normalize
from services.strong_reid import extract_person_embedding


def persons_at(path, t, fps, models, conf=0.15):
    frame = load_frame(path, t, fps)
    if frame is None:
        return []
    dets = _detect(models["det_person_path"], frame, conf, [0])
    out = []
    for d in dets:
        crop = _crop(frame, d["bbox"])
        if crop is None:
            continue
        emb, _ = extract_person_embedding(
            crop, youtu_root=models["youtu_root"], strong_root=models["strong_reid_root"],
        )
        out.append({"emb": l2_normalize(emb), "conf": d["confidence"], "bbox": d["bbox"]})
    return out


def best_pair(a, b):
    best = (-1.0, None, None)
    for x in a:
        for y in b:
            c = cosine(x["emb"], y["emb"])
            if c > best[0]:
                best = (c, x, y)
    return best


def main():
    models = load_models()
    for i in [2, 5, 6, 7, 8]:
        name, t71, t81 = PERSON_CASES[i]
        print(f"\n=== {i} {name} ===")
        refs = ref_from_screenshot(i, models)
        if refs.get(71) and refs.get(81):
            print(f"  shot_pair cos={cosine(refs[71]['emb'], refs[81]['emb']):.3f}")
        else:
            print("  shot_pair NO_REF")
        for conf in (0.28, 0.15, 0.10):
            a = persons_at(P71, t71, 20.0, models, conf=conf)
            b = persons_at(P81, t81, 25.0, models, conf=conf)
            c, _, _ = best_pair(a, b)
            print(f"  video conf>={conf:.2f} n71={len(a)} n81={len(b)} best_cos={c:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
