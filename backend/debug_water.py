"""临时调试脚本：可视化水位检测预处理中间图。

用法:
  cd backend
  python debug_water.py <图片路径>

输出到当前目录:
  debug_red_mask.jpg    - 红色掩码（白=红色区域）
  debug_A_original.jpg  - 原图 + 水面线
  debug_B_digit_bin.jpg - 数字连通域二值图（应只有数字，无 E 形条）
  debug_C_ruler_crop.jpg - 裁剪放大 3× 后的二值图
"""
import sys
import cv2
import numpy as np

sys.path.insert(0, ".")
from services.water_level import _red_mask, detect_water_surface


def main(img_path):
    img = cv2.imread(img_path)
    if img is None:
        print(f"无法读取图片: {img_path}")
        return

    h_img, w_img = img.shape[:2]
    print(f"图像尺寸: {w_img}x{h_img}")

    # 红色掩码
    mask = _red_mask(img)
    print(f"红色像素数: {int(mask.sum() // 255)}")
    cv2.imwrite("debug_red_mask.jpg", mask)

    # 连通域分析
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8, ltype=cv2.CV_32S
    )

    img_area = h_img * w_img
    min_area = max(30, img_area * 0.00012)
    max_area = img_area * 0.010

    print(f"\n{'#':>4}  {'W':>5}  {'H':>5}  {'Area':>7}  {'H/W':>6}  pass?")
    digit_mask = np.zeros_like(mask)
    for i in range(1, num_labels):
        x, y, bw, bh, area = stats[i]
        aspect = bh / max(bw, 1)
        area_ok = min_area <= area <= max_area
        aspect_ok = aspect >= 0.45
        passed = area_ok and aspect_ok
        if passed:
            digit_mask[labels == i] = 255
        if area >= min_area * 0.5:
            print(f"{i:>4}  {bw:>5}  {bh:>5}  {area:>7}  {aspect:>6.2f}  "
                  f"{'YES' if passed else 'no'} (area={area_ok}, asp={aspect_ok})")

    # 数字二值图
    if digit_mask.any():
        out_b = np.full((h_img, w_img, 3), 255, dtype=np.uint8)
        out_b[digit_mask > 0] = 0
        cv2.imwrite("debug_B_digit_bin.jpg", out_b)
        print("\n-> debug_B_digit_bin.jpg saved")

        coords = cv2.findNonZero(mask)
        if coords is not None:
            rx, ry, rw, rh = cv2.boundingRect(coords)
            pad = 15
            x1, y1 = max(0, rx - pad), max(0, ry - pad)
            x2, y2 = min(w_img, rx + rw + pad), min(h_img, ry + rh + pad)
            crop = out_b[y1:y2, x1:x2]
            big = cv2.resize(crop, (crop.shape[1] * 3, crop.shape[0] * 3),
                             interpolation=cv2.INTER_NEAREST)
            cv2.imwrite("debug_C_ruler_crop.jpg", big)
            print(f"-> debug_C_ruler_crop.jpg saved (crop [{x1},{y1}]-[{x2},{y2}], scale 3x)")
    else:
        print("\nWARN: no components passed filter! Adjust threshold 0.45 or red mask threshold=35")

    # 水面线
    wy, conf = detect_water_surface(img)
    print(f"\nWater surface: y={wy} ({wy/h_img*100:.1f}%)  conf={conf:.2f}")

    annotated = img.copy()
    cv2.line(annotated, (0, wy), (w_img, wy), (0, 30, 255), 3)
    cv2.imwrite("debug_A_original.jpg", annotated)
    print("-> debug_A_original.jpg saved")

    print("\nCheck:")
    print("  1. debug_red_mask.jpg  - digits/E-marks should be white")
    print("  2. debug_B_digit_bin.jpg - should have only digit characters (E-bars removed)")
    print("  3. debug_C_ruler_crop.jpg - digits should be large and clear for OCR")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "test_gauge.jpg"
    main(path)
