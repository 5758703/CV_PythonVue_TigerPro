"""检测结果报告编排：统计 → 关键词 → 案例检索 → DeepSeek 生成 → 组装。

DeepSeek 不可用时用案例库兜底，报告始终可用（meta.aiAvailable=False + warning）。
"""
import json
from collections import OrderedDict
from datetime import datetime

import case_library
import deepseek

_RISK_RANK = {"高": 3, "中": 2, "低": 1}


def _is_medical_scene(model_name, model_category, classes):
    text = " ".join([
        str(model_name or "").lower(),
        str(model_category or "").lower(),
        " ".join(str(c or "").lower() for c in (classes or [])),
    ])
    keys = ("脑肿瘤", "医学影像", "brain", "tumor", "glioma", "meningioma", "pituitary")
    return any(k in text for k in keys)


def _is_rocket_scene(model_name, model_category, classes):
    text = " ".join([
        str(model_name or "").lower(),
        str(model_category or "").lower(),
        " ".join(str(c or "").lower() for c in (classes or [])),
    ])
    keys = ("火箭", "rocket", "航天", "falcon", "engine flames", "rocket body", "space")
    return any(k in text for k in keys)


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


def _build_prompt(model_name, model_category, stats, keywords, cases, conf,
                  medical=False, rocket=False):
    if medical:
        system = (
            "你是神经影像方向的医学影像分析助手。"
            "你只能基于给定检测结果与参考案例生成辅助分析，严禁给出确诊结论。"
            "请使用审慎、医疗合规语气，明确提示“AI 结果仅供辅助，需医生最终判读”。"
            "只返回 JSON，字段固定为 summary(字符串)、"
            "risk(对象:{level:\"高|中|低\", desc:字符串})、"
            "findings(数组:[{className, note}])、"
            "suggestions(数组:[{title, detail}])、conclusion(字符串)。"
        )
    elif rocket:
        system = (
            "你是航天发射与火箭回收领域的视觉分析助手。"
            "基于 Rocket Body / Engine Flames / Space 等检测统计与参考案例，"
            "输出火箭姿态跟踪与回收过程解读（中文、专业、可执行）。"
            "不要编造未检出的目标或遥测数据；明确这是视觉检测辅助而非飞行安全裁决。"
            "只返回 JSON，字段固定为 summary(字符串)、"
            "risk(对象:{level:\"高|中|低\", desc:字符串})、"
            "findings(数组:[{className, note}])、"
            "suggestions(数组:[{title, detail}])、conclusion(字符串)。"
        )
    else:
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


def _fallback(stats, cases, medical=False, rocket=False):
    """DeepSeek 不可用时，用案例库内容组装报告核心字段。"""
    level = "低"
    for c in cases:
        if _RISK_RANK.get(c["risk_level"], 0) > _RISK_RANK.get(level, 0):
            level = c["risk_level"]
    suggestions = [{"title": c["title"], "detail": c["suggestion"]} for c in cases]
    findings = [{"className": b["className"],
                 "note": f"检出 {b['count']} 个，平均置信度 {b['avgConf']:.0%}"}
                for b in stats["byClass"]]
    if medical:
        summary = (f"本次共检出 {stats['total']} 个疑似目标，覆盖 {len(stats['byClass'])} 个类别。"
                   "AI 服务暂不可用，以下结论基于内置医学案例库生成，仅作辅助参考。")
    elif rocket:
        summary = (f"共检出 {stats['total']} 个火箭相关目标，覆盖 {len(stats['byClass'])} 个类别。"
                   "AI 服务暂不可用，以下结论基于内置火箭回收案例库生成，仅供视觉跟踪辅助。")
    else:
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
    medical_scene = _is_medical_scene(model_name, model_category, classes)
    rocket_scene = _is_rocket_scene(model_name, model_category, classes)
    keywords = case_library.extract_keywords(detections, model_category)
    cases = case_library.search_cases(keywords, classes)

    ai_available = True
    warning = None
    try:
        system, user = _build_prompt(model_name, model_category, stats,
                                     keywords, cases, conf,
                                     medical=medical_scene, rocket=rocket_scene)
        core = deepseek.chat_json(system, user)
        # 校验关键字段，缺失则降级
        if not isinstance(core, dict) or "summary" not in core:
            raise deepseek.DeepSeekError("返回结构缺少必要字段")
    except deepseek.DeepSeekError as e:
        ai_available = False
        warning = f"AI 分析服务暂不可用（{e}），已使用内置案例库生成兜底建议。"
        core = _fallback(stats, cases, medical=medical_scene, rocket=rocket_scene)

    disclaimer = None
    if medical_scene:
        disclaimer = ("医学免责声明：本报告由 AI 基于图像检测结果自动生成，仅用于辅助分析，"
                      "不能替代医生诊断、病理结果或临床决策。请以执业医师最终意见为准。")
    elif rocket_scene:
        disclaimer = ("航天视觉辅助声明：本报告基于目标检测框统计生成，"
                      "不代表官方飞行数据或任务结论，关键决策须以遥测与任务控制中心信息为准。")

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
        "disclaimer": disclaimer,
    }
