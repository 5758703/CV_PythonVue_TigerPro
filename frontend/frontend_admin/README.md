# Tiger AI Platform · 管理控制台（frontend_admin）

多任务 / 多模态 AI 模型管理与测试平台的 **Web 控制台**。基于 **Vue 3 + Vite + Element Plus**，
提供模型全生命周期管理（纳管 / 拉权重 / 在线测试）与覆盖视觉·文本·语音·多模态的任务测试页面，
并内置 RBAC 权限管理（用户 / 角色 / 部门 / 岗位 / 菜单）。

> 配套后端见 [`../../backend/README.md`](../../backend/README.md)。  
> 项目门户见 [`../frontend_home/README.md`](../frontend_home/README.md)。  
> 前端总览见 [`../README.md`](../README.md)。

---

## 技术架构

```
浏览器 (SPA)  :5173
   │  axios（/api 前缀）
   ▼
Vite Dev Server ── proxy /api、/openapi ──▶ Flask 后端 :5001
   │
   ├─ Vue Router 4   路由 + 登录守卫（token / redirect 深链）
   ├─ Pinia          全局状态（用户信息 / token / 角色权限）
   ├─ Element Plus   UI 组件库 + 图标
   ├─ ECharts        首页统计图表
   └─ v-permission   按钮级权限指令
```

- **单页应用（SPA）**：前后端分离，打包为静态资源，经 `/api` 调用后端。
- **权限驱动 UI**：登录后拉取角色 / 菜单 / 按钮权限。
- **与门户联动**：顶栏「项目门户」跳转 `VITE_PORTAL_URL`；登录态写入 `localStorage` + Cookie `tiger_ai_token` 供门户跨端口识别。

## 技术栈

| 类别 | 选型 |
|---|---|
| 框架 | Vue 3.4（`<script setup>`） |
| 构建 | Vite 5（`host: localhost`，端口 **5173**） |
| UI | Element Plus 2.7 + `@element-plus/icons-vue` |
| 状态 | Pinia 2 |
| 路由 | Vue Router 4 |
| HTTP | axios 1.7 |
| 图表 | ECharts 5 |

## 目录结构

```
frontend_admin/
├─ .env.example            # VITE_PORTAL_URL=http://localhost:5174
├─ vite.config.js          # 端口 5173 + /api 代理
├─ package.json
└─ src/
   ├─ main.js
   ├─ api/                 # ai / system / auth / request
   ├─ utils/               # authStorage（token+Cookie）、portal.js
   ├─ layout/              # 侧栏 / 顶栏（含「项目门户」）
   ├─ router/              # 含 /login?redirect= 深链
   ├─ store/user.js
   └─ views/               # Dashboard、Login、ai/*、system/*
```

## 本地运行

前置：Node.js ≥ 18、后端 `http://127.0.0.1:5001` 已启动。

```bash
cd frontend/frontend_admin
cp .env.example .env   # 可选
npm install
npm run dev            # http://localhost:5173
```

| 账号 | 密码 | 角色 |
|---|---|---|
| admin | admin123 | 超级管理员 |
| tiger | 123456 | 普通角色（只读） |

环境变量：

| 变量 | 说明 | 默认 |
|------|------|------|
| `VITE_PORTAL_URL` | 项目门户地址 | `http://localhost:5174` |
| `VITE_BASE` | 子路径部署前缀（生产 `/console/`） | `/` |

完整部署见 [`docs/deploy`](../../docs/deploy/README.md)。

## 构建与部署

```bash
npm run build       # 产物 dist/
npm run preview
```

### Nginx（门户 + 控制台同域示例）

```nginx
# 门户 /
location / {
    root /var/www/tiger-ai/portal;
    try_files $uri $uri/ /index.html;
}

# 控制台 /console/
location /console/ {
    alias /var/www/tiger-ai/admin/;
    try_files $uri $uri/ /console/index.html;
}

location /api/ {
    proxy_pass http://127.0.0.1:5001/;
    proxy_set_header Host $host;
    client_max_body_size 500m;
}

location /openapi/ {
    proxy_pass http://127.0.0.1:5001/openapi/;
    proxy_set_header Host $host;
    client_max_body_size 500m;
}
```

子域部署时：门户与控制台分别 `root`；构建前设置 `VITE_PORTAL_URL` / 门户侧 `VITE_ADMIN_URL`。

## 说明

- 门户深链：`/login?redirect=/ai/fall` 登录后进入目标页（防开放重定向，仅允许站内路径）。
- JWT 经 `src/api/request.js` 注入；401 清登录态并回登录页。
- Open API：`/openapi/v1`（AppKey）；控制台开放平台：`/system/open-app`。
- 长耗时推理相关 axios 已设 `timeout: 0`。
