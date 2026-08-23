"""从截图 VLC 时间戳区域粗读时刻（调试用）。"""
import glob
import os
import re
import sys

import cv2

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
img_dir = os.path.join(ROOT, "docs", "test_data", "images")
pattern = sys.argv[1] if len(sys.argv) > 1 else "*骑*"
files = sorted(glob.glob(os.path.join(img_dir, pattern)))
print(f"dir={img_dir} count={len(files)}")
for path in files:
    img = cv2.imread(path)
    if img is None:
        print(os.path.basename(path), "READ_FAIL")
        continue
    h, w = img.shape[:2]
    # 左下角 cam71 / 右下角 cam81 各约 1/2 宽
    for tag, x0, x1 in (("71", 0, w // 2), ("81", w // 2, w)):
        roi = img[int(h * 0.88) : h, x0:x1]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, th = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
        txt = ""
        try:
            import pytesseract
            txt = pytesseract.image_to_string(th, config="--psm 7").strip()
        except Exception:
            pass
        m = re.search(r"(\d{1,2}):(\d{2})", txt)
        ts = f"{m.group(1)}:{m.group(2)}" if m else "?"
        print(f"  {os.path.basename(path)} cam{tag} ts~{ts} ocr={txt[:40]!r}")
