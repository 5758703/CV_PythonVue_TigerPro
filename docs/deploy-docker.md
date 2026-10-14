# Docker Compose 部署（实验性）

> 当前状态：**实验性骨架**，用于降低新人环境成本，尚非生产级。完整跑通与
> 硬化是后续 Issue 的事。本文件列出已知限制与仍待办项。

这套 Compose 把应用已有的几块拼在一起：

- `db` — MySQL 8（数据落 `db-data` 卷，`deploy/initdb/` 里的一次性脚本只锁字符集）
- `backend` — Flask `app.py`（:5001，REST + JWT）
- `gateway` — Flask `gateway_app.py`（:5002，开放平台 Open API）
- `frontend_admin` / `frontend_home` — 两个 Vite 前端（5173 / 5174）

## 快速开始

```sh
cd deploy
cp .env.example .env      # 填 SECRET_KEY、DB_PASSWORD 等
docker compose config     # 不构建，先校验 YAML / 变量
docker compose up --build
```

访问：

- 控制台：http://localhost:5173
- 门户：http://localhost:5174
- 后端 REST：http://localhost:5001
- 开放平台网关：http://localhost:5002

## 密钥不进镜像

所有敏感值（`SECRET_KEY`、`DB_PASSWORD`，以及可选的 `HF_TOKEN` /
`MODELSCOPE_TOKEN` / `ROBOFLOW_API_KEY` / `DEEPSEEK_API_KEY` /
`QWEN_VL_API_KEY`）都从 `deploy/.env` 注入，Dockerfile 里没有任何真实密钥。
`.env` 被 `.gitignore` 挡在仓库外，只提交 `.env.example`。

## 已知限制

- **模型体积大、首次拉权重慢**：CV 权重在容器首次运行时才下载，冷启动
  很慢；给宿主机留足内存。`backend-data` 卷把上传目录和已拉取权重存下来，
  重建镜像不会重下。
- **CPU 优先**：目前默认 `YOLO_INFER_BACKEND=auto`（OpenVINO 优先、回退
  `.pt`），没有 GPU 加速；视频/实时检测在纯 CPU 上偏慢。
- **Flask dev 服务器**：骨架直接 `python app.py`（Flask 自带 server），
  适合本地/演示，不适合对外暴露；生产应换 WSGI + 反向代理（见
  `backend/README.md` 的 gunicorn 段落）。
- **异步 worker 未纳入**：转换/视频/训练等后台任务靠
  `scripts/admin_job_worker.py`、`scripts/open_job_worker.py`，骨架里没单独
  起服务，需要时再补一个 service。
- **前端是 `vite preview`**：只服务构建产物，够演示；正式部署建议换成静态
  托管 + 反向代理。

## 验收清单

- [ ] `docker compose config` 通过
- [ ] 文档写明「实验性」与后续 Issue（本文件已标注）
- [ ] 密钥不进镜像（已用 `deploy/.env` 注入，仓库只留 `.env.example`）

## 后续可拆的 Issue

- 加 GPU / OpenVINO 设备选择与资源预留
- 把 worker、反向代理、静态托管拆成独立 service
- 给 `db` 与 backend 加启动自检与日志集中
- 生产化：非 root 用户、只读文件系统、健康检查统一
