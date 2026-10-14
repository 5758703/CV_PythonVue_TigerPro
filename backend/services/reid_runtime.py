"""Shared runtime policy for independent person ReID and MTMC."""
from __future__ import annotations
import os


def runtime_name(value=None):
    name = str(value or os.environ.get("REID_RUNTIME", "python")).strip().lower()
    if name not in ("python", "cpp", "auto"):
        raise ValueError("reidRuntime must be python, cpp or auto")
    return name


def summarize_runtime(metadata):
    """Summarize an operation without hiding earlier native fallback calls."""
    records = [m for m in metadata if m]
    if not records:
        return {}
    result = dict(records[-1])
    result["callCount"] = len(records)
    for field in ("provider", "backend", "effectiveRuntime"):
        values = sorted({str(m[field]) for m in records if m.get(field)})
        if values:
            result[field] = values[0] if len(values) == 1 else "mixed"
            result[field + "s"] = values
    reasons = list(dict.fromkeys(str(m["fallbackReason"]) for m in records if m.get("fallbackReason")))
    if reasons or any(m.get("degraded") for m in records):
        result["degraded"] = True
    if reasons:
        result["fallbackReason"] = "; ".join(reasons)
    return result


def _native_extract(path, images):
    from services.reid_cpp import extract_batch
    return extract_batch(path, images)


def _dispatch(path, images, runtime, legacy):
    name = runtime_name(runtime)
    if name == "python":
        return legacy()
    try:
        features, meta = _native_extract(path() if callable(path) else path, images)
        return features, {**meta, "requestedRuntime": name, "effectiveRuntime": "cpp"}
    except Exception as error:
        if name == "cpp":
            raise RuntimeError(f"ReID C++ inference failed: {error}") from error
        features, meta = legacy()
        return features, {**meta, "requestedRuntime": name, "effectiveRuntime": "python",
                          "degraded": True, "fallbackReason": str(error)}


def extract_youtu(model_path, image, *, runtime=None, prefer="fp32", legacy=None):
    from person_reid_dnn import resolve_onnx, extract_feature
    legacy = legacy or (lambda: extract_feature(model_path, image, prefer=prefer, runtime="python"))
    if runtime_name(runtime) == "python":
        return legacy()
    features, meta = _dispatch(lambda: resolve_onnx(model_path, prefer=prefer), [image], runtime,
                               lambda: _legacy_batch([image], lambda crop: legacy()))
    return features[0], meta


def _legacy_batch(images, extract):
    import numpy as np
    features, metadata = [], []
    for image in images:
        feature, meta = extract(image)
        features.append(feature)
        metadata.append(meta)
    return np.stack(features), {**summarize_runtime(metadata), "batchSize": len(features)}


def extract_youtu_batch(model_path, images, *, runtime=None):
    from person_reid_dnn import extract_feature, resolve_onnx
    images = list(images)
    if not images:
        return [], {}
    name = runtime_name(runtime)
    legacy = lambda: _legacy_batch(images, lambda image: extract_feature(model_path, image, runtime="python"))
    if name == "python":
        return legacy()
    return _dispatch(lambda: resolve_onnx(model_path), images, name, legacy)


def extract_strong(path, image, *, runtime=None, legacy):
    if runtime_name(runtime) == "python":
        return legacy(), {}
    features, meta = _dispatch(path, [image], runtime, lambda: _legacy_batch([image], lambda crop: (legacy(), {})))
    return features[0], meta
