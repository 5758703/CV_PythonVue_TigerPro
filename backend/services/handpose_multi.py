"""手势识别多引擎结果合并（数字 MediaPipe + 手语 YOLO）。"""
from __future__ import annotations

import base64
from typing import Any

import cv2
import numpy as np


def merge_estimate_results(
    img: np.ndarray,
    selected: list[str],
    mp_data: dict[str, Any] | None,
    csl_data: dict[str, Any] | None,
    *,
    draw: bool = False,
) -> dict[str, Any]:
    """合并多引擎结果；双开时 displayText 为「数字 | 手语」。"""
    digit_text = None
    sign_text = None
    label_zh = None
    hands: list = []
    detections: list = []

    if mp_data:
        digit_text = mp_data.get("displayText")
        hands = mp_data.get("hands") or []
    if csl_data:
        sign_text = csl_data.get("displayText")
        label_zh = csl_data.get("labelZh")
        detections = csl_data.get("detections") or []

    parts = []
    if digit_text not in (None, ""):
        parts.append(str(digit_text))
    if sign_text not in (None, ""):
        parts.append(str(sign_text))
    combined = " | ".join(parts) if parts else None

    active = []
    if mp_data is not None:
        active.append("mediapipe")
    if csl_data is not None:
        active.append("csl-yolo11s")

    recognizer = active[0] if len(active) == 1 else ",".join(active)

    data: dict[str, Any] = {
        "recognizer": recognizer,
        "recognizers": active,
        "requestedRecognizers": selected,
        "digitText": digit_text,
        "signText": sign_text,
        "displayText": combined,
        "labelZh": label_zh,
        "hands": hands,
        "detections": detections,
        "width": int(img.shape[1]),
        "height": int(img.shape[0]),
    }
    if mp_data:
        data["leftDigit"] = mp_data.get("leftDigit")
        data["rightDigit"] = mp_data.get("rightDigit")
        data["primaryDigit"] = mp_data.get("primaryDigit")
        data["totalCount"] = mp_data.get("totalCount", 0)
        data["extendedTotal"] = mp_data.get("extendedTotal", 0)
        data["primaryLabel"] = None
        data["confidence"] = None
    if csl_data:
        data["primaryLabel"] = csl_data.get("primaryLabel")
        data["confidence"] = csl_data.get("confidence")
        data["classes"] = csl_data.get("classes")
        data["count"] = csl_data.get("count", len(detections))

    if draw:
        data["imageBase64"] = draw_combined(img, hands, detections)
    return data


def draw_combined(img: np.ndarray, hands: list, detections: list) -> str | None:
    from services.handpose import draw_hands

    vis = img.copy()
    if hands:
        vis = draw_hands(vis, hands)
    for d in detections or []:
        bbox = d.get("bbox") or []
        if len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{d.get('className', '?')} {float(d.get('confidence') or 0):.2f}"
        cv2.putText(vis, label, (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, (0, 255, 0), 2, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", vis)
    return base64.b64encode(buf.tobytes()).decode() if ok else None
