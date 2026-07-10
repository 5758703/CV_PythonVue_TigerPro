# CV Python Tigerpro

Flask + Vue 前后端分离 web 项目，实现 **RBAC 用户角色权限管理系统**。

```
backend/    Flask + Flask-SQLAlchemy + PyMySQL + Flask-Cors + Flask-JWT-Extended
frontend/   Vue3 + Vite + Element Plus + Vue Router + Pinia + Axios + ECharts
```
<img width="1920" height="869" alt="image" src="https://github.com/user-attachments/assets/0301e97a-85f5-441d-90cb-8d86d15efec8" />



https://github.com/user-attachments/assets/bbd6ffcd-348a-4df1-b7b5-587ac6a6f22f



## 功能

- 用户注册 / 登录（JWT 认证）
- RBAC：用户·角色·部门(无限级树)·岗位·菜单/权限
- 多对多：用户↔角色、用户↔部门、用户↔岗位、角色↔权限、用户↔权限
- 权限分类：
  - 功能权限 — 菜单(M目录/C菜单)、按钮(F，前端 `v-permission`)、API 接口(A，后端校验)
  - 数据权限 — 角色 `data_scope`：1 仅本人 / 2 本部门 / 3 本部门及下级 / 4 全部

## 默认账号（种子数据自动写入）

| 账号 | 密码 | 角色 | 数据范围 | 说明 |
|------|------|------|----------|------|
| `admin` | `admin123` | 超级管理员(admin) | 全部数据 | 全菜单 + 全部增删改 |
| `tiger` | `123456` | 普通角色(common) | 本部门(前端组) | 只读，用户列表仅见本部门 |

> 初始化幂等：`sys_user` 无数据时才灌种子（5 部门 / 4 岗位 / 31 菜单 / 2 角色 / 2 用户）。

## 数据表

| 表 | 说明 |
|----|------|
| `sys_user` | 用户（主部门 dept_id）|
| `sys_role` | 角色（data_scope 数据范围）|
| `sys_dept` | 部门（无限级树，ancestors 祖级链）|
| `sys_job` | 岗位 |
| `sys_menu` | 菜单/权限（menu_type M/C/F/A）|
| `sys_user_role` / `sys_user_dept` / `sys_user_post` | 用户的角色/部门/岗位（多对多）|
| `sys_role_menu` / `sys_user_menu` | 角色权限 / 用户直接授权（多对多）|

## 后端 backend

```bash
conda activate cv_python_tigerpro
cd backend
pip install -r requirements.txt

cp .env.example .env      # 编辑 .env 填入 MySQL 账号密码（默认 root/123456）
# MySQL 建库：
#   CREATE DATABASE cv_python_tigerpro DEFAULT CHARSET utf8mb4;

python app.py            # http://127.0.0.1:5001 （启动自动建表 + 灌种子）
```

返回结构统一 `{ code, message, data }`，`code=0` 成功。请求头带 `Authorization: Bearer <token>`。

接口：

| 模块 | 路径 | 说明 |
|------|------|------|
| 认证 | `POST /api/auth/login` | 登录，返回 `{token}` |
| 认证 | `POST /api/auth/register` | 注册（默认普通角色）|
| 认证 | `GET /api/auth/info` | 当前用户 + 角色标识 + 权限标识 |
| 认证 | `GET /api/auth/routers` | 当前用户可见菜单树（侧栏）|
| 认证 | `POST /api/auth/logout` | 退出 |
| 用户 | `/api/system/user` | GET 列表(数据权限) / POST / PUT / DELETE |
| 角色 | `/api/system/role` | CRUD + 菜单授权 + data_scope |
| 部门 | `/api/system/dept` | 树 + CRUD |
| 岗位 | `/api/system/job` | CRUD |
| 菜单 | `/api/system/menu` | 树 + CRUD |
| 健康 | `GET /api/health` | 健康检查 |

功能权限装饰器 `@permission_required("system:user:add")`；数据权限 `apply_user_data_scope()` 按角色 data_scope 过滤。

## 前端 frontend

```bash
cd frontend
npm install
npm run dev              # http://127.0.0.1:5173
```

Vite 代理：前端 `/api` → `http://127.0.0.1:5001`。

- 登录后守卫调 `getInfo`+`getRouters` → 动态侧栏 + 权限标识
- 按钮级权限：`v-permission="'system:user:add'"`，无权限移除元素
- 页面：登录、首页(统计卡+ECharts)、系统管理(用户/角色/部门/岗位/菜单)

## 文档

| 文档 | 说明 |
|------|------|
| [羽毛球分析模块](docs/badminton-analysis.md) | 技术栈、依赖、姿态/检测模型权重、球场自动检测、HUD 鹰眼、API 与使用流程 |
| [图像分割模块](docs/image-segmentation.md) | 技术栈、依赖、模型权重、API 与使用流程（RF-DETR-Seg / MobileSAM） |

> 文档内保留 **实测截图占位**，可在 `docs/images/` 下按章节补充项目截图后替换。

## 启动顺序

1. 启动 MySQL，建库 `cv_python_tigerpro`
2. 后端 `python app.py`（:5001，自动建表+种子）
3. 前端 `npm run dev`（:5173），浏览器打开，用 `admin/admin123` 登录
<img width="1920" height="869" alt="744ec6c19b3817d1e7c1efe5d66124e7" src="https://github.com/user-attachments/assets/90d8bbee-e9f1-4e73-a5fe-0e1389ef9769" />

<img width="1920" height="869" alt="243ec0a85149c5fc2c79168466bfd19d" src="https://github.com/user-attachments/assets/9a0850dd-1607-4b8a-8385-05c62ac37859" />

<img width="1920" height="869" alt="a894ca39be5586d2f9bcc7a587404d4d" src="https://github.com/user-attachments/assets/a1c939e0-3f35-47df-b878-dfb85e095821" />
