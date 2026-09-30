# CV Python Tigerpro

<p align="center">
  <img src="assets/tiger-ai-logo.svg" alt="Tiger AI" width="330" />
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <a href="README.en.md">English</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-182A40?labelColor=18A6B2" alt="Apache-2.0" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-182A40?labelColor=18A6B2" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/Vue-3-182A40?labelColor=18A6B2" alt="Vue 3" />
</p>

A Flask + Vue platform for **multi-task computer vision and speech AI**, with separate portal and admin applications. It brings together RBAC, model management, detection, pose estimation, face and vehicle analysis, OCR, training, testing, and inference.

**License:** [Apache-2.0](LICENSE) ([Chinese summary](LICENSE.zh-CN.md); the English license governs) · **Repository:** https://github.com/5758703/CV_PythonVue_TigerPro

**Explore** · [Quick start](#quick-start) · [Features](#features) · [Demos](#demos-and-screenshots) · [Backend](#backend) · [Frontends](#frontends) · [Documentation](#documentation) · [Contributing](#contributing)

---

## Quick start

```text
backend/                 Flask + SQLAlchemy + JWT + Ultralytics / InsightFace / OCR …
frontend/frontend_home/  Project portal (Vue 3 + Vite)             → http://localhost:5174
frontend/frontend_admin/ Admin console (Vue 3 + Element Plus)     → http://localhost:5173
```

1. **Backend:** follow [`backend/README.md`](backend/README.md). Python 3.12 and the `scripts/setup_venv.ps1` / `run_backend.ps1` scripts are recommended.
2. **Console:** `cd frontend/frontend_admin && npm install && npm run dev` (`:5173`).
3. **Portal:** `cd frontend/frontend_home && npm install && npm run dev` (`:5174`).
4. Open http://localhost:5174 and select **Enter Console**. Use the random `admin` password printed on first startup or `INITIAL_ADMIN_PASSWORD` from `.env`.

> Use **localhost** consistently on your machine; do not mix it with `127.0.0.1`. See [`frontend/README.md`](frontend/README.md) for the frontend overview.

## Features

### Recent additions

| Capability | What it does | Entry / documentation |
|---|---|---|
| **OmDet-Turbo open-vocabulary detection** | Zero-shot detection from a text category list (Swin Tiny); prompt categories on the image detection page; works alongside fixed-class YOLO. | `/ai/image` · model key `omdet-turbo-swin-tiny` |
| **VLM-FO1 multimodal grounding** | Fine-grained natural-language / REC grounding; YOLO proposals filtered by FO1; prompts on the image detection page. | `/ai/image` · model key `vlm-fo1-3b` |
| **MOSS-Transcribe-Diarize ASR** | Multi-speaker transcription with timestamps, audio/video upload, subtitle preview, and JSON/SRT/ASS export. | `/ai/asr` · model key `moss-transcribe-diarize-0p9b` |
| **Cross-camera MTMC evidence storage** | Three gates (confirmed / candidate / new), tracklet evidence, an evidence-storage session switch, and manual candidate promotion/rejection. | `/ai/mtmc` · [guide](docs/mtmc-cross-camera-reid.md) |
| **Cross-camera MTMC re-identification** | Shared multi-stream ingestion → tracklets → OSNet/CLIP in parallel with Youtu → vehicle visual ReID plus plate fusion → global IDs; AI overlay on the monitoring wall; McByte++. | `/ai/mtmc` · [guide](docs/mtmc-cross-camera-reid.md) |
| **Fall detection** | Four pose measures; image, video, and camera input; async annotated video and trigger events; alert rules and sound. | `/ai/fall` · `fall_detection` alerts |
| **Gesture recognition** | MediaPipe number gestures and YOLO Chinese sign language, runnable together with video sequence output. | `/ai/handpose` |
| **Project portal** | `frontend_home` (`:5174`), console deep links, and shared login state through the `tiger_ai_token` cookie. | http://localhost:5174 |
| **Windows screen RTSP** | Streams the local desktop into camera management and the monitoring wall for testing without a physical camera. | [Instructions](docs/camera-screen-rtsp.md) |
| **Separate model-management section** | Top-level sidebar section for the model list and training, next to AI recognition. | `/ai/model` · `/ai/training` |
| **Production model scenarios, phase one** | Nine fixed model routes, four workbench types, dynamic readiness, and inference shared by the admin UI and Open API. | `/ai/scenarios` · [examples](backend/docs/openapi_examples.md#生产模型场景) |

For more detail, see the [recent feature overview](docs/articles/平台近期新增功能说明.md).

### Capability overview

- User registration and sign-in with JWT authentication.
- RBAC for users, roles, departments (unlimited-depth tree), posts, menus, and permissions.
- Many-to-many relations among users, roles, departments, posts, and permissions.
- Functional permissions for menus (`M` directories / `C` pages), buttons (`F`, frontend `v-permission`), and API endpoints (`A`, backend validation). Role `data_scope`: 1 self, 2 department, 3 department and descendants, 4 all data.
- Vision: object and open-vocabulary detection (OmDet-Turbo), natural-language grounding (VLM-FO1), smoking/phone-use alerts, pose, segmentation, fall and gesture recognition (including Chinese sign language), face recognition (InsightFace + OpenCV YuNet+SFace), person ReID (Youtu), cross-camera MTMC with evidence and candidate promotion, LaMa inpainting, table recognition (YOLO + RapidOCR + SLANet), and tracking for vehicles and absence from workstations with multi-station and moving-camera compensation.
- Speech: ASR (`funasr` and MOSS-Transcribe-Diarize multi-speaker transcription) and TTS.
- Lightweight OpenCV Zoo models: YuNet+SFace, Youtu Person ReID, EfficientSAM, LaMa, and MobileNet V2 with DNN / ONNX Runtime fallback.
- **Security detection pack:** 11 local ONNX models covering smoke and fire, forest fire and disaster extensions, PPE and helmets, falls and actions, fights, weapons, and plates. Seed category `sec-*`; ONNX Runtime CPU inference with image/video/camera input and alert rules.
- **Weight conversion (`pt → onnx`):** async export from model management (`imgsz`, `dynamic`, `half`). Detection prefers an `.onnx` in the same directory unless `YOLO_PREFER_ONNX=0`; model lists support page sizes 1–200 with local persistence.
- Live detection with **local or network cameras**; Windows desktop RTSP can feed the monitoring wall. See the [screen RTSP guide](docs/camera-screen-rtsp.md).
- **Two frontends:** a public portal with deep links and an admin console with RBAC navigation and AI workbenches.

## Demos and screenshots

```text
backend/                 Flask + Flask-SQLAlchemy + PyMySQL + Flask-Cors + Flask-JWT-Extended
frontend/frontend_home/  Vue 3 + Vite (project portal)
frontend/frontend_admin/ Vue 3 + Vite + Element Plus + Vue Router + Pinia + Axios + ECharts
```

### Video demos

|  |  |  |
| :---: | :---: | :---: |
| [▶ 演示 01 / Demo 01](https://github.com/user-attachments/assets/c591bb3c-9900-4bad-b103-072fa68f995d) | [▶ 演示 02 / Demo 02](https://github.com/user-attachments/assets/22b18f3f-fb99-4a56-a341-7fa5674215c9) | [▶ 演示 03 / Demo 03](https://github.com/user-attachments/assets/32f917e8-108a-455a-a8fe-35f864cf1074) |
| [▶ 演示 04 / Demo 04](https://github.com/user-attachments/assets/32b4cbfe-a0e2-4908-b570-2d85da2050ff) | [▶ 演示 05 / Demo 05](https://github.com/user-attachments/assets/69ead2ad-c3d6-4e38-a808-3f53a44be973) | [▶ 演示 06 / Demo 06](https://github.com/user-attachments/assets/22651205-df17-46a4-9142-1d5ce315ef80) |
| [▶ 演示 07 / Demo 07](https://github.com/user-attachments/assets/797b89e0-3330-4c33-9315-e2d34c9c8517) | [▶ 演示 08 / Demo 08](https://github.com/user-attachments/assets/be7e76bc-f0f3-42fb-b380-4cf3643d62b1) | [▶ 演示 09 / Demo 09](https://github.com/user-attachments/assets/9e2abc22-ecfe-414d-b3e2-8f72f904d416) |
| [▶ 演示 10 / Demo 10](https://github.com/user-attachments/assets/ce3d8ab3-18fe-406f-b1ab-fc147299acb6) | [▶ 演示 11 / Demo 11](https://github.com/user-attachments/assets/ab4ecbfa-39ea-4480-bb06-1da073eb855e) | [▶ 演示 12 / Demo 12](https://github.com/user-attachments/assets/9839f84d-97d5-4507-bbaf-f86b3d1b8d28) |
| [▶ 演示 13 / Demo 13](https://github.com/user-attachments/assets/9cc0e219-2d54-4da3-93b6-ad3befb1f4d9) | [▶ 演示 14 / Demo 14](https://github.com/user-attachments/assets/91eab844-0848-4b06-aebd-30076f1a2dc4) | [▶ 演示 15 / Demo 15](https://github.com/user-attachments/assets/0c88fac9-9f05-4054-8092-a0a0a676820c) |
| [▶ 演示 16 / Demo 16](https://github.com/user-attachments/assets/4adb3002-c697-4d0e-a795-89166f1c2734) | [▶ 演示 17 / Demo 17](https://github.com/user-attachments/assets/e50ffe56-197e-476a-a92c-55b5c40db184) | [▶ 演示 18 / Demo 18](https://github.com/user-attachments/assets/43fb406a-1f5b-4f78-a785-bf266aa4f9a0) |
| [▶ 演示 19 / Demo 19](https://github.com/user-attachments/assets/661d3ead-cb44-447a-8670-419b52612612) | [▶ 演示 20 / Demo 20](https://github.com/user-attachments/assets/0d52f28b-b3e3-4790-9d78-f19ae5618632) | [▶ 演示 21 / Demo 21](https://github.com/user-attachments/assets/bbd6ffcd-348a-4df1-b7b5-587ac6a6f22f) |

### Screenshots

|  |  |  |
| :---: | :---: | :---: |
| <img src="https://github.com/user-attachments/assets/0301e97a-85f5-441d-90cb-8d86d15efec8" alt="image" width="300" /> | <img src="https://github.com/user-attachments/assets/cc54a1ee-6334-4b0f-a520-6fabf47f50b4" alt="微信图片_20260719005341_513_226" width="300" /> | <img src="https://github.com/user-attachments/assets/ee916e47-bf88-4fbd-a75c-6761fd999aba" alt="ScreenShot_2026-07-05_122934_328" width="300" /> |
| <img src="https://github.com/user-attachments/assets/d91426a3-54aa-48d5-be13-c17c5fb42d71" alt="微信图片_20260719050319_517_226" width="300" /> | <img src="https://github.com/user-attachments/assets/ff2e2c00-f651-4c31-9dbd-10dce529554c" alt="微信图片_20260719005341_513_226" width="300" /> | <img src="https://github.com/user-attachments/assets/c185531d-b2df-4043-bde8-f39abbe41fb4" alt="微信图片_20260709055050_436_226" width="300" /> |
| <img src="https://github.com/user-attachments/assets/df69d5e3-205b-4e5c-b537-2ba5cb3bb030" alt="微信图片_20260719013021_514_226" width="300" /> | <img src="https://github.com/user-attachments/assets/ff246778-0dc9-4c45-b783-c7a7fff7bb4e" alt="微信图片_20260709055035_435_226" width="300" /> | <img src="https://github.com/user-attachments/assets/2e9fe963-6991-47ea-9683-36bfb9ca8928" alt="微信图片_20260719013047_515_226" width="300" /> |
| <img src="https://github.com/user-attachments/assets/f0821d2b-67ab-4da2-89eb-3448d0dfa811" alt="微信图片_20260709055007_434_226" width="300" /> | <img src="https://github.com/user-attachments/assets/b1dbfebc-5c29-4d48-b0b5-eb929ed7ad4a" alt="微信图片_20260717110704_504_226" width="300" /> | <img src="https://github.com/user-attachments/assets/25a0a9c2-666a-4e12-b48e-0e35c6daf9e1" alt="FireShot Capture 017 - Tiger AI Platform · 多任务AI模型管理与测试平台 -  localhost" width="300" /> |
| <img src="https://github.com/user-attachments/assets/c94e004a-1b56-489c-b816-8885ec1292c2" alt="demo_result_on_your_image" width="300" /> | <img src="https://github.com/user-attachments/assets/4b54483e-5e5a-422a-92c7-148ca115909f" alt="微信图片_20260718031938_508_226" width="300" /> | <img src="https://github.com/user-attachments/assets/cdcd0c34-a6cd-4363-b771-c8b3fa380758" alt="微信图片_20260717105559_500_226" width="300" /> |
| <img src="https://github.com/user-attachments/assets/93c3913e-3e10-4c33-8cfa-1658c18f3fe4" alt="微信图片_20260704112908_365_226" width="300" /> | <img src="https://github.com/user-attachments/assets/fb1596b1-02be-4e89-b861-a765aa416d16" alt="微信图片_20260704235432_374_226" width="300" /> |  |

## Default accounts (automatically seeded)

| Account | Password | Role | Data scope | Access |
|---|---|---|---|---|
| `admin` | `INITIAL_ADMIN_PASSWORD` or the random password in the first startup log | Super admin (`admin`) | All data | All menus and write operations |
| `tiger` | `INITIAL_DEMO_PASSWORD` or the random password in the first startup log | Common role (`common`) | Own department (frontend group) | Read-only; user list limited to own department |

> Seeding is idempotent: only an empty `sys_user` table receives the initial 5 departments, 4 posts, 31 menus, 2 roles, and 2 users. Existing database passwords remain unchanged.

## Database tables

| Table | Purpose |
|---|---|
| `sys_user` | Users, with a primary `dept_id` |
| `sys_role` | Roles and `data_scope` |
| `sys_dept` | Department tree and `ancestors` chain |
| `sys_job` | Posts |
| `sys_menu` | Menus / permissions (`M/C/F/A`) |
| `sys_user_role` / `sys_user_dept` / `sys_user_post` | Many-to-many user relationships |
| `sys_role_menu` / `sys_user_menu` | Role permissions / direct user permissions |

## Backend

```bash
conda activate cv_python_tigerpro
cd backend
pip install -r requirements.txt

cp .env.example .env      # Set MySQL credentials and a fixed random SECRET_KEY
# Create the MySQL database:
#   CREATE DATABASE cv_python_tigerpro DEFAULT CHARSET utf8mb4;

python app.py             # http://127.0.0.1:5001 (creates tables and seeds on startup)
```

Responses use `{ code, message, data }`, with `code=0` for success. Send `Authorization: Bearer <token>` in requests.

| Module | Route | Purpose |
|---|---|---|
| Auth | `POST /api/auth/login` | Sign in; returns `{token}` |
| Auth | `POST /api/auth/register` | Register with the common role by default |
| Auth | `GET /api/auth/info` | Current user, role identifiers, and permission identifiers |
| Auth | `GET /api/auth/routers` | Menu tree visible to the current user |
| Auth | `POST /api/auth/logout` | Sign out |
| Users | `/api/system/user` | GET list (data scope) / POST / PUT / DELETE |
| Roles | `/api/system/role` | CRUD, menu grants, `data_scope` |
| Departments | `/api/system/dept` | Tree and CRUD |
| Posts | `/api/system/job` | CRUD |
| Menus | `/api/system/menu` | Tree and CRUD |
| Model scenarios | `/api/ai/model-scenarios` | Phase-one list, detail, and multipart inference |
| Faces | `/api/ai/face` | Gallery CRUD, enroll, recognize |
| Person ReID | `/api/ai/reid` | Gallery CRUD, enroll, recognize, search, search-video |
| Health | `GET /api/health` | Health check |

The `@permission_required("system:user:add")` decorator checks functional permission; `apply_user_data_scope()` filters by the role's `data_scope`.

## Frontends

The repository has two frontend applications; see the [frontend overview](frontend/README.md).

| Directory | Role | Development URL |
|---|---|---|
| [`frontend/frontend_home`](frontend/frontend_home) | Public project portal and entry point | http://localhost:5174 |
| [`frontend/frontend_admin`](frontend/frontend_admin) | Admin console | http://localhost:5173 |

### Portal: `frontend_home`

```bash
cd frontend/frontend_home
npm install
npm run dev              # http://localhost:5174
```

- Public `/api/portal/summary` and `/api/health` requests use a Vite proxy to `:5001`.
- Portal calls to action open the target page when signed in; otherwise they use `/login?redirect=`. Use `localhost` consistently.
- The console writes `localStorage` and the `tiger_ai_token` cookie; the portal can read login state across local ports.

### Console: `frontend_admin`

```bash
cd frontend/frontend_admin
npm install
npm run dev              # http://localhost:5173
```

Vite proxies `/api` to `http://127.0.0.1:5001`.

- After login, guards call `getInfo` and `getRouters` to build RBAC navigation and permission identifiers.
- Button permissions use `v-permission="'system:user:add'"`.
- The top-bar **Project Portal** link uses `VITE_PORTAL_URL` (default: http://localhost:5174).
- Portal deep links are supported, for example `/login?redirect=/ai/fall`.
- Pages cover login, dashboard, AI tasks, and system management (users, roles, departments, posts, menus).

## Documentation

> The repository currently tracks only `docs/community/`. Other `docs/` links below refer to local materials and may not open on GitHub. They remain listed to preserve the original README content.

| Guide | Scope |
|---|---|
| [Investor pitch](docs/investor-pitch.md) | Full module positioning, market, and pitch script for VCs |
| [Deployment overview](docs/deploy/README.md) | Local, Linux, and experimental Docker paths |
| [Local development](docs/deploy/local.md) | Windows, macOS, and Linux setup |
| [Linux production](docs/deploy/linux.md) | Ubuntu / Debian / CentOS / RHEL setup and operations |
| [Docker deployment](docs/deploy/docker.md) | Experimental Compose setup |
| [Supervision usage](docs/supervision-usage.md) | `supervision.Detections` and Annotator in the RF-DETR path |
| [Frontend overview](frontend/README.md) | Portal and admin console |
| [Badminton analysis](docs/badminton-analysis.md) | Stack, pose/ball models, court/net, HUD, API, and [§11 Roboflow export/training guide](docs/badminton-analysis.md#11-附录roboflow-导出-yolo11--yolov8-zip-与平台自训指南) |
| [Image/video segmentation](docs/image-segmentation.md) | RF-DETR-Seg, YOLOE, MobileSAM, weights, API, and workflow |
| [Data annotation](docs/数据标注功能说明.md) | Video frames, Canvas labels, YOLO datasets, APIs, and FAQ |
| [External annotation tools](docs/外接标注工具操作说明.md) | X-AnyLabeling, CVAT, Roboflow, and dataset import |
| [Pose model selection](docs/姿态估计模型选型说明.md) | Seven pose models and a badminton quick reference |
| [Annotation quality and conversion](docs/数据标注质量检测与格式转换.md) | Metrics, five format conversions, and pretraining checks |
| [Tiger AI model frameworks and types](docs/TigerAI平台模型框架与类型汇总.md) | Inference frameworks, task types, seed models, and workbenches |
| [Face recognition](docs/face-recognition.md) | InsightFace, YuNet+SFace, video, landmarks, gallery, API |
| [Face recognition overview](docs/人脸识别功能汇总.md) | Model selection and implementation summary |
| [Person ReID](docs/person-reid.md) | Youtu ReID, gallery, permissions, face fusion, detector priority, API |
| [Cross-camera MTMC](docs/mtmc-cross-camera-reid.md) | Shared streams, ReID, vehicle/plate fusion, global IDs, monitoring overlay |
| [EMQX / MQTT scenarios](docs/emqx-mqtt-usage-scenarios.md) | Potential alert, MTMC, and absence uses; not yet merged |
| [Edge AI pipeline feasibility](docs/edge-ai-video-pipeline-engine.md) | ONNX, visual pipeline, RTSP, detection, VLM, MTMC, alerts, MQTT/Webhook, phases 0–3 |
| [Recent feature overview](docs/articles/平台近期新增功能说明.md) | MTMC, falls, gestures, portal, RTSP, and model management |
| [Windows screen RTSP](docs/camera-screen-rtsp.md) | Desktop streaming into camera management and monitoring |
| [OpenCV Zoo models](docs/opencv-zoo-models.md) | EfficientSAM, LaMa, MobileNet, face/person index |
| [Open API examples](backend/docs/openapi_examples.md) | Scenario list/detail, multipart inference, readiness, errors |
| [Table recognition](docs/表格识别功能汇总.md) | YOLO detection, RapidOCR, SLANet_plus, model/API/UI/code |
| [Tracking scenario classification](docs/目标追踪-场景分类说明.md) | General, vehicle, and absence tracking architecture |
| [Absence detection](docs/人员离岗检测-功能说明.md) | Multi-station rules, camera motion compensation, API, acceptance |
| [Vehicle tracking](docs/车辆追踪-技术说明与操作手册.md) | Plate OCR, speed, congestion, trajectories, passage records |
| [Detection alerts](docs/detection-alerts.md) | Smoke/fire/crowd and PPE/line-crossing rules and events |
| [Monitoring wall and unknown-face alerts](docs/p2-监控墙与陌生人脸告警.md) | 24/7 RTSP wall and unknown-face alert workflow |
| [Smoke/fire and crowd alerts](docs/烟火与人员聚集告警功能汇总.md) | Models, thresholds, overlays, events, image placeholders |
| [Line crossing alerts](docs/越线入侵告警功能汇总.md) | Geometry, rule engine, tracking UI, configuration |

> Some documentation retains **measured screenshot placeholders**. Add chapter screenshots under `docs/images/` before replacing them.

## Startup order

1. Start MySQL and create `cv_python_tigerpro`.
2. Start the backend with `python app.py` (`:5001`; creates tables and seeds data).
3. Start the console: `cd frontend/frontend_admin && npm run dev` → http://localhost:5173.
4. Start the portal: `cd frontend/frontend_home && npm run dev` → http://localhost:5174. Open the portal, choose **Enter Console**, and sign in with `admin` and the initial password.

|  |  |  |
| :---: | :---: | :---: |
| <img src="https://github.com/user-attachments/assets/90d8bbee-e9f1-4e73-a5fe-0e1389ef9769" alt="744ec6c19b3817d1e7c1efe5d66124e7" width="300" /> | <img src="https://github.com/user-attachments/assets/9a0850dd-1607-4b8a-8385-05c62ac37859" alt="243ec0a85149c5fc2c79168466bfd19d" width="300" /> | <img src="https://github.com/user-attachments/assets/a1c939e0-3f35-47df-b878-dfb85e095821" alt="a894ca39be5586d2f9bcc7a587404d4d" width="300" /> |

## Contributing

GitHub is the final record for project work and decisions. The workflow is:

**Discussion → Issue (with acceptance criteria) → Claim → PR → Review → Squash merge → CHANGELOG / release**

| Document | Purpose |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, conventions, branches, PRs |
| [Deployment guide](docs/deploy/README.md) | Local, Linux, Docker |
| [GOVERNANCE.md](GOVERNANCE.md) | Roles, permissions, promotion, decisions |
| [ROADMAP.md](ROADMAP.md) | Version planning |
| [SECURITY.md](SECURITY.md) | **Report security issues privately, not through public issues** |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Conduct standards |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Dependencies and model licenses |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [Eight good-first-issues](docs/community/good-first-issues.md) | Beginner-friendly tasks |
| [Community index](docs/community/README.md) | Community documentation |

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=5758703/CV_PythonVue_TigerPro&type=Date)](https://star-history.com/#5758703/CV_PythonVue_TigerPro&Date)

Open source takes time and care. Donations are welcome.

|  |  |
| :---: | :---: |
| <img src="https://github.com/user-attachments/assets/797c35ba-a7fd-434f-841e-4de19fac4f1a" alt="f0afa6f30ce5b11d3bc0b17c42ab5c9a" width="160" /> | <img src="https://github.com/user-attachments/assets/077e8228-f416-4d44-8c47-c6976788af07" alt="5ea44947061de1d34f2c713fb8ce5ce8" width="160" /> |
