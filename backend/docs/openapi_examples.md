# TigerPro Open API 调用示例

Base: `http://127.0.0.1:5001`（Gateway 模式默认 `5002`）

文档站: http://127.0.0.1:5001/openapi/v1/docs

## 鉴权

```http
X-App-Id: <YOUR_APP_ID>
X-Api-Key: <YOUR_API_KEY>
```

或 `Authorization: Bearer <api_key>`。

## 生产模型场景

模型场景接口不走全量桥接别名，直接使用以下三个端点：

- `GET /openapi/v1/model-scenarios?phase=1`：第一阶段场景列表，需要 `model-scenario:read` scope。
- `GET /openapi/v1/model-scenarios/<model_key>`：单场景详情，需要 `model-scenario:read` scope。
- `POST /openapi/v1/model-scenarios/<model_key>/infer`：同步推理，需要 `model-scenario:infer` scope。

下列示例全部使用占位凭据；请通过环境变量注入真实值，不要把密钥写入脚本或版本库。

```bash
# 第一阶段列表
curl -s "http://127.0.0.1:5001/openapi/v1/model-scenarios?phase=1" \
  -H "X-App-Id: $TIGERPRO_APP_ID" \
  -H "X-Api-Key: $TIGERPRO_API_KEY"

# 单场景详情
curl -s "http://127.0.0.1:5001/openapi/v1/model-scenarios/yolo26n-obb" \
  -H "X-App-Id: $TIGERPRO_APP_ID" \
  -H "X-Api-Key: $TIGERPRO_API_KEY"

# 交互分割：points 与 labels 为等长 JSON 数组；也可提交 box=[x1,y1,x2,y2]
curl -s -X POST "http://127.0.0.1:5001/openapi/v1/model-scenarios/efficient-sam/infer" \
  -H "X-App-Id: $TIGERPRO_APP_ID" \
  -H "X-Api-Key: $TIGERPRO_API_KEY" \
  -F "file=@./surface-defect.jpg" \
  -F 'points=[[320,240],[360,260]]' \
  -F 'labels=[1,0]' \
  -F "precision=fp32"

# 车辆 ReID：gallery 可重复提交
curl -s -X POST "http://127.0.0.1:5001/openapi/v1/model-scenarios/clip-reid-vehicle/infer" \
  -H "X-App-Id: $TIGERPRO_APP_ID" \
  -H "X-Api-Key: $TIGERPRO_API_KEY" \
  -F "query=@./query-vehicle.jpg" \
  -F "gallery=@./camera-b-01.jpg" \
  -F "gallery=@./camera-c-02.jpg" \
  -F "threshold=0.70"

# 车牌检测
curl -s -X POST "http://127.0.0.1:5001/openapi/v1/model-scenarios/keremberke-yolov5m-license-plate/infer" \
  -H "X-App-Id: $TIGERPRO_APP_ID" \
  -H "X-Api-Key: $TIGERPRO_API_KEY" \
  -F "file=@./entrance.jpg" \
  -F "conf=0.50" \
  -F "imgsz=640"

# 旋转框 OBB 检测
curl -s -X POST "http://127.0.0.1:5001/openapi/v1/model-scenarios/yolo26n-obb/infer" \
  -H "X-App-Id: $TIGERPRO_APP_ID" \
  -H "X-Api-Key: $TIGERPRO_API_KEY" \
  -F "file=@./rotated-target.jpg" \
  -F "conf=0.45" \
  -F "imgsz=1024"
```

列表和详情中的就绪字段来自当前模型登记、权重与运行环境，不会加载模型：

| 字段 | 含义 |
|------|------|
| `configured` | `AiModel` 中存在与 `modelKey` 精确匹配的登记记录 |
| `enabled` | 模型登记状态为启用 |
| `weightsPresent` | 配置的相对权重路径存在且包含可用资产 |
| `runtimeAvailable` | 场景声明的运行库当前可发现 |
| `ready` | 启用、权重和运行库均满足，可提交推理 |
| `reason` | 未就绪时的可操作原因；就绪时为 `null` |

不要只依据 `configured` 提交推理；客户端应以 `ready` 为最终门槛。服务端仍会重新校验 scope、模型状态、权重、文件和参数。成功响应包含 `requestId`，响应头同时返回 `X-Request-Id`；排障时请记录该值。错误响应也保留 `requestId`，不会暴露绝对权重路径或内部堆栈。

| HTTP | 常见场景 | 处理建议 |
|------|----------|----------|
| `400` | 图片/参数无效、模型未登记/未启用、权重缺失或运行配置不匹配 | 修正输入，或按 `reason` 完成模型准备 |
| `403` | 缺少 `model-scenario:read` / `model-scenario:infer` scope，或应用/IP 策略拒绝 | 调整应用授权或白名单后重试 |
| `413` | multipart 请求超过服务端 `MAX_CONTENT_LENGTH` | 压缩或缩小图片；ReID 多图也受整个请求上限约束 |
| `500` | 运行库加载或推理异常 | 使用 `requestId` 查询服务端日志，不要原样向终端用户展示内部错误 |

车牌工作台当前是 detector-only：结果只保证车牌框、置信度、裁剪/叠加等定位信息。除非后续明确接入 OCR，不得把检测类别或框内容解释为车牌字符。车辆 ReID 同样不是检测器，完整跨镜流程仍需检测、跟踪、质量筛选与拓扑约束。

## 全量桥接（推荐）

控制台可桥接的 `/api/...` 对应：

```text
/openapi/v1/x/<去掉 /api/ 后的路径>
```

授权方式：

- 域级：`domain:face`、`domain:ai_model`、`domain:sys_user` …（与 Blueprint 一一对应）
- 细粒度：与 RBAC 相同，如 `ai:face:list`
- 超管：`*:*:*`
- `/api/system/open-app` **不可**桥接

控制台「开放平台」按五大分组展示全部 Blueprint 域，可「新建/刷新本域应用」或「一键对齐全部域应用」。

```bash
# 分域目录（groups + domains + endpoints）
curl -s http://127.0.0.1:5001/openapi/v1/capabilities \
  -H "X-App-Id: app_demo" \
  -H "X-Api-Key: $API_KEY"

# 管理端：一键为全部可桥接域创建/刷新应用
curl -X POST http://127.0.0.1:5001/api/system/open-app/ensure-domains \
  -H "Authorization: Bearer <admin_jwt>"

# 管理端：仅为某人脸域创建应用
curl -X POST http://127.0.0.1:5001/api/system/open-app/from-domain \
  -H "Authorization: Bearer <admin_jwt>" \
  -H "Content-Type: application/json" \
  -d '{"domainId":"face","qpsLimit":20,"dailyLimit":5000}'

# 等价于 POST /api/ai/face/recognize
curl -s -X POST http://127.0.0.1:5001/openapi/v1/x/ai/face/recognize \
  -H "X-App-Id: app_face" \
  -H "X-Api-Key: $API_KEY" \
  -F "file=@./face.jpg" \
  -F "modelId=1"

# 用户列表（需 sys_user 域应用或含 domain:sys_user）
curl -s "http://127.0.0.1:5001/openapi/v1/x/system/user?pageNum=1&pageSize=10" \
  -H "X-App-Id: app_sys_user" \
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
