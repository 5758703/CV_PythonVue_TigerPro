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

这三个端点除应用凭据外，还必须携带 `X-Timestamp`、`X-Nonce`、`X-Signature`。签名密钥是创建应用时返回的**原始 API key**（不是数据库中的摘要），签名算法为 HMAC-SHA256：

```text
payload_sha256 = SHA256(sorted(payload_lines).join("\n"))
canonical = METHOD + "\n" + PATH_WITHOUT_QUERY + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + payload_sha256
signature = hex(HMAC-SHA256(raw_api_key, canonical))
```

GET/HEAD 的 payload 是空字节。multipart 的每个普通字段行是 `form:<url-encoded-name>=<url-encoded-value>`，每个文件行是 `file:<url-encoded-field-name>:<sha256-of-file-bytes>`；所有行按字典序排序。不要签 multipart boundary、文件名、Content-Type 或 query string。

将随后代码保存为 `signed_scenario.py` 后即可从 PowerShell 运行；凭据只从环境变量读取。需要先安装 `requests`，并在当前目录准备 `rotated-target.jpg`。

```powershell
$env:TIGERPRO_APP_ID = "app_demo"
$env:TIGERPRO_API_KEY = "创建应用时仅显示一次的原始密钥"
python .\signed_scenario.py
```

```python
import hashlib
import hmac
import os
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "http://127.0.0.1:5001"
APP_ID = os.environ["TIGERPRO_APP_ID"]
API_KEY = os.environ["TIGERPRO_API_KEY"]


def payload_hash(fields=(), files=()):
    lines = [f"form:{quote(name, safe='')}={quote(value, safe='')}" for name, value in fields]
    lines += [
        f"file:{quote(field, safe='')}:{hashlib.sha256(content).hexdigest()}"
        for field, (_filename, content, _content_type) in files
    ]
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()


def signed_headers(method, path, digest):
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    canonical = "\n".join((method.upper(), path, timestamp, nonce, digest))
    signature = hmac.new(API_KEY.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "X-App-Id": APP_ID,
        "X-Api-Key": API_KEY,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }


# 场景列表：query 不进入 canonical path，GET payload 为空字节。
path = "/openapi/v1/model-scenarios"
empty_digest = hashlib.sha256(b"").hexdigest()
response = requests.get(
    BASE + path,
    params={"phase": 1},
    headers=signed_headers("GET", path, empty_digest),
    timeout=30,
)
response.raise_for_status()
print(response.json())

# OBB 推理：fields/files 的顺序不影响签名，文件内容必须与发送内容一致。
path = "/openapi/v1/model-scenarios/yolo26n-obb/infer"
content = Path("rotated-target.jpg").read_bytes()
fields = [("conf", "0.45"), ("imgsz", "1024")]
files = [("file", ("rotated-target.jpg", content, "image/jpeg"))]
response = requests.post(
    BASE + path,
    data=fields,
    files=files,
    headers=signed_headers("POST", path, payload_hash(fields, files)),
    timeout=120,
)
response.raise_for_status()
print(response.json())
```

交互分割可增加 `points`、`labels`、`box`、`mode`、`precision=fp32|int8`；车辆 ReID 使用一个 `query` 和重复的 `gallery` 文件字段；检测使用 `conf` 与 `imgsz`。每次调用必须生成新 nonce。时间戳允许窗口由 `OPENAPI_SIGNATURE_MAX_AGE_SECONDS` 配置。

应用管理接口的 `ipAllowlist` 接受 IPv4/IPv6 地址或 CIDR 数组；空数组表示不限制。默认 `TRUST_PROXY=0`，白名单只检查 TCP 对端地址并忽略客户端可伪造的 `X-Forwarded-For`。只有服务部署在受控反向代理之后、且代理会覆盖该头时才可设 `TRUST_PROXY=1`；此时服务使用最左侧转发地址。

列表和详情中的就绪字段来自当前模型登记、权重与运行环境，不会加载模型：

| 字段 | 含义 |
|------|------|
| `configured` | `AiModel` 中存在与 `modelKey` 精确匹配的登记记录 |
| `enabled` | 模型登记状态为启用 |
| `weightsPresent` | 配置的相对权重路径存在且包含可用资产 |
| `runtimeAvailable` | 场景声明的运行库当前可发现 |
| `adapter` | 场景绑定的服务端适配器；客户端不可覆盖 |
| `published` / `apiEnabled` | 场景是否发布、是否允许 API 调用 |
| `ready` | 兼容字段，与 `apiReady` 保持一致 |
| `apiReady` | 精确 task/library、适配器、权重、运行库、发布和 API 开关均满足 |
| `reason` | 未就绪时的可操作原因；就绪时为 `null` |

不要只依据 `configured` 提交推理；客户端应以 `apiReady` 为最终门槛。服务端仍会重新校验签名、scope、模型状态、权重、文件和参数。成功响应包含 `requestId`，响应头同时返回 `X-Request-Id`；排障时请记录该值。错误响应也保留 `requestId`，不会暴露绝对权重路径或内部堆栈。

| HTTP | 常见场景 | 处理建议 |
|------|----------|----------|
| `401` | 签名缺失、过期或不匹配 | 用原始 API key 重算签名，并校准调用方时钟 |
| `400` | 图片/参数无效、模型未登记/未启用、权重缺失或运行配置不匹配 | 修正输入，或按 `reason` 完成模型准备 |
| `403` | 缺少 `model-scenario:read` / `model-scenario:infer` scope，或应用/IP 策略拒绝 | 调整应用授权或白名单后重试 |
| `409` | nonce 已使用 | 生成新 nonce 后重新签名，不要重放旧请求 |
| `413` | 单张图片字节数或解码像素数超过场景独立上限 | 压缩或缩小图片；ReID 还受 gallery 数量上限约束 |
| `429` | 共享 QPS 或 UTC 日配额耗尽 | 等待 `Retry-After` 秒，再用新时间戳和新 nonce 重试 |
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
