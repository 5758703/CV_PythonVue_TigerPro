"""Validated inference entry point for registered model scenarios."""

from __future__ import annotations

import base64
import binascii
from collections import OrderedDict
import io
import json
import math
from pathlib import Path
from time import perf_counter
import warnings

import cv2
import numpy as np
from flask import current_app

from models import AiModel
from services.model_scenario_contract import evaluate_scenario_contract
from services.model_scenario_readiness import _find_module_spec, _weight_path
from services.model_scenarios import get_scenario


class ScenarioInputError(ValueError):
    """A client-correctable scenario inference error."""


_DETECTION_EXTENSIONS = frozenset((".pt", ".pth", ".onnx", ".engine"))
_READ_CHUNK_BYTES = 64 * 1024
_OBB_MODEL_CACHE: OrderedDict[tuple[str, int, int], object] = OrderedDict()
_MAX_OBB_CACHE_ITEMS = 4


class ScenarioPayloadTooLarge(ScenarioInputError):
    """A scenario-specific request resource limit was exceeded."""


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


def _segmentation_prompts(
    form,
    *,
    allow_auto: bool,
    width: int,
    height: int,
) -> tuple[list | None, list | None, list | None]:
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
    if mode not in ("prompt", "auto"):
        raise ScenarioInputError("mode must be prompt or auto")
    if not allow_auto and mode == "auto":
        raise ScenarioInputError("auto mode is not supported by this scenario")
    if mode != "auto" and not points and not box:
        raise ScenarioInputError("invalid segmentation prompts")
    maximum = int(current_app.config.get("SCENARIO_MAX_PROMPTS", 6))
    prompt_count = len(points or ()) + (1 if box else 0)
    if prompt_count > maximum:
        raise ScenarioInputError(f"at most {maximum} prompt points are allowed")
    if points and any(
        point[0] < 0 or point[0] >= width or point[1] < 0 or point[1] >= height
        for point in points
    ):
        raise ScenarioInputError("segmentation prompt coordinates must be inside the image")
    if box and not (
        0 <= box[0] < box[2] <= width
        and 0 <= box[1] < box[3] <= height
    ):
        raise ScenarioInputError("segmentation box must be ordered and inside the image")
    return points, labels, box


def _read_image(upload, scenario: dict, *, label: str = "image") -> tuple[bytes, np.ndarray]:
    if upload is None or not getattr(upload, "filename", ""):
        raise ScenarioInputError(f"{label} is required")
    extension = Path(upload.filename).suffix.lower()
    allowed = frozenset(item.lower() for item in scenario["input"]["formats"])
    if extension not in allowed:
        raise ScenarioInputError("unsupported image extension")
    max_size = int(current_app.config.get("SCENARIO_MAX_IMAGE_BYTES", 12 * 1024 * 1024))
    chunks = []
    remaining = max_size + 1
    while remaining > 0:
        chunk = upload.read(min(_READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    if len(raw) > max_size:
        raise ScenarioPayloadTooLarge(f"{label} exceeds the scenario image size limit")
    max_pixels = int(current_app.config.get("SCENARIO_MAX_PIXELS", 40_000_000))
    try:
        from PIL import Image

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as header:
                width, height = header.size
                if width <= 0 or height <= 0:
                    raise ScenarioInputError("invalid image data")
                if width * height > max_pixels:
                    raise ScenarioPayloadTooLarge(f"{label} exceeds the scenario pixel limit")
                header.verify()
    except ScenarioInputError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ScenarioPayloadTooLarge(f"{label} exceeds the scenario pixel limit") from exc
    except (OSError, SyntaxError, ValueError) as exc:
        raise ScenarioInputError("invalid image data") from exc
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ScenarioInputError("invalid image data")
    height, width = image.shape[:2]
    if width * height > max_pixels:
        raise ScenarioPayloadTooLarge(f"{label} exceeds the scenario pixel limit")
    return raw, image


def _resolve_model(scenario: dict, *, precision: str | None = None) -> tuple[AiModel, Path]:
    model = AiModel.query.filter_by(model_key=scenario["modelKey"]).first()
    if model is None:
        raise ScenarioInputError("model is not registered")
    configured_path = _weight_path(model.file_path)
    contract = evaluate_scenario_contract(
        scenario,
        model,
        configured_path,
        runtime_probe=lambda module: _find_module_spec(module) is not None,
        requested_precision=precision,
    )
    if not contract.api_ready:
        raise ScenarioInputError(contract.reason or "model scenario is unavailable")
    assert contract.weight_path is not None
    path = contract.weight_path
    if scenario["ability"] == "vehicle-reid":
        from services.vehicle_reid_feat import resolve_vehicle_onnx

        if resolve_vehicle_onnx(str(path)) is None:
            raise ScenarioInputError("model weights are incompatible with scenario runtime")
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
    xywhr = obb.xywhr.cpu().numpy() if getattr(obb, "xywhr", None) is not None else []
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
        if len(xywhr) > index and len(xywhr[index]) >= 5:
            angle = math.degrees(float(xywhr[index][4])) % 180.0
            item["angle"] = round(angle, 2)
            item["angleUnit"] = "degrees"
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


def _clear_obb_model_cache() -> None:
    _OBB_MODEL_CACHE.clear()


def _get_obb_model(path: str):
    """Load PT/ONNX OBB assets with an explicit task and bounded local cache."""
    resolved = Path(path).resolve()
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise ScenarioInputError("model weights are missing") from exc
    signature = (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))
    cached = _OBB_MODEL_CACHE.get(signature)
    if cached is not None:
        _OBB_MODEL_CACHE.move_to_end(signature)
        return cached

    from ultralytics import YOLO

    model = YOLO(str(resolved), task="obb")
    for key in tuple(_OBB_MODEL_CACHE):
        if key[0] == str(resolved):
            _OBB_MODEL_CACHE.pop(key, None)
    _OBB_MODEL_CACHE[signature] = model
    while len(_OBB_MODEL_CACHE) > _MAX_OBB_CACHE_ITEMS:
        _OBB_MODEL_CACHE.popitem(last=False)
    return model


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
    model = _get_obb_model(path) if obb else _get_model(path)
    if not obb and _is_legacy_yolov5_weight(path):
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


def _add_mask_metrics(result: dict) -> dict:
    """Annotate returned masks from their encoded pixels, never a proxy box."""
    for detection in result.get("detections") or ():
        encoded = detection.get("maskBase64") if isinstance(detection, dict) else None
        if not encoded:
            continue
        try:
            mask_bytes = base64.b64decode(encoded, validate=True)
            mask = cv2.imdecode(np.frombuffer(mask_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
        except (binascii.Error, ValueError, TypeError):
            mask = None
        if mask is None or mask.size == 0:
            continue
        if mask.ndim == 3:
            active = np.any(mask != 0, axis=2)
        else:
            active = mask != 0
        area = int(np.count_nonzero(active))
        total = int(active.shape[0] * active.shape[1])
        detection["areaPixels"] = area
        detection["areaRatio"] = area / total if total else 0.0
    return result


def _segment(model: AiModel, path: Path, raw: bytes, image: np.ndarray, form) -> dict:
    library = (model.library or "").strip().lower()
    height, width = image.shape[:2]
    if library == "mobilesam":
        from inference import segment_image_mobilesam

        if form.get("precision") not in (None, ""):
            raise ScenarioInputError("precision is not supported by this scenario")
        points, point_labels, box = _segmentation_prompts(
            form, allow_auto=True, width=width, height=height,
        )
        mode = (form.get("mode") or "prompt").strip().lower()
        if mode != "auto":
            return _add_mask_metrics(_segment_mobilesam_prompt(
                path, raw, points=points, point_labels=point_labels, box=box,
            ))
        return _add_mask_metrics(segment_image_mobilesam(
            str(path), raw, points=points, point_labels=point_labels, box=box,
            mode=mode, draw=True,
        ))
    if library == "opencv-sam":
        from inference import segment_image_efficientsam

        points, point_labels, box = _segmentation_prompts(
            form, allow_auto=False, width=width, height=height,
        )
        precision = (form.get("precision") or "fp32").strip().lower()
        if precision not in ("fp32", "int8"):
            raise ScenarioInputError("precision must be fp32 or int8")
        return _add_mask_metrics(segment_image_efficientsam(
            str(path), raw, points=points, point_labels=point_labels, box=box,
            draw=True, precision=precision,
        ))
    raise ScenarioInputError(f"unsupported segmentation runtime: {library or 'unknown'}")


def _vehicle_reid(path: Path, files, form, scenario: dict) -> dict:
    query_upload = files.get("query")
    gallery_uploads = files.getlist("gallery")
    if query_upload is None or not query_upload.filename:
        raise ScenarioInputError("query image is required")
    if not gallery_uploads:
        raise ScenarioInputError("at least one gallery image is required")
    maximum = int(current_app.config.get("SCENARIO_MAX_GALLERY_IMAGES", 32))
    if len(gallery_uploads) > maximum:
        raise ScenarioInputError(f"at most {maximum} gallery images are allowed")
    _query_raw, query_image = _read_image(query_upload, scenario, label="query image")
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
    for source_index, upload in enumerate(gallery_uploads):
        _gallery_raw, image = _read_image(upload, scenario, label="gallery image")
        embedding, meta = extract_vehicle_embedding(str(path), image)
        if meta.get("backend") != "vehicle-onnx":
            raise RuntimeError("vehicle ReID runtime did not use configured weights")
        score = cosine(query_embedding, embedding)
        raw_score = float(score) if score is not None else None
        rounded = round(raw_score, 4) if raw_score is not None else None
        matches.append({
            "filename": upload.filename,
            "similarity": rounded,
            "distance": round(1.0 - raw_score, 4) if raw_score is not None else None,
            "matched": raw_score is not None and raw_score >= threshold,
            "sourceIndex": source_index,
            "_rawSimilarity": raw_score,
        })
        del image
    matches.sort(
        key=lambda item: -item["_rawSimilarity"]
        if item["_rawSimilarity"] is not None else float("inf")
    )
    for rank, item in enumerate(matches, start=1):
        item.pop("_rawSimilarity", None)
        item["rank"] = rank
    return {"query": query_upload.filename, "backend": safe_query_meta, "matches": matches}


def run_scenario(model_key: str, files, form) -> dict:
    """Validate and execute one registered scenario by its exact catalog key."""
    scenario = get_scenario(model_key)
    if scenario is None:
        raise ScenarioInputError("model scenario not found")
    requested_precision = None
    if model_key == "efficient-sam":
        requested_precision = (form.get("precision") or "fp32").strip().lower()
        if requested_precision not in ("fp32", "int8"):
            raise ScenarioInputError("precision must be fp32 or int8")
    model, path = _resolve_model(scenario, precision=requested_precision)
    allowed_fields = {
        "interactive-segmentation": frozenset(("points", "labels", "pointLabels", "box", "mode", "precision")),
        "vehicle-reid": frozenset(("threshold",)),
        "plate-detection": frozenset(("conf", "imgsz")),
        "obb": frozenset(("conf", "imgsz")),
    }.get(scenario["ability"], frozenset())
    unknown_fields = sorted(set(form.keys()) - allowed_fields)
    if unknown_fields:
        raise ScenarioInputError(f"unknown form field: {unknown_fields[0]}")
    allowed_files = (
        frozenset(("query", "gallery"))
        if scenario["ability"] == "vehicle-reid"
        else frozenset(("file",))
    )
    unknown_files = sorted(set(files.keys()) - allowed_files)
    if unknown_files:
        raise ScenarioInputError(f"unknown file field: {unknown_files[0]}")
    ability = scenario["ability"]
    started = perf_counter()
    if ability == "vehicle-reid":
        result = _vehicle_reid(path, files, form, scenario)
    else:
        raw, image = _read_image(files.get("file"), scenario)
        if ability == "interactive-segmentation":
            result = _segment(model, path, raw, image, form)
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
