"""对外 Open API v1：/openapi/v1/*

鉴权：X-App-Id + X-Api-Key（或 Authorization: Bearer <key>）
- 精简能力：vision/detect、ocr、face、water、jobs（兼容）
- 全量桥接：/openapi/v1/x/<原 /api/ 路径> ，按域 / 细粒度 Scope 授权
- 目录：GET /openapi/v1/catalog 、/capabilities
"""
from flask import Blueprint, Response, request

from openapi_spec import DOCS_HTML, OPENAPI_SPEC
from security_open import (
    current_open_app,
    open_error,
    open_ok,
    require_open_scope,
)
from services import job_store
from services import metrics_registry as metrics
from services import openapi_handlers as handlers
from services.object_store import store_upload
from services.openapi_bridge import register_bridge_routes
from services.openapi_catalog import (
    app_allows_endpoint,
    catalog_stats,
    list_domains,
)

openapi_v1_bp = Blueprint("openapi_v1", __name__, url_prefix="/openapi/v1")
register_bridge_routes(openapi_v1_bp)


@openapi_v1_bp.get("/health")
def health():
    """公开存活探测（无需 AppKey）。"""
    snap = metrics.snapshot()
    return open_ok({
        "status": "ok",
        "version": "v1",
        "uptimeSec": snap.get("uptimeSec"),
        "objectStore": __import__("flask").current_app.config.get("OBJECT_STORE_BACKEND", "local"),
        "catalog": catalog_stats(),
    })


@openapi_v1_bp.get("/openapi.json")
def openapi_json():
    spec = dict(OPENAPI_SPEC)
    paths = dict(spec.get("paths") or {})
    paths["/x/{subpath}"] = {
        "parameters": [{
            "name": "subpath",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
            "description": "对应控制台 /api/ 之后的路径，例如 ai/face/recognize",
        }],
        "get": {"summary": "桥接 GET /api/{subpath}", "responses": {"200": {"description": "透传"}}},
        "post": {"summary": "桥接 POST /api/{subpath}", "responses": {"200": {"description": "透传"}}},
        "put": {"summary": "桥接 PUT", "responses": {"200": {"description": "透传"}}},
        "patch": {"summary": "桥接 PATCH", "responses": {"200": {"description": "透传"}}},
        "delete": {"summary": "桥接 DELETE", "responses": {"200": {"description": "透传"}}},
    }
    paths["/catalog"] = {
        "get": {
            "summary": "分域 API 目录与授权状态",
            "responses": {"200": {"description": "OK"}},
        }
    }
    spec["paths"] = paths
    return Response(
        __import__("json").dumps(spec, ensure_ascii=False),
        mimetype="application/json",
    )


@openapi_v1_bp.get("/docs")
def docs():
    return Response(DOCS_HTML, mimetype="text/html")


@openapi_v1_bp.get("/metrics")
def prometheus_metrics():
    return Response(metrics.render_prometheus(), mimetype="text/plain; version=0.0.4")


@openapi_v1_bp.get("/capabilities")
@require_open_scope("")
def capabilities():
    app = current_open_app()
    owned = app.scope_list() if app else []
    domains = []
    for d in list_domains():
        granted_eps = 0
        bridgeable = 0
        for e in d["endpoints"]:
            if not e.get("bridgeable"):
                continue
            bridgeable += 1
            if app_allows_endpoint(owned, e):
                granted_eps += 1
        domains.append({
            "id": d["id"],
            "label": d["label"],
            "risk": d["risk"],
            "domainScope": d["domainScope"],
            "domainGranted": (
                f"domain:{d['id']}" in owned or "*" in owned or "*:*:*" in owned
            ),
            "bridgeableCount": bridgeable,
            "grantedCount": granted_eps,
        })
    return open_ok({
        "appId": app.app_id if app else None,
        "scopes": owned,
        "stats": catalog_stats(),
        "domains": domains,
        "bridgeBase": "/openapi/v1/x",
        "docs": "/openapi/v1/docs",
        "catalog": "/openapi/v1/catalog",
    })


def _flag_async() -> bool:
    return (request.form.get("async") or request.args.get("async") or "0") in (
        "1", "true", "True", "yes",
    )


@openapi_v1_bp.post("/vision/detect")
@require_open_scope("vision:detect")
def vision_detect():
    """图片目标检测。form: file|image, modelId, conf?, draw?, async?"""
    file = request.files.get("file") or request.files.get("image")
    if file is None or not file.filename:
        return open_error(400, 400, "未接收到图片（file）", "validation")
    try:
        model_id = int(request.form.get("modelId") or 0)
    except (TypeError, ValueError):
        return open_error(400, 400, "modelId 无效", "validation")
    if model_id <= 0:
        return open_error(400, 400, "modelId 必填", "validation")
    try:
        conf = float(request.form.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25
    draw = (request.form.get("draw") or "1") not in ("0", "false", "False")
    image_bytes = file.read()
    app = current_open_app()

    if _flag_async():
        uri = store_upload(image_bytes, prefix="vision-detect", ext=".jpg",
                           content_type="image/jpeg")
        job_id = job_store.create_job(
            "vision:detect",
            {"modelId": model_id, "conf": conf, "draw": draw},
            app_pk=app.id if app else None,
            app_id=app.app_id if app else None,
            input_uri=uri,
        )
        metrics.incr("tigerpro_open_jobs_created", capability="vision:detect")
        return open_ok({"jobId": job_id, "status": "queued"}, message="已排队")

    try:
        data = handlers.run_vision_detect(
            model_id=model_id, image_bytes=image_bytes, conf=conf, draw=draw
        )
    except ValueError as e:
        return open_error(400, 400, str(e), "validation")
    except Exception as e:  # noqa: BLE001
        return open_error(500, 500, f"检测失败：{e}", "inference")
    return open_ok(data, message="检测完成")


@openapi_v1_bp.post("/vision/ocr")
@require_open_scope("vision:ocr")
def vision_ocr():
    file = request.files.get("file") or request.files.get("image")
    if file is None or not file.filename:
        return open_error(400, 400, "未接收到图片（file）", "validation")
    try:
        det_id = int(request.form.get("detId") or 0)
        rec_id = int(request.form.get("recId") or 0)
    except (TypeError, ValueError):
        return open_error(400, 400, "detId / recId 无效", "validation")
    if det_id <= 0 or rec_id <= 0:
        return open_error(400, 400, "detId 与 recId 必填", "validation")
    try:
        data = handlers.run_vision_ocr(
            det_id=det_id, rec_id=rec_id, image_bytes=file.read()
        )
    except ValueError as e:
        return open_error(400, 400, str(e), "validation")
    except Exception as e:  # noqa: BLE001
        return open_error(500, 500, f"OCR 失败：{e}", "inference")
    return open_ok(data, message="识别完成")


@openapi_v1_bp.post("/face/recognize")
@require_open_scope("face:recognize")
def face_recognize():
    file = request.files.get("file") or request.files.get("image")
    if file is None or not file.filename:
        return open_error(400, 400, "未接收到图片（file）", "validation")
    try:
        model_id = int(request.form.get("modelId") or 0)
    except (TypeError, ValueError):
        return open_error(400, 400, "modelId 无效", "validation")
    if model_id <= 0:
        return open_error(400, 400, "modelId 必填", "validation")
    try:
        threshold = float(request.form.get("threshold", 0.4))
    except (TypeError, ValueError):
        threshold = 0.4
    try:
        det_thresh = float(request.form.get("detThresh", 0.5))
    except (TypeError, ValueError):
        det_thresh = 0.5
    draw = (request.form.get("draw") or "0") in ("1", "true", "True")
    try:
        data = handlers.run_face_recognize(
            model_id=model_id,
            image_bytes=file.read(),
            threshold=threshold,
            det_thresh=det_thresh,
            draw=draw,
        )
    except ValueError as e:
        return open_error(400, 400, str(e), "validation")
    except Exception as e:  # noqa: BLE001
        return open_error(500, 500, f"识别失败：{e}", "inference")
    return open_ok(data, message="识别完成")


@openapi_v1_bp.post("/water/read")
@require_open_scope("water:read")
def water_read():
    file = request.files.get("file") or request.files.get("image")
    if file is None or not file.filename:
        return open_error(400, 400, "未接收到图片（file）", "validation")
    try:
        det_id = int(request.form.get("detId") or 0)
        rec_id = int(request.form.get("recId") or 0)
    except (TypeError, ValueError):
        return open_error(400, 400, "detId / recId 无效", "validation")
    if det_id <= 0 or rec_id <= 0:
        return open_error(400, 400, "detId 与 recId 必填", "validation")
    water_y_ratio = None
    raw_wy = (request.form.get("waterYRatio") or "").strip()
    if raw_wy:
        try:
            v = float(raw_wy)
            if 0.0 < v < 1.0:
                water_y_ratio = v
        except ValueError:
            pass
    try:
        data = handlers.run_water_read(
            det_id=det_id,
            rec_id=rec_id,
            image_bytes=file.read(),
            water_y_ratio=water_y_ratio,
        )
    except ValueError as e:
        return open_error(400, 400, str(e), "validation")
    except Exception as e:  # noqa: BLE001
        return open_error(500, 500, f"水位检测失败：{e}", "inference")
    return open_ok(data, message="检测完成")


@openapi_v1_bp.get("/jobs/<job_id>")
@require_open_scope("jobs:read")
def get_job(job_id):
    job = job_store.get_job(job_id)
    if job is None:
        return open_error(404, 404, "任务不存在", "not_found")
    app = current_open_app()
    if app and job.get("appId") and job.get("appId") != app.app_id:
        return open_error(403, 403, "无权查看该任务", "forbidden")
    return open_ok(job_store.public_job(job))
