"""检测结果案例库 + 关键词提取 + 相似案例检索。

纯本地逻辑、无外部依赖，供 report.py 在调用 DeepSeek 前组织上下文，
DeepSeek 不可用时也作为建议兜底来源。案例按分类管理。
"""

# 内置案例库（模块级常量）。两分类：生产安全风险识别 / 通用。
CASES = [
    {
        "id": "medical-brain-no-tumor",
        "category": "医学影像-脑肿瘤",
        "title": "未见明显肿瘤高风险征象",
        "scene": "检测结果以 no_tumor / normal 为主",
        "keywords": ["no_tumor", "normal", "无肿瘤", "脑肿瘤"],
        "match_classes": ["no_tumor", "normal"],
        "risk_level": "低",
        "suggestion": "当前图像未见明显肿瘤高风险征象。建议结合临床症状与既往史，"
                      "按医嘱定期复查 MRI，并由影像科医生最终判读。",
    },
    {
        "id": "medical-brain-suspected-tumor",
        "category": "医学影像-脑肿瘤",
        "title": "疑似脑肿瘤征象",
        "scene": "检测到肿瘤相关类别（tumor/glioma/meningioma/pituitary）",
        "keywords": ["tumor", "glioma", "meningioma", "pituitary", "脑肿瘤"],
        "match_classes": ["tumor", "glioma", "meningioma", "pituitary"],
        "risk_level": "高",
        "suggestion": "存在疑似肿瘤征象，建议尽快由神经影像专科医生复核，必要时完善增强 MRI、"
                      "弥散/灌注序列及相关实验室检查，综合评估后制定进一步诊疗方案。",
    },
    {
        "id": "medical-brain-low-confidence",
        "category": "医学影像-脑肿瘤",
        "title": "医学影像结果置信度偏低",
        "scene": "脑肿瘤检测结果整体置信度不足，存在误检/漏检风险",
        "keywords": ["低置信度", "误检", "漏检", "脑肿瘤", "医学影像"],
        "match_classes": [],
        "risk_level": "中",
        "suggestion": "建议复核原始 DICOM 质量并进行多序列、多切面判读；"
                      "必要时更换更匹配的数据域模型，避免单次 AI 结果直接用于临床决策。",
    },
    {
        "id": "rocket-landing-tracking",
        "category": "航天-火箭回收",
        "title": "火箭回收阶段目标跟踪",
        "scene": "同时检测到 Rocket Body 与 Engine Flames，处于发射/着陆关键阶段",
        "keywords": ["rocket body", "engine flames", "火箭", "回收", "着陆", "falcon"],
        "match_classes": ["rocket body", "engine flames"],
        "risk_level": "中",
        "suggestion": "持续跟踪火箭本体与发动机火焰区域，记录帧间位移与姿态变化；"
                      "结合遥测数据交叉验证视觉跟踪结果，关注着陆腿展开与减速点火时序。",
    },
    {
        "id": "rocket-launch-flames",
        "category": "航天-火箭回收",
        "title": "发动机火焰显著",
        "scene": "画面以 Engine Flames 为主，可能处于点火/反推阶段",
        "keywords": ["engine flames", "火焰", "点火", "反推", "rocket"],
        "match_classes": ["engine flames"],
        "risk_level": "中",
        "suggestion": "标注火焰区域时序与强度变化，用于判断推力阶段；"
                      "注意曝光过饱和导致的框漂移，必要时降低置信度阈值并人工复核关键帧。",
    },
    {
        "id": "rocket-body-only",
        "category": "航天-火箭回收",
        "title": "火箭本体可见（无火焰）",
        "scene": "检测到 Rocket Body，未检出 Engine Flames",
        "keywords": ["rocket body", "火箭本体", "滑翔", "回收"],
        "match_classes": ["rocket body"],
        "risk_level": "低",
        "suggestion": "适用于自由落体/滑翔段跟踪；建议开启多目标追踪（目标追踪页）"
                      "保持 ID 连续，并记录本体在画面中的尺度变化以估计距离趋势。",
    },
    {
        "id": "rocket-no-target",
        "category": "航天-火箭回收",
        "title": "未检出火箭相关目标",
        "scene": "仅背景 Space 或未检出 Rocket Body / Engine Flames",
        "keywords": ["space", "背景", "未检出", "火箭"],
        "match_classes": ["space"],
        "risk_level": "低",
        "suggestion": "检查视频时段是否处于火箭出画/遮挡阶段；"
                      "可尝试降低置信度阈值或切换更高分辨率源；确认镜头视场是否覆盖回收走廊。",
    },
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
