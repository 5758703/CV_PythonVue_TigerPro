# TigerPro Open API 调用示例

模型场景端点使用 HMAC-SHA256 请求签名：

- `GET /openapi/v1/model-scenarios?phase=1`（`model-scenario:read`）
- `GET /openapi/v1/model-scenarios/<modelKey>`（`model-scenario:read`）
- `POST /openapi/v1/model-scenarios/<modelKey>/infer`（`model-scenario:infer`）

## Canonical 规范

签名密钥是创建应用时仅显示一次的原始 API key。每次请求必须使用新的 nonce。

```text
canonical = METHOD + "\n"
          + NORMALIZED_PATH + "\n"
          + NORMALIZED_QUERY + "\n"
          + TIMESTAMP + "\n"
          + NONCE + "\n"
          + NORMALIZED_CONTENT_TYPE + "\n"
          + PAYLOAD_SHA256
signature = lowercase_hex(HMAC-SHA256(raw_api_key, canonical))
```

- path 使用 RFC 3986 编码，保留 `/ - . _ ~`。
- query 保留重复键；逐个 RFC 3986 编码后，按编码后的 `(key, value)` 排序并以 `&` 连接。
- GET/HEAD 的 payload 是空字节 SHA256；允许缺失或为 `0` 的 Content-Length。
- POST 推理必须提供正整数 Content-Length；缺失返回 411，无效或不大于零返回 400，超限返回 413。
- multipart Content-Type 只签小写媒体类型 `multipart/form-data`，不签 boundary。
- multipart 严格按传输中的原始 part 顺序签名，保留从 0 开始的 index，不排序。
- 普通 part：`index:form:urlencoded-field=urlencoded-value`。
- 文件 part：`index:file:urlencoded-field:urlencoded-safe-filename:lowercase-part-content-type:sha256(file-bytes)`。
- part 的字段名、值、filename、part Content-Type、文件内容、顺序或 index 任何变化都会导致验签失败。

## 可执行 Python 示例

以下 helper 与服务端 canonical 规则一致。`requests` 会先发送普通字段，再发送文件字段，因此 helper 也按实际发送顺序构造清单。

```python
import hashlib
import hmac
import os
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlsplit

import requests

BASE = "http://127.0.0.1:5001"
APP_ID = os.environ["TIGERPRO_APP_ID"]
API_KEY = os.environ["TIGERPRO_API_KEY"]


def enc(value):
    return quote(str(value), safe="-._~")


def normalized_query(path):
    pairs = [(enc(k), enc(v)) for k, v in parse_qsl(urlsplit(path).query, keep_blank_values=True)]
    return "&".join(f"{key}={value}" for key, value in sorted(pairs))


def multipart_hash(fields, files):
    lines = [
        f"{index}:form:{enc(name)}={enc(value)}"
        for index, (name, value) in enumerate(fields)
    ]
    offset = len(lines)
    lines.extend(
        f"{offset + index}:file:{enc(field)}:{enc(filename)}:{part_type.lower()}:"
        f"{hashlib.sha256(content).hexdigest()}"
        for index, (field, (filename, content, part_type)) in enumerate(files)
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def signed_headers(method, path, payload_sha256, content_type=""):
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    parsed = urlsplit(path)
    canonical = "\n".join((
        method.upper(), quote(parsed.path, safe="/-._~"), normalized_query(path),
        timestamp, nonce, content_type.lower(), payload_sha256,
    ))
    signature = hmac.new(
        API_KEY.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256,
    ).hexdigest()
    return {
        "X-App-Id": APP_ID,
        "X-Api-Key": API_KEY,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }


list_path = "/openapi/v1/model-scenarios?phase=1&tag=b&tag=a"
empty_hash = hashlib.sha256(b"").hexdigest()
print(requests.get(
    BASE + list_path,
    headers=signed_headers("GET", list_path, empty_hash),
    timeout=30,
).json())

infer_path = "/openapi/v1/model-scenarios/yolo26n-obb/infer"
content = Path("rotated-target.jpg").read_bytes()
fields = [("conf", "0.45"), ("imgsz", "1024")]
files = [("file", ("rotated-target.jpg", content, "image/jpeg"))]
print(requests.post(
    BASE + infer_path,
    data=fields,
    files=files,
    headers=signed_headers(
        "POST", infer_path, multipart_hash(fields, files), "multipart/form-data",
    ),
    timeout=120,
).json())
```

允许的普通字段是 `points`、`labels`、`pointLabels`、`box`、`mode`、`precision`、`threshold`、`conf`、`imgsz`；文件字段是 `file`、`query`、`gallery`。服务端同时限制 part 数、文件数、单文件大小、总请求大小和解码像素数。

成功和错误响应都包含 `requestId`，响应头也返回 `X-Request-Id`。常见错误：401 签名错误，409 nonce 重放，411 POST 缺少 Content-Length，413 请求超限，429 配额耗尽。

## 全量桥接（推荐）

控制台可桥接的 `/api/...` 对应 `/openapi/v1/x/<去掉 /api/ 后的路径>`。授权支持与 RBAC 相同的细粒度权限（例如 `ai:face:list`）、域级权限（例如 `domain:face`）以及超级权限 `*:*:*`；`/api/system/open-app` 不可桥接。

```bash
# 查看可用域和端点
curl -s http://127.0.0.1:5001/openapi/v1/capabilities \
  -H "X-App-Id: app_demo" -H "X-Api-Key: $API_KEY"

# 管理端为全部可桥接域创建或刷新应用
curl -X POST http://127.0.0.1:5001/api/system/open-app/ensure-domains \
  -H "Authorization: Bearer <admin_jwt>"

# 调用桥接的人脸识别端点
curl -X POST http://127.0.0.1:5001/openapi/v1/x/ai/face/recognize \
  -H "X-App-Id: app_face" -H "X-Api-Key: $API_KEY" \
  -F "file=@./face.jpg" -F "modelId=1"
```

## 精简别名（仍可用）

部分常用能力保留精简别名，例如：

```bash
curl -X POST http://127.0.0.1:5001/openapi/v1/vision/detect \
  -H "X-App-Id: app_demo" -H "X-Api-Key: $API_KEY" \
  -F "file=@./sample.jpg" -F "modelId=1"
```

异步调用增加 `async=1`，响应返回 `jobId`。异步任务需要运行：

```bash
python scripts/open_job_worker.py
```

## Webhook / Gateway

Webhook 在开放应用管理界面配置。独立网关通过 `python gateway_app.py` 启动，默认监听 5002；主应用默认监听 5001。监控指标端点为 `GET /openapi/v1/metrics`。
