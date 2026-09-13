"""Management endpoints for the registered model scenario catalog."""

from __future__ import annotations

import logging
import re
from time import perf_counter
import uuid

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from security import permission_required
from services.model_scenario_inference import (
    ScenarioInputError,
    ScenarioPayloadTooLarge,
    run_scenario,
)
from services.model_scenario_readiness import scenario_with_readiness
from services.model_scenarios import get_scenario, list_scenarios


model_scenario_bp = Blueprint(
    "model_scenario", __name__, url_prefix="/api/ai/model-scenarios",
)
logger = logging.getLogger(__name__)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _request_id() -> str:
    supplied = (request.headers.get("X-Request-Id") or "").strip()
    return supplied if _REQUEST_ID.fullmatch(supplied) else uuid.uuid4().hex


def _response(
    *,
    code: int,
    message: str,
    data,
    http_status: int,
    operation: str,
    started: float,
    request_id: str,
    error_type: str | None = None,
):
    latency_ms = max(0, round((perf_counter() - started) * 1000))
    fields = {
        "request_id": request_id,
        "operation": operation,
        "status": http_status,
        "latency_ms": latency_ms,
    }
    if error_type:
        fields["error_type"] = error_type
        logger.warning(
            "model scenario request failed request_id=%(request_id)s "
            "operation=%(operation)s status=%(status)s latency_ms=%(latency_ms)s "
            "error_type=%(error_type)s",
            fields,
        )
    else:
        logger.info(
            "model scenario request request_id=%(request_id)s "
            "operation=%(operation)s status=%(status)s latency_ms=%(latency_ms)s",
            fields,
        )
    response = jsonify(code=code, message=message, data=data)
    response.status_code = http_status
    response.headers["X-Request-Id"] = request_id
    return response


@model_scenario_bp.get("")
@permission_required("ai:model:list")
def list_model_scenarios():
    started = perf_counter()
    request_id = _request_id()
    operation = "list"
    raw_phase = request.args.get("phase")
    try:
        phase = int(raw_phase) if raw_phase is not None else None
    except ValueError:
        return _response(
            code=400, message="phase must be an integer", data=None,
            http_status=400, operation=operation, started=started,
            request_id=request_id, error_type="validation",
        )
    try:
        data = [scenario_with_readiness(item) for item in list_scenarios(phase=phase)]
    except Exception as exc:  # noqa: BLE001 - response/log must not expose model internals
        return _response(
            code=500, message="model scenario lookup failed", data=None,
            http_status=500, operation=operation, started=started,
            request_id=request_id, error_type=type(exc).__name__,
        )
    return _response(
        code=0, message="ok", data=data, http_status=200,
        operation=operation, started=started, request_id=request_id,
    )


@model_scenario_bp.get("/<string:model_key>")
@permission_required("ai:model:query")
def get_model_scenario(model_key: str):
    started = perf_counter()
    request_id = _request_id()
    operation = "detail"
    try:
        scenario = get_scenario(model_key)
        if scenario is None:
            return _response(
                code=404, message="model scenario not found", data=None,
                http_status=404, operation=operation, started=started,
                request_id=request_id, error_type="not_found",
            )
        data = scenario_with_readiness(scenario)
    except Exception as exc:  # noqa: BLE001
        return _response(
            code=500, message="model scenario lookup failed", data=None,
            http_status=500, operation=operation, started=started,
            request_id=request_id, error_type=type(exc).__name__,
        )
    return _response(
        code=0, message="ok", data=data, http_status=200,
        operation=operation, started=started, request_id=request_id,
    )


@model_scenario_bp.post("/<string:model_key>/infer")
@permission_required("ai:model:query")
def infer_model_scenario(model_key: str):
    started = perf_counter()
    request_id = _request_id()
    operation = "infer"
    try:
        result = run_scenario(model_key, request.files, request.form)
    except (ScenarioPayloadTooLarge, RequestEntityTooLarge) as exc:
        message = (
            str(exc) if isinstance(exc, ScenarioPayloadTooLarge)
            else "request entity too large"
        )
        return _response(
            code=413, message=message, data=None, http_status=413,
            operation=operation, started=started, request_id=request_id,
            error_type="request_too_large",
        )
    except ScenarioInputError as exc:
        return _response(
            code=400, message=str(exc), data=None, http_status=400,
            operation=operation, started=started, request_id=request_id,
            error_type="validation",
        )
    except Exception as exc:  # noqa: BLE001
        return _response(
            code=500, message="inference failed", data=None, http_status=500,
            operation=operation, started=started, request_id=request_id,
            error_type=type(exc).__name__,
        )
    return _response(
        code=0, message="ok", data=result, http_status=200,
        operation=operation, started=started, request_id=request_id,
    )
