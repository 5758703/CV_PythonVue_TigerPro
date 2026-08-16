# Tiger AI · 前端说明

本仓库前端拆为两个独立 Vite 应用：

| 目录 | 角色 | 开发地址 | 文档 |
|------|------|----------|------|
| [`frontend_home`](./frontend_home) | **项目门户**（对外入口 / 宣传） | http://localhost:5174 | [README](./frontend_home/README.md) |
| [`frontend_admin`](./frontend_admin) | **管理控制台**（登录后业务） | http://localhost:5173 | [README](./frontend_admin/README.md) |

配套后端：[`../backend/README.md`](../backend/README.md)。

## 推荐启动顺序

```bash
# 1. 后端 :5001
cd backend && python app.py

# 2. 控制台 :5173
cd frontend/frontend_admin && npm install && npm run dev

# 3. 门户 :5174
cd frontend/frontend_home && npm install && npm run dev
```

本机请统一使用 **localhost**（不要混用 `127.0.0.1`），否则登录 Cookie / `localStorage` 不同源。

默认账号：`admin` / `admin123`。

## 互相跳转

- 门户 → 控制台：按 Cookie `tiger_ai_token` 判断登录态；已登录直达目标页，未登录 `/login?redirect=...`
- 控制台 → 门户：顶栏用户名左侧「项目门户」（`VITE_PORTAL_URL`，默认 `:5174`）
