"""Validated inference entry point for registered model scenarios."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
from flask import current_app

from models import AiModel
from services.model_scenario_readiness import _weight_path, _weights_present
from services.model_scenarios import get_scenario


class ScenarioInputError(ValueError):
    """A client-correctable scenario inference error."""


_EXPECTED_TASKS = {
    "interactive-segmentation": frozenset(("interactive-segmentation",)),
    "vehicle-reid": frozenset(("vehicle-reid",)),
    "plate-detection": frozenset(("object-detection",)),
    "obb": frozenset(("obb",)),
}
_DETECTION_EXTENSIONS = frozenset((".pt", ".pth", ".onnx", ".engine", ".weights"))


def _number(form, name: str, default: float) -> float:
    raw = form.get(name)
    try:
        value = default if raw in (None, "") else float(raw)
    except (TypeError, ValueError) as exc:
        raise ScenarioInputError(f"{name} must be a number between 0 and 1") from exc
    if not 0 <= value <= 1:
        raise ScenarioInputError(f"{name} must be a number between 0 and 1")
    return value


def _imgsz(form, default: int = 640) -> int:
    raw = form.get("imgsz")
    try:
        value = default if raw in (None, "") else int(raw)
    except (TypeError, ValueError) as exc:
        raise ScenarioInputError("imgsz must be an integer between 32 and 4096") from exc
    if not 32 <= value <= 4096:
        raise ScenarioInputError("imgsz must be an integer between 32 and 4096")
    return value


def _json_value(form, *names: str):
    raw = None
    field = names[0]
    for name in names:
        candidate = form.get(name)
        if candidate not in (None, ""):
            raw = candidate
            field = name
            break
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ScenarioInputError(f"{field} must be valid JSON") from exc


def _read_image(upload, scenario: dict, *, label: str = "image") -> tuple[bytes, np.ndarray]:
    if upload is None or not getattr(upload, "filename", ""):
        raise ScenarioInputError(f"{label} is required")
    extension = Path(upload.filename).suffix.lower()
    allowed = frozenset(item.lower() for item in scenario["input"]["formats"])
    if extension not in allowed:
        raise ScenarioInputError("unsupported image extension")
    raw = upload.read()
    max_size = int(current_app.config["MAX_CONTENT_LENGTH"])
    if len(raw) > max_size:
        raise ScenarioInputError("image exceeds the configured upload size limit")
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ScenarioInputError("invalid image data")
    return raw, image


def _resolve_model(scenario: dict) -> tuple[AiModel, Path]:
    model = AiModel.query.filter_by(model_key=scenario["modelKey"]).first()
    if model is None:
        raise ScenarioInputError("model is not registered")
    allowed_tasks = _EXPECTED_TASKS[scenario["ability"]]
    if (model.task or "").strip().lower() not in allowed_tasks:
        raise ScenarioInputError("registered model task does not match scenario ability")
    if model.status != "0":
        raise ScenarioInputError("model is disabled")
    path = _weight_path(model.file_path)
    if not _weights_present(path, model.library):
        raise ScenarioInputError("model weights are missing")
    assert path is not None
    return model, path


def _detection_weight(path: Path) -> str:
    if path.is_file():
        return str(path)
    candidates = sorted(
        candidate for candidate in path.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in _DETECTION_EXTENSIONS
    )
    if not candidates:
        raise ScenarioInputError("model weights are missing")
    return str(candidates[0])


def _obb_detections(result, model) -> list[dict]:
    names = getattr(result, "names", None) or getattr(model, "names", None) or {}
    obb = getattr(result, "obb", None)
    if obb is None:
        return []
    xyxy = obb.xyxy.cpu().numpy() if getattr(obb, "xyxy", None) is not None else []
    quads = obb.xyxyxyxy.cpu().numpy() if getattr(obb, "xyxyxyxy", None) is not None else []
    scores = obb.conf.cpu().numpy() if getattr(obb, "conf", None) is not None else None
    classes = obb.cls.cpu().numpy() if getattr(obb, "cls", None) is not None else None
    from inference import _safe_class_name

    items = []
    for index in range(max(len(xyxy), len(quads))):
        class_id = int(classes[index]) if classes is not None else 0
        item = {
            "className": _safe_class_name(names, class_id),
            "classId": class_id,
            "confidence": round(float(scores[index]), 4) if scores is not None else 0.0,
            "bbox": [round(float(value), 1) for value in xyxy[index].tolist()] if len(xyxy) > index else [],
        }
        if len(quads) > index:
            item["quad"] = [
                [round(float(value), 1) for value in point]
                for point in quads[index].tolist()
            ]
        items.append(item)
    return items


def _legacy_yolov5_detections(results, model, conf: float) -> list[dict]:
    from inference import _safe_class_name

    names = getattr(results, "names", None) or getattr(model, "names", None) or {}
    rows = results.xyxy[0]
    if hasattr(rows, "cpu"):
        rows = rows.cpu().numpy()
    detections = []
    for row in rows:
        if len(row) < 6 or float(row[4]) < conf:
            continue
        class_id = int(row[5])
        detections.append({
            "className": _safe_class_name(names, class_id),
            "classId": class_id,
            "confidence": round(float(row[4]), 4),
            "bbox": [round(float(value), 1) for value in row[:4]],
        })
    return detections


def _predict_detection(path: str, raw: bytes, *, conf: float, imgsz: int, obb: bool) -> dict:
    """Narrow adapter around the existing Ultralytics inference primitives."""
    from inference import (
        _get_model,
        _is_legacy_yolov5_weight,
        _safe_plot,
        _ultralytics_boxes_to_detections,
        _yolo_predict_kwargs,
    )

    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ScenarioInputError("invalid image data")
    model = _get_model(path)
    if _is_legacy_yolov5_weight(path):
        model.conf = conf
        result = model(image, size=imgsz)
        detections = _legacy_yolov5_detections(result, model, conf)
        plotted = image.copy()
        for detection in detections:
            x1, y1, x2, y2 = (int(value) for value in detection["bbox"])
            cv2.rectangle(plotted, (x1, y1), (x2, y2), (0, 255, 255), 2)
    else:
        result = model.predict(image, **_yolo_predict_kwargs(conf=conf, imgsz=imgsz))[0]
        detections = _obb_detections(result, model) if obb else _ultralytics_boxes_to_detections(result, model)
        plotted = _safe_plot(result, image)
    ok, encoded = cv2.imencode(".jpg", plotted)
    height, width = image.shape[:2]
    return {
        "detections": detections,
        "count": len(detections),
        "imageBase64": base64.b64encode(encoded.tobytes()).decode() if ok else None,
        "width": width,
        "height": height,
    }


def _segment(model: AiModel, path: Path, raw: bytes, form) -> dict:
    points = _json_value(form, "points")
    point_labels = _json_value(form, "labels", "pointLabels")
    box = _json_value(form, "box")
    library = (model.library or "").strip().lower()
    if library == "mobilesam":
        from inference import segment_image_mobilesam

        return segment_image_mobilesam(
            str(path), raw, points=points, point_labels=point_labels, box=box,
            mode=(form.get("mode") or "prompt").strip().lower(), draw=True,
        )
    if library in ("opencv-sam", "efficientsam", "efficient-sam"):
        from inference import segment_image_efficientsam

        return segment_image_efficientsam(
            str(path), raw, points=points, point_labels=point_labels, box=box,
            draw=True, precision=(form.get("precision") or "fp32").strip().lower(),
        )
    raise ScenarioInputError(f"unsupported segmentation runtime: {library or 'unknown'}")


def _vehicle_reid(path: Path, files, form, scenario: dict) -> dict:
    query_upload = files.get("query")
    gallery_uploads = files.getlist("gallery")
    if query_upload is None or not query_upload.filename:
        raise ScenarioInputError("query image is required")
    if not gallery_uploads:
        raise ScenarioInputError("at least one gallery image is required")
    _query_raw, query_image = _read_image(query_upload, scenario, label="query image")
    gallery = [
        (upload.filename, _read_image(upload, scenario, label="gallery image")[1])
        for upload in gallery_uploads
    ]
    threshold = _number(form, "threshold", float(scenario["defaults"].get("threshold", 0.7)))
    from services.vehicle_reid_feat import cosine, extract_vehicle_embedding

    query_embedding, query_meta = extract_vehicle_embedding(str(path), query_image)
    matches = []
    for filename, image in gallery:
        embedding, _meta = extract_vehicle_embedding(str(path), image)
        score = cosine(query_embedding, embedding)
        rounded = round(float(score), 4) if score is not None else None
        matches.append({
            "filename": filename,
            "similarity": rounded,
            "matched": rounded is not None and rounded >= threshold,
        })
    return {"query": query_upload.filename, "backend": query_meta, "matches": matches}


def run_scenario(model_key: str, files, form) -> dict:
    """Validate and execute one registered scenario by its exact catalog key."""
    scenario = get_scenario(model_key)
    if scenario is None:
        raise ScenarioInputError("model scenario not found")
    model, path = _resolve_model(scenario)
    ability = scenario["ability"]
    started = perf_counter()
    if ability == "vehicle-reid":
        result = _vehicle_reid(path, files, form, scenario)
    else:
        raw, _image = _read_image(files.get("file"), scenario)
        if ability == "interactive-segmentation":
            result = _segment(model, path, raw, form)
        else:
            conf = _number(form, "conf", float(scenario["defaults"].get("conf", 0.5)))
            size = _imgsz(form, int(scenario["defaults"].get("imgsz", 640)))
            result = _predict_detection(
                _detection_weight(path), raw, conf=conf, imgsz=size, obb=ability == "obb",
            )
    return {
        "modelKey": scenario["modelKey"],
        "workbench": scenario["workbenchType"],
        "elapsedMs": max(0, round((perf_counter() - started) * 1000)),
        "result": result,
    }
