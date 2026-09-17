"""Read-only runtime prerequisites for the model scenario catalog."""

from __future__ import annotations

import importlib.machinery
import importlib.util
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
    "insightface": "insightface",
    "opencv-face": "cv2",
}
_VEHICLE_REID_LIBRARIES = frozenset(("clip-reid", "transreid", "vit-reid"))
_EFFICIENT_SAM_LIBRARIES = frozenset(("opencv-sam", "efficientsam", "efficient-sam"))
_FACE_LIBRARIES = frozenset(("insightface", "opencv-face"))
_MIN_ONNX_ASSET_BYTES = 100_000
_EFFICIENT_SAM_ONNX_NAMES = (
    "image_segmentation_efficientsam_ti_2025april.onnx",
    "image_segmentation_efficientsam_ti_2025april_int8.onnx",
    "image_segmentation_efficientsam_ti_2024may.onnx",
)


def _weight_path(file_path: str | None, *, library: str | None = None) -> Path | None:
    """Resolve a database weight path under MODEL_FOLDER or InsightFace root."""
    if not file_path:
        return None

    relative_path = Path(file_path)
    if relative_path.is_absolute():
        return None

    normalized = file_path.replace("\\", "/").strip().lower().rstrip("/")
    library_name = (library or "").strip().lower()
    if normalized == "insightface" or library_name == "insightface":
        upload_folder = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
        try:
            candidate = (upload_folder / "insightface").resolve()
            candidate.relative_to(upload_folder)
        except ValueError:
            return None
        return candidate

    model_folder = Path(current_app.config["MODEL_FOLDER"]).resolve()
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
    """Find a top-level runtime module without importing a package parent.

    PathFinder covers ordinary site-packages installs. Editable / PEP 660 installs
    (common for local ultralytics forks) only appear on the full meta path, so we
    fall back to ``importlib.util.find_spec`` for top-level names. Dotted names are
    rejected so readiness never executes a parent package to reach a submodule.
    """
    if not module_name.isidentifier():
        return None
    try:
        spec = importlib.machinery.PathFinder.find_spec(module_name)
        if spec is not None:
            return spec
        return importlib.util.find_spec(module_name)
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
            supportedPrecisions=[],
        )
        return result

    weight_path = _weight_path(model.file_path, library=model.library)
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
        supportedPrecisions=list(contract.supported_precisions),
    )
    return result


def group_with_readiness(group: dict) -> dict:
    """Join a merged scenario group with per-model readiness and aggregate flags."""
    models = [scenario_with_readiness(item) for item in group.get("models") or []]
    any_ready = any(bool(item.get("apiReady") or item.get("ready")) for item in models)
    # Prefer the first ready model as default; otherwise keep registry order.
    default_model_key = group.get("defaultModelKey")
    for item in models:
        if item.get("apiReady") or item.get("ready"):
            default_model_key = item["modelKey"]
            break
    result = dict(group)
    result.update(
        models=models,
        modelCount=len(models),
        defaultModelKey=default_model_key,
        anyReady=any_ready,
        apiReady=any_ready,
        ready=any_ready,
        configured=any(item.get("configured") for item in models),
        weightsPresent=any(item.get("weightsPresent") for item in models),
        runtimeAvailable=any(item.get("runtimeAvailable") for item in models),
        reason=None if any_ready else next(
            (item.get("reason") for item in models if item.get("reason")),
            "no model in this scenario is ready",
        ),
    )
    return result
