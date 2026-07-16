"""InsightFace PoC：下载 buffalo_s、测 CPU 推理延迟。

用法（在 backend 目录或任意处）:
  python scripts/poc_insightface.py
"""
from __future__ import annotations

import os
import sys
import time

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads", "insightface"))


def main():
    from insightface.app import FaceAnalysis

    pack = sys.argv[1] if len(sys.argv) > 1 else "buffalo_s"
    os.makedirs(ROOT, exist_ok=True)
    print(f"root={ROOT} pack={pack}")

    t0 = time.time()
    app = FaceAnalysis(name=pack, root=ROOT, providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    print(f"prepare: {time.time() - t0:.2f}s")

    # 合成图（无真实人脸时 faces 为空，仅测管线开销）
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(img, (200, 120), (440, 400), (180, 180, 180), -1)

    times = []
    for _ in range(5):
        t1 = time.time()
        faces = app.get(img)
        times.append((time.time() - t1) * 1000)
    print(f"infer_ms avg={sum(times)/len(times):.1f} last_n={len(faces)}")
    print("OK — 建议阈值余弦相似度 0.35~0.45，用真实登记库标定。")


if __name__ == "__main__":
    main()
