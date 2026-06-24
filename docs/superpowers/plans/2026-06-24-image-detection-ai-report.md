# 图片检测 AI 报告功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 图片检测完成后，调 DeepSeek 对检测结果做深度分析，结合内置案例库（关键词提取→相似案例搜索→建议生成）产出正式检测报告，页内渲染并支持 PDF 导出。

**Architecture:** 后端新增三个纯模块（`case_library.py` 检索、`deepseek.py` 客户端、`report.py` 编排）+ 一个路由 `POST /ai/model/<mid>/analyze-report`，复用前端已持有的检测结果、不重跑推理。前端在 `image/index.vue` 新增报告区与 PDF 导出。DeepSeek 不可用时用案例库兜底，报告始终可用。

**Tech Stack:** 后端 Flask + requests（DeepSeek HTTP，OpenAI 兼容）+ pytest（新引入，仅测纯逻辑）。前端 Vue3 + Element Plus + jspdf + html2canvas。

## Global Constraints

- DeepSeek 接口：`POST https://api.deepseek.com/chat/completions`，模型 `deepseek-chat`，`response_format={"type":"json_object"}`，超时 60s。
- API key 经 env `DEEPSEEK_API_KEY` 读取，默认值兜底 ``。**绝不进前端、绝不硬编码到组件**。
- 案例库两分类：`生产安全风险识别`、`通用`。
- 报告 JSON 结构见 spec §4：`{meta, stats, summary, risk, findings, suggestions, matchedCases, keywords, conclusion, warning}`。
- 路由权限 `ai:model:query`，与现有 detect 一致。错误统一 `jsonify(code=..., message=...)`。
- 现有检测推理（`detect_image` / `/detect` 路由）**不得改动**。
- 输出语言：报告内容中文。
- 后端测试命令统一在 `backend/` 目录下运行 `python -m pytest`。

---

### Task 1: 案例库模块（检索逻辑，引入 pytest）

**Files:**
- Create: `backend/case_library.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_case_library.py`
- Modify: `backend/requirements.txt`（追加 `pytest`、`requests`）

**Interfaces:**
- Consumes: 检测结果 detection 列表，每项形如 `{"className": str, "confidence": float, "bbox": [x1,y1,x2,y2]}`。
- Produces:
  - `CASES: list[dict]` 每条 `{id:str, category:str, title:str, scene:str, keywords:list[str], match_classes:list[str], risk_level:str("高"|"中"|"低"), suggestion:str}`
  - `extract_keywords(detections: list[dict], model_category: str|None) -> list[str]`
  - `search_cases(keywords: list[str], classes: list[str], top_n: int = 3) -> list[dict]`

- [ ] **Step 1: 追加后端依赖**

修改 `backend/requirements.txt`，在文件末尾追加两行：

```
# DeepSeek AI 报告：HTTP 调用 + 纯逻辑单测
requests==2.32.3
pytest==8.3.3
```

- [ ] **Step 2: 写失败测试**

创建 `backend/tests/__init__.py`（空文件）。

创建 `backend/tests/test_case_library.py`：

```python
from case_library import extract_keywords, search_cases, CASES


def test_cases_have_two_categories():
    cats = {c["category"] for c in CASES}
    assert "生产安全风险识别" in cats
    assert "通用" in cats


def test_every_case_has_required_fields():
    for c in CASES:
        for f in ("id", "category", "title", "scene", "keywords",
                  "match_classes", "risk_level", "suggestion"):
            assert f in c, f"案例 {c.get('id')} 缺字段 {f}"
        assert c["risk_level"] in ("高", "中", "低")


def test_extract_keywords_from_detections():
    dets = [{"className": "person", "confidence": 0.9, "bbox": [0, 0, 1, 1]},
            {"className": "person", "confidence": 0.8, "bbox": [0, 0, 1, 1]},
            {"className": "helmet", "confidence": 0.7, "bbox": [0, 0, 1, 1]}]
    kws = extract_keywords(dets, "生产安全风险识别")
    assert "person" in kws
    assert "helmet" in kws
    # 去重：person 出现两次只保留一个
    assert kws.count("person") == 1
    # 模型分类作为关键词纳入
    assert "生产安全风险识别" in kws


def test_search_cases_matches_by_class():
    cases = search_cases(["person", "未戴安全帽"], ["person", "helmet"], top_n=3)
    assert len(cases) >= 1
    assert all("suggestion" in c for c in cases)


def test_search_cases_empty_match_falls_back_to_general():
    cases = search_cases(["完全不相关xyz"], ["不存在的类"], top_n=3)
    assert len(cases) >= 1
    assert all(c["category"] == "通用" for c in cases)
```

- [ ] **Step 3: 运行测试确认失败**

Run（在 `backend/` 目录）: `python -m pytest tests/test_case_library.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'case_library'`

- [ ] **Step 4: 实现 case_library.py**

创建 `backend/case_library.py`：

```python
"""检测结果案例库 + 关键词提取 + 相似案例检索。

纯本地逻辑、无外部依赖，供 report.py 在调用 DeepSeek 前组织上下文，
DeepSeek 不可用时也作为建议兜底来源。案例按分类管理。
"""

# 内置案例库（模块级常量）。两分类：生产安全风险识别 / 通用。
CASES = [
    {
        "id": "safety-no-helmet",
        "category": "生产安全风险识别",
        "title": "作业人员未佩戴安全帽",
        "scene": "工地/厂区检测到人员但缺少安全帽目标",
        "keywords": ["person", "人员", "未戴安全帽", "安全帽", "helmet"],
        "match_classes": ["person", "head", "no-helmet"],
        "risk_level": "高",
        "suggestion": "立即提醒未佩戴安全帽人员撤离危险区域并补戴；"
                      "在入口设置安全帽佩戴检查岗；将该点位纳入高频巡检。",
    },
    {
        "id": "safety-fire-smoke",
        "category": "生产安全风险识别",
        "title": "疑似烟雾/明火",
        "scene": "画面检测到 fire/smoke 类目标",
        "keywords": ["fire", "smoke", "明火", "烟雾", "火情"],
        "match_classes": ["fire", "smoke"],
        "risk_level": "高",
        "suggestion": "立即核实火情、就近取用灭火器并启动应急预案；"
                      "确认消防通道畅通；联动报警与现场断电。",
    },
    {
        "id": "safety-crowd",
        "category": "生产安全风险识别",
        "title": "人员聚集密度过高",
        "scene": "同一画面检测到大量 person 目标",
        "keywords": ["person", "人员", "聚集", "拥挤", "crowd"],
        "match_classes": ["person"],
        "risk_level": "中",
        "suggestion": "评估区域承载上限、做人流疏导与分流；"
                      "在密集时段增派现场管理人员；设置单向通行路线。",
    },
    {
        "id": "safety-vehicle-intrusion",
        "category": "生产安全风险识别",
        "title": "车辆进入人行/限行区域",
        "scene": "人车混行区域同时检测到 person 与车辆类目标",
        "keywords": ["car", "truck", "forklift", "车辆", "叉车", "人车混行"],
        "match_classes": ["car", "truck", "bus", "forklift"],
        "risk_level": "中",
        "suggestion": "设置人车物理隔离与限速标识；规划车辆专用通道；"
                      "在交叉点增设警示与减速带。",
    },
    {
        "id": "general-objects",
        "category": "通用",
        "title": "目标检测结果通用解读",
        "scene": "任意类别检测结果的通用处理",
        "keywords": [],
        "match_classes": [],
        "risk_level": "低",
        "suggestion": "核对检测目标类别与数量是否符合预期；"
                      "对低置信度目标人工复核；如需更高精度可调高置信度阈值或更换模型。",
    },
    {
        "id": "general-low-conf",
        "category": "通用",
        "title": "低置信度目标偏多",
        "scene": "多数目标置信度偏低，结果可靠性存疑",
        "keywords": ["低置信度", "误检", "漏检"],
        "match_classes": [],
        "risk_level": "低",
        "suggestion": "适当提高置信度阈值以减少误检；对关键目标人工二次确认；"
                      "考虑使用针对该场景微调的模型权重。",
    },
]

_GENERAL_FALLBACK = [c for c in CASES if c["category"] == "通用"]


def extract_keywords(detections, model_category):
    """从检测结果与模型分类聚合关键词（去重、保序）。"""
    kws = []
    seen = set()

    def _add(k):
        if k and k not in seen:
            seen.add(k)
            kws.append(k)

    for d in detections or []:
        _add(d.get("className"))
    if model_category:
        _add(model_category)
    return kws


def search_cases(keywords, classes, top_n=3):
    """按关键词命中 + 类别命中打分，取 Top-N；全 0 时回退通用兜底案例。"""
    kw_set = {str(k).lower() for k in (keywords or [])}
    cls_set = {str(c).lower() for c in (classes or [])}

    scored = []
    for case in CASES:
        case_kws = {str(k).lower() for k in case["keywords"]}
        case_cls = {str(c).lower() for c in case["match_classes"]}
        score = len(kw_set & case_kws) * 1 + len(cls_set & case_cls) * 2
        if score > 0:
            scored.append((score, case))

    if not scored:
        return list(_GENERAL_FALLBACK[:top_n])

    scored.sort(key=lambda t: t[0], reverse=True)
    return [c for _s, c in scored[:top_n]]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_case_library.py -v`
Expected: PASS（5 个用例全绿）

- [ ] **Step 6: Commit**

```bash
git add backend/case_library.py backend/tests/__init__.py backend/tests/test_case_library.py backend/requirements.txt
git commit -m "feat: 案例库检索模块（关键词提取+相似案例搜索）"
```

---

### Task 2: DeepSeek 客户端

**Files:**
- Create: `backend/deepseek.py`
- Create: `backend/tests/test_deepseek.py`
- Modify: `backend/config.py:42`（追加 DEEPSEEK 配置）

**Interfaces:**
- Consumes: `Config.DEEPSEEK_API_KEY`、`Config.DEEPSEEK_BASE_URL`、`Config.DEEPSEEK_MODEL`。
- Produces: `chat_json(system_prompt: str, user_prompt: str, timeout: int = 60) -> dict`
  —— 返回解析后的 JSON dict；网络/超时/解析失败抛 `DeepSeekError`。

- [ ] **Step 1: 追加 config 配置**

修改 `backend/config.py`，在第 42 行 `MODELSCOPE_TOKEN = ...` 之后追加：

```python

    # DeepSeek（检测结果 AI 分析报告）：OpenAI 兼容接口
    DEEPSEEK_API_KEY = os.getenv(
        "DEEPSEEK_API_KEY", ""
    )
    DEEPSEEK_BASE_URL = os.getenv(
        "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
    )
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
```

- [ ] **Step 2: 写失败测试**

创建 `backend/tests/test_deepseek.py`：

```python
import json
import pytest
import deepseek


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_chat_json_parses_content(monkeypatch):
    content = json.dumps({"summary": "ok", "risk": {"level": "低", "desc": "无"}})
    payload = {"choices": [{"message": {"content": content}}]}
    monkeypatch.setattr(deepseek.requests, "post",
                        lambda *a, **k: _FakeResp(payload))
    out = deepseek.chat_json("sys", "user")
    assert out["summary"] == "ok"
    assert out["risk"]["level"] == "低"


def test_chat_json_raises_on_network_error(monkeypatch):
    def _boom(*a, **k):
        raise deepseek.requests.exceptions.Timeout("timeout")
    monkeypatch.setattr(deepseek.requests, "post", _boom)
    with pytest.raises(deepseek.DeepSeekError):
        deepseek.chat_json("sys", "user")
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_deepseek.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'deepseek'`

- [ ] **Step 4: 实现 deepseek.py**

创建 `backend/deepseek.py`：

```python
"""DeepSeek 客户端（OpenAI 兼容 chat/completions）。

仅供检测结果 AI 报告使用。强制 JSON 输出。失败抛 DeepSeekError，
由上层 report.py 捕获并降级。
"""
import json

import requests

from config import Config


class DeepSeekError(Exception):
    pass


def chat_json(system_prompt, user_prompt, timeout=60):
    """调 DeepSeek 返回解析后的 JSON dict。失败抛 DeepSeekError。"""
    url = f"{Config.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": Config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "stream": False,
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except (requests.exceptions.RequestException, KeyError, IndexError,
            ValueError) as e:
        raise DeepSeekError(str(e)) from e
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_deepseek.py -v`
Expected: PASS（2 个用例）

- [ ] **Step 6: Commit**

```bash
git add backend/deepseek.py backend/tests/test_deepseek.py backend/config.py
git commit -m "feat: DeepSeek 客户端（OpenAI 兼容，强制 JSON）"
```

---

### Task 3: 报告编排（含降级兜底）

**Files:**
- Create: `backend/report.py`
- Create: `backend/tests/test_report.py`

**Interfaces:**
- Consumes: `case_library.extract_keywords/search_cases`、`deepseek.chat_json/DeepSeekError`。
- Produces: `build_report(model_name, model_category, detections, width, height, conf, image_name) -> dict`
  —— 返回 spec §4 报告结构 dict。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_report.py`：

```python
import report
import deepseek


_DETS = [
    {"className": "person", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
    {"className": "person", "confidence": 0.7, "bbox": [0, 0, 10, 10]},
]


def test_build_report_ai_success(monkeypatch):
    monkeypatch.setattr(report.deepseek, "chat_json", lambda s, u: {
        "summary": "检出2人",
        "risk": {"level": "中", "desc": "人员聚集"},
        "findings": [{"className": "person", "note": "2 个"}],
        "suggestions": [{"title": "疏导", "detail": "分流"}],
        "conclusion": "建议关注",
    })
    rep = report.build_report("yolo", "生产安全风险识别", _DETS, 100, 100, 0.25, "a.jpg")
    assert rep["meta"]["aiAvailable"] is True
    assert rep["meta"]["modelName"] == "yolo"
    assert rep["stats"]["total"] == 2
    assert rep["stats"]["byClass"][0]["className"] == "person"
    assert rep["stats"]["byClass"][0]["count"] == 2
    assert rep["summary"] == "检出2人"
    assert rep["matchedCases"]
    assert rep["keywords"]
    assert rep["warning"] is None


def test_build_report_falls_back_when_ai_fails(monkeypatch):
    def _boom(s, u):
        raise deepseek.DeepSeekError("network down")
    monkeypatch.setattr(report.deepseek, "chat_json", _boom)
    rep = report.build_report("yolo", "通用", _DETS, 100, 100, 0.25, "a.jpg")
    assert rep["meta"]["aiAvailable"] is False
    assert rep["warning"]
    # 兜底建议来自案例库
    assert len(rep["suggestions"]) >= 1
    assert rep["risk"]["level"] in ("高", "中", "低")
    assert rep["stats"]["total"] == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'report'`

- [ ] **Step 3: 实现 report.py**

创建 `backend/report.py`：

```python
"""检测结果报告编排：统计 → 关键词 → 案例检索 → DeepSeek 生成 → 组装。

DeepSeek 不可用时用案例库兜底，报告始终可用（meta.aiAvailable=False + warning）。
"""
import json
from collections import OrderedDict
from datetime import datetime

import case_library
import deepseek

_RISK_RANK = {"高": 3, "中": 2, "低": 1}


def _aggregate(detections):
    """聚合：总数、按类计数与均值置信度、最高置信度。"""
    groups = OrderedDict()
    max_conf = 0.0
    for d in detections or []:
        name = d.get("className", "unknown")
        conf = float(d.get("confidence", 0) or 0)
        max_conf = max(max_conf, conf)
        g = groups.setdefault(name, [])
        g.append(conf)
    by_class = [
        {"className": name,
         "count": len(confs),
         "avgConf": round(sum(confs) / len(confs), 4) if confs else 0}
        for name, confs in groups.items()
    ]
    return {
        "total": len(detections or []),
        "byClass": by_class,
        "maxConf": round(max_conf, 4),
    }


def _build_prompt(model_name, model_category, stats, keywords, cases, conf):
    system = (
        "你是工业与公共安全领域的视觉检测分析专家。"
        "基于给定的目标检测统计结果与参考案例，输出一份专业、可执行的中文分析。"
        "只返回 JSON，字段固定为 summary(字符串)、"
        "risk(对象:{level:\"高|中|低\", desc:字符串})、"
        "findings(数组:[{className, note}])、"
        "suggestions(数组:[{title, detail}])、conclusion(字符串)。"
        "建议须结合参考案例并贴合检测到的目标，不要编造不存在的目标。"
    )
    user = json.dumps({
        "模型": model_name,
        "模型分类": model_category,
        "置信度阈值": conf,
        "检测统计": stats,
        "提取关键词": keywords,
        "参考案例": [
            {"标题": c["title"], "分类": c["category"],
             "风险等级": c["risk_level"], "处理建议": c["suggestion"]}
            for c in cases
        ],
    }, ensure_ascii=False)
    return system, user


def _fallback(stats, cases):
    """DeepSeek 不可用时，用案例库内容组装报告核心字段。"""
    level = "低"
    for c in cases:
        if _RISK_RANK.get(c["risk_level"], 0) > _RISK_RANK.get(level, 0):
            level = c["risk_level"]
    suggestions = [{"title": c["title"], "detail": c["suggestion"]} for c in cases]
    findings = [{"className": b["className"],
                 "note": f"检出 {b['count']} 个，平均置信度 {b['avgConf']:.0%}"}
                for b in stats["byClass"]]
    summary = (f"共检出 {stats['total']} 个目标，覆盖 {len(stats['byClass'])} 个类别。"
               "AI 服务暂不可用，以下结论基于内置案例库生成。")
    return {
        "summary": summary,
        "risk": {"level": level, "desc": "依据匹配案例的最高风险等级评估。"},
        "findings": findings,
        "suggestions": suggestions,
        "conclusion": "建议结合现场情况核实上述风险点并落实处理建议。",
    }


def build_report(model_name, model_category, detections, width, height,
                 conf, image_name):
    stats = _aggregate(detections)
    classes = [b["className"] for b in stats["byClass"]]
    keywords = case_library.extract_keywords(detections, model_category)
    cases = case_library.search_cases(keywords, classes)

    ai_available = True
    warning = None
    try:
        system, user = _build_prompt(model_name, model_category, stats,
                                     keywords, cases, conf)
        core = deepseek.chat_json(system, user)
        # 校验关键字段，缺失则降级
        if not isinstance(core, dict) or "summary" not in core:
            raise deepseek.DeepSeekError("返回结构缺少必要字段")
    except deepseek.DeepSeekError as e:
        ai_available = False
        warning = f"AI 分析服务暂不可用（{e}），已使用内置案例库生成兜底建议。"
        core = _fallback(stats, cases)

    return {
        "meta": {
            "modelName": model_name,
            "category": model_category,
            "imageName": image_name,
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "conf": conf,
            "aiAvailable": ai_available,
        },
        "stats": stats,
        "summary": core.get("summary", ""),
        "risk": core.get("risk", {"level": "低", "desc": ""}),
        "findings": core.get("findings", []),
        "suggestions": core.get("suggestions", []),
        "matchedCases": [
            {"id": c["id"], "title": c["title"],
             "category": c["category"], "risk_level": c["risk_level"]}
            for c in cases
        ],
        "keywords": keywords,
        "conclusion": core.get("conclusion", ""),
        "warning": warning,
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS（2 个用例）

- [ ] **Step 5: 跑全部后端测试**

Run: `python -m pytest -v`
Expected: PASS（Task1/2/3 共 9 个用例全绿）

- [ ] **Step 6: Commit**

```bash
git add backend/report.py backend/tests/test_report.py
git commit -m "feat: 检测报告编排（DeepSeek 生成 + 案例库降级兜底）"
```

---

### Task 4: 新增 /analyze-report 路由

**Files:**
- Modify: `backend/routes/ai_model.py`（在 `detect` 路由之后、`_video_jobs` 之前插入新路由，约第 683 行）

**Interfaces:**
- Consumes: `report.build_report`、`AiModel`、现有 `permission_required`。
- Produces: `POST /api/ai/model/<mid>/analyze-report`，body JSON `{detections, width, height, count, imageName, conf}`，返回 `{code:0, message, data:<报告>}`。

- [ ] **Step 1: 实现路由**

在 `backend/routes/ai_model.py` 第 682 行（`return jsonify(code=0, message="检测完成", data=result)` 之后、第 685 行 `# 视频检测异步任务进度表` 之前）插入：

```python


@ai_model_bp.post("/<int:mid>/analyze-report")
@permission_required("ai:model:query")
def analyze_report(mid):
    """对已完成的图片检测结果做 DeepSeek AI 分析，生成正式检测报告。"""
    m = AiModel.query.get_or_404(mid)
    data = request.get_json(silent=True) or {}
    detections = data.get("detections")
    if not isinstance(detections, list):
        return jsonify(code=400, message="缺少检测结果 detections"), 400

    try:
        conf = float(data.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25

    try:
        from report import build_report
        result = build_report(
            model_name=m.modelName,
            model_category=m.category,
            detections=detections,
            width=data.get("width"),
            height=data.get("height"),
            conf=conf,
            image_name=data.get("imageName") or "未命名图片",
        )
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"报告生成失败：{e}"), 500
    return jsonify(code=0, message="报告生成完成", data=result)
```

注意：`m.modelName` / `m.category` 字段名以 `backend/models` 中 `AiModel` 定义为准；若属性名不同（如 `model_name`），按实际定义调整这两行（见 Step 2 确认）。

- [ ] **Step 2: 确认 AiModel 字段名**

Run（在 `backend/`）: `python -c "from models import AiModel; print([c.name for c in AiModel.__table__.columns])"`
Expected: 打印列名，确认含 `modelName`/`category`（或对应名）。若与上面代码不符，改 Step 1 的两个属性名后继续。

- [ ] **Step 3: 启动后端冒烟验证**

Run（在 `backend/`，后台）: 启动 `python app.py`，确认无导入错误、监听 5001。
然后用已登录获得的 JWT 调用（替换 `<TOKEN>` 与一个有效模型 id `<MID>`）：

```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/model/<MID>/analyze-report \
  -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  -d '{"detections":[{"className":"person","confidence":0.9,"bbox":[0,0,10,10]}],"width":100,"height":100,"count":1,"imageName":"t.jpg","conf":0.25}'
```

Expected: 返回 `code:0` 且 `data.meta.aiAvailable` 为 true/false 均可（取决于网络），`data.summary`、`data.suggestions`、`data.matchedCases` 非空。

- [ ] **Step 4: Commit**

```bash
git add backend/routes/ai_model.py
git commit -m "feat: 新增 /analyze-report 路由生成检测 AI 报告"
```

---

### Task 5: 前端 API + 报告渲染

**Files:**
- Modify: `frontend/src/api/ai.js`（在 `detect` 方法之后追加 `analyzeReport`）
- Modify: `frontend/src/views/ai/image/index.vue`

**Interfaces:**
- Consumes: 后端 `/analyze-report`、`result.value`（现有检测结果 `{count,width,height,detections}`）。
- Produces: 页内 `report` 响应式状态 + 报告卡片渲染 + 「生成AI检测报告」按钮 + `riskTagType` + `exportPdf`（本任务先占位）。

- [ ] **Step 1: 追加 API 方法**

修改 `frontend/src/api/ai.js`，在 `detect` 方法（第 23-27 行，以 `}),` 结尾）之后追加：

```javascript
  // 对检测结果做 DeepSeek AI 分析，生成正式报告
  analyzeReport: (id, payload) =>
    request.post(`/ai/model/${id}/analyze-report`, payload, { timeout: 0 }),
```

- [ ] **Step 2: 报告区按钮与状态（script）**

修改 `frontend/src/views/ai/image/index.vue`，在 `<script setup>` 中 `const result = ref(null)`（第 178 行）之后追加状态：

```javascript
const report = ref(null)
const reporting = ref(false)
const reportEl = ref(null)
```

把 `clearResult`（第 287-290 行）整体替换为：

```javascript
const clearResult = () => {
  result.value = null
  activeIndex.value = -1
  report.value = null
}
```

在 `detect` 函数中设置 `result.value = res.data`（第 320 行）之后那一行追加：

```javascript
    report.value = null
```

在 `clearAll`（第 330 行起）函数体内（`activeIndex.value = -1` 那行后）追加：

```javascript
  report.value = null
```

新增生成报告方法（放在 `detect` 函数之后，第 328 行 `}` 之后）：

```javascript
const genReport = async () => {
  if (!result.value) return
  reporting.value = true
  try {
    const payload = {
      detections: result.value.detections,
      width: result.value.width,
      height: result.value.height,
      count: result.value.count,
      imageName: file.value?.name || '未命名图片',
      conf: conf.value
    }
    const res = await modelApi.analyzeReport(modelId.value, payload)
    report.value = res.data
    if (report.value?.warning) ElMessage.warning(report.value.warning)
  } catch (e) {
    ElMessage.error('报告生成失败')
  } finally {
    reporting.value = false
  }
}

const riskTagType = (level) => ({ 高: 'danger', 中: 'warning', 低: 'success' }[level] || 'info')

// 真正的 PDF 导出在 Task 6 接入；此处占位以便本任务独立验证
const exportPdf = () => ElMessage.info('PDF 导出将在下一步接入')
```

- [ ] **Step 3: 报告区按钮与卡片（template）**

在 `result-meta` 这个 `<div>`（第 86-115 行）内、`</el-table>` 之后、该 `<div>` 闭合标签 `</div>`（第 115 行）之前，追加生成按钮：

```html
        <div class="report-actions">
          <el-button type="primary" :loading="reporting" @click="genReport">
            生成AI检测报告
          </el-button>
        </div>
```

在 `result-meta` 的闭合 `</div>`（第 115 行）之后、`</el-card>`（第 116 行）之前，新增报告卡片：

```html
        <div v-if="report" ref="reportEl" class="ai-report">
          <div class="rp-head">
            <h3>智能检测分析报告</h3>
            <div class="rp-meta">
              <span>模型：{{ report.meta.modelName }}（{{ report.meta.category || '未分类' }}）</span>
              <span>图片：{{ report.meta.imageName }}</span>
              <span>生成时间：{{ report.meta.generatedAt }}</span>
              <span>置信度阈值：{{ report.meta.conf }}</span>
            </div>
            <el-button class="rp-pdf" link type="primary" :icon="Download" @click="exportPdf">下载PDF</el-button>
          </div>

          <el-alert v-if="!report.meta.aiAvailable" type="warning" :closable="false" :title="report.warning" style="margin-bottom: 12px" />

          <div class="rp-imgs">
            <div class="rp-img"><div class="rp-img-t">原图</div><img v-if="previewSrc" :src="previewSrc" /></div>
            <div class="rp-img"><div class="rp-img-t">检测结果</div><img v-if="resultSrc" :src="resultSrc" /></div>
          </div>

          <div class="rp-sec">
            <h4>一、检测概述</h4>
            <p>{{ report.summary }}</p>
            <div class="rp-tags">
              <el-tag v-for="(b, i) in report.stats.byClass" :key="i" type="info" effect="plain">
                {{ b.className }} × {{ b.count }}（{{ (b.avgConf * 100).toFixed(0) }}%）
              </el-tag>
            </div>
          </div>

          <div class="rp-sec">
            <h4>二、风险评估</h4>
            <el-tag :type="riskTagType(report.risk.level)" effect="dark">风险等级：{{ report.risk.level }}</el-tag>
            <p>{{ report.risk.desc }}</p>
          </div>

          <div class="rp-sec" v-if="report.findings.length">
            <h4>三、逐项发现</h4>
            <ul><li v-for="(f, i) in report.findings" :key="i"><b>{{ f.className }}：</b>{{ f.note }}</li></ul>
          </div>

          <div class="rp-sec">
            <h4>四、AI 智能建议</h4>
            <ol class="rp-sug"><li v-for="(s, i) in report.suggestions" :key="i"><b>{{ s.title }}</b><div>{{ s.detail }}</div></li></ol>
          </div>

          <div class="rp-sec" v-if="report.matchedCases.length">
            <h4>五、匹配案例</h4>
            <div class="rp-tags">
              <el-tag v-for="c in report.matchedCases" :key="c.id" :type="riskTagType(c.risk_level)" effect="plain">
                {{ c.title }}（{{ c.category }}·{{ c.risk_level }}）
              </el-tag>
            </div>
            <div class="rp-tags" style="margin-top: 6px">
              <span class="rp-kw">关键词：</span>
              <el-tag v-for="(k, i) in report.keywords" :key="i" size="small">{{ k }}</el-tag>
            </div>
          </div>

          <div class="rp-sec">
            <h4>六、结论</h4>
            <p>{{ report.conclusion }}</p>
          </div>
        </div>
```

- [ ] **Step 4: 报告区样式**

在 `<style scoped>` 末尾（第 447 行 `.cls-dot {...}` 块的 `}` 之后、`</style>` 之前）追加：

```css
.report-actions {
  margin-top: 16px;
}
.ai-report {
  margin-top: 20px;
  padding: 20px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fff;
}
.rp-head {
  position: relative;
  border-bottom: 2px solid #409eff;
  padding-bottom: 10px;
  margin-bottom: 16px;
}
.rp-head h3 {
  margin: 0 0 6px;
  color: #1f2d3d;
}
.rp-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: #909399;
}
.rp-pdf {
  position: absolute;
  right: 0;
  top: 0;
}
.rp-imgs {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}
.rp-img {
  flex: 1;
  min-width: 0;
}
.rp-img-t {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.rp-img img {
  width: 100%;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}
.rp-sec {
  margin-bottom: 16px;
}
.rp-sec h4 {
  margin: 0 0 8px;
  color: #3a4a63;
}
.rp-sec p {
  margin: 6px 0;
  line-height: 1.7;
  color: #5a6b87;
}
.rp-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.rp-sug li {
  margin-bottom: 10px;
  line-height: 1.7;
}
.rp-kw {
  font-size: 12px;
  color: #909399;
}
```

- [ ] **Step 5: 确认 Download 图标已导入**

`Download` 已在第 125 行 `import { ... Download ... } from '@element-plus/icons-vue'` 中导入。无需改动，仅确认存在。

- [ ] **Step 6: 手动验证**

启动前端（`cd frontend && npm run dev`）与后端，登录后到「图像检测」页：选模型+图片→开始检测→出现「生成AI检测报告」按钮→点击→报告卡片渲染（概述/风险/发现/建议/匹配案例/结论俱全）。点「下载PDF」弹占位提示。

Expected: 报告完整渲染，风险标签按等级着色，AI 不可用时顶部出现黄色警告条。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/ai.js frontend/src/views/ai/image/index.vue
git commit -m "feat: 图片检测页 AI 报告渲染与生成按钮"
```

---

### Task 6: PDF 导出（jspdf + html2canvas）

**Files:**
- Modify: `frontend/package.json`（dependencies 追加 jspdf、html2canvas）
- Modify: `frontend/src/views/ai/image/index.vue`（替换 `exportPdf` 占位实现 + import）

**Interfaces:**
- Consumes: `reportEl`（报告卡片 DOM ref）、`report.value.meta.imageName`。
- Produces: 真正的 `exportPdf()` —— 截图报告 DOM 生成多页 A4 PDF 下载。

- [ ] **Step 1: 安装依赖**

Run（在 `frontend/`）: `npm install jspdf html2canvas`
Expected: `package.json` dependencies 出现 `jspdf` 与 `html2canvas`，安装无错。

- [ ] **Step 2: 引入库**

修改 `frontend/src/views/ai/image/index.vue`，在 `<script setup>` 顶部 import 区（第 127 行 `import { modelApi } from '../../../api/ai'` 之后）追加：

```javascript
import jsPDF from 'jspdf'
import html2canvas from 'html2canvas'
```

- [ ] **Step 3: 实现 exportPdf**

把 Task 5 Step 2 的占位 `exportPdf`：

```javascript
// 真正的 PDF 导出在 Task 6 接入；此处占位以便本任务独立验证
const exportPdf = () => ElMessage.info('PDF 导出将在下一步接入')
```

整体替换为：

```javascript
const exportPdf = async () => {
  if (!reportEl.value) return
  try {
    const canvas = await html2canvas(reportEl.value, { scale: 2, useCORS: true, backgroundColor: '#ffffff' })
    const img = canvas.toDataURL('image/jpeg', 0.92)
    const pdf = new jsPDF('p', 'mm', 'a4')
    const pw = pdf.internal.pageSize.getWidth()
    const ph = pdf.internal.pageSize.getHeight()
    const imgH = (canvas.height * pw) / canvas.width // 等比缩放后总高(mm)
    let left = imgH
    let pos = 0
    pdf.addImage(img, 'JPEG', 0, pos, pw, imgH)
    left -= ph
    while (left > 0) {
      pos -= ph
      pdf.addPage()
      pdf.addImage(img, 'JPEG', 0, pos, pw, imgH)
      left -= ph
    }
    const name = (report.value?.meta?.imageName || 'detection').replace(/\.[^.]+$/, '')
    pdf.save(`${name}_AI检测报告.pdf`)
  } catch (e) {
    ElMessage.error('PDF 导出失败')
  }
}
```

- [ ] **Step 4: 手动验证**

重启前端 dev（装新依赖后需重启）。生成报告后点「下载PDF」：浏览器下载 `<图名>_AI检测报告.pdf`，打开确认中文正常、含原图/检测图/各小节，长报告正确分页。

Expected: PDF 下载且内容完整、中文无乱码。

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/views/ai/image/index.vue
git commit -m "feat: 检测报告 PDF 导出（html2canvas + jspdf）"
```

---

## Self-Review

**1. Spec coverage：**
- spec §3.1 deepseek.py → Task 2 ✓；case_library.py → Task 1 ✓；report.py → Task 3 ✓
- spec §3.2 路由 → Task 4 ✓
- spec §4 报告结构 → Task 3 build_report 组装 ✓
- spec §5 容错降级 → Task 3 `_fallback` + test_report 降级用例 ✓
- spec §6 前端渲染 → Task 5 ✓；PDF → Task 6 ✓
- spec §7 依赖 → 后端 Task 1（requests/pytest）、前端 Task 6（jspdf/html2canvas）✓
- spec §8 安全（key 仅后端 env）→ Task 2 config，前端不涉及 key ✓
- spec §9 验收 1-6 全部覆盖 ✓

**2. Placeholder scan：** Task 5 的 `exportPdf` 占位是**有意的**临时实现，Task 6 Step 3 显式替换为完整代码——非计划缺陷。其余步骤均含完整代码/命令/预期。

**3. Type consistency：**
- `extract_keywords(detections, model_category)`、`search_cases(keywords, classes, top_n)` Task1 定义、Task3 调用一致 ✓
- `chat_json(system_prompt, user_prompt)` Task2 定义、Task3 调用一致 ✓
- `build_report(model_name, model_category, detections, width, height, conf, image_name)` Task3 定义、Task4 调用一致 ✓
- 报告字段名（meta/stats/summary/risk/findings/suggestions/matchedCases/keywords/conclusion/warning）后端 Task3 与前端 Task5 模板一致 ✓
- `report` / `reporting` / `reportEl` / `riskTagType` / `exportPdf` 前端命名 Task5、Task6 一致 ✓
