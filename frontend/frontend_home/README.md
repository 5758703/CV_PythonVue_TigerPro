# Tiger AI Platform · 门户前端（frontend_home）

对外宣传与入口门户。基于 **Vue 3 + Vite**，不依赖 Element Plus / 登录态。
业务能力与权限控制在 [`../frontend_admin`](../frontend_admin) 控制台中完成。

## 与后台的关系

| 项目 | 角色 | 默认端口 |
|------|------|----------|
| `frontend_home` | 门户（本项目） | **5174** |
| `frontend_admin` | 管理控制台 | 5173 |
| `backend` | Flask API | 5001 |

门户 CTA 通过 `VITE_ADMIN_URL` 跳转到控制台。点击时读取 Cookie `tiger_ai_token`（及同源 `localStorage.token`）：
已登录直达目标页，未登录打开 `/login?redirect=...`。本机请统一使用 **localhost**（不要混用 `127.0.0.1`）。

## 本地运行

前置：Node.js ≥ 18；建议同时启动后端与 `frontend_admin`。

```bash
cd frontend/frontend_home
cp .env.example .env   # 若尚无 .env
npm install
npm run dev             # http://127.0.0.1:5174
```

控制台（另开终端）：

```bash
cd frontend/frontend_admin
npm install
npm run dev             # http://127.0.0.1:5173
```

## 环境变量

见 `.env.example`：

- `VITE_ADMIN_URL` — 控制台根地址（跳转入口）
- `VITE_API_PROXY_TARGET` — 开发代理后端
- `VITE_GITHUB_URL` — 仓库链接
- `VITE_OPENAPI_DOCS_PATH` — OpenAPI 文档路径

## 公开接口

开发期 Vite 将 `/api`、`/openapi` 代理到后端：

| 接口 | 说明 |
|------|------|
| `GET /api/health` | 后端存活 |
| `GET /api/portal/summary` | 门户聚合统计（模型/数据集/任务分布，无需登录） |
| `GET /openapi/v1/health` | OpenAPI 健康 |
| `GET /openapi/v1/docs` | 开放文档 |

后端不可用时，门户仍展示演示数据，并提示「后端离线」。

## 构建

```bash
npm run build    # 产物 dist/
npm run preview
```

生产部署建议：站点根路径托管门户；`/console` 或子域托管 `frontend_admin`；`/api` 与 `/openapi` 反代到 Flask。请将 `VITE_ADMIN_URL` 设为控制台公网地址后重新 build。
