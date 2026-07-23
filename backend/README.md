# Tiger AI Platform · 后端

多任务 / 多模态 AI 模型管理与测试平台的服务端。基于 **Flask + SQLAlchemy + JWT**，
统一纳管多引擎 AI 模型，提供权重拉取（HuggingFace / ModelScope 双源）、在线推理测试，
以及 RBAC 权限系统（用户 / 角色 / 部门 / 岗位 / 菜单）。纯 **CPU** 即可运行全部任务。

> 配套前端见 [`../frontend/README.md`](../frontend/README.md)。

---

## 技术架构

```
前端 (SPA)
   │  REST /api/*  （JWT 鉴权）
   ▼
Flask 应用 :5001
   ├─ routes/         蓝图：auth / user / role / dept / job / menu / ai_model
   ├─ security.py     RBAC：JWT 解析 + 权限点(perms)校验装饰器
   ├─ models/         SQLAlchemy 实体（User/Role/Menu/... + AiModel）
   ├─ extensions.py   db / jwt / cors 实例
   ├─ config.py       配置（读 .env：数据库 / JWT / 上传目录 / HF·MS 令牌）
   ├─ seed.py         种子数据（默认账号 / RBAC 菜单 / 示例模型，幂等）
   ├─ app.py          应用工厂 + 轻量迁移(_migrate) + 启动入口
   └─ inference.py    多引擎推理层（惰性加载，按需导入）
        ├─ ultralytics YOLO        目标检测（图片/视频/摄像头）
        ├─ transformers            文本分类/零样本/完形/翻译/摘要/生成/NER/QA/图像分类/DETR/MMS-TTS
        ├─ funasr / funasr_onnx    语音识别（SenseVoice / 量化 onnx）
        ├─ sherpa-onnx             MeloTTS 中英混合语音合成
        └─ VibeVoice (vendored)    实时语音合成（预置音色）
   ▼
MySQL（元数据） + uploads/（模型权重 / 上传媒体 / 输出）
```

- **应用工厂模式**：`create_app()` 注册蓝图、初始化 db/jwt/cors，启动时建表 + 轻量迁移 + 写种子。
- **多引擎、惰性加载**：`inference.py` 体积大的库（torch/transformers/funasr 等）全部按需导入，加快启动。
- **双下载源**：`ai_model` 的 `source_url` 主机名决定从 HuggingFace 或 ModelScope 拉权重。
- **权重存储**：拉取后存 `uploads/models/<模型标识>/`（目录型）或单文件 `.pt`（YOLO）。

## 技术栈

| 类别 | 选型 |
|---|---|
| Web 框架 | Flask 3 + Flask-Cors + Flask-JWT-Extended |
| ORM / DB | Flask-SQLAlchemy + PyMySQL → **MySQL 8** |
| 运行时 | Python **3.12**（推荐 `backend/.venv`；RapidOCR 1.4.4 不支持 3.13） |
| 深度学习 | torch / torchvision / torchaudio **2.11（CPU）** |
| 推理引擎 | ultralytics(YOLO)、transformers 4.51、funasr、funasr_onnx、sherpa-onnx、onnxruntime |
| 模型来源 | huggingface_hub、modelscope |
| 媒体处理 | OpenCV、imageio-ffmpeg(H.264)、soundfile、librosa |
| 第三方推理代码（vendored） | `uploads/models/third_party/VibeVoice` |

## 目录结构

```
backend/
├─ app.py            # 入口：create_app() + _migrate() + app.run(:5001)
├─ config.py         # 配置（.env 注入）
├─ extensions.py     # db / jwt / cors
├─ security.py       # permission_required 等 RBAC 装饰器
├─ seed.py           # 种子数据（幂等）
├─ inference.py      # 多引擎推理实现
├─ models/           # ORM 实体（user.py / ai_model.py / ...）
├─ routes/           # 蓝图（auth/user/role/dept/job/menu/ai_model）
├─ requirements.txt
├─ .env.example      # 环境变量样例（复制为 .env）
└─ uploads/          # 运行时：models(含 third_party/VibeVoice) / videos / audios / outputs
```

## 环境准备

### 1. 数据库

安装 MySQL 8，创建数据库（表由应用启动时自动建立）：

```sql
CREATE DATABASE cv_python_tigerpro DEFAULT CHARACTER SET utf8mb4;
```

### 2. Python 环境（推荐 3.12 虚拟环境）

车辆追踪 / 车牌 OCR 依赖 `rapidocr_onnxruntime==1.4.4`，**须 Python 3.12 及以下**（3.13 仅能装 1.2.x 且识别异常）。

**方式 A：项目自带 venv（Windows 推荐）**

```powershell
cd backend
.\scripts\setup_venv.ps1          # 创建 .venv（Python 3.12）并安装依赖
.\scripts\run_backend.ps1         # 启动
```

手动等价步骤：

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\scripts\run_backend.ps1
```

**方式 B：conda**

```bash
conda create -n cv_python_tigerpro python=3.12 -y
conda activate cv_python_tigerpro
pip install -r requirements.txt
```

> **torch 全家桶须对齐 2.11（CPU 版）**：
> `pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cpu`

### 3. 环境变量

复制 `.env.example` 为 `.env` 并填写：

```ini
SECRET_KEY=change-me
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=你的密码
DB_NAME=cv_python_tigerpro
HF_TOKEN=            # 可选：拉取 HuggingFace 受限模型
MODELSCOPE_TOKEN=    # 可选：拉取 ModelScope 受限模型
ROBOFLOW_API_KEY=    # 可选：拉取 Roboflow Universe 模型（如 Rocket Detect）
```

### 4. 语音 / 数字人引擎（按需，可选）

仅用 YOLO / transformers 任务可跳过。需要 VibeVoice 时，clone 官方推理代码：

```bash
git clone https://github.com/microsoft/VibeVoice  backend/uploads/models/third_party/VibeVoice
```
运行时由 `inference._ensure_vibevoice_path` 自动注入 `sys.path`。

## 本地运行

```powershell
# Windows（推荐）
cd backend
.\scripts\run_backend.ps1
```

```bash
# 或手动激活环境
conda activate cv_python_tigerpro   # 或 backend\.venv\Scripts\Activate.ps1
cd backend
python app.py        # http://0.0.0.0:5001 （debug + 自动重载）
```

启动时自动：建表 → 轻量迁移 → 写种子（默认账号 admin/admin123、tiger/123456；RBAC 菜单；示例模型）。

健康检查：`GET http://127.0.0.1:5001/api/health` → `{"code":0,"message":"ok"}`。

单独初始化种子（可选）：`python seed.py`。

## 使用流程

1. 前端「模型管理」新增模型（填 `task` / `library` / `source_url`），或用内置示例模型。
2. 点「拉取权重」从 HuggingFace / ModelScope / Roboflow 下载到 `uploads/models/<标识>/`。
3. 到对应任务页在线测试（检测 / 分类 / 文本 / 语音识别 / 语音合成 / 数字人）。

## 部署

> 生产环境关闭 `debug`，用 WSGI 服务器托管，前置 Nginx（见前端 README 的反代配置）。

**Linux（gunicorn）**
```bash
pip install gunicorn
gunicorn -w 1 -k gthread --threads 4 -t 0 -b 0.0.0.0:5001 "app:app"
```

**Windows（waitress）**
```bash
pip install waitress
waitress-serve --listen=0.0.0.0:5001 app:app
```

部署要点：
- **worker 数宜小**（推理吃内存，模型按进程缓存）；用线程（`--threads`）承载并发，`timeout` 设 0（推理耗时长）。
- 视频检测 / 数字人为**异步后台任务**（内存任务表 + 轮询进度），多 worker 下任务表不共享 —— 单 worker 或外置任务队列。
- `uploads/models/third_party/`（VibeVoice）、`.env` 需随部署保留；权重 / 视频文件大，注意磁盘与上传体积上限（默认 500MB）。
- 首次推理会下载 / 加载模型，存在冷启动延迟；模型按 `model_dir` 进程内缓存复用。

## API 速览

| 模块 | 前缀 | 说明 |
|---|---|---|
| 认证 | `/api/auth` | 登录 / 注册 / 用户信息（JWT） |
| 系统管理 | `/api/system/*` | user / role / dept / job / menu（RBAC） |
| AI 模型 | `/api/ai/model` | CRUD、拉权重(`/fetch`)、各任务在线测试（detect / classify / transcribe / tts / ...） |

所有受保护接口需请求头 `Authorization: Bearer <token>`，并校验对应权限点（`perms`）。
