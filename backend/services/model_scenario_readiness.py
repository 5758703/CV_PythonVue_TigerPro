"""Read-only runtime prerequisites for the model scenario catalog."""

from __future__ import annotations

import importlib.machinery
from pathlib import Path

from flask import current_app
from models import AiModel
from services.model_scenario_contract import evaluate_scenario_contract


_LIBRARY_MODULES = {
    "opencv-sam": "cv2",
    "efficientsam": "cv2",
    "efficient-sam": "cv2",
    "mobilesam": "mobile_sam",
    "mobile-sam": "mobile_sam",
    "mobile_sam": "mobile_sam",
    "clip-reid": "onnxruntime",
    "transreid": "onnxruntime",
    "vit-reid": "onnxruntime",
}
_VEHICLE_REID_LIBRARIES = frozenset(("clip-reid", "transreid", "vit-reid"))
_EFFICIENT_SAM_LIBRARIES = frozenset(("opencv-sam", "efficientsam", "efficient-sam"))
_MIN_ONNX_ASSET_BYTES = 100_000
_EFFICIENT_SAM_ONNX_NAMES = (
    "image_segmentation_efficientsam_ti_2025april.onnx",
    "image_segmentation_efficientsam_ti_2025april_int8.onnx",
    "image_segmentation_efficientsam_ti_2024may.onnx",
)


def _weight_path(file_path: str | None) -> Path | None:
    """Resolve a database weight path under the configured model folder."""
    if not file_path:
        return None

    model_folder = Path(current_app.config["MODEL_FOLDER"]).resolve()
    relative_path = Path(file_path)
    if relative_path.is_absolute():
        return None
    # Existing uploads store paths relative to UPLOAD_FOLDER ("models/..."),
    # while readiness intentionally anchors relative assets at MODEL_FOLDER.
    if relative_path.parts and relative_path.parts[0].lower() == "models":
        relative_path = Path(*relative_path.parts[1:])
    try:
        candidate = (model_folder / relative_path).resolve()
        candidate.relative_to(model_folder)
    except ValueError:
        return None
    return candidate


def _library_name(library: str | None) -> str:
    return (library or "").strip().lower()


def _find_module_spec(module_name: str):
    """Find a top-level runtime module without importing a package parent."""
    if not module_name.isidentifier():
        return None
    try:
        return importlib.machinery.PathFinder.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None


def _runtime_available(library: str | None) -> bool:
    library_name = _library_name(library)
    if not library_name:
        return False
    module_name = _LIBRARY_MODULES.get(library_name, library_name)
    return _find_module_spec(module_name) is not None


def _large_onnx_in_directory(
    weight_path: Path, *, names: tuple[str, ...] = (), allow_any_name: bool = False,
) -> bool:
    try:
        candidates = [weight_path / name for name in names]
        if allow_any_name:
            candidates.extend(path for path in weight_path.iterdir() if path.suffix.lower() == ".onnx")
        return any(path.is_file() and path.stat().st_size > _MIN_ONNX_ASSET_BYTES for path in candidates)
    except OSError:
        return False


def _weights_present(weight_path: Path | None, library: str | None) -> bool:
    if weight_path is None:
        return False
    try:
        if weight_path.is_file():
            return weight_path.stat().st_size > 0
        if not weight_path.is_dir():
            return False
    except OSError:
        return False

    library_name = _library_name(library)
    if library_name in _VEHICLE_REID_LIBRARIES:
        return _large_onnx_in_directory(weight_path, allow_any_name=True)
    if library_name in _EFFICIENT_SAM_LIBRARIES:
        return _large_onnx_in_directory(weight_path, names=_EFFICIENT_SAM_ONNX_NAMES)
    try:
        return any(path.is_file() and path.stat().st_size > 0 for path in weight_path.rglob("*"))
    except OSError:
        return False


def scenario_with_readiness(scenario: dict) -> dict:
    """Join one scenario with its registered model's non-loading readiness state."""
    result = dict(scenario)
    model = AiModel.query.filter_by(model_key=scenario["modelKey"]).first()
    if model is None:
        result.update(
            model=None,
            configured=False,
            enabled=False,
            weightsPresent=False,
            runtimeAvailable=False,
            ready=False,
            apiReady=False,
            reason="model is not registered",
        )
        return result

    weight_path = _weight_path(model.file_path)
    enabled = model.status == "0"
    contract = evaluate_scenario_contract(
        scenario,
        model,
        weight_path,
        runtime_probe=lambda module: _find_module_spec(module) is not None,
    )

    result.update(
        model=model.to_dict(),
        configured=True,
        enabled=enabled,
        weightsPresent=contract.weights_present,
        runtimeAvailable=contract.runtime_available,
        ready=contract.api_ready,
        apiReady=contract.api_ready,
        reason=contract.reason,
    )
    return result
