# Tiger AI Platform · 门户前端（frontend_home）

对外宣传与入口门户。基于 **Vue 3 + Vite + lucide-vue-next**，无 Element Plus / 无登录表单。
业务能力在 [`../frontend_admin`](../frontend_admin) 控制台完成。

> 前端总览见 [`../README.md`](../README.md)。

## 与后台的关系

| 项目 | 角色 | 默认地址 |
|------|------|----------|
| `frontend_home` | 门户（本项目） | http://localhost:5174 |
| `frontend_admin` | 管理控制台 | http://localhost:5173 |
| `backend` | Flask API | http://127.0.0.1:5001 |

跳转规则（点击时判定）：

1. 读取 Cookie `tiger_ai_token`（控制台登录时写入，同主机跨端口可读）
2. **已登录** → 直达控制台目标页（如 `/index`、`/ai/image`）
3. **未登录** → `http://localhost:5173/login?redirect=...`

本机请统一使用 **localhost**（不要混用 `127.0.0.1`）。

## 本地运行

```bash
cd frontend/frontend_home
cp .env.example .env
npm install
npm run dev             # http://localhost:5174
```

另开终端启动控制台：

```bash
cd frontend/frontend_admin
npm install && npm run dev   # http://localhost:5173
```

## 环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `VITE_DEV_PORT` | 开发端口 | `5174` |
| `VITE_ADMIN_URL` | 控制台根地址 | `http://localhost:5173` |
| `VITE_API_PROXY_TARGET` | 后端代理 | `http://127.0.0.1:5001` |
| `VITE_GITHUB_URL` | 仓库链接 | 本仓库 GitHub |
| `VITE_OPENAPI_DOCS_PATH` | OpenAPI 文档路径 | `/openapi/v1/docs` |

## 公开接口

开发期 Vite 代理 `/api`、`/openapi` → 后端：

| 接口 | 说明 |
|------|------|
| `GET /api/health` | 后端存活 |
| `GET /api/portal/summary` | 门户聚合统计（无需登录） |
| `GET /openapi/v1/health` | OpenAPI 健康 |
| `GET /openapi/v1/docs` | 开放文档 |

后端不可用时展示演示数据，并提示「后端离线」。

## 构建

```bash
npm run build
npm run preview
```

生产：将 `VITE_ADMIN_URL` 设为控制台公网地址后 build；站点根路径托管门户，`/console` 或子域托管控制台。
