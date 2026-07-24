# 项目治理（GOVERNANCE）

本文描述 **CV Python Vue TigerPro** 的角色、权限、晋升与决策机制。  
治理目标：在单人维护起步阶段保持决策清晰，同时让贡献者有可预期的参与路径。

相关文档：[CONTRIBUTING.md](./CONTRIBUTING.md) · [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) · [ROADMAP.md](./ROADMAP.md)

---

## 1. 治理模型

采用 **Maintainer 决策制（BDFL-lite）**：

- **日常技术决策**：Maintainer 与相关 Module Owner 协商，Maintainer 最终拍板
- **任务与结论**：必须以 GitHub Issue / Discussion / PR 为最终记录
- **重大变更**：先 RFC 式 Discussion 或 Issue，收集意见后再实施

当前阶段不设立董事会/基金会。社区成熟后可修订本文，引入多维护者共治。

---

## 2. 角色与权限

| 角色 | 谁 | 权限 | 责任 |
|------|----|------|------|
| **Maintainer** | 仓库所有者（现为 [@5758703](https://github.com/5758703)） | `admin`：合并 `main`、发版、改保护分支、加人 | 路线图、安全响应、最终合并、发布 |
| **Module Owner** | 经晋升的核心贡献者 | 对负责目录有 Review 优先权；可获 `write` 或保持 `triage`+强制评审 | 该模块 Issue 分诊、验收标准、PR Review |
| **Collaborator（Triage）** | 活跃贡献者 | 管理 Issue/PR 标签与里程碑，无强制合并权 | 分诊、复现、引导新人 |
| **Contributor** | 任意提交 PR 或反馈的人 | Fork + PR | 按 CONTRIBUTING 流程贡献 |
| **用户 / 报告者** | 使用与反馈者 | 开 Issue/Discussion | 提供可复现信息 |

GitHub 权限对照：

- Maintainer → Owner / Admin
- Module Owner → 通常 Write（或保持 Triage，由 CODEOWNERS 强制 Review）
- Collaborator → Triage
- 其他人 → 通过 Fork 贡献

目录评审人见 [`.github/CODEOWNERS`](./.github/CODEOWNERS)。

---

## 3. 模块划分（Module）

| 模块 | 典型路径 | 说明 |
|------|----------|------|
| `backend` | `backend/routes/`, `backend/models/`, `backend/services/`（非 AI 专属） | API、RBAC、业务服务 |
| `frontend` | `frontend/src/` | Vue 页面与交互 |
| `ai` | `backend/inference.py`, `backend/services/*track*`, face/badminton 等, `backend/seed.py` 模型段 | 推理与模型 |
| `devops` | `backend/scripts/`, CI、Docker（规划中）、部署文档 | 环境与发布 |
| `database` | `backend/models/`, 迁移/种子 | 数据模型 |
| `docs` | `docs/`, 根目录 `*.md` | 文档与社区 |

一个 PR 可跨模块；跨模块时需对应 Owner 或 Maintainer 评审。

---

## 4. 晋升机制

### 4.1 Contributor → Collaborator（Triage）

满足多数条件，由 Maintainer 邀请：

- 合并 **≥ 3** 个有质量的 PR，或高质量复现/分诊 **≥ 10** 个 Issue
- 遵守行为准则与贡献流程
- 愿意持续参与至少 1–2 个月

### 4.2 Collaborator → Module Owner

- 在某模块持续贡献，合并 **≥ 5** 个该模块 PR，或主导完成 1 个里程碑级功能
- 能独立写清验收标准并做建设性 Review
- Maintainer 在 Issue/Discussion 中公示提名，**观察期 7 天**无原则反对后任命
- 更新 `CODEOWNERS` 与本文件「现任名单」

### 4.3 Module Owner → Maintainer（共维护）

- 长期负责发布与安全响应
- 经现有 Maintainer 同意，并可签署必要的仓库权限移交说明
- 单人阶段不强制增设；出现稳定共维护者后再修订

### 4.4 卸任与暂停

- 可主动申请卸任；超过 **90 天**无实质参与，Maintainer 可调整权限并更新 CODEOWNERS
- 违反行为准则：立即暂停权限，按 CODE_OF_CONDUCT 处理

---

## 5. 决策机制

| 议题类型 | 流程 | 决策者 |
|----------|------|--------|
| 拼写/文档/小修复 | 直接 PR | Maintainer 合并 |
| 功能/增强 | Discussion → Issue → PR | Maintainer（参考 Owner） |
| 架构/换依赖/破坏性变更 | Discussion（RFC）≥ 5 天 → Issue → PR | Maintainer |
| 安全漏洞 | 私密渠道（见 SECURITY.md） | Maintainer |
| 许可证变更 | 公开 Discussion ≥ 14 天 | Maintainer（须极度谨慎） |
| 商业合作/商标 | 不在开源仓表决 | 项目所有者线下约定 |

**投票：** 当前不采用正式投票。若未来多 Maintainer，可采用「lazy consensus」：提案公示后 N 天无反对即通过。

**冲突升级：** Module Owner 之间意见不一致 → Maintainer 裁决 → 结果写回 Issue。

---

## 6. 发布与版本

- 版本号建议语义化：`MAJOR.MINOR.PATCH`（现阶段 `0.x` 允许破坏性变更，但须在 CHANGELOG 标明）
- 合并到 `main` 后，由 Maintainer：
  1. 更新 `CHANGELOG.md`
  2. 打 tag（如 `v0.3.0`）
  3. 可选：GitHub Release 附摘要与升级注意
- 发版说明须列出：新功能、修复、破坏性变更、致谢贡献者

---

## 7. 现任名单

| 角色 | 人员 | 模块 |
|------|------|------|
| Maintainer | [@5758703](https://github.com/5758703) | 全局 |
| Module Owner | （虚位以待） | — |
| Collaborator | （虚位以待） | — |

更新本表须通过 PR，并由 Maintainer 合并。

---

## 8. 修订本治理文件

对本文件的修改：

1. 开 Discussion 或 Issue 说明动机  
2. 提交 PR 修改 `GOVERNANCE.md`  
3. Maintainer 合并后即时生效  

---

*最后更新：2026-07-24*
