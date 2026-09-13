"""Read-only runtime prerequisites for the model scenario catalog."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from config import Config
from models import AiModel


def _weight_path(file_path: str | None) -> Path | None:
    """Resolve a database weight path under the configured model folder."""
    if not file_path:
        return None

    model_folder = Path(Config.MODEL_FOLDER).resolve()
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


def _runtime_available(library: str | None) -> bool:
    if not library:
        return False
    try:
        return importlib.util.find_spec(library) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
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
            reason="model is not registered",
        )
        return result

    weight_path = _weight_path(model.file_path)
    enabled = model.status == "0"
    weights_present = weight_path is not None and weight_path.exists()
    runtime_available = _runtime_available(model.library)
    ready = enabled and weights_present and runtime_available
    if not enabled:
        reason = "model is disabled"
    elif not weights_present:
        reason = "model weights are missing"
    elif not runtime_available:
        reason = "runtime library is unavailable"
    else:
        reason = None

    result.update(
        model=model.to_dict(),
        configured=True,
        enabled=enabled,
        weightsPresent=weights_present,
        runtimeAvailable=runtime_available,
        ready=ready,
        reason=reason,
    )
    return result
