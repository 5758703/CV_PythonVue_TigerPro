# TigerPro Open API 调用示例

Base: `http://127.0.0.1:5001`（Gateway 模式默认 `5002`）

文档站: http://127.0.0.1:5001/openapi/v1/docs

## 鉴权

```http
X-App-Id: app_demo
X-Api-Key: tp_live_demo_change_me_in_production_01
```

或 `Authorization: Bearer <api_key>`。

## 全量桥接（推荐）

控制台可桥接的 `/api/...` 对应：

```text
/openapi/v1/x/<去掉 /api/ 后的路径>
```

授权方式：

- 域级：`domain:face`、`domain:ai_model`、`domain:training` …
- 细粒度：与 RBAC 相同，如 `ai:face:list`
- 超管：`*:*:*`
- `/api/system/open-app` **不可**桥接

```bash
# 等价于 POST /api/ai/face/recognize
curl -s -X POST http://127.0.0.1:5001/openapi/v1/x/ai/face/recognize \
  -H "X-App-Id: app_demo" \
  -H "X-Api-Key: $API_KEY" \
  -F "file=@./face.jpg" \
  -F "modelId=1"

# 用户列表
curl -s "http://127.0.0.1:5001/openapi/v1/x/system/user?pageNum=1&pageSize=10" \
  -H "X-App-Id: app_demo" \
  -H "X-Api-Key: $API_KEY"

# 分域目录
curl -s http://127.0.0.1:5001/openapi/v1/catalog \
  -H "X-App-Id: app_demo" \
  -H "X-Api-Key: $API_KEY"
```

## 精简别名（仍可用）

```bash
curl -s -X POST http://127.0.0.1:5001/openapi/v1/vision/detect \
  -H "X-App-Id: app_demo" \
  -H "X-Api-Key: $API_KEY" \
  -F "file=@./sample.jpg" \
  -F "modelId=1"
```

异步：`async=1` → `jobId`，需运行 `python scripts/open_job_worker.py`。

## Webhook / Gateway

控制台配置 Webhook；独立网关：`python gateway_app.py`（:5002）。  
指标：`GET /openapi/v1/metrics`
