# 路线图（ROADMAP）

> 本文是**方向规划**，不是合同。具体任务以 GitHub Issue 为准；认领与验收走 [CONTRIBUTING.md](./CONTRIBUTING.md) 流程。  
> 更新日期：2026-08-10

仓库：https://github.com/5758703/CV_PythonVue_TigerPro

---

## 当前定位（v0.x）

Flask + Vue3 的 **多任务视觉 / 语音 AI 管理平台**：项目门户（`frontend_home`）+ 管理控制台（`frontend_admin`）、模型管理、RBAC、检测/姿态/分割、人脸 1:N、行人重识别、车辆追踪、OCR/表格、羽毛球分析、训练与告警等。优先保证 **CPU 可跑、可部署、可贡献**。

---

## 版本规划

### v0.2 — 社区与可贡献性（进行中）

| 目标 | 状态 | 说明 |
|------|------|------|
| 社区协作文件齐全 | 进行中 | CONTRIBUTING / GOVERNANCE / SECURITY 等 |
| Issue / PR 模板与标签 | 进行中 | `.github/` |
| Good first issues 清单 | 进行中 | [docs/community/good-first-issues.md](./docs/community/good-first-issues.md) |
| README 快速开始前置 | 待认领 | 截图可保留，但启动步骤需更清晰 |

### v0.3 — 部署体验

| 目标 | 状态 | 建议标签 |
|------|------|----------|
| Docker / Compose 一键启动（backend + frontend_home + frontend_admin + mysql） | 进行中（实验性骨架见 `deploy/`） | `devops` `feature` `help-wanted` |
| 部署文档（本地 / Linux / Docker） | 进行中 | `docs` `devops` |
| CI：lint + 基础 import/冒烟 | 待认领 | `devops` `enhancement` |
| Windows / Linux 部署文档对齐 | 待认领 | `docs` `devops` |
| 健康检查与就绪探针接口 | 待认领 | `backend` `devops` |

### v0.4 — 平台稳定性

| 目标 | 状态 | 建议标签 |
|------|------|----------|
| 推理任务超时/取消/队列可视化增强 | 规划 | `ai` `backend` `advanced` |
| OpenVINO 热路径文档与羽毛球 YOLO 对齐 | 规划 | `ai` `enhancement` |
| 前端关键页错误态与空态统一 | 规划 | `frontend` `enhancement` |
| 数据库迁移策略文档化 | 规划 | `database` `docs` |

### v0.5 — 能力增强（可选）

| 目标 | 状态 | 说明 |
|------|------|------|
| 人脸服务可拆分部署文档（独立 API 形态） | 规划 | 非必须改架构，先文档与边界 |
| 车辆追踪评测集与回归脚本 | 规划 | `ai` `advanced` |
| 活体检测 / 1:1 比对 | 远期 | 需单独 RFC |
| 多维护者共治修订 GOVERNANCE | 视社区情况 | — |

---

## 可认领任务入口

1. 浏览带 [`good-first-issue`](https://github.com/5758703/CV_PythonVue_TigerPro/issues?q=is%3Aissue+is%3Aopen+label%3Agood-first-issue) 的 Issue  
2. 或从 [新手任务文案](./docs/community/good-first-issues.md) 复制后按流程开 Issue 并认领  
3. 更大任务标 `help-wanted` / `advanced`，先 Discussion 再开发  

### 欢迎优先认领的方向

- Docker / CI / 部署文档（`devops`）
- 贡献指南落地与中英文 README 精简（`docs`）
- 前端无障碍与表单校验小改进（`frontend`）
- 后端接口错误信息一致性（`backend`）
- 模型种子与 THIRD_PARTY 许可证补全（`ai` `docs`）

---

## 非目标（短期不做）

- 重写为其他语言/框架
- 绑定单一云厂商专有服务
- 在未讨论的情况下引入沉重新中间件
- 公开仓库中提交真实生产数据或人脸隐私数据

---

## 如何影响路线图

1. 在 Discussions 提出想法  
2. 维护者确认后建 Issue，并视情况挂到 Milestone（`v0.3` 等）  
3. 合并足够多相关 PR 后，在发版说明中关闭对应里程碑  

提案被推迟或拒绝时，会在 Issue 中写明原因（范围/优先级/维护成本）。
