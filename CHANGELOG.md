# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 精神，版本号尽量采用语义化版本（现阶段为 `0.x`）。

格式：每个版本记录 **新增 / 变更 / 修复 / 文档 / 破坏性变更**。

---

## [Unreleased]

### 新增

- **双前端架构**：`frontend/frontend_home` 项目门户（:5174）+ `frontend/frontend_admin` 管理控制台（:5173）；公开接口 `GET /api/portal/summary`；门户按 Cookie `tiger_ai_token` 判断登录态跳转；控制台顶栏「项目门户」入口
- **行人重识别（Youtu ReID）**：OpenCV Zoo `opencv-person-reid-youtu`；独立权限 `ai:reid:*` 与表 `reid_person` / `reid_embedding(modality=appearance)`；实时「像谁/未知」、底库 Top-K、录像片段检索；可选混合近距人脸；行人检测默认优先级 `yolo26n` → `winedarksea-yolo26n_person` → `simoswish-PersonDetector_YOLO26_PRW`
- **OpenCV YuNet+SFace 人脸后端**：与 InsightFace 并列；本地视频源；YuNet 五色关键点叠加
- **LaMa 图像修复**（`inpainting-lama` / `/ai/inpaint`）：涂抹遮罩 + 外扩；DNN→ORT 回退
- **EfficientSAM 交互分割**（`efficient-sam`）：点选/框选；OpenCV DNN
- **MobileNet V2 分类**（`mobilenet-v2`）：ImageNet-1000 + 中文标签；实时分类页
- **人员离岗检测**（目标追踪场景页签）：YOLO+ByteTrack 检人 → InsightFace/FAISS 识人，整帧/单工位/多工位模式，每工位独立名单与离岗计时/告警，事件 CSV 导出
- **离岗镜头运动补偿**：手持/移动镜头视频下工位钉在画面内容上（背景光流全局仿射 + `refSec` 参考帧，`services/camera_motion.py`）；新增 `/api/ai/absence/motion-profile` 接口供前端画布同步补偿；工位被摇出画面（可见面积 <30%）自动按断流规则暂停计时
- 离岗绘制工位交互：左视频预览 + 右冻结底图画布分离，左侧叠加层实时显示工位随真实桌位移动
- YOLO 推理 **ONNX 优先加载**：权重目录存在同名 `.onnx`（如脑肿瘤 `best.pt`/`best.onnx`）时优先用 ONNX Runtime 推理，免去 472MB PyTorch 权重反序列化与 OpenVINO 重复导出尝试；`YOLO_PREFER_ONNX=0` 可关闭
- 新增 **手势识别页面（手部 21 关键点 + 手指动态识别数字）**：集成 HuggingFace `opencv/handpose_estimation_mediapipe` 与配套 `opencv/palm_detection_mediapipe`（OpenCV Zoo MediaPipe 双模型，cv2.dnn CPU 推理 24–37ms/帧）；本地摄像头实时/图片两种模式，逐指彩色骨架叠加，角度法数伸直手指出数字（0-5/手，双手至 10），数字稳定约 1 秒自动记入**动态数字序列**（可复制/清空/语音播报）；新增菜单「视觉识别→手势识别」（`ai:handpose:list`）、接口 `POST /api/ai/handpose/estimate`、新模块 `services/handpose.py`（前后处理移植自 opencv_zoo，SSD anchors 程序生成并逐值核对）
- 集成 **鱼类检测模型**（HuggingFace `akridge/yolo11-fish-detector-grayscale`）：水下灰度影像 fish 单类检测（YOLO11n），分类「海洋-鱼类检测」，本地同时落盘 pt + onnx 双权重，推理自动走 ONNX Runtime
- 集成 **安防检测器模型包（11 个本地 ONNX）**：烟火×3（含 88 类碰撞/灾害扩展）、PPE/安全帽×2、跌倒/行为×2、打架×2、武器（枪/刀）、车牌，统一分类「安防检测」种子登记（`sec-*`，幂等绑定权重），全部经 ONNX Runtime CPU 推理，可在图片/视频/摄像头检测及告警规则中选用；原包「跌倒检测 YOLOv12m」实测为 COCO80 通用模型，已如实标注
- 模型管理 **权重格式转换（pt → onnx）**：列表新增「转换」对话框，展示 pt/onnx 权重明细并支持分别下载；异步导出（imgsz / dynamic / half 可配，Ultralytics export + simplify），完成后检测自动走 ONNX Runtime；接口 `weight-info` / `convert-weight` / `convert-progress`、下载支持 `?ext=pt|onnx`（onnx → pt 因 ONNX 为冻结推理图不支持还原，界面已说明）
- 社区协作文件：`CONTRIBUTING.md`、`GOVERNANCE.md`、`ROADMAP.md`、`SECURITY.md`、`CODE_OF_CONDUCT.md`、`THIRD_PARTY_NOTICES.md`
- GitHub Issue / PR 模板、`CODEOWNERS`、标签说明与新手任务清单

### 修复

- 离岗视频任务的离岗计时改按**视频时间轴**（帧号/fps）推进，不再把处理耗时算进离岗时长（4 秒视频误报 180+ 秒）
- 离岗视频任务结果补充每工位状态 `stats.zones`，前端工位标签正常显示
- LaMa 遮罩：避免 PNG 全不透明 alpha 被误当作整图遮罩；支持 dilate 外扩

### 文档

- 更新双前端说明：根 `README.md`、`frontend/README.md`、`frontend_home` / `frontend_admin` README、`backend/README.md`、`CONTRIBUTING.md`、`GOVERNANCE.md`、`THIRD_PARTY_NOTICES.md`
- 新增 `docs/person-reid.md`、`docs/opencv-zoo-models.md`；更新 `docs/face-recognition.md` / `docs/人脸识别功能汇总.md`
- 更新 `README.md` 功能列表与文档索引、`THIRD_PARTY_NOTICES.md` OpenCV Zoo 条目
- 更新 `人员离岗检测-功能说明.md` / `目标追踪-场景分类说明.md` / `README.md`：镜头运动补偿原理、接口与验收清单
- 统一贡献流程：Discussion → Issue → 认领 → PR → Squash 合并 → CHANGELOG / 发版

---

## [0.1.0] - 2026-07-01

### 新增

- Flask + Vue3 RBAC 与多任务 AI 平台能力基线（检测 / 姿态 / 分割 / 人脸 / 车辆 / OCR / 语音等）
- Apache License 2.0

> 注：`0.1.0` 日期为占位，用于开启变更日志；精确历史以 Git 记录为准。

---

[Unreleased]: https://github.com/5758703/CV_PythonVue_TigerPro/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/5758703/CV_PythonVue_TigerPro/releases/tag/v0.1.0
