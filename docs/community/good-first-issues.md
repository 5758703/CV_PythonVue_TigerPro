# Good First Issues（8 条可公开文案）

将下列条目复制为 GitHub Issue（推荐用对应模板），并打上标签：  
`good-first-issue` + `ready` + 类型/模块 + 建议优先级 `P2` 或 `P3`。

认领方式：在 Issue 评论「我来认领」，维护者 Assignees 后改标签 `in-progress`。

协作总流程见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。

---

## GFI-01 · 精简 README「快速开始」区块

**建议标签：** `docs` `good-first-issue` `ready` `P2`

**背景和目标：**  
根 README 截图/视频较多，新人不易快速找到环境准备与启动命令。希望在文首增加简洁的「快速开始」，并把社区文档链接放在显眼位置。

**涉及模块：** docs  

**预期结果：**  
- README 顶部 30 秒内能看到：克隆 → 后端 → 门户/控制台 → 默认账号  
- 明确双前端路径：`frontend/frontend_home`（:5174）与 `frontend/frontend_admin`（:5173）  
- 增加指向 `CONTRIBUTING.md` / `ROADMAP.md` / `SECURITY.md` / `THIRD_PARTY_NOTICES.md` 的链接区  

**验收标准：**  
- [ ] 「快速开始」命令在干净机器上可跟随（或明确前置依赖）  
- [ ] 社区文档链接全部有效  
- [ ] 不删除现有演示素材，可后置到「演示」章节  

**是否需要测试和文档：** 需按文档冒烟一遍；属文档变更。  
**是否已有人员认领：** 无人认领  

---

## GFI-02 · 一键创建仓库标签脚本或文档落地

**建议标签：** `devops` `docs` `good-first-issue` `ready` `P2`

**背景和目标：**  
[`.github/LABELS.md`](../../.github/LABELS.md) 已定义标签，需在 GitHub 仓库实际创建，避免 Issue 无法打标。

**涉及模块：** devops, docs  

**预期结果：**  
- 使用 `gh label create …` 在本仓库创建全部约定标签；或提供 `scripts/create_github_labels.ps1` / `.sh`  
- 在 LABELS.md 注明「已在仓库生效」或执行方法  

**验收标准：**  
- [ ] `gh label list` 可见类型/模块/状态/优先级/难度标签  
- [ ] 文档与脚本任一路径可复现  

**是否需要测试和文档：** 需要（执行脚本验证）；更新 LABELS.md。  
**是否已有人员认领：** 无人认领  

---

## GFI-03 · backend `.env.example` 注释与 README 交叉引用

**建议标签：** `docs` `backend` `devops` `good-first-issue` `ready` `P3`

**背景和目标：**  
`.env.example` 已有多项配置（含 YOLO OpenVINO 等），希望每项有一行中文说明，并在 `backend/README.md` 增加「必填 vs 可选」小节表。

**涉及模块：** docs, backend, devops  

**预期结果：**  
- `.env.example` 关键配置有简短注释  
- `backend/README.md` 有配置速查表（数据库、JWT、YOLO_INFER_*、第三方 Key 等）  

**验收标准：**  
- [ ] 新贡献者只读这两处即可完成最小本地配置  
- [ ] 无真实密钥写入仓库  

**是否需要测试和文档：** 文档为主；可选按速查表启动一次后端。  
**是否已有人员认领：** 无人认领  

---

## GFI-04 · 前端 API 错误提示一致性小改进

**建议标签：** `frontend` `enhancement` `good-first-issue` `ready` `P2`

**背景和目标：**  
部分页面 catch 后只显示泛化「失败」；希望在 1–2 个高频页（如车辆追踪或模型列表）统一展示后端 `message`（若有）。

**涉及模块：** frontend（`frontend/frontend_admin`）  

**预期结果：**  
- 至少两个控制台页面的失败提示优先使用接口返回的 `message`  
- 不改变成功路径行为  

**验收标准：**  
- [ ] 故意触发错误（如未选模型）时提示可读  
- [ ] 无 eslint 新增错误  
- [ ] PR 注明改动的文件列表  

**是否需要测试和文档：** 需要手动冒烟；一般不改用户文档。  
**是否已有人员认领：** 无人认领  

---

## GFI-05 · 增加 `GET /api/health`（或等价）健康检查

**建议标签：** `backend` `devops` `feature` `good-first-issue` `ready` `P2`

**背景和目标：**  
部署与编排需要简单存活探针，避免只依赖首页 HTML。

**涉及模块：** backend, devops  

**预期结果：**  
- 提供无需登录（或明确约定）的健康检查接口，返回 JSON如 `{ "status": "ok" }`  
- 在 `backend/README.md` 记录路径与示例 curl  

**验收标准：**  
- [ ] 本地请求返回 200 与明确 JSON  
- [ ] 不在健康检查中执行重模型加载  
- [ ] README 有示例  

**是否需要测试和文档：** 需要；文档必须更新。  
**是否已有人员认领：** 无人认领  

---

## GFI-06 · Docker Compose 骨架（MySQL + backend + 双前端草案）

**建议标签：** `devops` `feature` `help-wanted` `good-first-issue` `ready` `P1`

**背景和目标：**  
降低新人环境成本。先提交**可讨论的 Compose 骨架**（即使尚非完美生产级），包含服务定义、卷、端口与 README 片段。

**涉及模块：** devops, docs  

**预期结果：**  
- 仓库根或 `deploy/` 下有 `docker-compose.yml` 草案  
- 服务至少覆盖：MySQL、backend、`frontend_admin`、`frontend_home`（或文档说明门户可后接）  
- `docs/deploy-docker.md` 说明已知限制（模型体积、CPU、首次拉权重等）  

**验收标准：**  
- [ ] `docker compose config` 通过  
- [ ] 文档写清「当前状态：实验性」与后续 Issue  
- [ ] 不把密钥写进镜像；使用 env 文件示例  

**是否需要测试和文档：** 需要；若本地无 Docker 需在 PR 说明只提交骨架。  
**是否已有人员认领：** 无人认领  

> 注：完整跑通可拆 follow-up Issue；本 GFI 接受「高质量骨架 + 文档」。

---

## GFI-07 · THIRD_PARTY_NOTICES 补全 3+ 条模型许可证链接

**建议标签：** `docs` `ai` `good-first-issue` `ready` `P3`

**背景和目标：**  
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) 表格需更精确的「许可证链接」列，减少商用误用风险。

**涉及模块：** docs, ai  

**预期结果：**  
- 至少为 3 个常用 `model_key` 补充可点击的上游许可/模型卡链接与一句话摘要  
- 若发现 AGPL/特殊条款，用加粗或「注意」标明  

**验收标准：**  
- [ ] 链接可打开  
- [ ] 与 `seed.py` 中 source 一致或已注明差异  
- [ ] PR 列出核对过的模型  

**是否需要测试和文档：** 纯文档；需人工打开链接核对。  
**是否已有人员认领：** 无人认领  

---

## GFI-08 · 为 CONTRIBUTING 流程增加简易示意图（Mermaid）

**建议标签：** `docs` `good-first-issue` `ready` `P3`

**背景和目标：**  
CONTRIBUTING 已有 ASCII 流程，希望增加 GitHub 可渲染的 Mermaid 图，降低理解成本。

**涉及模块：** docs  

**预期结果：**  
- 在 `CONTRIBUTING.md`「统一协作流程」节增加 Mermaid `flowchart`  
- 与现有文字步骤一致（Discussion → Issue → 认领 → PR → Squash → CHANGELOG）  

**验收标准：**  
- [ ] GitHub 网页预览可渲染  
- [ ] 未删减原有文字流程  
- [ ] 安全漏洞例外仍保留文字说明  

**是否需要测试和文档：** 文档；预览检查即可。  
**是否已有人员认领：** 无人认领  

---

## 维护者操作建议

创建上述 Issue 后：

1. 标题使用文案中的标题（可加 `[gfi]` 前缀）  
2. 正文粘贴「背景…认领」整段  
3. 标签：`good-first-issue` `ready` + 类型 + 模块 + 优先级  
4. 可挂 Milestone：`v0.2` 或 `v0.3`  
