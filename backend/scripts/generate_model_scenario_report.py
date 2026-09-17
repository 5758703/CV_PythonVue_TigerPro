"""Generate the project model usage-scenario audit from seed metadata.

The output is intentionally committed documentation; rerun this script after
adding a seeded model so the inventory and per-model implementation cards stay
in sync.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))
import export_csdn_models_catalog as catalog  # noqa: E402

OUT = ROOT / "docs" / "articles" / "MODEL_USAGE_SCENARIOS.md"


TASK_ROUTE = {
    "object-detection": ("图片/视频/摄像头检测", "/ai/image、/ai/video、/camera"),
    "instance-segmentation": ("图像分割", "/ai/segment"),
    "interactive-segmentation": ("交互分割", "/ai/segment"),
    "pose-estimation": ("姿态估计/运动分析", "/ai/pose、/ai/badminton"),
    "wholebody-pose-estimation": ("全身姿态", "/ai/pose"),
    "obb": ("旋转框检测", "/ai/image"),
    "image-classification": ("图像分类", "/ai/classify"),
    "image-inpainting": ("图像修复", "/ai/inpaint"),
    "text-classification": ("文本分析", "/ai/text"),
    "zero-shot-classification": ("零样本分类", "/ai/text"),
    "fill-mask": ("完形填空", "/ai/text"),
    "summarization": ("文本生成", "/ai/generate"),
    "translation": ("文本生成", "/ai/generate"),
    "token-classification": ("实体识别", "/ai/ner"),
    "question-answering": ("智能问答", "/ai/qa"),
    "automatic-speech-recognition": ("语音识别", "/ai/asr"),
    "text-to-speech": ("语音合成", "/ai/tts"),
    "talking-head": ("数字人", "/ai/talking"),
    "face-recognition": ("人脸底库", "/ai/face"),
    "person-reid": ("跨镜行人", "/ai/mtmc"),
    "vehicle-reid": ("跨镜车辆", "/ai/mtmc"),
    "text-detection": ("OCR/表格/车牌", "/ai/table、/ai/vehicle"),
    "text-recognition": ("OCR/表格/车牌", "/ai/table、/ai/vehicle"),
    "table-structure": ("表格识别", "/ai/table"),
    "visual-diagnosis": ("缺陷诊断", "/ai/defect"),
}


def inventory() -> list[dict]:
    seed = catalog.SEED.read_text(encoding="utf-8")
    rows = catalog.parse_ensure_ai_models(seed) + catalog.parse_security_specs(seed)
    # These are registered through helper functions whose keys are variables,
    # so the generic regex intentionally cannot discover them.
    rows += [
        dict(model_key="chinese-sign-language-tigerhhzz-yolo11s", model_name="中国手语识别（YOLO11s·tigerhhzz）", category="手势识别", task="object-detection", library="ultralytics", description="逐帧检测手语类别，结合时序去抖输出手语词。"),
        dict(model_key="opencv-handpose-mediapipe", model_name="手部关键点估计（MediaPipe·OpenCV）", category="手势识别", task="pose-estimation", library="opencv-dnn", description="OpenCV DNN 手掌检测与 21 点手部关键点。"),
        dict(model_key="yolo11-fish-detector-grayscale", model_name="鱼类检测（灰度水下·YOLO11n）", category="海洋-鱼类检测", task="object-detection", library="ultralytics", description="灰度水下视频鱼类定位与计数。"),
    ]
    from services.yolo_master import YOLO_MASTER_MODELS
    rows += [dict(model_key=s["key"], model_name=s["name"], category={"instance-segmentation": "实例分割", "pose-estimation": "姿态估计", "obb": "旋转框检测", "image-classification": "图像分类"}.get(s["task"], "通用目标检测"), task=s["task"], library="yolo-master", version=s.get("version", ""), description=s["desc"]) for s in YOLO_MASTER_MODELS]
    by_key = {r["model_key"]: r for r in rows if r.get("model_key") not in {None, "key"}}
    return sorted(by_key.values(), key=lambda r: (r.get("category", ""), r["model_key"].lower()))


def scenario(m: dict) -> tuple[str, str, str, str, str]:
    k = m["model_key"].lower()
    task = m.get("task", "object-detection")
    if "plate" in k and "reid" not in k:
        return ("园区车辆进出口号牌采集", "先用通用车辆模型裁出车辆 ROI，再定位车牌；pose/OBB 版本先做四点透视，最后交给 PP-OCRv6。", "车牌框、矫正图、号牌文本与置信度；绑定 track_id，触发黑名单或陌生车告警。", "白天/夜间各采集近中远距离车辆；按车牌完整识别率而非仅检测 mAP 验收。", "仅负责车牌定位的模型不能直接读出字符；模糊、反光、严重侧拍必须允许多帧投票。")
    if "fire" in k or "smoke" in k:
        return ("仓库/林区早期烟火预警", "摄像头低帧率常驻检测，连续多帧命中后由告警引擎按区域、持续时间和冷却期确认。", "火/烟框、首帧证据、摄像头与时间；推送告警中心并保留事件片段。", "用蒸汽、云雾、红灯、焊花作负样本；分别统计烟与火的事件级召回率和每摄像头日误报。", "不得单帧联动消防设备；红外/夜间域需单独标定阈值。")
    if any(x in k for x in ("ppe", "helmet", "hard-hat")):
        return ("工地人员防护装备合规巡检", "先检测 person，再在人员框内关联安全帽、反光衣、口罩等正负类别；进入作业区持续缺失才成事件。", "人员级 PPE 状态、违规截图与区域；生成班组整改记录。", "按遮挡、俯视、多人重叠分层验收；核心指标是人员级漏报/误报，不是装备框总数。", "小目标依赖高分辨率和近景机位；不能把画面中的备用安全帽关联给旁边人员。")
    if "fall" in k:
        return ("养老院/厂区人员跌倒告警", "检测人体并结合框宽高比、位置变化与多帧持续状态，过滤弯腰、躺椅和坐地。", "疑似跌倒事件、前后视频证据与位置；通知值守人员复核。", "以完整事件评估召回、误报/小时和告警延迟，覆盖遮挡与不同机位。", "检测器类别不是医疗诊断；必须采用时序确认和人工复核。")
    if "fight" in k or "weapon" in k:
        return ("公共区域暴力/危险物品预警", "在重点区域检测打斗或枪刀，连续帧确认并保存上下文；高风险事件进入人工快速复核。", "目标框、风险类别、证据片段和摄像头位置；升级安保工单。", "用拥抱、运动、工具施工等困难负样本压测，统计事件级误报率。", "模型输出只是风险线索，不应自动认定违法事实。")
    if "smoking" in k or "cigarette" in k:
        return ("禁烟区域吸烟行为识别", "检测香烟/手口动作，在人员 ROI 内做空间关联，并以连续帧和区域规则确认。", "涉事人员轨迹、吸烟截图与持续时长；生成劝阻告警。", "覆盖手机贴脸、饮水、吃东西等负样本；按人次事件精确率验收。", "香烟极小，远景全画面推理可靠性低，应限制机位距离。")
    if "phone" in k:
        return ("驾驶舱/值守岗位违规使用手机", "人员或驾驶员 ROI 内检测手机，叠加值班时段与持续时长，过滤路过者。", "人员、手机框、违规持续时间和证据图；触发岗位告警。", "加入对讲机、纸张、手扶面部等负样本；验收事件准确率。", "仅见手机不等于违规，必须结合岗位区域和持续时间。")
    if task in ("person-reid", "vehicle-reid"):
        obj = "车辆" if task == "vehicle-reid" else "行人"
        return (f"园区多摄像头{obj}轨迹串联", f"检测与单镜跟踪先生成 tracklet，裁剪高质量 {obj} 图送入本模型提特征，再结合拓扑、时间窗和车牌/类别完成跨镜关联。", f"global_id、相似度、跨镜时间线与最佳截图；用于轨迹检索和滞留分析。", "按同一目标跨镜 top-1、IDF1、误合并率及未知目标拒识率验收。", "ReID 不是检测器；必须与检测、跟踪、质量筛选和拓扑约束组合。")
    if task == "face-recognition":
        return ("门禁访客身份核验", "检测并对齐人脸，提取 embedding 与授权底库比对；低质量或低相似度进入未知人员分支。", "身份候选、相似度、活体/质量状态；驱动放行或人工复核。", "按不同光照、口罩、侧脸测试 TAR/FAR，并对阈值做独立标定。", "项目未证明具备活体检测时，不可单独用于高安全门禁。")
    if task in ("pose-estimation", "wholebody-pose-estimation"):
        return ("运动技术与人员动作分析", "逐帧输出关键点，按 track_id 平滑后计算关节角、挥拍阶段或手部动作；羽毛球场景再融合球检测。", "骨架、动作阶段、角度/速度和异常提示；生成训练报告。", "分别评估关键点可见率、动作阶段准确率和端到端 FPS。", "关键点模型不直接理解业务动作；必须增加时序规则或分类层。")
    if task in ("instance-segmentation", "interactive-segmentation"):
        return ("缺陷/目标精细轮廓提取", "检测或用户点选/框选产生提示，输出 mask；计算面积、占比，并可送入 LaMa 修复或质检流程。", "像素级 mask、面积与叠加预览；导出标注或缺陷统计。", "用 IoU/Dice、边界误差和交互点击次数验收。", "开放词汇/通用分割不等同于行业缺陷分类，生产前需行业样本校验。")
    if task == "image-inpainting":
        return ("监控截图隐私对象擦除与素材修复", "用户或分割模型提供 mask，LaMa 对遮罩区域补全，保留原图与审计记录。", "修复图和 mask；用于报告脱敏或标注数据清理。", "检查边界接缝、结构一致性及不同 mask 尺度耗时。", "修复内容是生成结果，不能作为原始证据。")
    if task in ("text-detection", "text-recognition", "table-structure"):
        return ("票据/巡检表结构化录入", "文本检测定位文字，识别模型转字符；表格模型恢复行列结构，最终输出 HTML/CSV。", "文字框、文本、单元格坐标与结构化表；进入业务台账。", "检测召回、字符准确率、单元格结构准确率分别验收。", "三类模型各司其职，不能只部署其中一个就期待完整表格结果。")
    if task == "automatic-speech-recognition":
        return ("值班录音/会议转写", "上传音频后统一采样率；ASR 输出文本，支持的模型附时间戳、说话人或情绪事件，再送摘要/检索。", "转写文本、时间轴及可选说话人；形成可检索记录。", "按普通话/方言/噪声/多人重叠分别统计 CER/WER、实时率。", "模型语种和说话人能力不同；无 diarization 的模型不能宣称区分多人。")
    if task == "text-to-speech":
        return ("告警与数字人语音播报", "将模板化告警文本送入 TTS，选择音色并缓存常用语音；输出可进一步驱动数字人。", "WAV 音频、时长与音色信息；用于广播或数字人。", "验收首包延迟、实时率、可懂度及中英混读。", "声音克隆需另有参考音频和授权；普通 TTS 模型不自动具备克隆能力。")
    if task == "talking-head":
        return ("数字人讲解员", "上传授权头像和 TTS/录音，生成口型同步视频；异步任务轮询进度并保存成品。", "MP4、任务状态和失败原因；用于展厅解说。", "验收唇音同步、面部稳定性、生成倍率和 GPU 显存。", "当前项目说明为 GPU 脚手架，上线前必须完成运行时与肖像授权。")
    if task in ("text-classification", "zero-shot-classification", "fill-mask", "summarization", "translation", "token-classification", "question-answering"):
        return ("告警文本与业务文档智能处理", "通过对应文本接口输入正文；分类/NER/问答/摘要/翻译按任务输出，再由业务规则决定归档或展示。", "标签概率、实体、答案或生成文本；进入报告和搜索索引。", "用本项目语料建立金标集，评估 F1/ROUGE/人工可用率及延迟。", "预训练模型存在语种和领域边界；金融、安防结论不得只依赖通用模型。")
    if "tumor" in k:
        return ("脑部影像疑似病灶辅助标记", "上传影像后检测疑似区域，结构化结果交给报告模块/DeepSeek生成辅助说明。", "病灶框、置信度和辅助报告；供专业人员复核。", "按设备/序列/医院外部集验证灵敏度与假阳性。", "仅作科研/辅助，不得替代医生诊断；需医疗合规与数据脱敏。")
    if "ball" in k or "badminton" in k:
        return ("羽毛球比赛落点与回合分析", "检测小球并与球员姿态、球场标定、轨迹滤波融合，形成击球和落点事件。", "球轨迹、回合、落点热力图与比赛报告。", "按小球召回、轨迹中断率、落点误差和实时性验收。", "单帧小球极易漏检，必须使用高帧率、ROI 与轨迹插值。")
    if "rocket" in k:
        return ("火箭发射/回收视频目标跟踪", "检测箭体和发动机火焰，结合专用跟踪与镜头运动补偿保持轨迹。", "目标轨迹、阶段事件和标注视频。", "按远距小目标召回、轨迹完整率和 ID 切换验收。", "仅适用于数据集定义的视觉类别，不提供飞行安全决策。")
    if "fish" in k:
        return ("水下养殖鱼群计数与活动监测", "对灰度水下视频检测鱼体，ByteTrack 去重计数并按区域统计密度。", "鱼框、轨迹、过线计数和密度趋势。", "按浑浊度和鱼群重叠分层评估计数误差。", "训练域为灰度水下画面，彩色或其他物种需重新验证。")
    if task == "image-classification":
        return ("图片内容预分类与数据集质检", "整图预处理后输出 Top-K 类别；低置信样本送人工标注或更专用模型。", "Top-K 标签与概率；用于素材路由和数据清洗。", "以项目自有类别映射评估 top-1/top-5 和拒识覆盖率。", "ImageNet 通用类别不能替代检测，也不适合直接判断局部目标。")
    return ("园区视频通用目标发现", "图片、视频或摄像头帧进入模型，统一输出框；按区域/越线/持续时间规则组合为业务事件。", "类别、框、置信度、track_id 与证据图；供告警、统计或后续 OCR/ReID。", "按场景统计 mAP/召回、误报/小时、FPS，并建立困难负样本集。", "通用 COCO 模型只覆盖既定类别；行业目标必须专训或使用开放词汇模型。")


def main() -> None:
    models = inventory()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for m in models:
        grouped[m.get("category") or "未分类"].append(m)
    lines = [
        "# TigerPro 模型使用场景与落地分析",
        "",
        "> 生成依据：`backend/seed.py` 的启动注册项及 `services/yolo_master.py` 动态规格。模型管理页读取数据库，故未注册的 `uploads/models/*` 目录不计入正式模型列表。",
        "",
        f"## 1. 结论与口径\n\n当前可注册模型共 **{len(models)} 个**。模型是否真正可用还同时取决于：数据库 `status=0`、`file_path` 可解析、权重存在、对应运行库已安装、任务路由支持。仅在列表出现不等于已经生产可用。",
        "",
        "推荐把模型落地拆成四层：模型产生原子结果（框/mask/关键点/文本/向量）→ 服务组合时序与多模型信息 → 告警/报告形成业务事件 → 金标集与监控闭环验收。",
        "",
        "## 2. 共性实施基线",
        "",
        "1. 在模型管理确认 modelKey、任务、运行库、权重路径和启用状态；业务选择必须使用 modelId/modelKey，不靠中文名。",
        "2. 用 20 条冒烟样本验证接口和可视化，再以真实机位/语料建立至少 200 条分层金标集。",
        "3. 视觉视频场景记录事件级召回、误报/小时、端到端 FPS；文本/语音按任务记录 F1、CER/WER、人工可用率。",
        "4. 阈值、版本、运行设备、输入分辨率和规则参数必须随模型版本一起留档，支持回滚。",
        "5. 高风险场景（医疗、人脸、暴力、火灾）一律保留人工复核，不把单次模型输出直接当事实或执行指令。",
        "",
        "## 3. 逐模型场景化实现",
        "",
    ]
    idx = 0
    for category, items in grouped.items():
        lines += [f"### 3.{len([x for x in lines if x.startswith('### 3.')]) + 1} {category}", ""]
        for m in items:
            idx += 1
            task = m.get("task", "object-detection")
            page, route = TASK_ROUTE.get(task, ("模型管理/对应业务页", "/ai/model"))
            s, flow, out, accept, bound = scenario(m)
            desc = str(m.get("description") or "").strip()
            if desc == "(":
                desc = "种子元数据中的描述由表达式拼接，具体能力以任务和运行库为准。"
            lines += [
                f"#### {idx}. {m.get('model_name') or m['model_key']} (`{m['model_key']}`)", "",
                f"- **定位**：{m.get('category', '未分类')} / `{task}` / `{m.get('library', '-')}`；入口：{page}（`{route}`）。{desc}",
                f"- **具体场景**：{s}。",
                f"- **实现流程**：{flow}",
                f"- **产出与联动**：{out}",
                f"- **验收方式**：{accept}",
                f"- **边界/风险**：{bound}", "",
            ]
    lines += [
        "## 4. 发现的落地缺口",
        "",
        "- `uploads/models` 中存在未被 seed 注册的本地权重目录；它们不会稳定出现在模型列表，应完成来源、许可、任务、运行库和 class names 核验后再正式登记。",
        "- 部分模型种子描述使用 Python 表达式拼接，现有正则目录脚本会解析成 `(`；运行时数据库本身不受影响，但文档生成器不应把该值当完整说明。",
        "- 同一能力存在多套候选模型（车牌、人脸、ReID、姿态、烟火、PPE）；应按同一真实样本集做 A/B，而不是全部同时上线。",
        "- 云端说明型、第三方仓库型和 GPU 脚手架型模型需要额外运行时；上线清单应明确“已登记、权重就绪、接口可跑、业务验收”四种状态。",
        "",
        "## 5. 上线优先级建议",
        "",
        "- P0：通用检测 + 告警规则；PP-OCRv6 检测/识别 + 车牌；检测 + ReID + MTMC。它们与现有业务服务组合最完整。",
        "- P1：烟火/PPE/跌倒/手机/吸烟等安防专模；逐机位建负样本和事件规则后上线。",
        "- P2：姿态+羽毛球、表格识别、ASR/TTS、文本模型；适合形成独立业务页闭环。",
        "- P3：医学、多模态、数字人、开放词汇与第三方运行时模型；先完成合规、资源与稳定性验证。",
        "",
        "---",
        "",
        "更新模型后运行：`python backend/scripts/generate_model_scenario_report.py`。",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"generated {OUT} ({len(models)} models)")


if __name__ == "__main__":
    main()
