"""VLM-FO1 本地推理封装（官方仓库 + 本项目 YOLO 候选框）。

官方流程：候选框 proposals → VLM-FO1 按自然语言筛选 region index → bbox。
本项目用 Ultralytics YOLO（低阈值）替代 UPN/SAM3 生成 proposals，降低接入成本。

环境变量：
  VLM_FO1_ROOT          官方仓库根目录（默认 uploads/models/third_party/VLM-FO1）
  VLM_FO1_PROPOSAL_WEIGHT  候选框 YOLO .pt 路径（可选）
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import threading
from typing import Any

import cv2
import numpy as np

_lock = threading.Lock()
_fo1_cache: dict[str, tuple] = {}  # model_dir -> (tokenizer, model, image_processors)

OD_TEMPLATE = "Please detect {} in this image. Answer the question with object indexes."
REC_TEMPLATE = "Please detect {} in this image. Answer the question with object indexes."

_GROUND_RE = re.compile(
    r"<ground>(.*?)</ground>\s*<objects>(.*?)</objects>",
    re.IGNORECASE | re.DOTALL,
)
_REGION_RE = re.compile(r"<region\s*(\d+)\s*>", re.IGNORECASE)


def resolve_vlm_fo1_root() -> str | None:
    env = (os.getenv("VLM_FO1_ROOT") or "").strip()
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(here, "uploads", "models", "third_party", "VLM-FO1")
    if os.path.isdir(default) and os.path.isdir(os.path.join(default, "vlm_fo1")):
        return default
    return None


def ensure_vlm_fo1_on_path() -> str:
    root = resolve_vlm_fo1_root()
    if not root:
        raise RuntimeError(
            "未找到 VLM-FO1 官方代码。请执行：\n"
            "  python scripts/setup_vlm_fo1.py\n"
            "或设置环境变量 VLM_FO1_ROOT 指向克隆后的仓库根目录，"
            "并 pip install -r <repo>/requirements.txt"
        )
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def _find_proposal_weight() -> str | None:
    env = (os.getenv("VLM_FO1_PROPOSAL_WEIGHT") or "").strip()
    if env and os.path.isfile(env):
        return env
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models = os.path.join(here, "uploads", "models")
    candidates = [
        "yolo26n/yolo26n.pt",
        "yolo26n.pt",
        "yolo11n/yolo11n.pt",
        "yolo11n.pt",
        "yolov8n.pt",
        "yolo26s/yolo26s.pt",
    ]
    for rel in candidates:
        p = os.path.join(models, rel.replace("/", os.sep))
        if os.path.isfile(p):
            return p
    # 扫描任一较小的 yolo*.pt
    if os.path.isdir(models):
        found: list[str] = []
        for root, _dirs, files in os.walk(models):
            for f in files:
                if f.lower().endswith(".pt") and "yolo" in f.lower() and "pose" not in f.lower():
                    found.append(os.path.join(root, f))
        if found:
            found.sort(key=lambda x: os.path.getsize(x))
            return found[0]
    return None


def propose_boxes_yolo(
    image_bgr: np.ndarray,
    *,
    weight_path: str | None = None,
    conf: float = 0.12,
    max_boxes: int = 80,
) -> list[list[float]]:
    """用 YOLO 低阈值生成候选框（替代 UPN）。"""
    path = weight_path or _find_proposal_weight()
    if not path:
        raise RuntimeError(
            "VLM-FO1 需要候选框检测权重。请设置 VLM_FO1_PROPOSAL_WEIGHT，"
            "或在 uploads/models 下放置 yolo26n/yolo11n 等 .pt"
        )
    from ultralytics import YOLO

    model = YOLO(path)
    results = model.predict(source=image_bgr, conf=float(conf), verbose=False)
    boxes: list[tuple[float, list[float]]] = []
    if results:
        r0 = results[0]
        if getattr(r0, "boxes", None) is not None and r0.boxes is not None:
            xyxy = r0.boxes.xyxy.cpu().numpy()
            confs = r0.boxes.conf.cpu().numpy()
            for c, row in zip(confs, xyxy):
                boxes.append((float(c), [float(row[0]), float(row[1]), float(row[2]), float(row[3])]))
    boxes.sort(key=lambda x: -x[0])
    return [b for _c, b in boxes[: max(1, int(max_boxes))]]


def parse_fo1_prediction_to_label_boxes(prediction: str, bbox_list: list) -> dict[str, list[list[float]]]:
    """解析 FO1 输出中的 <ground>/<objects>/<regionN> → label→bboxes。"""
    text = str(prediction or "")
    label_to_indexes: dict[str, set[int]] = {}
    for label_text, indexes in _GROUND_RE.findall(text):
        label = (label_text or "").strip() or "object"
        idxs = {int(m) for m in _REGION_RE.findall(indexes or "")}
        if not idxs:
            continue
        label_to_indexes.setdefault(label, set()).update(idxs)

    # 兜底：无 ground 包装时，收集全部 region，归到 generic
    if not label_to_indexes:
        idxs = {int(m) for m in _REGION_RE.findall(text)}
        if idxs:
            label_to_indexes["object"] = idxs

    out: dict[str, list[list[float]]] = {}
    n = len(bbox_list)
    for label, idxs in label_to_indexes.items():
        boxes = []
        for i in sorted(idxs):
            if 0 <= i < n:
                boxes.append(list(bbox_list[i]))
        if boxes:
            out[label] = boxes
    return out


def label_boxes_to_detections(
    label_boxes: dict[str, list[list[float]]],
    *,
    default_conf: float = 0.6,
) -> list[dict]:
    dets = []
    names = list(label_boxes.keys())
    for li, (label, boxes) in enumerate(label_boxes.items()):
        for box in boxes:
            if len(box) < 4:
                continue
            dets.append({
                "className": str(label),
                "classId": int(li),
                "confidence": float(default_conf),
                "bbox": [round(float(box[0]), 1), round(float(box[1]), 1),
                         round(float(box[2]), 1), round(float(box[3]), 1)],
            })
    return dets


def _get_fo1(model_dir: str):
    ensure_vlm_fo1_on_path()
    with _lock:
        if model_dir in _fo1_cache:
            return _fo1_cache[model_dir]
        from vlm_fo1.model.builder import load_pretrained_model

        tokenizer, model, image_processors = load_pretrained_model(model_dir)
        _fo1_cache[model_dir] = (tokenizer, model, image_processors)
        return tokenizer, model, image_processors


def build_target_phrase(prompt: str | None, classes: str | list | None) -> str:
    p = (prompt or "").strip()
    if p:
        return p
    if isinstance(classes, str):
        parts = [x.strip() for x in classes.replace("，", ",").split(",") if x.strip()]
    elif isinstance(classes, (list, tuple)):
        parts = [str(x).strip() for x in classes if str(x).strip()]
    else:
        parts = []
    if parts:
        return ", ".join(parts)
    return "object"


def ground_image(
    model_dir: str,
    image_bgr: np.ndarray,
    *,
    prompt: str | None = None,
    classes: str | list | None = None,
    proposal_conf: float = 0.12,
    max_proposals: int = 80,
    score: float = 0.55,
) -> dict[str, Any]:
    """端到端：YOLO proposals + VLM-FO1 筛选 → 标准化 detections。"""
    import torch
    from PIL import Image

    ensure_vlm_fo1_on_path()
    from vlm_fo1.mm_utils import prepare_inputs

    target = build_target_phrase(prompt, classes)
    bbox_list = propose_boxes_yolo(
        image_bgr, conf=proposal_conf, max_boxes=max_proposals,
    )
    if not bbox_list:
        return {
            "detections": [],
            "count": 0,
            "prompt": target,
            "proposalCount": 0,
            "rawText": "",
            "engine": "vlm-fo1",
        }

    tokenizer, model, image_processors = _get_fo1(model_dir)
    img_pil = Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
        img_pil.save(tmp_path, quality=95)

    try:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": tmp_path}},
                    {"type": "text", "text": OD_TEMPLATE.format(target)},
                ],
                "bbox_list": bbox_list,
            }
        ]
        device = "cuda" if torch.cuda.is_available() else "cpu"
        generation_kwargs = prepare_inputs(
            model_dir,
            model,
            image_processors,
            tokenizer,
            messages,
            device=device,
            max_tokens=2048,
            top_p=0.05,
            temperature=0.0,
            do_sample=False,
        )
        with torch.inference_mode():
            output_ids = model.generate(**generation_kwargs)
        prompt_len = generation_kwargs["inputs"].shape[1]
        raw = tokenizer.decode(output_ids[0, prompt_len:]).strip()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    label_boxes = parse_fo1_prediction_to_label_boxes(raw, bbox_list)
    # 官方 extract 若可用则优先
    try:
        from vlm_fo1.mm_utils import extract_predictions_to_bboxes
        official = extract_predictions_to_bboxes(raw, bbox_list)
        if isinstance(official, dict) and official:
            label_boxes = {
                str(k): [list(b) for b in (v or [])]
                for k, v in official.items()
            }
    except Exception:  # noqa: BLE001
        pass

    detections = label_boxes_to_detections(label_boxes, default_conf=float(score))
    return {
        "detections": detections,
        "count": len(detections),
        "prompt": target,
        "proposalCount": len(bbox_list),
        "rawText": raw,
        "engine": "vlm-fo1",
        "promptClasses": [target],
    }
