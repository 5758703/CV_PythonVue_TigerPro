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


def _top_k(form, default: int = 5) -> int:
    raw = form.get("topK")
    try:
        value = default if raw in (None, "") else int(raw)
    except (TypeError, ValueError) as exc:
        raise ScenarioInputError("topK must be an integer between 1 and 20") from exc
    if not 1 <= value <= 20:
        raise ScenarioInputError("topK must be an integer between 1 and 20")
    return value


def _dilate_px(form, default: int = 0) -> int:
    raw = form.get("dilatePx")
    try:
        value = default if raw in (None, "") else int(raw)
    except (TypeError, ValueError) as exc:
        raise ScenarioInputError("dilatePx must be an integer between 0 and 64") from exc
    if not 0 <= value <= 64:
        raise ScenarioInputError("dilatePx must be an integer between 0 and 64")
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
    configured_path = _weight_path(model.file_path, library=model.library)
    contract = evaluate_scenario_contract(
        scenario,
        model,
        configured_path,
        runtime_probe=lambda module: _find_module_spec(module) is not None,
        requested_precision=precision,
    )
    if not contract.api_ready:
        raise ScenarioInputError(contract.reason or "model scenario is unavailable")
    path = contract.weight_path
    if path is None and str(model.library or "").strip().lower() != "qwen-vl-api":
        raise ScenarioInputError(contract.reason or "model scenario is unavailable")
    if path is None:
        path = Path(".")
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


def _predict_plate_pose(path: str, raw: bytes, *, conf: float, imgsz: int) -> dict:
    """Convert YOLO plate-pose keypoints into detection + quad payloads."""
    from inference import _get_model, _safe_plot, _yolo_predict_kwargs

    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ScenarioInputError("invalid image data")
    model = _get_model(path)
    result = model.predict(image, **_yolo_predict_kwargs(conf=conf, imgsz=imgsz))[0]
    detections = []
    keypoints = getattr(result, "keypoints", None)
    boxes = getattr(result, "boxes", None)
    confs = boxes.conf.cpu().numpy() if boxes is not None and getattr(boxes, "conf", None) is not None else None
    xyxy = boxes.xyxy.cpu().numpy() if boxes is not None and getattr(boxes, "xyxy", None) is not None else None
    kp_data = keypoints.data.cpu().numpy() if keypoints is not None and getattr(keypoints, "data", None) is not None else []
    for index, points in enumerate(kp_data):
        visible = [point for point in points if len(point) >= 2 and (len(point) < 3 or float(point[2]) > 0)]
        if len(visible) < 2 and (xyxy is None or index >= len(xyxy)):
            continue
        if xyxy is not None and index < len(xyxy):
            bbox = [round(float(value), 1) for value in xyxy[index].tolist()]
        else:
            xs = [float(point[0]) for point in visible]
            ys = [float(point[1]) for point in visible]
            bbox = [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]
        quad = [[round(float(point[0]), 1), round(float(point[1]), 1)] for point in points[:4]]
        detections.append({
            "className": "license_plate",
            "classId": 0,
            "confidence": round(float(confs[index]), 4) if confs is not None and index < len(confs) else 0.0,
            "bbox": bbox,
            "quad": quad,
            "keypoints": [
                [round(float(point[0]), 1), round(float(point[1]), 1), round(float(point[2]), 4) if len(point) > 2 else 1.0]
                for point in points
            ],
        })
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


def _face_recognize(model: AiModel, path: Path, raw: bytes, form, scenario: dict) -> dict:
    """1:N face recognition against the enrolled gallery for this model key."""
    from inference import recognize_faces

    threshold = _number(form, "threshold", float(scenario["defaults"].get("threshold", 0.4)))
    det_thresh = _number(form, "detThresh", float(scenario["defaults"].get("detThresh", 0.5)))
    library = str(model.library or "insightface").strip().lower()
    if library == "insightface":
        # contract.weight_path is the pack directory: uploads/insightface/models/<pack>
        pack_dir = path if path.name.startswith("buffalo") else path
        root_dir = str(pack_dir.parent.parent) if pack_dir.parent.name == "models" else str(path)
        pack_name = str(model.version or pack_dir.name)
    else:
        root_dir = str(path if path.is_dir() else path.parent)
        pack_name = str(model.version or "")
    return recognize_faces(
        root_dir,
        pack_name,
        model.model_key,
        raw,
        threshold=threshold,
        det_thresh=det_thresh,
        draw=True,
        library=library,
    )


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


def _inpaint(path: Path, files, form, scenario: dict) -> dict:
    from inference import inpaint_image_lama

    raw, _image = _read_image(files.get("file"), scenario, label="image")
    mask_raw, _mask = _read_image(files.get("mask"), scenario, label="mask")
    dilate = _dilate_px(form, int(scenario["defaults"].get("dilatePx", 0)))
    try:
        payload = inpaint_image_lama(str(path), raw, mask_raw, dilate_px=dilate)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "inpainting failed") from exc
    return {
        "imageBase64": payload.get("imageBase64"),
        "maskPreviewBase64": payload.get("maskPreviewBase64"),
        "width": payload.get("width"),
        "height": payload.get("height"),
        "backend": payload.get("backend"),
        "maskPixels": payload.get("maskPixels"),
        "dilatePx": payload.get("dilatePx", dilate),
        "latencyMs": payload.get("latencyMs"),
    }


def _classify(model: AiModel, path: Path, raw: bytes, form, scenario: dict) -> dict:
    top_k = _top_k(form, int(scenario["defaults"].get("topK", 5)))
    precision = (form.get("precision") or scenario["defaults"].get("precision") or "fp32")
    precision = str(precision).strip().lower()
    if precision not in ("fp32", "int8"):
        raise ScenarioInputError("precision must be fp32 or int8")
    library = str(model.library or "").strip().lower()
    try:
        if library == "yolo-master":
            from services import yolo_master as ym

            conf = _number(form, "conf", float(scenario["defaults"].get("conf", 0.25)))
            payload = ym.classify_image(str(path), raw, top_k=top_k, conf=conf)
        else:
            from inference import classify_image

            payload = classify_image(
                str(path),
                raw,
                task=str(model.task or "image-classification"),
                top_k=top_k,
                library=library,
                precision=precision,
            )
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "classification failed") from exc
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        results = []
    normalized = []
    for item in results:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        score = item.get("score")
        if not isinstance(label, str) or not label:
            continue
        entry = {"label": label}
        if _is_finite_number(score):
            entry["score"] = round(float(score), 4)
        normalized.append(entry)
    return {
        "results": normalized,
        "top": normalized[0] if normalized else None,
        "topK": top_k,
        "precision": payload.get("precision") if isinstance(payload, dict) else precision,
        "backend": payload.get("backend") if isinstance(payload, dict) else None,
        "latencyMs": payload.get("latencyMs") if isinstance(payload, dict) else None,
        "engine": payload.get("engine") if isinstance(payload, dict) else None,
    }


def _body_pose(model: AiModel, model_key: str, path: Path, raw: bytes, form, scenario: dict) -> dict:
    conf = _number(form, "conf", float(scenario["defaults"].get("conf", 0.25)))
    library = str(model.library or "").strip().lower()
    try:
        if library == "rtmlib" or model_key.startswith(("rtmo", "rtmpose", "dwpose")):
            from inference import estimate_pose_rtmlib

            payload = estimate_pose_rtmlib(model_key, str(path), raw, conf=conf, draw=True)
        elif library == "yolo-master":
            from services import yolo_master as ym

            payload = ym.estimate_pose(str(path), raw, conf=conf, draw=True)
        else:
            from inference import estimate_pose

            payload = estimate_pose(_detection_weight(path), raw, conf=conf, draw=True)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "pose estimation failed") from exc
    persons = payload.get("persons") if isinstance(payload, dict) else None
    if not isinstance(persons, list):
        persons = []
    return {
        "count": int(payload.get("count") or len(persons)),
        "persons": persons,
        "imageBase64": payload.get("imageBase64"),
        "width": payload.get("width"),
        "height": payload.get("height"),
        "keypointCount": payload.get("keypointCount") or 17,
        "poseType": payload.get("poseType") or "body17",
        "conf": conf,
    }


def _multimodal_ground(path: Path, raw: bytes, form, scenario: dict) -> dict:
    from inference import detect_image_vlm_fo1

    conf = _number(form, "conf", float(scenario["defaults"].get("conf", 0.25)))
    prompt = form.get("prompt")
    if prompt in (None, ""):
        prompt = scenario["defaults"].get("prompt") or "person"
    prompt = str(prompt).strip()
    if not prompt:
        raise ScenarioInputError("prompt is required")
    if len(prompt) > 500:
        raise ScenarioInputError("prompt must be at most 500 characters")
    try:
        payload = detect_image_vlm_fo1(
            str(path), raw, conf=conf, draw=True, prompt=prompt,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "multimodal grounding failed") from exc
    detections = payload.get("detections") if isinstance(payload, dict) else None
    if not isinstance(detections, list):
        detections = []
    return {
        "detections": detections,
        "count": int(payload.get("count") or len(detections)),
        "imageBase64": payload.get("imageBase64"),
        "width": payload.get("width"),
        "height": payload.get("height"),
        "prompt": prompt,
        "promptClasses": payload.get("promptClasses"),
        "engine": payload.get("engine") or "vlm-fo1",
        "proposalCount": payload.get("proposalCount"),
    }


def _open_vocab(path: Path, raw: bytes, form, scenario: dict) -> dict:
    from inference import detect_image_omdet

    conf = _number(form, "conf", float(scenario["defaults"].get("conf", 0.25)))
    classes = form.get("classes")
    prompt = form.get("prompt")
    if classes in (None, "") and prompt not in (None, ""):
        classes = prompt
    if classes in (None, ""):
        classes = scenario["defaults"].get("prompt") or scenario["defaults"].get("classes") or "person"
    classes = str(classes).strip()
    if not classes:
        raise ScenarioInputError("classes or prompt is required")
    try:
        payload = detect_image_omdet(str(path), raw, conf=conf, draw=True, classes=classes)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "open-vocab detection failed") from exc
    detections = payload.get("detections") if isinstance(payload, dict) else None
    if not isinstance(detections, list):
        detections = []
    return {
        "detections": detections,
        "count": int(payload.get("count") or len(detections)),
        "imageBase64": payload.get("imageBase64"),
        "width": payload.get("width"),
        "height": payload.get("height"),
        "promptClasses": payload.get("promptClasses") or [classes],
        "engine": payload.get("engine") or "omdet",
    }


def _predict_objects(model: AiModel, path: Path, raw: bytes, form, scenario: dict, *, obb: bool) -> dict:
    conf = _number(form, "conf", float(scenario["defaults"].get("conf", 0.5)))
    size = _imgsz(form, int(scenario["defaults"].get("imgsz", 640)))
    library = str(model.library or "").strip().lower()
    model_key = str(model.model_key or scenario.get("modelKey") or "")
    try:
        if library == "modelscope":
            from inference import detect_image_modelscope

            return detect_image_modelscope(str(path), raw, conf=conf, draw=True)
        if library == "rfdetr":
            from inference import detect_image_rfdetr

            return detect_image_rfdetr(str(path), raw, conf=conf, draw=True, model_key=model_key)
        if library == "transformers":
            from inference import detect_image_hf, detect_image_omdet, _is_omdet_model

            if _is_omdet_model(str(path)) or "omdet" in model_key.lower():
                classes = form.get("classes") or form.get("prompt") or "person"
                return detect_image_omdet(str(path), raw, conf=conf, draw=True, classes=classes)
            return detect_image_hf(
                str(path), raw, conf=conf, draw=True,
                task=str(model.task or "object-detection"),
            )
        if library == "yolo-master":
            from services import yolo_master as ym

            if obb or str(model.task or "").lower() == "obb":
                return ym.detect_obb(str(path), raw, conf=conf, draw=True, model_key=model_key)
            return ym.detect_image(str(path), raw, conf=conf, draw=True, model_key=model_key)
        return _predict_detection(
            _detection_weight(path), raw, conf=conf, imgsz=size, obb=obb,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "detection failed") from exc


def _instance_segment(model: AiModel, path: Path, raw: bytes, form, scenario: dict) -> dict:
    conf = _number(form, "conf", float(scenario["defaults"].get("conf", 0.25)))
    library = str(model.library or "").strip().lower()
    model_key = str(model.model_key or scenario.get("modelKey") or "")
    classes = form.get("classes")
    try:
        if library == "rfdetr":
            from inference import segment_image_rfdetr

            payload = segment_image_rfdetr(
                str(path), raw, conf=conf, draw=True, model_key=model_key,
            )
        elif library == "yolo-master":
            from services import yolo_master as ym

            payload = ym.segment_image(str(path), raw, conf=conf, draw=True)
        else:
            from inference import segment_image_ultralytics

            payload = segment_image_ultralytics(
                _detection_weight(path), raw, conf=conf, draw=True, classes=classes,
            )
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "instance segmentation failed") from exc
    return _add_mask_metrics(payload if isinstance(payload, dict) else {"detections": []})


def _person_reid(path: Path, files, form, scenario: dict) -> dict:
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
    threshold = _number(form, "threshold", float(scenario["defaults"].get("threshold", 0.45)))
    from person_reid_dnn import extract_feature
    from services.reid_gallery import l2_normalize
    from services.vehicle_reid_feat import cosine

    try:
        query_feat, query_meta = extract_feature(str(path), query_image)
        query_embedding = l2_normalize(np.asarray(query_feat, dtype=np.float32))
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "person ReID failed") from exc
    matches = []
    for source_index, upload in enumerate(gallery_uploads):
        _gallery_raw, image = _read_image(upload, scenario, label="gallery image")
        feat, _meta = extract_feature(str(path), image)
        embedding = l2_normalize(np.asarray(feat, dtype=np.float32))
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
    matches.sort(
        key=lambda item: -item["_rawSimilarity"]
        if item["_rawSimilarity"] is not None else float("inf")
    )
    for rank, item in enumerate(matches, start=1):
        item.pop("_rawSimilarity", None)
        item["rank"] = rank
    return {
        "query": query_upload.filename,
        "backend": {"engine": "person-reid", **(query_meta or {})},
        "matches": matches,
    }


def _hand_pose(path: Path, raw: bytes, form, scenario: dict) -> dict:
    from services.handpose import detect_hands, draw_hands

    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ScenarioInputError("invalid image data")
    conf = _number(form, "conf", float(scenario["defaults"].get("conf", 0.8)))
    try:
        hands = detect_hands(image, str(path), hand_conf=conf)
        plotted = draw_hands(image.copy(), hands)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "hand pose failed") from exc
    ok, encoded = cv2.imencode(".jpg", plotted)
    height, width = image.shape[:2]
    return {
        "count": len(hands),
        "hands": hands,
        "imageBase64": base64.b64encode(encoded.tobytes()).decode() if ok else None,
        "width": width,
        "height": height,
    }


def _industrial_diagnosis(raw: bytes, form, scenario: dict) -> dict:
    from services.defect_diagnosis import qwen_vl_configured, run_pipeline

    if not qwen_vl_configured():
        raise ScenarioInputError("Qwen-VL API is not configured")
    prompt = (form.get("prompt") or scenario["defaults"].get("scenario") or "general")
    conf = _number(form, "conf", float(scenario["defaults"].get("conf", 0.25)))
    # Cloud diagnosis still needs a local detector gate; reuse a common YOLO if present.
    model_folder = Path(current_app.config["MODEL_FOLDER"])
    det_candidates = [
        model_folder / "yolo26n" / "yolo26n.pt",
        model_folder / "yolo26n.pt",
        model_folder / "yolo11n" / "yolo11n.pt",
        model_folder / "yolov8n.pt",
    ]
    det_path = next((str(item) for item in det_candidates if item.is_file()), None)
    if det_path is None:
        raise ScenarioInputError("no local detector weight available for diagnosis gate")
    try:
        return run_pipeline(
            raw, det_path=det_path, conf=conf, scenario=str(prompt), draw=True,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "industrial diagnosis failed") from exc


def _form_text(form, name: str = "text", *, required: bool = True, maximum: int = 8000) -> str:
    value = form.get(name)
    text = "" if value is None else str(value).strip()
    if required and not text:
        raise ScenarioInputError(f"{name} is required")
    if len(text) > maximum:
        raise ScenarioInputError(f"{name} must be at most {maximum} characters")
    return text


def _text_nlp(model: AiModel, path: Path, form, scenario: dict) -> dict:
    ability = scenario["ability"]
    directory = str(path)
    try:
        if ability == "token-classification":
            from inference import extract_entities

            return extract_entities(directory, _form_text(form), task=str(model.task or ability))
        if ability == "text-classification":
            from inference import classify_text

            return classify_text(directory, _form_text(form), task=str(model.task or ability))
        if ability == "zero-shot-classification":
            from inference import zero_shot

            labels_raw = form.get("labels") or scenario["defaults"].get("labels") or ""
            if isinstance(labels_raw, str):
                labels = [item.strip() for item in labels_raw.split(",") if item.strip()]
            elif isinstance(labels_raw, list):
                labels = [str(item).strip() for item in labels_raw if str(item).strip()]
            else:
                labels = []
            if len(labels) < 2:
                raise ScenarioInputError("labels must include at least two candidates")
            return zero_shot(directory, _form_text(form), labels, task=str(model.task or ability))
        if ability == "fill-mask":
            from inference import fill_mask

            return fill_mask(
                directory, _form_text(form), task=str(model.task or ability),
                top_k=_top_k(form, int(scenario["defaults"].get("topK", 5))),
            )
        if ability in ("summarization", "translation"):
            from inference import generate_text

            return generate_text(directory, _form_text(form), task=str(model.task or ability))
        if ability == "question-answering":
            from inference import answer_question

            return answer_question(
                directory,
                _form_text(form, "question"),
                _form_text(form, "context", maximum=20000),
                task=str(model.task or ability),
            )
    except ScenarioInputError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "text inference failed") from exc
    raise ScenarioInputError(f"unsupported text ability: {ability}")


def _save_upload_temp(upload, *, suffix: str) -> Path:
    import tempfile

    if upload is None or not getattr(upload, "filename", ""):
        raise ScenarioInputError("audio is required" if suffix.startswith(".wav") or suffix.startswith(".mp") else "file is required")
    raw = upload.read()
    if not raw:
        raise ScenarioInputError("uploaded file is empty")
    max_size = int(current_app.config.get("SCENARIO_MAX_IMAGE_BYTES", 12 * 1024 * 1024)) * 4
    if len(raw) > max_size:
        raise ScenarioPayloadTooLarge("uploaded file exceeds the scenario size limit")
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    handle.write(raw)
    handle.close()
    return Path(handle.name)


def _speech_asr(model: AiModel, path: Path, files, form, scenario: dict) -> dict:
    upload = files.get("file")
    suffix = Path(getattr(upload, "filename", "") or "audio.wav").suffix.lower() or ".wav"
    temp = _save_upload_temp(upload, suffix=suffix)
    library = str(model.library or "").strip().lower()
    try:
        if library in ("funasr-nano",):
            from inference import transcribe_audio_nano

            return transcribe_audio_nano(str(path), str(temp))
        if library in ("funasr-onnx",):
            from inference import transcribe_audio_onnx

            return transcribe_audio_onnx(str(path), str(temp))
        if library in ("funasr",):
            from inference import transcribe_audio

            return transcribe_audio(str(path), str(temp))
        if "moss" in str(model.model_key or "").lower():
            from inference import transcribe_audio_moss_diarize

            return transcribe_audio_moss_diarize(str(path), str(temp))
        if "moonshine" in str(model.model_key or "").lower():
            from inference import transcribe_audio_moonshine

            return transcribe_audio_moonshine(str(path), str(temp))
        from inference import transcribe_audio_transformers

        return transcribe_audio_transformers(str(path), str(temp))
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "speech recognition failed") from exc
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _speech_tts(model: AiModel, path: Path, form, scenario: dict) -> dict:
    text = _form_text(form)
    library = str(model.library or "").strip().lower()
    try:
        if library in ("sherpa-onnx", "melotts"):
            from inference import synthesize_speech_melotts

            return synthesize_speech_melotts(str(path), text)
        if library == "vibevoice":
            from inference import synthesize_speech_vibevoice

            speaker = form.get("speaker") or scenario["defaults"].get("speaker") or "en-Carter_man"
            return synthesize_speech_vibevoice(str(path), text, speaker=str(speaker))
        from inference import synthesize_speech_hf

        return synthesize_speech_hf(str(path), text, task=str(model.task or "text-to-speech"))
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "text-to-speech failed") from exc


def _talking_head(path: Path, files, form, scenario: dict) -> dict:
    import tempfile

    image = files.get("file") or files.get("image")
    audio = files.get("audio")
    if image is None or not getattr(image, "filename", ""):
        raise ScenarioInputError("image is required")
    if audio is None or not getattr(audio, "filename", ""):
        raise ScenarioInputError("audio is required")
    image_temp = _save_upload_temp(image, suffix=Path(image.filename).suffix.lower() or ".jpg")
    audio_temp = _save_upload_temp(audio, suffix=Path(audio.filename).suffix.lower() or ".wav")
    out_temp = Path(tempfile.mkstemp(suffix=".mp4")[1])
    try:
        from inference import synthesize_talking_head

        synthesize_talking_head(str(path), str(image_temp), str(audio_temp), str(out_temp))
        video_b64 = base64.b64encode(out_temp.read_bytes()).decode() if out_temp.is_file() else None
        return {"videoBase64": video_b64, "format": "mp4"}
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "talking-head synthesis failed") from exc
    finally:
        for item in (image_temp, audio_temp, out_temp):
            try:
                item.unlink(missing_ok=True)
            except OSError:
                pass


def _document_ocr(model: AiModel, path: Path, raw: bytes, form, scenario: dict) -> dict:
    key = str(model.model_key or "")
    library = str(model.library or "").strip().lower()
    conf = _number(form, "conf", float(scenario["defaults"].get("conf", 0.25)))
    try:
        if library == "ultralytics" or "table-extraction" in key:
            return _predict_detection(_detection_weight(path), raw, conf=conf, imgsz=640, obb=False)
        if library == "rapidtable":
            # Best-effort: return structure payload if rapidtable API exists locally.
            try:
                from rapidtable import RapidTable  # type: ignore

                engine = RapidTable(model_path=str(path))
                result = engine(raw)
                return {"tables": result, "engine": "rapidtable"}
            except Exception as exc:  # noqa: BLE001
                raise ScenarioInputError(str(exc) or "table structure failed") from exc
        # PP-OCR: prefer paired det+rec under MODEL_FOLDER when available.
        model_folder = Path(current_app.config["MODEL_FOLDER"])
        det_dir = model_folder / "PP-OCRv6_small_det_onnx"
        rec_dir = model_folder / "PP-OCRv6_small_rec_onnx"
        if not det_dir.is_dir():
            det_dir = path if path.is_dir() else path.parent
        if not rec_dir.is_dir():
            rec_dir = det_dir
        from inference import paddle_ocr

        rec_only = "rec" in key and "det" not in key
        return paddle_ocr(str(det_dir), str(rec_dir), raw, rec_only=rec_only)
    except ScenarioInputError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise ScenarioInputError(str(exc) or "document OCR failed") from exc


_TEXT_ABILITIES = frozenset((
    "token-classification",
    "text-classification",
    "zero-shot-classification",
    "fill-mask",
    "summarization",
    "translation",
    "question-answering",
))


def run_scenario(model_key: str, files, form) -> dict:
    """Validate and execute one registered scenario by its exact catalog key."""
    scenario = get_scenario(model_key)
    if scenario is None:
        raise ScenarioInputError("model scenario not found")
    requested_precision = None
    if model_key in ("efficient-sam", "mobilenet-v2"):
        requested_precision = (form.get("precision") or scenario["defaults"].get("precision") or "fp32")
        requested_precision = str(requested_precision).strip().lower()
        if requested_precision not in ("fp32", "int8"):
            raise ScenarioInputError("precision must be fp32 or int8")
    model, path = _resolve_model(scenario, precision=requested_precision)
    ability = scenario["ability"]
    allowed_fields = {
        "interactive-segmentation": frozenset(("points", "labels", "pointLabels", "box", "mode", "precision")),
        "vehicle-reid": frozenset(("threshold",)),
        "person-reid": frozenset(("threshold",)),
        "plate-detection": frozenset(("conf", "imgsz")),
        "plate-pose": frozenset(("conf", "imgsz")),
        "object-detection": frozenset(("conf", "imgsz")),
        "obb": frozenset(("conf", "imgsz")),
        "face-recognition": frozenset(("threshold", "detThresh")),
        "image-inpainting": frozenset(("dilatePx",)),
        "image-classification": frozenset(("topK", "precision", "conf")),
        "multimodal-grounding": frozenset(("prompt", "conf")),
        "open-vocab-detection": frozenset(("prompt", "classes", "conf")),
        "body-pose": frozenset(("conf",)),
        "instance-segmentation": frozenset(("conf", "classes")),
        "hand-pose": frozenset(("conf",)),
        "industrial-diagnosis": frozenset(("prompt", "conf")),
        "document-ocr": frozenset(("conf",)),
        "token-classification": frozenset(("text",)),
        "text-classification": frozenset(("text",)),
        "zero-shot-classification": frozenset(("text", "labels")),
        "fill-mask": frozenset(("text", "topK")),
        "summarization": frozenset(("text",)),
        "translation": frozenset(("text",)),
        "question-answering": frozenset(("question", "context")),
        "speech-recognition": frozenset(("language",)),
        "text-to-speech": frozenset(("text", "speaker")),
        "talking-head": frozenset(),
    }.get(ability, frozenset())
    unknown_fields = sorted(set(form.keys()) - allowed_fields)
    if unknown_fields:
        raise ScenarioInputError(f"unknown form field: {unknown_fields[0]}")
    if ability in ("vehicle-reid", "person-reid"):
        allowed_files = frozenset(("query", "gallery"))
    elif ability == "image-inpainting":
        allowed_files = frozenset(("file", "mask"))
    elif ability in _TEXT_ABILITIES or ability == "text-to-speech":
        allowed_files = frozenset()
    elif ability == "talking-head":
        allowed_files = frozenset(("file", "image", "audio"))
    else:
        allowed_files = frozenset(("file",))
    unknown_files = sorted(set(files.keys()) - allowed_files)
    if unknown_files:
        raise ScenarioInputError(f"unknown file field: {unknown_files[0]}")
    started = perf_counter()
    if ability == "vehicle-reid":
        result = _vehicle_reid(path, files, form, scenario)
    elif ability == "person-reid":
        result = _person_reid(path, files, form, scenario)
    elif ability == "face-recognition":
        raw, _image = _read_image(files.get("file"), scenario)
        result = _face_recognize(model, path, raw, form, scenario)
    elif ability == "image-inpainting":
        result = _inpaint(path, files, form, scenario)
    elif ability == "image-classification":
        raw, _image = _read_image(files.get("file"), scenario)
        result = _classify(model, path, raw, form, scenario)
    elif ability == "body-pose":
        raw, _image = _read_image(files.get("file"), scenario)
        result = _body_pose(model, scenario["modelKey"], path, raw, form, scenario)
    elif ability == "multimodal-grounding":
        raw, _image = _read_image(files.get("file"), scenario)
        result = _multimodal_ground(path, raw, form, scenario)
    elif ability == "open-vocab-detection":
        raw, _image = _read_image(files.get("file"), scenario)
        result = _open_vocab(path, raw, form, scenario)
    elif ability == "instance-segmentation":
        raw, _image = _read_image(files.get("file"), scenario)
        result = _instance_segment(model, path, raw, form, scenario)
    elif ability == "hand-pose":
        raw, _image = _read_image(files.get("file"), scenario)
        result = _hand_pose(path, raw, form, scenario)
    elif ability == "industrial-diagnosis":
        raw, _image = _read_image(files.get("file"), scenario)
        result = _industrial_diagnosis(raw, form, scenario)
    elif ability == "document-ocr":
        raw, _image = _read_image(files.get("file"), scenario)
        result = _document_ocr(model, path, raw, form, scenario)
    elif ability in _TEXT_ABILITIES:
        result = _text_nlp(model, path, form, scenario)
    elif ability == "speech-recognition":
        result = _speech_asr(model, path, files, form, scenario)
    elif ability == "text-to-speech":
        result = _speech_tts(model, path, form, scenario)
    elif ability == "talking-head":
        result = _talking_head(path, files, form, scenario)
    else:
        raw, image = _read_image(files.get("file"), scenario)
        if ability == "interactive-segmentation":
            result = _segment(model, path, raw, image, form)
        elif ability == "plate-pose":
            conf = _number(form, "conf", float(scenario["defaults"].get("conf", 0.5)))
            size = _imgsz(form, int(scenario["defaults"].get("imgsz", 640)))
            result = _predict_plate_pose(_detection_weight(path), raw, conf=conf, imgsz=size)
        else:
            result = _predict_objects(
                model, path, raw, form, scenario, obb=ability == "obb",
            )
    return {
        "modelKey": scenario["modelKey"],
        "workbench": scenario["workbenchType"],
        "elapsedMs": max(0, round((perf_counter() - started) * 1000)),
        "result": result,
    }
