"""水位尺 OCR 识别服务。

流程：
  0. (可选) YOLOv8 检测水位尺区域 → 裁剪 + 放大，聚焦 OCR
  1. 水面线检测 —— 图像下半段水平边缘梯度法
  2. 多策略 OCR（4 级，逐级尝试直到 ≥2 个刻度）
     策略 A：原图
     策略 B：仅保留数字连通域（过滤 E 形刻度水平条）→ 黑字白底二值图
     策略 C：数字连通域二值图裁剪刻度列 + 放大 3 倍
     策略 D：CLAHE 增强原图
  3. 线性插值计算水位值（精度 0.01 m）
  4. 标注图生成

YOLOv8 权重位置（训练后自动加载）:
    backend/weights/water_gauge_yolo.pt
"""
import base64
import re
from pathlib import Path

import cv2
import numpy as np

# ── YOLO 权重路径 ─────────────────────────────────────
_WEIGHT_PATH = Path(__file__).parent.parent / "weights" / "water_gauge_yolo.pt"
_yolo_model  = None   # 延迟加载，避免未训练时报错


def _load_yolo():
    """延迟加载 YOLOv8 模型（权重存在才加载）。"""
    global _yolo_model
    if _yolo_model is not None:
        return _yolo_model
    if not _WEIGHT_PATH.exists():
        return None
    try:
        from ultralytics import YOLO
        _yolo_model = YOLO(str(_WEIGHT_PATH))
        return _yolo_model
    except Exception:
        return None


def _detect_gauge_crop(img_bgr, conf_thresh=0.25, scale=3):
    """用 YOLOv8 检测水位尺区域，裁剪并放大 scale 倍。

    返回 (cropped_img, off_x, off_y, scale) 或 None（未检测到/无模型）。
    crop 使用**原始彩色图**，坐标映射回原图时需 /scale + offset。
    """
    model = _load_yolo()
    if model is None:
        return None

    h, w = img_bgr.shape[:2]
    results = model(img_bgr, conf=conf_thresh, verbose=False)
    boxes = results[0].boxes if results else None
    if boxes is None or len(boxes) == 0:
        return None

    # 置信度最高的框
    confs = boxes.conf.cpu().numpy()
    best  = int(confs.argmax())
    x1, y1, x2, y2 = boxes.xyxy[best].cpu().numpy().astype(int)

    # 加 padding
    pad = 20
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)

    crop = img_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    big = cv2.resize(crop,
                     (crop.shape[1] * scale, crop.shape[0] * scale),
                     interpolation=cv2.INTER_LANCZOS4)
    return big, x1, y1, scale


# ────────────────── 1. 水面线检测 ──────────────────

def detect_water_surface(img_bgr):
    """自动检测水面线 y 坐标（在原图坐标系内）。

    排除顶部 30%（天际线/建筑强边缘），在 30–92% 范围内找
    水平 Sobel 边缘密度最大跳变点。

    返回 (water_y, confidence)。
    """
    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    blurred = cv2.GaussianBlur(gray, (5, 5), 1.5)
    sobel_y = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    row_strength = np.abs(sobel_y).mean(axis=1)

    ks = max(3, h // 20)
    smoothed = np.convolve(row_strength, np.ones(ks) / ks, mode='same')

    top = int(h * 0.30)
    bot = int(h * 0.08)
    search = smoothed[top: h - bot]

    if len(search) < 4:
        return h // 2, 0.3

    diff = np.abs(np.diff(search))
    peak = int(np.argmax(diff)) + top
    mean_v = float(diff.mean()) or 1e-6
    conf = min(1.0, float(diff[peak - top]) / (mean_v * 3))

    return peak, conf


# ────────────────── 2. 图像预处理 ──────────────────

def _red_mask(img_bgr):
    """纯红区域二值掩码：R - max(G,B) > 35。"""
    b, g, r = cv2.split(img_bgr)
    excess = np.clip(
        r.astype(np.int16) - np.maximum(g, b).astype(np.int16),
        0, 255
    ).astype(np.uint8)
    _, mask = cv2.threshold(excess, 35, 255, cv2.THRESH_BINARY)
    k = np.ones((3, 3), np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)


def _digits_only_binary(img_bgr):
    """过滤 E 形刻度水平条，只保留数字连通域 → 黑字白底（等尺寸，坐标不变）。

    E 形刻度横条：高/宽 < 0.45（宽扁）→ 过滤
    数字 2-10 ：高/宽 ≥ 0.45（近方或竖长）→ 保留

    返回 None 若无红色内容。
    """
    h_img, w_img = img_bgr.shape[:2]
    mask = _red_mask(img_bgr)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask, connectivity=8, ltype=cv2.CV_32S
    )

    digit_mask = np.zeros_like(mask)
    img_area = h_img * w_img

    for i in range(1, num_labels):
        x, y, bw, bh, area = stats[i]
        if area < max(30, img_area * 0.00012) or area > img_area * 0.010:
            continue
        if bh / max(bw, 1) < 0.45:
            continue
        digit_mask[labels == i] = 255

    if not digit_mask.any():
        return None

    out = np.full((h_img, w_img, 3), 255, dtype=np.uint8)
    out[digit_mask > 0] = 0
    return out


def _ruler_crop_upscale(img_bgr, base_binary, scale=3):
    """裁剪红色内容列，对 base_binary 裁剪并放大 scale 倍。返回 (img,ox,oy,sc) 或 None。"""
    h, w = img_bgr.shape[:2]
    mask = _red_mask(img_bgr)
    coords = cv2.findNonZero(mask)
    if coords is None or base_binary is None:
        return None

    rx, ry, rw, rh = cv2.boundingRect(coords)
    pad = 15
    x1 = max(0, rx - pad)
    y1 = max(0, ry - pad)
    x2 = min(w, rx + rw + pad)
    y2 = min(h, ry + rh + pad)

    crop = base_binary[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    big = cv2.resize(crop,
                     (crop.shape[1] * scale, crop.shape[0] * scale),
                     interpolation=cv2.INTER_NEAREST)
    return big, x1, y1, scale


def _clahe_enhance(img_bgr):
    """CLAHE 对比度增强（备用）。"""
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


# ────────────────── 3. OCR 数字解析 ──────────────────

def _parse_value(text):
    """从 OCR 文本提取水位刻度数值（范围 0–9999）。"""
    t = (text.strip()
         .replace('O', '0').replace('o', '0')
         .replace('l', '1').replace('I', '1')
         .replace('—', '.').replace('-', '.'))
    m = re.search(r'\d+(?:\.\d+)?', t)
    if not m:
        return None
    try:
        v = float(m.group())
        if 0 <= v <= 9999:
            return v
    except ValueError:
        pass
    return None


def _collect_marks(ocr_lines, off_x=0.0, off_y=0.0, scale=1.0):
    """提取有效刻度列表，去重（同值取最高置信度），坐标映射回原图。"""
    candidates = {}
    for item in (ocr_lines or []):
        val = _parse_value(item.get("text", ""))
        if val is None:
            continue
        box = item.get("box", [])
        if not box or len(box) < 2:
            continue
        orig_box = [[p[0] / scale + off_x, p[1] / scale + off_y] for p in box]
        orig_cx = float(np.mean([p[0] for p in orig_box]))
        orig_cy = float(np.mean([p[1] for p in orig_box]))
        score = float(item.get("score", 0))
        if val not in candidates or score > candidates[val]["score"]:
            candidates[val] = {"value": val, "cy": orig_cy, "cx": orig_cx,
                                "box": orig_box, "score": score}
    return sorted(candidates.values(), key=lambda x: x["cy"])


def _to_bytes(frame):
    if frame is None:
        return None
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return buf.tobytes() if ok else None


def _run_ocr_on_image(ocr_fn, img_bgr, image_bytes, off_x=0.0, off_y=0.0, scale=1.0):
    """对单张图执行 4 级 OCR 策略，返回 (marks, raw_lines)。

    off_x/off_y/scale 用于把该图坐标映射回最终原图坐标系。
    """
    best_marks, best_lines = [], []

    def _try(get_bytes_fn, sx=off_x, sy=off_y, sc=scale):
        nonlocal best_marks, best_lines
        b = get_bytes_fn()
        if b is None:
            return False
        try:
            lines = ocr_fn(b) or []
        except Exception:
            lines = []
        marks = _collect_marks(lines, sx, sy, sc)
        if len(marks) > len(best_marks):
            best_marks = marks
            best_lines = lines
        return len(marks) >= 2

    # A：原图字节（最高质量）
    if image_bytes and _try(lambda: image_bytes):
        return best_marks, best_lines

    # B：数字连通域黑字白底（过滤 E 形条，等尺寸，坐标不变）
    digit_bin = _digits_only_binary(img_bgr)
    if _try(lambda: _to_bytes(digit_bin)):
        return best_marks, best_lines

    # C：B 裁剪刻度列 + 放大 3×
    ruler = _ruler_crop_upscale(img_bgr, digit_bin, scale=3)
    if ruler is not None:
        big_img, lox, loy, lsc = ruler
        if _try(lambda: _to_bytes(big_img),
                sx=off_x + lox / scale, sy=off_y + loy / scale, sc=scale * lsc):
            return best_marks, best_lines

    # D：CLAHE 增强原图
    _try(lambda: _to_bytes(_clahe_enhance(img_bgr)))

    return best_marks, best_lines


def _run_ocr_multi(ocr_fn, img_bgr, image_bytes):
    """主 OCR 调度：先尝试 YOLO 裁剪后的高质量图，再回退到原图策略。"""

    # ── 尝试 YOLO 检测裁剪 ──
    gauge_crop = _detect_gauge_crop(img_bgr, scale=3)
    if gauge_crop is not None:
        crop_img, ox, oy, sc = gauge_crop
        marks, lines = _run_ocr_on_image(
            ocr_fn, crop_img, None,   # 裁剪图无原始字节，传 None 跳策略 A
            off_x=ox, off_y=oy, scale=sc
        )
        if len(marks) >= 2:
            return marks, lines
        # 裁剪图结果不足 2 刻度，继续原图策略

    # ── 原图多策略 OCR ──
    return _run_ocr_on_image(ocr_fn, img_bgr, image_bytes)


# ────────────────── 4. 水位插值计算 ──────────────────

def _interpolate(marks, water_y):
    """插值/外推水位值（精度 0.01 m）。"""
    if not marks:
        return None, "failed", "No valid scale marks detected"
    if len(marks) == 1:
        return round(marks[0]["value"], 2), "single", "Only 1 mark, uncertain"

    above = [m for m in marks if m["cy"] <= water_y]
    below = [m for m in marks if m["cy"] > water_y]

    if above and below:
        u, d = above[-1], below[0]
        dy = d["cy"] - u["cy"]
        if dy == 0:
            return round(u["value"], 2), "match", f"Water surface at {u['value']} m"
        ratio = (water_y - u["cy"]) / dy
        level = u["value"] + ratio * (d["value"] - u["value"])
        return round(level, 2), "interp", f"Between {u['value']} ~ {d['value']} m"

    if len(marks) < 2:
        return round(marks[0]["value"], 2), "single-side", "Insufficient marks"

    m1, m2 = (marks[0], marks[1]) if not above else (marks[-2], marks[-1])
    dy = m2["cy"] - m1["cy"]
    if dy == 0:
        return round(m1["value"], 2), "extrap", "Marks overlap"
    level = m1["value"] + (m2["value"] - m1["value"]) / dy * (water_y - m1["cy"])
    side = "below" if not above else "above"
    return round(level, 2), f"extrap({side})", f"Extrapolated from {m1['value']},{m2['value']}"


# ────────────────── 5. 标注图生成 ──────────────────

def _draw(img, marks, water_y, level, method, gauge_box=None):
    h, w = img.shape[:2]

    # YOLO 检测框
    if gauge_box:
        gx1, gy1, gx2, gy2 = gauge_box
        cv2.rectangle(img, (gx1, gy1), (gx2, gy2), (255, 140, 0), 2)
        cv2.putText(img, "WaterGuage", (gx1, gy1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 140, 0), 1, cv2.LINE_AA)

    # 刻度框
    for m in marks:
        pts = np.array([[int(p[0]), int(p[1])] for p in m["box"]], np.int32)
        cv2.polylines(img, [pts], True, (0, 210, 50), 2)
        lbl = f"{m['value']:.0f}" if m["value"] == int(m["value"]) else str(m["value"])
        cv2.putText(img, lbl, (int(m["cx"]) + 6, int(m["cy"]) + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 60), 2, cv2.LINE_AA)

    # 水面线
    cv2.line(img, (0, water_y), (w, water_y), (0, 30, 255), 3)
    cv2.circle(img, (w // 2, water_y), 7, (0, 30, 255), -1)

    # 读数标注
    lvl_str = f"{level:.2f} m" if level is not None else "N/A"
    text = f"Level: {lvl_str} [{method}]"
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    bx, by = 10, max(40, water_y - 40)
    cv2.rectangle(img, (bx - 4, by - th - 8), (bx + tw + 8, by + 6), (0, 0, 0), -1)
    cv2.rectangle(img, (bx - 4, by - th - 8), (bx + tw + 8, by + 6), (0, 30, 255), 2)
    cv2.putText(img, text, (bx, by),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)


# ────────────────── 主入口 ──────────────────

def detect_water_level(ocr_fn, image_bytes, manual_water_y_ratio=None):
    """水位检测主函数。

    Args:
        ocr_fn: callable(image_bytes) -> list[{text, score, box}]
        image_bytes: 待检测图片二进制。
        manual_water_y_ratio: float|None，手动水面线（归一化 0–1）。

    Returns dict:
        level, waterY, waterYRatio, surfaceConfidence, method, note,
        marks, markCount, ocrRawCount, gaugeDetected,
        imageBase64, width, height
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片，请上传有效的图像文件")
    h, w = img.shape[:2]

    # 水面线检测（在原图坐标系）
    if manual_water_y_ratio is not None:
        water_y = int(float(manual_water_y_ratio) * h)
        surf_conf = 1.0
    else:
        water_y, surf_conf = detect_water_surface(img)
    water_y = int(np.clip(water_y, 0, h - 1))

    # YOLO 检测框（用于标注）
    gauge_box = None
    yolo_result = _detect_gauge_crop(img, scale=1)   # scale=1 只取坐标
    if yolo_result is not None:
        _, gx1, gy1, _ = yolo_result
        model = _load_yolo()
        if model:
            res = model(img, conf=0.25, verbose=False)
            if res and res[0].boxes and len(res[0].boxes):
                b = res[0].boxes.xyxy[0].cpu().numpy().astype(int)
                gauge_box = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))

    # 多策略 OCR
    marks, ocr_lines = _run_ocr_multi(ocr_fn, img, image_bytes)
    level, method, note = _interpolate(marks, water_y)

    # 标注图
    annotated = img.copy()
    _draw(annotated, marks, water_y, level, method, gauge_box)
    ok2, buf2 = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 92])
    img_b64 = base64.b64encode(buf2.tobytes()).decode() if ok2 else None

    return {
        "level": level,
        "waterY": water_y,
        "waterYRatio": round(water_y / h, 4),
        "surfaceConfidence": round(surf_conf, 4),
        "method": method,
        "note": note,
        "marks": [{"value": m["value"], "y": round(m["cy"], 1)} for m in marks],
        "markCount": len(marks),
        "ocrRawCount": len(ocr_lines),
        "gaugeDetected": gauge_box is not None,
        "imageBase64": img_b64,
        "width": w,
        "height": h,
    }
