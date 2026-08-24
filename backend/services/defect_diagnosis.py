"""Defect diagnosis dual-engine (Qwen3-VL-Seg inspired, cloud-first).

Pipeline:
  1) YOLO gate — real-time suspicious ROI filter
  2) Box-guided mask — MobileSAM / EfficientSAM (proxy for Seg decoder)
  3) Qwen-VL multimodal API — structured root-cause diagnosis
  4) Fallback templates when API key missing or call fails
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

import cv2
import numpy as np
import requests

from config import Config

log = logging.getLogger(__name__)

SCENARIOS = ("general", "pcb", "injection")


class QwenVLError(Exception):
    """Raised when the multimodal diagnosis API fails."""


def qwen_vl_configured() -> bool:
    return bool((Config.QWEN_VL_API_KEY or "").strip())


def engine_status() -> dict:
    return {
        "qwenVlConfigured": qwen_vl_configured(),
        "qwenVlBaseUrl": Config.QWEN_VL_BASE_URL,
        "qwenVlModel": Config.QWEN_VL_MODEL,
        "suspiciousConfDefault": float(Config.DEFECT_SUSPICIOUS_CONF),
        "mode": "cloud_first",
        "description": (
            "YOLO gate + box-guided SAM mask + Qwen-VL cloud diagnosis; "
            "falls back to rule templates without API key."
        ),
    }


def filter_suspicious(detections: list[dict], suspicious_conf: float) -> list[dict]:
    thr = float(suspicious_conf)
    out = []
    for d in detections or []:
        try:
            conf = float(d.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf >= thr:
            out.append(d)
    return out


def _expand_bbox(bbox, w: int, h: int, pad_ratio: float = 0.1):
    x1, y1, x2, y2 = [float(v) for v in bbox]
    bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
    px, py = bw * pad_ratio, bh * pad_ratio
    nx1 = max(0, int(round(x1 - px)))
    ny1 = max(0, int(round(y1 - py)))
    nx2 = min(w, int(round(x2 + px)))
    ny2 = min(h, int(round(y2 + py)))
    if nx2 <= nx1:
        nx2 = min(w, nx1 + 1)
    if ny2 <= ny1:
        ny2 = min(h, ny1 + 1)
    return [nx1, ny1, nx2, ny2]


def _crop_roi_b64(img_bgr, bbox, pad_ratio: float = 0.1) -> str | None:
    h, w = img_bgr.shape[:2]
    x1, y1, x2, y2 = _expand_bbox(bbox, w, h, pad_ratio)
    roi = img_bgr[y1:y2, x1:x2]
    if roi.size == 0:
        return None
    ok, buf = cv2.imencode(".jpg", roi, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode()


def _rect_mask_b64(h: int, w: int, bbox) -> str | None:
    from inference import _encode_mask_b64

    mask = np.zeros((h, w), dtype=bool)
    x1, y1, x2, y2 = [int(round(float(v))) for v in bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 > x1 and y2 > y1:
        mask[y1:y2, x1:x2] = True
    return _encode_mask_b64(mask)


def _scenario_hint(scenario: str) -> str:
    s = (scenario or "general").lower()
    if s == "pcb":
        return (
            "场景：PCB / 电子装配质检。关注虚焊、连锡、缺件、极性反、刮伤、污染等。"
            "工艺建议可涉及回流温度曲线、锡膏印刷、贴片偏移、波峰焊参数。"
        )
    if s == "injection":
        return (
            "场景：注塑件质检。关注气泡、缩水、飞边、缺料、熔接痕、烧焦、顶白等。"
            "工艺建议可涉及保压时间/压力、料温、模温、排气槽、注射速度。"
        )
    return (
        "场景：通用工业外观质检。关注裂纹、凹陷、污渍、色差、变形、异物等。"
        "工艺建议应具体、可执行。"
    )


def build_diagnosis_prompt(scenario: str, detection: dict) -> str:
    cls = detection.get("className") or "unknown"
    conf = detection.get("confidence")
    return (
        f"{_scenario_hint(scenario)}\n"
        f"检测器初步类别：{cls}，置信度：{conf}。\n"
        "请以质检工程师视角分析图中可疑区域，仅输出一个 JSON 对象，字段：\n"
        "defectType(string), severity(low|medium|high|critical), "
        "locationDesc(string), rootCause(string), "
        "processAdvice(string array), confidence(0-1 number)。\n"
        "不要输出 Markdown 代码块或其它说明文字。"
    )


def extract_json_object(text: str) -> dict:
    """Parse JSON object from model output; tolerate fences / trailing noise."""
    if not text or not str(text).strip():
        raise ValueError("empty diagnosis text")
    raw = str(text).strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        obj = json.loads(raw[start : end + 1])
        if isinstance(obj, dict):
            return obj
    raise ValueError("no JSON object in diagnosis text")


def normalize_diagnosis(obj: dict | None, *, detection: dict, scenario: str, engine: str) -> dict:
    o = obj if isinstance(obj, dict) else {}
    advice = o.get("processAdvice") or o.get("advice") or []
    if isinstance(advice, str):
        advice = [advice] if advice.strip() else []
    if not isinstance(advice, list):
        advice = [str(advice)]
    advice = [str(a).strip() for a in advice if str(a).strip()]
    severity = str(o.get("severity") or "medium").lower().strip()
    if severity not in ("low", "medium", "high", "critical"):
        severity = "medium"
    try:
        conf = float(o.get("confidence"))
    except (TypeError, ValueError):
        try:
            conf = float(detection.get("confidence") or 0.5)
        except (TypeError, ValueError):
            conf = 0.5
    conf = max(0.0, min(1.0, conf))
    defect_type = (
        str(o.get("defectType") or o.get("type") or detection.get("className") or "可疑缺陷").strip()
    )
    return {
        "defectType": defect_type,
        "severity": severity,
        "locationDesc": str(o.get("locationDesc") or o.get("location") or "检测框内区域").strip(),
        "rootCause": str(o.get("rootCause") or o.get("cause") or "待人工复核确认成因").strip(),
        "processAdvice": advice or ["建议人工复核并记录工艺参数"],
        "confidence": round(conf, 4),
        "engine": engine,
        "className": detection.get("className"),
        "bbox": detection.get("bbox"),
        "localConfidence": detection.get("confidence"),
        "scenario": scenario,
        "rawText": o.get("_rawText"),
    }


def fallback_diagnosis(detection: dict, scenario: str = "general") -> dict:
    """Rule template when Qwen-VL is unavailable."""
    cls = (detection.get("className") or "defect").lower()
    s = (scenario or "general").lower()
    if s == "pcb":
        tip = {
            "defectType": detection.get("className") or "PCB可疑缺陷",
            "rootCause": f"检测器标记为「{cls}」，常见成因包括锡膏量异常、回流曲线偏离、贴片偏移或污染。",
            "processAdvice": [
                "复核锡膏印刷厚度与开口设计",
                "核对回流温度曲线与链速",
                "检查贴片吸嘴与供料器稳定性",
            ],
        }
    elif s == "injection":
        tip = {
            "defectType": detection.get("className") or "注塑可疑缺陷",
            "rootCause": f"检测器标记为「{cls}」，常见成因包括保压不足、排气不畅、料温/模温不当或模具磨损。",
            "processAdvice": [
                "适当延长保压时间并核查保压压力",
                "清理模具排气槽与分型面",
                "核对料筒温度与模具温度设定",
            ],
        }
    else:
        tip = {
            "defectType": detection.get("className") or "外观可疑缺陷",
            "rootCause": f"检测器标记为「{cls}」，需结合工艺上下文确认是否为真实缺陷。",
            "processAdvice": [
                "对比标准样品确认缺陷定义",
                "记录工位、班次与工艺参数",
                "必要时放大复检或换角度复拍",
            ],
        }
    tip["severity"] = "medium"
    tip["locationDesc"] = "YOLO 可疑检测框区域"
    tip["confidence"] = float(detection.get("confidence") or 0.5)
    tip["_rawText"] = None
    return normalize_diagnosis(tip, detection=detection, scenario=scenario, engine="fallback")


def chat_vision_json(
    image_b64: str,
    prompt: str,
    *,
    system_prompt: str | None = None,
    timeout: int = 90,
) -> dict:
    """Call OpenAI-compatible multimodal chat and parse JSON object."""
    api_key = (Config.QWEN_VL_API_KEY or "").strip()
    if not api_key:
        raise QwenVLError("QWEN_VL_API_KEY not configured")
    url = f"{Config.QWEN_VL_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    sys_msg = system_prompt or (
        "You are an industrial quality inspection engineer. "
        "Respond with a single JSON object only."
    )
    body = {
        "model": Config.QWEN_VL_MODEL,
        "messages": [
            {"role": "system", "content": sys_msg},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        ],
        "temperature": 0.2,
        "stream": False,
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except (requests.exceptions.RequestException, KeyError, IndexError, TypeError) as e:
        raise QwenVLError(str(e)) from e
    try:
        obj = extract_json_object(content)
    except (ValueError, json.JSONDecodeError) as e:
        raise QwenVLError(f"invalid JSON from VLM: {e}") from e
    obj["_rawText"] = content if isinstance(content, str) else str(content)
    return obj


def diagnose_one(detection: dict, roi_b64: str | None, scenario: str) -> dict:
    if not roi_b64 or not qwen_vl_configured():
        return fallback_diagnosis(detection, scenario)
    try:
        obj = chat_vision_json(roi_b64, build_diagnosis_prompt(scenario, detection))
        return normalize_diagnosis(obj, detection=detection, scenario=scenario, engine="qwen_vl")
    except QwenVLError as e:
        log.warning("qwen-vl diagnose failed: %s", e)
        fb = fallback_diagnosis(detection, scenario)
        fb["rawText"] = str(e)
        fb["engine"] = "fallback"
        return fb


def segment_boxes(
    image_bytes: bytes,
    boxes: list,
    *,
    seg_path: str | None,
    seg_lib: str | None,
) -> list[str | None]:
    """Box-guided masks; one maskBase64 per box (or None)."""
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return [None] * len(boxes)
    h, w = img.shape[:2]
    lib = (seg_lib or "").lower()
    masks: list[str | None] = []
    if not seg_path:
        for box in boxes:
            masks.append(_rect_mask_b64(h, w, box))
        return masks

    for box in boxes:
        try:
            if lib in ("mobilesam", "mobile-sam", "mobile_sam"):
                from inference import segment_image_mobilesam

                res = segment_image_mobilesam(
                    seg_path, image_bytes, box=list(box), mode="prompt", draw=False
                )
            elif lib in ("opencv-sam", "efficientsam", "efficient-sam", "efficient_sam"):
                from inference import segment_image_efficientsam

                res = segment_image_efficientsam(
                    seg_path, image_bytes, box=list(box), draw=False
                )
            else:
                masks.append(_rect_mask_b64(h, w, box))
                continue
            dets = (res or {}).get("detections") or []
            mb = dets[0].get("maskBase64") if dets else None
            masks.append(mb or _rect_mask_b64(h, w, box))
        except Exception as e:  # noqa: BLE001
            log.warning("box-guided segment failed: %s", e)
            masks.append(_rect_mask_b64(h, w, box))
    return masks


def _overlay_result(img_bgr, items: list[dict]) -> str | None:
    """Draw boxes + translucent masks; return JPEG base64."""
    from inference import _decode_mask_b64

    canvas = img_bgr.copy()
    colors = [
        (0, 165, 255),
        (0, 255, 128),
        (255, 128, 0),
        (255, 0, 255),
        (0, 255, 255),
    ]
    for i, it in enumerate(items):
        color = colors[i % len(colors)]
        b64 = it.get("maskBase64")
        if b64:
            mask = _decode_mask_b64(b64)
            if mask is not None and mask.shape[:2] == canvas.shape[:2]:
                overlay = canvas.copy()
                overlay[mask] = (
                    0.45 * np.array(color, dtype=np.float32)
                    + 0.55 * overlay[mask].astype(np.float32)
                ).astype(np.uint8)
                canvas = overlay
        bbox = it.get("bbox") or []
        if len(bbox) == 4:
            x1, y1, x2, y2 = [int(round(float(v))) for v in bbox]
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            label = it.get("label") or it.get("className") or f"#{i + 1}"
            cv2.putText(
                canvas,
                str(label)[:40],
                (x1, max(16, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )
    ok, buf = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode()


def run_pipeline(
    image_bytes: bytes,
    *,
    det_path: str,
    seg_path: str | None = None,
    seg_lib: str | None = None,
    conf: float = 0.25,
    suspicious_conf: float | None = None,
    scenario: str = "general",
    draw: bool = True,
    model_key: str | None = None,
) -> dict[str, Any]:
    """Full dual-engine diagnosis on one image."""
    from inference import detect_image

    scenario = (scenario or "general").lower()
    if scenario not in SCENARIOS:
        scenario = "general"
    sus_thr = (
        float(Config.DEFECT_SUSPICIOUS_CONF)
        if suspicious_conf is None
        else float(suspicious_conf)
    )

    det_result = detect_image(
        det_path, image_bytes, conf=conf, draw=False, model_key=model_key
    )
    all_dets = list(det_result.get("detections") or [])
    suspicious = filter_suspicious(all_dets, sus_thr)

    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")
    h, w = img.shape[:2]

    boxes = [d.get("bbox") for d in suspicious if d.get("bbox") and len(d["bbox"]) == 4]
    mask_list = segment_boxes(
        image_bytes, boxes, seg_path=seg_path, seg_lib=seg_lib
    ) if boxes else []

    seg_engine = "none"
    if seg_path and boxes:
        lib = (seg_lib or "").lower()
        if lib in ("mobilesam", "mobile-sam", "mobile_sam"):
            seg_engine = "mobilesam"
        elif lib in ("opencv-sam", "efficientsam", "efficient-sam", "efficient_sam"):
            seg_engine = "efficientsam"
        else:
            seg_engine = "bbox_rect"
    elif boxes:
        seg_engine = "bbox_rect"

    enriched: list[dict] = []
    diagnoses: list[dict] = []
    for i, d in enumerate(suspicious):
        item = dict(d)
        mb = mask_list[i] if i < len(mask_list) else None
        if mb:
            item["maskBase64"] = mb
        item["label"] = f"{d.get('className') or 'obj'} {float(d.get('confidence') or 0):.2f}"
        roi_b64 = _crop_roi_b64(img, d["bbox"]) if d.get("bbox") else None
        diag = diagnose_one(d, roi_b64, scenario)
        diag["index"] = i
        item["diagnosis"] = {
            "defectType": diag.get("defectType"),
            "severity": diag.get("severity"),
            "engine": diag.get("engine"),
        }
        enriched.append(item)
        diagnoses.append(diag)

    image_b64 = _overlay_result(img, enriched) if draw else None
    vl_used = any(d.get("engine") == "qwen_vl" for d in diagnoses)
    return {
        "width": w,
        "height": h,
        "scenario": scenario,
        "suspiciousConf": sus_thr,
        "detCount": len(all_dets),
        "suspiciousCount": len(suspicious),
        "detections": all_dets,
        "suspicious": enriched,
        "diagnoses": diagnoses,
        "imageBase64": image_b64,
        "engines": {
            "detector": "yolo",
            "segmentation": seg_engine,
            "diagnosis": "qwen_vl" if vl_used else ("fallback" if diagnoses else "none"),
            "qwenVlConfigured": qwen_vl_configured(),
            "qwenVlModel": Config.QWEN_VL_MODEL if qwen_vl_configured() else None,
        },
    }
