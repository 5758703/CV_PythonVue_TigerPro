"""文档表格识别服务。

流水线：
  1. YOLO 检测表格区域（bordered / borderless）
  2. 对各表格裁剪区跑 RapidOCR（单元格文字）
  3. SLANet_plus（rapid-table）还原结构并匹配文字 → HTML
  4. HTML → CSV；原图叠加表格框与单元格框

未检出表格时，将整图视为一张表继续识别。
"""
from __future__ import annotations

import base64
import csv
import io
import re
from html.parser import HTMLParser
from typing import Callable

import cv2
import numpy as np


class _HtmlTableParser(HTMLParser):
    """简易 HTML table → 二维单元格文本。"""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._row = None
        self._cell = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "tr":
            self._row = []
        elif t in ("td", "th") and self._row is not None:
            self._cell = True
            self._buf = []

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("td", "th") and self._cell and self._row is not None:
            text = "".join(self._buf).strip().replace("\n", " ")
            self._row.append(text)
            self._cell = False
            self._buf = []
        elif t == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell:
            self._buf.append(data)


def html_to_rows(html: str) -> list[list[str]]:
    if not html:
        return []
    parser = _HtmlTableParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001
        return []
    return [r for r in parser.rows if any(c.strip() for c in r)]


def rows_to_csv(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def _encode_jpg_b64(img_bgr) -> str | None:
    ok, buf = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _clip_bbox(bbox, w, h, pad=8):
    x1, y1, x2, y2 = [float(v) for v in bbox]
    x1 = max(0, int(x1) - pad)
    y1 = max(0, int(y1) - pad)
    x2 = min(w, int(x2) + pad)
    y2 = min(h, int(y2) + pad)
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _is_table_det(d) -> bool:
    name = (d.get("className") or "").lower()
    if "table" in name or "bordered" in name or "borderless" in name:
        return True
    # yolov8m-table-extraction 类名常见为 bordered / borderless
    return name in ("bordered", "borderless", "0", "1")


def _draw_overlay(img, tables, detections):
    vis = img.copy()
    for d in detections or []:
        bbox = d.get("bbox") or []
        if len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        cv2.rectangle(vis, (x1, y1), (x2, y2), (64, 160, 255), 2)
        label = f"{d.get('className', 'table')} {float(d.get('confidence') or 0):.2f}"
        cv2.putText(
            vis, label, (x1, max(16, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (64, 160, 255), 2, cv2.LINE_AA,
        )
    for t in tables or []:
        cells = t.get("cellBboxes") or []
        ox, oy = t.get("offset") or [0, 0]
        for cell in cells:
            if not cell or len(cell) < 4:
                continue
            # cell 可能是 [x1,y1,x2,y2] 或 四点
            if len(cell) == 4 and not isinstance(cell[0], (list, tuple)):
                x1, y1, x2, y2 = [int(v) for v in cell]
            else:
                xs = [float(p[0]) for p in cell]
                ys = [float(p[1]) for p in cell]
                x1, y1, x2, y2 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
            cv2.rectangle(vis, (x1 + ox, y1 + oy), (x2 + ox, y2 + oy), (80, 200, 120), 1)
    return vis


def recognize_tables(
    image_bytes: bytes,
    *,
    detect_fn: Callable[[bytes], dict] | None,
    ocr_fn: Callable[[bytes], dict],
    table_fn: Callable[[np.ndarray, list], dict],
    conf: float = 0.25,
    whole_image_fallback: bool = True,
) -> dict:
    """执行 YOLO → RapidOCR → SLANet_plus 流水线。

    detect_fn(image_bytes) -> {detections:[{bbox,className,confidence}, ...]}
    ocr_fn(image_bytes) -> {lines:[{box,text,score}, ...]}
    table_fn(crop_bgr, ocr_lines) -> {html, cellBboxes, elapse}
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    h, w = img.shape[:2]

    detections = []
    if detect_fn is not None:
        det_res = detect_fn(image_bytes) or {}
        detections = [
            d for d in (det_res.get("detections") or [])
            if _is_table_det(d) and float(d.get("confidence") or 0) >= conf
        ]
        detections.sort(key=lambda d: float(d.get("confidence") or 0), reverse=True)

    regions = []
    for d in detections:
        clipped = _clip_bbox(d.get("bbox") or [], w, h)
        if clipped:
            regions.append({
                "bbox": list(clipped),
                "className": d.get("className") or "table",
                "confidence": float(d.get("confidence") or 0),
            })

    if not regions and whole_image_fallback:
        regions.append({
            "bbox": [0, 0, w, h],
            "className": "full-image",
            "confidence": 1.0,
        })

    tables = []
    for idx, region in enumerate(regions):
        x1, y1, x2, y2 = region["bbox"]
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        ok, crop_buf = cv2.imencode(".jpg", crop)
        if not ok:
            continue
        crop_bytes = crop_buf.tobytes()

        ocr_res = ocr_fn(crop_bytes) or {}
        lines = ocr_res.get("lines") or []

        try:
            struct = table_fn(crop, lines) or {}
        except Exception as e:  # noqa: BLE001
            tables.append({
                "index": idx,
                "bbox": region["bbox"],
                "className": region["className"],
                "confidence": region["confidence"],
                "offset": [x1, y1],
                "html": "",
                "csv": "",
                "rows": [],
                "ocrCount": len(lines),
                "cellBboxes": [],
                "elapse": 0,
                "error": str(e),
            })
            continue

        html = (struct.get("html") or "").strip()
        # 去掉可能的 markdown 代码围栏
        html = re.sub(r"^```html\s*", "", html, flags=re.I)
        html = re.sub(r"\s*```$", "", html)
        rows = html_to_rows(html)
        csv_text = rows_to_csv(rows)
        cell_bboxes = struct.get("cellBboxes") or []

        tables.append({
            "index": idx,
            "bbox": region["bbox"],
            "className": region["className"],
            "confidence": region["confidence"],
            "offset": [x1, y1],
            "html": html,
            "csv": csv_text,
            "rows": rows,
            "ocrCount": len(lines),
            "cellBboxes": cell_bboxes,
            "elapse": float(struct.get("elapse") or 0),
            "error": None,
        })

    vis = _draw_overlay(img, tables, detections)
    return {
        "tables": tables,
        "tableCount": len(tables),
        "detections": detections,
        "detectCount": len(detections),
        "width": w,
        "height": h,
        "imageBase64": _encode_jpg_b64(vis),
        "fallbackFullImage": bool(not detections and tables),
    }
