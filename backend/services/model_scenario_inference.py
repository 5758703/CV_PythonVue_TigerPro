"""Validated inference entry point for registered model scenarios."""

from __future__ import annotations

import base64
import json
import math
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
_ABILITY_LIBRARIES = {
    "interactive-segmentation": frozenset(("mobilesam", "opencv-sam", "efficientsam", "efficient-sam")),
    "vehicle-reid": frozenset(("clip-reid", "transreid", "vit-reid")),
    "plate-detection": frozenset(("ultralytics",)),
    "obb": frozenset(("ultralytics",)),
}
_SCENARIO_LIBRARIES = {
    "efficient-sam": frozenset(("opencv-sam", "efficientsam", "efficient-sam")),
    "mobile-sam": frozenset(("mobilesam",)),
    "clip-reid-vehicle": frozenset(("clip-reid",)),
    "transreid-vehicle": frozenset(("transreid",)),
    "vehicle-vit-reid": frozenset(("vit-reid",)),
    "keremberke-yolov5m-license-plate": frozenset(("ultralytics",)),
    "keremberke-yolov5n-license-plate": frozenset(("ultralytics",)),
    "yolo26n-p2-plate": frozenset(("ultralytics",)),
    "yolo26n-obb": frozenset(("ultralytics",)),
}
_DETECTION_EXTENSIONS = frozenset((".pt", ".pth", ".onnx", ".engine"))


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


def _is_finite_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _segmentation_prompts(form, *, allow_auto: bool) -> tuple[list | None, list | None, list | None]:
    points = _json_value(form, "points")
    labels = _json_value(form, "labels", "pointLabels")
    box = _json_value(form, "box")
    valid_points = (
        points is None
        or isinstance(points, list)
        and all(
            isinstance(point, list)
            and len(point) == 2
            and all(_is_finite_number(value) for value in point)
            for point in points
        )
    )
    valid_labels = (
        labels is None
        or isinstance(labels, list)
        and all(_is_finite_number(value) and value in (0, 1) for value in labels)
    )
    valid_box = (
        box is None
        or isinstance(box, list)
        and len(box) == 4
        and all(_is_finite_number(value) for value in box)
    )
    labels_match = (
        (points is None and labels is None)
        or isinstance(points, list)
        and isinstance(labels, list)
        and len(points) == len(labels)
    )
    if not (valid_points and valid_labels and valid_box and labels_match):
        raise ScenarioInputError("invalid segmentation prompts")
    mode = (form.get("mode") or "prompt").strip().lower()
    if not allow_auto and mode == "auto":
        raise ScenarioInputError("invalid segmentation prompts")
    if mode != "auto" and not points and not box:
        raise ScenarioInputError("invalid segmentation prompts")
    return points, labels, box


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
    library = (model.library or "").strip().lower()
    if (
        library not in _ABILITY_LIBRARIES[scenario["ability"]]
        or library not in _SCENARIO_LIBRARIES[scenario["modelKey"]]
    ):
        raise ScenarioInputError("unsupported runtime library for scenario")
    path = _weight_path(model.file_path)
    if not _weights_present(path, model.library):
        raise ScenarioInputError("model weights are missing")
    assert path is not None
    if scenario["ability"] == "vehicle-reid":
        from services.vehicle_reid_feat import resolve_vehicle_onnx

        if resolve_vehicle_onnx(str(path)) is None:
            raise ScenarioInputError("model weights are incompatible with scenario runtime")
    elif scenario["modelKey"] == "efficient-sam":
        from efficient_sam_dnn import resolve_onnx

        try:
            resolve_onnx(str(path))
        except (FileNotFoundError, OSError):
            raise ScenarioInputError("model weights are incompatible with scenario runtime") from None
    elif scenario["modelKey"] == "mobile-sam" and (
        not path.is_file() or path.suffix.lower() not in (".pt", ".pth")
    ):
        raise ScenarioInputError("model weights are incompatible with scenario runtime")
    elif scenario["ability"] in ("plate-detection", "obb"):
        _detection_weight(path)
    return model, path


def _detection_weight(path: Path) -> str:
    if path.is_file():
        if path.suffix.lower() in _DETECTION_EXTENSIONS:
            return str(path)
        raise ScenarioInputError("model weights are incompatible with scenario runtime")
    candidates = sorted(
        candidate for candidate in path.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in _DETECTION_EXTENSIONS
    )
    if not candidates:
        raise ScenarioInputError("model weights are incompatible with scenario runtime")
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


def _segment_mobilesam_prompt(
    path: Path,
    raw: bytes,
    *,
    points: list | None,
    point_labels: list | None,
    box: list | None,
) -> dict:
    """Run MobileSAM prompts while preserving the predictor's native box path."""
    from inference import _blend_mask_detections, _encode_mask_b64, _get_mobile_sam_predictor

    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ScenarioInputError("invalid image data")
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    predictor = _get_mobile_sam_predictor(str(path))
    predictor.set_image(rgb)
    point_coords = np.asarray(points, dtype=np.float32) if points else None
    labels = np.asarray(point_labels, dtype=np.int32) if point_labels else None
    box_array = np.asarray(box, dtype=np.float32) if box else None
    masks, scores, _ = predictor.predict(
        point_coords=point_coords,
        point_labels=labels,
        box=box_array,
        multimask_output=box_array is None,
    )
    best = int(np.argmax(scores))
    mask = masks[best]
    ys, xs = np.where(mask)
    bbox = (
        [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
        if len(xs)
        else [0.0, 0.0, 0.0, 0.0]
    )
    detections = [{
        "className": "segment",
        "classId": 0,
        "confidence": round(float(scores[best]), 4),
        "bbox": [round(value, 1) for value in bbox],
        "maskBase64": _encode_mask_b64(mask),
    }]
    plotted = _blend_mask_detections(image, detections)
    ok, encoded = cv2.imencode(".jpg", plotted)
    height, width = image.shape[:2]
    return {
        "detections": detections,
        "count": 1,
        "imageBase64": base64.b64encode(encoded.tobytes()).decode() if ok else None,
        "width": width,
        "height": height,
    }


def _segment(model: AiModel, path: Path, raw: bytes, form) -> dict:
    library = (model.library or "").strip().lower()
    if library == "mobilesam":
        from inference import segment_image_mobilesam

        points, point_labels, box = _segmentation_prompts(form, allow_auto=True)
        mode = (form.get("mode") or "prompt").strip().lower()
        if mode != "auto":
            return _segment_mobilesam_prompt(
                path, raw, points=points, point_labels=point_labels, box=box,
            )
        return segment_image_mobilesam(
            str(path), raw, points=points, point_labels=point_labels, box=box,
            mode=mode, draw=True,
        )
    if library in ("opencv-sam", "efficientsam", "efficient-sam"):
        from inference import segment_image_efficientsam

        points, point_labels, box = _segmentation_prompts(form, allow_auto=False)
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
    if query_meta.get("backend") != "vehicle-onnx":
        raise RuntimeError("vehicle ReID runtime did not use configured weights")
    safe_query_meta = {
        key: query_meta[key]
        for key in ("backend", "dim", "inputSize")
        if key in query_meta
    }
    matches = []
    for filename, image in gallery:
        embedding, meta = extract_vehicle_embedding(str(path), image)
        if meta.get("backend") != "vehicle-onnx":
            raise RuntimeError("vehicle ReID runtime did not use configured weights")
        score = cosine(query_embedding, embedding)
        rounded = round(float(score), 4) if score is not None else None
        matches.append({
            "filename": filename,
            "similarity": rounded,
            "matched": rounded is not None and rounded >= threshold,
        })
    return {"query": query_upload.filename, "backend": safe_query_meta, "matches": matches}


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
