# 图片检测 AI 报告功能 — 设计文档

**日期：** 2026-06-24
**作者：** Claude (brainstorming)
**状态：** 待评审

## 1. 背景与目标

现有图片检测（`frontend/src/views/ai/image/index.vue` + `POST /ai/model/<mid>/detect`）只输出
目标框、类别、置信度、坐标。本功能在此基础上增加 **DeepSeek AI 对检测结果的深度分析**，
产出**正式检测报告**，挖掘检测数据深层信息，提升解读效率。

报告核心：**AI 智能建议** —— 基于案例库的智能处理建议生成，流程为
**关键词提取 → 相似案例搜索 → 建议生成**。

非目标（YAGNI）：不改动现有检测推理；不做报告历史持久化/数据库存储；不做案例库在线 CRUD
（本期案例库为内置 JSON）。

## 2. 总体流程

```
现有检测(不变)
  → 用户点「生成AI检测报告」
  → 前端把已有检测结果 POST 给后端 /ai/model/<mid>/analyze-report
  → 后端: 聚合统计 → 关键词提取 → 案例库相似搜索(Top-N) → 拼 prompt 调 DeepSeek
  → 返回结构化报告 JSON
  → 前端页内渲染报告
  → 「下载PDF」(html2canvas + jsPDF)
```

检测本身不变、仍快。AI 报告为**独立按钮、按需触发**，不拖慢检测主流程。

## 3. 后端设计

### 3.1 新增模块

**`backend/deepseek.py` — DeepSeek 客户端**
- OpenAI 兼容接口：`POST https://api.deepseek.com/chat/completions`，模型 `deepseek-chat`。
- HTTP 用 `requests`。请求设 `response_format={"type":"json_object"}`，强制返回 JSON。
- API key 从 `config.py` 读（env `DEEPSEEK_API_KEY`，默认值兜底为给定 key）。
- 超时 60s。失败抛异常，由 `report.py` 捕获降级。
- 暴露：`chat_json(system_prompt, user_prompt) -> dict`。

**`backend/case_library.py` — 案例库 + 检索**
- 内置案例库为 `case_library.py` 内的模块级常量（Python list），**按分类管理**。
  本期两个分类：`生产安全风险识别`、`通用`。
- 每条案例字段：
  ```
  { "id", "category", "title", "scene",
    "keywords": [...], "match_classes": [...],
    "risk_level": "高|中|低", "suggestion": "处理建议正文" }
  ```
- `extract_keywords(detections, model_category) -> list[str]`：
  从检测类别名、数量分布、模型分类聚合关键词（去重、归一）。
- `search_cases(keywords, classes, top_n=3) -> list[case]`：
  对每条案例打分 = 关键词命中数×权重 + match_classes 命中数×权重；
  取分>0 的 Top-N；全 0 时回退到 `通用` 分类的兜底案例。

**`backend/report.py` — 报告编排**
- `build_report(model, detections, width, height, conf, image_name) -> dict`：
  1. 聚合统计：类别计数、平均/最高置信度、目标总数。
  2. `keywords = extract_keywords(...)`。
  3. `cases = search_cases(keywords, classes)`。
  4. 构造 system + user prompt（含统计摘要 + 命中案例），调 `deepseek.chat_json`。
  5. 组装并返回报告 dict（见 §4）。
  6. DeepSeek 失败 → 降级（见 §5）。

### 3.2 新路由

`POST /ai/model/<int:mid>/analyze-report`，权限 `ai:model:query`（与 detect 一致）。
- 请求体（JSON）：`{ detections, width, height, count, imageName, conf }`
  —— 即前端已持有的检测结果，**不重跑推理**。
- 用 `mid` 查 `AiModel` 取 `modelName` / `category` 做报告抬头。
- 响应：`{ code:0, message, data: <报告JSON> }`。

## 4. 报告结构（响应 data）

```json
{
  "meta": {
    "modelName": "...", "category": "...",
    "imageName": "...", "generatedAt": "2026-06-24 12:00:00",
    "conf": 0.25, "aiAvailable": true
  },
  "stats": {
    "total": 7,
    "byClass": [{ "className": "person", "count": 3, "avgConf": 0.82 }],
    "maxConf": 0.95
  },
  "summary": "概述文本",
  "risk": { "level": "高|中|低", "desc": "风险评估说明" },
  "findings": [{ "className": "...", "note": "逐目标/逐类发现" }],
  "suggestions": [{ "title": "...", "detail": "AI 智能建议正文" }],
  "matchedCases": [{ "id", "title", "category", "risk_level" }],
  "keywords": ["..."],
  "conclusion": "结论文本",
  "warning": null
}
```

DeepSeek 被要求只生成 `summary / risk / findings / suggestions / conclusion`
五个字段（JSON）；`stats / matchedCases / keywords / meta` 由后端本地填充。

## 5. 容错与降级

DeepSeek 调用可能失败（网络/超时/key/限流）。原则：**报告始终可用**。

- DeepSeek 失败 → 仍返回报告：`meta.aiAvailable=false`，`warning` 填提示语；
  `summary / suggestions / conclusion` 用**案例库内容兜底**（直接取命中案例的
  `suggestion` 作为建议条目，risk 取命中案例最高等级）。
- 关键词提取 + 案例搜索为纯本地逻辑，永远成功。
- 后端 `try/except` 包住 DeepSeek，超时 60s。
- 案例库空匹配 → 回退 `通用` 分类兜底案例，不报错。
- 路由层 `try/except` 兜底返回 500 + 友好信息（与现有 detect 风格一致）。

## 6. 前端设计

### 6.1 `image/index.vue` 改动
- 检测完成（`result` 非空）后，结果区下方新增按钮「生成AI检测报告」+ 独立 loading 态
  `reporting`。
- 新增报告卡片（`v-if="report"`）：
  - 抬头：模型名 / 分类 / 图名 / 生成时间 / 置信度阈值。
  - 缩略：原图 + 检测结果图（复用 `previewSrc` / `resultSrc`）。
  - 概述段。
  - 风险评估：`el-tag`（高=danger / 中=warning / 低=success）+ 说明。
  - 逐目标发现：`el-table` 或列表。
  - AI 智能建议：编号列表（title + detail）。
  - 匹配案例：`el-tag` 列表（标题 + 分类 + 风险等级）。
  - 关键词：`el-tag` 列表。
  - 结论段。
  - `aiAvailable=false` 时顶部显示 `el-alert` 警告（AI 不可用、已用案例库兜底）。
- 「下载PDF」按钮：`html2canvas` 截报告卡片 DOM → `jsPDF` 拼成 A4 PDF
  （图像式，中文无忧；文字不可选，已接受）。多页时按高度分页。

### 6.2 `api/ai.js`
新增：
```js
analyzeReport: (id, payload) =>
  request.post(`/ai/model/${id}/analyze-report`, payload, { timeout: 0 })
```

## 7. 依赖变更

- 后端 `requirements.txt`：`+ requests`（DeepSeek HTTP）。
- 前端 `package.json`：`+ jspdf`、`+ html2canvas`（PDF 导出）。

## 8. 安全

- DeepSeek API key 存 `config.py` 经 env `DEEPSEEK_API_KEY` 读取，**绝不进前端、绝不硬编码到
  组件**。`config.py` 默认值仅作本地兜底；建议部署用 `.env`。
- key 仅在后端服务进程内使用，前端只见报告结果。

## 9. 验收标准

1. 完成图片检测后出现「生成AI检测报告」按钮。
2. 点击后生成含概述/风险/发现/AI建议/匹配案例/结论的页内报告。
3. AI 建议确实来自「关键词提取 → 案例库相似搜索 → DeepSeek 生成」链路。
4. 案例库按 `生产安全风险识别` / `通用` 两分类组织。
5. DeepSeek 不可用时仍出报告（案例库兜底 + 警告）。
6. 「下载PDF」导出中文正常的报告 PDF。
