# Tiger AI Platform · 前端

多任务 / 多模态 AI 模型管理与测试平台的 Web 前端。基于 **Vue 3 + Vite + Element Plus**，
提供模型全生命周期管理（纳管 / 拉权重 / 在线测试）与覆盖视觉·文本·语音·多模态的任务测试页面，
并内置 RBAC 权限管理（用户 / 角色 / 部门 / 岗位 / 菜单）。

> 配套后端见 [`../backend/README.md`](../backend/README.md)。

---

## 技术架构

```
浏览器 (SPA)
   │  axios（/api 前缀）
   ▼
Vite Dev Server :5173 ── proxy /api ──▶ Flask 后端 :5001
   │
   ├─ Vue Router 4   路由 + 登录守卫（token 校验、动态拉取权限）
   ├─ Pinia          全局状态（用户信息 / token / 角色权限）
   ├─ Element Plus   UI 组件库 + 图标
   ├─ ECharts        首页统计图表（任务分布饼图 / 分类柱状图）
   └─ v-permission   按钮级权限指令（基于后端返回的 perms）
```

- **单页应用（SPA）**：前后端分离，前端打包为静态资源，经 `/api` 调用后端 REST 接口。
- **权限驱动 UI**：登录后从后端拉取角色 / 菜单 / 按钮权限，路由守卫与 `v-permission` 指令据此放行。
- **任务页约定**：每个 AI 任务一个页面（`views/ai/*`），按 `library` + `task` 过滤可用模型，统一在线测试。

## 技术栈

| 类别 | 选型 |
|---|---|
| 框架 | Vue 3.4（`<script setup>` 组合式 API） |
| 构建 | Vite 5 |
| UI | Element Plus 2.7 + `@element-plus/icons-vue` |
| 状态 | Pinia 2 |
| 路由 | Vue Router 4 |
| HTTP | axios 1.7 |
| 图表 | ECharts 5 |
| 语言 | JavaScript（ESM） |

## 目录结构

```
frontend/
├─ index.html
├─ vite.config.js          # 端口 5173 + /api 代理到 127.0.0.1:5001
├─ package.json
└─ src/
   ├─ main.js              # 应用入口（挂载 Element Plus / Pinia / Router）
   ├─ api/                 # 接口封装（ai.js 模型与推理、system.js 系统管理、request.js axios 实例）
   ├─ composables/         # 组合式逻辑（useInferProgress 进度/ETA 等）
   ├─ directives/          # 自定义指令（v-permission 按钮权限）
   ├─ layout/              # 布局（侧栏 / 顶栏 / 菜单）
   ├─ router/              # 路由表 + 全局守卫
   ├─ store/               # Pinia（user 等）
   └─ views/
      ├─ Dashboard.vue     # 首页（平台介绍 + 统计图表）
      ├─ Login.vue / Register.vue
      ├─ ai/               # AI 任务页
      │   ├─ model/        # 模型管理（CRUD / 拉权重 / 测试 / 来源分类）
      │   ├─ image|video|camera/  # 目标检测：图片 / 视频 / 摄像头
      │   ├─ imgcls/       # 图像分类
      │   ├─ text/ generate/ ner/ qa/  # 文本：分析 / 生成 / 实体识别 / 问答
      │   ├─ asr/          # 语音识别
      │   ├─ tts/          # 文本转语音 / 音色克隆
      │   └─ talker/       # 数字人合成
      └─ system/           # 用户 / 角色 / 部门 / 岗位 / 菜单管理
```

## 本地运行

前置：**Node.js ≥ 18**、后端已在 `http://127.0.0.1:5001` 运行（见后端 README）。

```bash
cd frontend
npm install
npm run dev         # 开发服务器 http://localhost:5173（/api 自动代理到后端 5001）
```

打开 http://localhost:5173 ，默认账号：

| 账号 | 密码 | 角色 |
|---|---|---|
| admin | admin123 | 超级管理员（全部权限） |
| tiger | 123456 | 普通角色（只读） |

> 后端地址不是 `127.0.0.1:5001` 时，修改 `vite.config.js` 的 `server.proxy['/api'].target`。

## 构建与部署

```bash
cd frontend
npm install
npm run build       # 产物输出到 frontend/dist/
npm run preview     # 本地预览 dist（可选）
```

### Nginx 部署（推荐）

`dist/` 为纯静态资源，托管到 Nginx 并把 `/api` 反向代理到后端：

```nginx
server {
    listen 80;
    server_name your.domain.com;

    root  /var/www/tiger-ai/dist;   # frontend/dist 部署位置
    index index.html;

    # SPA 前端路由回退（history 模式）
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 反向代理后端 API
    location /api/ {
        proxy_pass         http://127.0.0.1:5001/;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        client_max_body_size 500m;   # 模型权重 / 视频上传较大
    }
}
```

- 前端使用 **history 路由**，务必配置 `try_files ... /index.html` 回退，否则刷新子路由 404。
- 上传权重 / 视频文件较大，`client_max_body_size` 需放大（后端单文件上限 500MB）。
- 静态资源可加缓存头；`index.html` 建议不缓存以便发版生效。

## 说明

- 所有后端接口走 `/api` 前缀；`src/api/request.js` 统一注入 JWT、处理 401。
- 在线测试为长耗时请求（拉模型 / CPU 推理），相关 axios 调用已设 `timeout: 0`。
- 图表、进度条等为前端实时计算，无需额外服务。
