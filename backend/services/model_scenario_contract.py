"""Side-effect-free contract checks shared by scenario readiness and inference."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ScenarioContractResult:
    weights_present: bool
    runtime_available: bool
    api_ready: bool
    reason: str | None
    weight_path: Path | None = None


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
_GENERIC_P2_BASE_NAMES = frozenset((
    "yolo26n.pt", "yolo26n.pth", "yolo26n.onnx", "yolo26n.engine",
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


def _compatible_weight(model_key: str, path: Path, extensions: frozenset[str]) -> Path | None:
    candidates = [item for item in _files(path) if item.suffix.lower() in extensions]
    if model_key in (
        "efficient-sam", "clip-reid-vehicle", "transreid-vehicle", "vehicle-vit-reid",
    ):
        candidates = [
            item for item in candidates
            if item.suffix.lower() == ".onnx" and item.stat().st_size > _MIN_DIRECTORY_ONNX_BYTES
        ]
    if model_key == "efficient-sam":
        preferred = [
            item for item in candidates
            if "image_segmentation_efficientsam" in item.name.lower()
        ]
        candidates = preferred or candidates
    return candidates[0] if candidates else None


def _training_marker_confirms_plate(weight_path: Path) -> bool:
    marker_paths = (
        weight_path.with_suffix(weight_path.suffix + ".scenario.json"),
        weight_path.with_suffix(".scenario.json"),
    )
    for marker in marker_paths:
        try:
            if not marker.is_file() or marker.stat().st_size > 16_384:
                continue
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
        if (
            data.get("modelKey") == "yolo26n-p2-plate"
            and data.get("trainingComplete") is True
        ):
            return True
    return weight_path.name.lower() not in _GENERIC_P2_BASE_NAMES


def evaluate_scenario_contract(
    scenario: dict,
    model,
    configured_path: Path | None,
    *,
    runtime_probe: Callable[[str], bool],
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

    if not scenario.get("published", False):
        return ScenarioContractResult(weights_present, runtime_available, False, "scenario is not published")
    if not scenario.get("apiEnabled", False):
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

    selected = _compatible_weight(model_key, configured_path, contract["extensions"])
    if selected is None:
        return ScenarioContractResult(
            True, runtime_available, False, "model weights are incompatible with scenario runtime",
        )
    if model_key == "yolo26n-p2-plate" and not _training_marker_confirms_plate(selected):
        return ScenarioContractResult(
            True, runtime_available, False,
            "plate-specific training completion is not verified", selected,
        )
    if not runtime_available:
        return ScenarioContractResult(
            True, False, False, "runtime library is unavailable", selected,
        )
    return ScenarioContractResult(True, True, True, None, selected)
