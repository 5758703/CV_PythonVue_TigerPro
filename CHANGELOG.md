# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 精神，版本号尽量采用语义化版本（现阶段为 `0.x`）。

格式：每个版本记录 **新增 / 变更 / 修复 / 文档 / 破坏性变更**。

---

## [Unreleased]

### 新增

- **人员离岗检测**（目标追踪场景页签）：YOLO+ByteTrack 检人 → InsightFace/FAISS 识人，整帧/单工位/多工位模式，每工位独立名单与离岗计时/告警，事件 CSV 导出
- **离岗镜头运动补偿**：手持/移动镜头视频下工位钉在画面内容上（背景光流全局仿射 + `refSec` 参考帧，`services/camera_motion.py`）；新增 `/api/ai/absence/motion-profile` 接口供前端画布同步补偿；工位被摇出画面（可见面积 <30%）自动按断流规则暂停计时
- 离岗绘制工位交互：左视频预览 + 右冻结底图画布分离，左侧叠加层实时显示工位随真实桌位移动
- 社区协作文件：`CONTRIBUTING.md`、`GOVERNANCE.md`、`ROADMAP.md`、`SECURITY.md`、`CODE_OF_CONDUCT.md`、`THIRD_PARTY_NOTICES.md`
- GitHub Issue / PR 模板、`CODEOWNERS`、标签说明与新手任务清单

### 修复

- 离岗视频任务的离岗计时改按**视频时间轴**（帧号/fps）推进，不再把处理耗时算进离岗时长（4 秒视频误报 180+ 秒）
- 离岗视频任务结果补充每工位状态 `stats.zones`，前端工位标签正常显示

### 文档

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
