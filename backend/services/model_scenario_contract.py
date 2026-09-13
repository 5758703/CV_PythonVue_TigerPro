"""Side-effect-free contract checks shared by scenario readiness and inference."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Callable


@dataclass(frozen=True)
class ScenarioContractResult:
    weights_present: bool
    runtime_available: bool
    api_ready: bool
    reason: str | None
    weight_path: Path | None = None
    supported_precisions: tuple[str, ...] = ()


_CONTRACTS = {
    "efficient-sam": {
        "task": "interactive-segmentation",
        "library": "opencv-sam",
        "adapter": "efficient_sam",
        "extensions": frozenset((".onnx",)),
        "runtime": ("cv2",),
    },
    "mobile-sam": {
        "task": "interactive-segmentation",
        "library": "mobilesam",
        "adapter": "mobile_sam",
        "extensions": frozenset((".pt", ".pth")),
        "runtime": ("mobile_sam",),
    },
    "clip-reid-vehicle": {
        "task": "vehicle-reid",
        "library": "clip-reid",
        "adapter": "vehicle_reid_onnx",
        "extensions": frozenset((".onnx",)),
        "runtime": ("onnxruntime",),
    },
    "keremberke-yolov5m-license-plate": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "keremberke-yolov5n-license-plate": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "transreid-vehicle": {
        "task": "vehicle-reid",
        "library": "transreid",
        "adapter": "vehicle_reid_onnx",
        "extensions": frozenset((".onnx",)),
        "runtime": ("onnxruntime",),
    },
    "vehicle-vit-reid": {
        "task": "vehicle-reid",
        "library": "vit-reid",
        "adapter": "vehicle_reid_onnx",
        "extensions": frozenset((".onnx",)),
        "runtime": ("onnxruntime",),
    },
    "yolo26n-obb": {
        "task": "obb",
        "library": "ultralytics",
        "adapter": "ultralytics_obb",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo26n-p2-plate": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
}

_MIN_DIRECTORY_ONNX_BYTES = 100_000
_EFFICIENT_SAM_ONNX_NAMES = frozenset((
    "image_segmentation_efficientsam_ti_2025april.onnx",
    "image_segmentation_efficientsam_ti_2025april_int8.onnx",
    "image_segmentation_efficientsam_ti_2024may.onnx",
))


def _model_value(model, name: str):
    if isinstance(model, dict):
        return model.get(name)
    return getattr(model, name, None)


def _files(path: Path) -> list[Path]:
    try:
        if path.is_file():
            return [path] if path.stat().st_size > 0 else []
        if path.is_dir():
            return sorted(
                candidate for candidate in path.rglob("*")
                if candidate.is_file() and candidate.stat().st_size > 0
            )
    except OSError:
        return []
    return []


def _compatible_weights(model_key: str, path: Path, extensions: frozenset[str]) -> list[Path]:
    candidates = [item for item in _files(path) if item.suffix.lower() in extensions]
    if model_key in (
        "efficient-sam", "clip-reid-vehicle", "transreid-vehicle", "vehicle-vit-reid",
    ):
        candidates = [
            item for item in candidates
            if item.suffix.lower() == ".onnx" and item.stat().st_size > _MIN_DIRECTORY_ONNX_BYTES
        ]
    if model_key == "efficient-sam":
        candidates = [
            item for item in candidates if item.name.lower() in _EFFICIENT_SAM_ONNX_NAMES
        ]
    return candidates


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(directory: Path) -> dict | None:
    marker = directory / "production-manifest.json"
    try:
        if not marker.is_file() or marker.stat().st_size > 16_384:
            return None
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _artifact_binding(data: dict, weight_path: Path) -> bool:
    artifact_file = data.get("artifactFile")
    expected_hash = data.get("artifactSha256")
    if (
        not isinstance(artifact_file, str)
        or not artifact_file
        or Path(artifact_file).name != artifact_file
        or not isinstance(expected_hash, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash)
        or artifact_file != weight_path.name
    ):
        return False
    try:
        return hmac.compare_digest(_sha256(weight_path), expected_hash.lower())
    except OSError:
        return False


def _production_manifest_confirms(model_key: str, task: str, weight_path: Path) -> bool:
    data = _read_manifest(weight_path.parent)
    if data is None or data.get("modelKey") != model_key or data.get("task") != task:
        return False
    if model_key == "yolo26n-p2-plate":
        classes = data.get("classes")
        normalized_classes = {
            str(item).strip().lower().replace("-", "_") for item in classes
        } if isinstance(classes, list) else set()
        if data.get("trainingComplete") is not True or not normalized_classes.intersection(
            ("plate", "license_plate")
        ):
            return False
    return _artifact_binding(data, weight_path)


def _efficient_sam_artifacts(
    configured_path: Path, candidates: list[Path], task: str,
) -> dict[str, Path] | None:
    directory = configured_path if configured_path.is_dir() else configured_path.parent
    data = _read_manifest(directory)
    if data is None or data.get("modelKey") != "efficient-sam" or data.get("task") != task:
        return None
    raw_artifacts = data.get("artifacts")
    if raw_artifacts is None:
        raw_artifacts = {"fp32": data}
    if not isinstance(raw_artifacts, dict) or not raw_artifacts:
        return None
    by_name = {candidate.name: candidate for candidate in candidates}
    resolved = {}
    for precision in ("fp32", "int8"):
        binding = raw_artifacts.get(precision)
        if binding is None:
            continue
        if not isinstance(binding, dict):
            return None
        artifact_file = binding.get("artifactFile")
        candidate = by_name.get(artifact_file) if isinstance(artifact_file, str) else None
        if candidate is None or not _artifact_binding(binding, candidate):
            return None
        resolved[precision] = candidate
    if len(resolved) != len(raw_artifacts):
        return None
    return resolved or None


def evaluate_scenario_contract(
    scenario: dict,
    model,
    configured_path: Path | None,
    *,
    runtime_probe: Callable[[str], bool],
    requested_precision: str | None = None,
) -> ScenarioContractResult:
    """Evaluate publication, exact DB metadata, assets, adapter and runtime.

    The function performs no imports, model loading, downloads, or writes.
    """
    model_key = str(scenario.get("modelKey") or "")
    contract = _CONTRACTS.get(model_key)
    all_files = _files(configured_path) if configured_path is not None else []
    weights_present = bool(all_files)
    adapter_matches = contract is not None and scenario.get("adapter") == contract["adapter"]
    library_matches = bool(contract) and (
        str(_model_value(model, "library") or "").strip().lower() == contract["library"]
    )
    runtime_available = bool(
        adapter_matches
        and library_matches
        and all(runtime_probe(module) for module in contract["runtime"])
    )

    if scenario.get("published") is not True:
        return ScenarioContractResult(weights_present, runtime_available, False, "scenario is not published")
    if scenario.get("apiEnabled") is not True:
        return ScenarioContractResult(weights_present, runtime_available, False, "scenario API is disabled")
    if not adapter_matches:
        return ScenarioContractResult(weights_present, runtime_available, False, "scenario adapter is not supported")
    if str(_model_value(model, "task") or "").strip().lower() != contract["task"]:
        return ScenarioContractResult(
            weights_present, runtime_available, False,
            "registered model task does not match scenario contract",
        )
    if not library_matches:
        return ScenarioContractResult(
            weights_present, runtime_available, False,
            "registered model library does not match scenario contract",
        )
    if str(_model_value(model, "status") or "") != "0":
        return ScenarioContractResult(weights_present, runtime_available, False, "model is disabled")
    if not weights_present:
        return ScenarioContractResult(False, runtime_available, False, "model weights are missing")

    candidates = _compatible_weights(model_key, configured_path, contract["extensions"])
    if not candidates:
        return ScenarioContractResult(
            True, runtime_available, False, "model weights are incompatible with scenario runtime",
        )
    efficient_artifacts = None
    if model_key == "efficient-sam" and configured_path is not None:
        efficient_artifacts = _efficient_sam_artifacts(
            configured_path, candidates, contract["task"],
        )
        if efficient_artifacts is None:
            return ScenarioContractResult(
                True, runtime_available, False,
                "production manifest is missing or invalid", candidates[0],
            )
        supported = tuple(
            precision for precision in ("fp32", "int8") if precision in efficient_artifacts
        )
        precision = requested_precision or ("fp32" if "fp32" in supported else supported[0])
        if precision not in efficient_artifacts:
            return ScenarioContractResult(
                True, runtime_available, False, "precision is not published",
                supported_precisions=supported,
            )
        selected = efficient_artifacts[precision]
    elif configured_path is not None and configured_path.is_dir() and len(candidates) != 1:
        return ScenarioContractResult(
            True, runtime_available, False, "model weight directory is ambiguous",
        )
    else:
        selected = candidates[0]
    if model_key == "yolo26n-p2-plate" and not _production_manifest_confirms(
        model_key, contract["task"], selected,
    ):
        return ScenarioContractResult(
            True, runtime_available, False,
            "plate-specific production manifest is missing or invalid", selected,
        )
    if not runtime_available:
        return ScenarioContractResult(
            True, False, False, "runtime library is unavailable", selected,
            tuple(efficient_artifacts) if efficient_artifacts else (),
        )
    return ScenarioContractResult(
        True, True, True, None, selected,
        tuple(efficient_artifacts) if efficient_artifacts else (),
    )
