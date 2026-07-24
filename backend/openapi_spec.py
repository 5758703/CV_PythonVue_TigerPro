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
