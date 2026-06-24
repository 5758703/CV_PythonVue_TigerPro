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
