"""Management endpoints for the registered model scenario catalog."""

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from security import permission_required
from services.model_scenario_inference import ScenarioInputError, run_scenario
from services.model_scenario_readiness import scenario_with_readiness
from services.model_scenarios import get_scenario, list_scenarios


model_scenario_bp = Blueprint(
    "model_scenario", __name__, url_prefix="/api/ai/model-scenarios",
)


def _ok(data):
    return jsonify(code=0, message="ok", data=data)


@model_scenario_bp.get("")
@permission_required("ai:model:list")
def list_model_scenarios():
    raw_phase = request.args.get("phase")
    try:
        phase = int(raw_phase) if raw_phase is not None else None
    except ValueError:
        return jsonify(code=400, message="phase must be an integer", data=None), 400
    return _ok([scenario_with_readiness(scenario) for scenario in list_scenarios(phase=phase)])


@model_scenario_bp.get("/<string:model_key>")
@permission_required("ai:model:query")
def get_model_scenario(model_key: str):
    scenario = get_scenario(model_key)
    if scenario is None:
        return jsonify(code=404, message="model scenario not found", data=None), 404
    return _ok(scenario_with_readiness(scenario))


@model_scenario_bp.post("/<string:model_key>/infer")
@permission_required("ai:model:query")
def infer_model_scenario(model_key: str):
    try:
        result = run_scenario(model_key, request.files, request.form)
    except RequestEntityTooLarge:
        return jsonify(code=413, message="request entity too large", data=None), 413
    except ScenarioInputError as exc:
        return jsonify(code=400, message=str(exc), data=None), 400
    except Exception:  # noqa: BLE001 - never expose model paths or runtime details
        return jsonify(code=500, message="inference failed", data=None), 500
    return _ok(result)
