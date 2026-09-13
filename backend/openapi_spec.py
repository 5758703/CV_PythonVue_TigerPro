"""OpenAPI 3.0 规范文档（静态生成，供 /openapi/v1/openapi.json 与 /docs）。"""

OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "TigerPro Open API",
        "version": "1.0.0",
        "description": (
            "对外能力网关。鉴权：`X-App-Id` + `X-Api-Key`（或 `Authorization: Bearer <key>`）。"
            "成功响应统一 `{ code:0, message, data, requestId }`。"
        ),
    },
    "servers": [{"url": "/openapi/v1", "description": "相对当前主机"}],
    "components": {
        "securitySchemes": {
            "ApiKeyHeader": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Api-Key",
            },
            "AppIdHeader": {
                "type": "apiKey",
                "in": "header",
                "name": "X-App-Id",
            },
        },
        "schemas": {
            "Envelope": {
                "type": "object",
                "properties": {
                    "code": {"type": "integer", "example": 0},
                    "message": {"type": "string"},
                    "requestId": {"type": "string"},
                    "data": {"type": "object"},
                },
            }
        },
    },
    "security": [{"ApiKeyHeader": [], "AppIdHeader": []}],
    "paths": {
        "/health": {
            "get": {
                "summary": "存活探测",
                "security": [],
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/capabilities": {
            "get": {
                "summary": "当前应用已授权能力",
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/model-scenarios": {
            "get": {
                "summary": "List model scenarios",
                "description": "Returns public scenario metadata and runtime readiness.",
                "x-required-scope": "model-scenario:read",
                "parameters": [{
                    "name": "phase",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "integer"},
                }],
                "responses": {
                    "200": {
                        "description": "Scenario catalog",
                        "content": {
                            "application/json": {
                                "example": {
                                    "code": 0,
                                    "message": "ok",
                                    "requestId": "req-123",
                                    "data": [{
                                        "modelKey": "yolo26n-obb",
                                        "workbenchType": "obb_detection",
                                        "configured": True,
                                        "ready": True,
                                        "reason": None,
                                    }],
                                }
                            }
                        },
                    },
                    "400": {"description": "Invalid phase"},
                    "401": {"description": "Invalid credentials"},
                    "403": {"description": "Missing model-scenario:read scope"},
                },
            }
        },
        "/model-scenarios/{modelKey}": {
            "get": {
                "summary": "Get model scenario",
                "description": "Returns public capability metadata, input rules, and readiness.",
                "x-required-scope": "model-scenario:read",
                "parameters": [{
                    "name": "modelKey",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }],
                "responses": {
                    "200": {"description": "Scenario metadata and readiness"},
                    "401": {"description": "Invalid credentials"},
                    "403": {"description": "Missing model-scenario:read scope"},
                    "404": {"description": "Unknown model scenario"},
                },
            }
        },
        "/model-scenarios/{modelKey}/infer": {
            "post": {
                "summary": "Run model scenario inference",
                "description": (
                    "Dispatches by the registered model key. The server never accepts a model "
                    "path or runtime library from the caller."
                ),
                "x-required-scope": "model-scenario:infer",
                "parameters": [{
                    "name": "modelKey",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }],
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "oneOf": [
                                    {"required": ["file"]},
                                    {"required": ["query", "gallery"]},
                                ],
                                "properties": {
                                    "file": {
                                        "type": "string",
                                        "format": "binary",
                                        "description": "Segmentation or detection image",
                                    },
                                    "query": {
                                        "type": "string",
                                        "format": "binary",
                                        "description": "Vehicle ReID query image",
                                    },
                                    "gallery": {
                                        "type": "array",
                                        "items": {"type": "string", "format": "binary"},
                                        "description": "One or more vehicle ReID gallery images",
                                    },
                                    "points": {"type": "string", "description": "JSON point array"},
                                    "labels": {"type": "string", "description": "JSON point-label array"},
                                    "box": {"type": "string", "description": "JSON [x1,y1,x2,y2]"},
                                    "mode": {"type": "string", "enum": ["prompt", "auto"]},
                                    "precision": {"type": "string"},
                                    "conf": {"type": "number", "minimum": 0, "maximum": 1},
                                    "imgsz": {
                                        "type": "integer", "minimum": 32, "maximum": 4096,
                                    },
                                    "threshold": {"type": "number", "minimum": 0, "maximum": 1},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Normalized inference result",
                        "content": {
                            "application/json": {
                                "example": {
                                    "code": 0,
                                    "message": "ok",
                                    "requestId": "req-123",
                                    "data": {
                                        "modelKey": "yolo26n-obb",
                                        "workbench": "obb_detection",
                                        "elapsedMs": 7,
                                        "result": {"detections": [], "count": 0},
                                    },
                                }
                            }
                        },
                    },
                    "400": {"description": "Unavailable scenario or invalid input"},
                    "401": {"description": "Invalid credentials"},
                    "403": {"description": "Missing model-scenario:infer scope"},
                    "413": {"description": "Configured upload limit exceeded"},
                    "500": {"description": "Sanitized inference failure"},
                },
            }
        },
        "/vision/detect": {
            "post": {
                "summary": "图片目标检测",
                "description": "multipart: file, modelId, conf?, draw?, async?=0|1",
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["file", "modelId"],
                                "properties": {
                                    "file": {"type": "string", "format": "binary"},
                                    "modelId": {"type": "integer"},
                                    "conf": {"type": "number", "default": 0.25},
                                    "draw": {"type": "string", "default": "1"},
                                    "async": {
                                        "type": "string",
                                        "description": "1=异步，返回 jobId",
                                        "default": "0",
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "检测结果或 jobId"}},
            }
        },
        "/vision/ocr": {
            "post": {
                "summary": "OCR",
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/face/recognize": {
            "post": {
                "summary": "1:N 人脸识别",
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/water/read": {
            "post": {
                "summary": "水位尺读数",
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/jobs/{jobId}": {
            "get": {
                "summary": "查询异步任务",
                "parameters": [
                    {
                        "name": "jobId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "任务状态"}},
            }
        },
        "/metrics": {
            "get": {
                "summary": "Prometheus 指标",
                "security": [],
                "responses": {"200": {"description": "text/plain"}},
            }
        },
    },
}

DOCS_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>TigerPro Open API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui.css"/>
  <style>body{margin:0} .topbar{display:none}</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: '/openapi/v1/openapi.json',
      dom_id: '#swagger-ui',
      presets: [SwaggerUIBundle.presets.apis],
      layout: 'BaseLayout'
    });
  </script>
</body>
</html>
"""
