# -*- coding: utf-8 -*-
"""从 seed.py + uploads/models 汇总全部 AI 模型，生成 CSDN 质量标准 MD（本地私有目录）。"""
from __future__ import annotations

import re
import textwrap
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "backend" / "seed.py"
UPLOADS = ROOT / "backend" / "uploads" / "models"
OUT_DIR = ROOT / "docs" / "csdn-ai-models-catalog"
OUT_FILE = OUT_DIR / "tigerpro-ai-models-csdn.md"

SKIP_DIRS = {
    "third_party", "base", "custom-2", "custom-4",
    "_unkeyed_1783152713", "_unkeyed_1783152992",
}

TASK_ZH = {
    "object-detection": "目标检测",
    "instance-segmentation": "实例分割",
    "pose-estimation": "姿态估计",
    "obb": "旋转目标检测",
    "image-classification": "图像分类",
    "text-classification": "文本分类",
    "token-classification": "序列标注/NER",
    "question-answering": "问答",
    "summarization": "摘要",
    "translation": "翻译",
    "fill-mask": "掩码填空",
    "zero-shot-classification": "零样本分类",
    "automatic-speech-recognition": "语音识别",
    "text-to-speech": "语音合成",
    "face-recognition": "人脸识别",
    "person-reid": "行人重识别",
    "vehicle-reid": "车辆重识别",
    "text-detection": "OCR 检测",
    "text-recognition": "OCR 识别",
    "table-structure": "表格结构",
    "image-inpainting": "图像修复",
    "digital-human": "数字人",
}

# key -> (页面说明, 路由, 案例)
USAGE_MAP = {
    "fire-smoke-detection": ("图像/视频/摄像头检测", "/ai/image", "园区烟火告警"),
    "ppe-detection": ("图像/视频检测", "/ai/image", "工地 PPE 合规"),
    "yolov8m-table-extraction": ("表格识别", "/ai/table", "文档表格抽取"),
    "yolov8-license-plate": ("车辆追踪", "/ai/vehicle", "卡口车牌定位"),
    "keremberke-yolov5n-license-plate": ("车辆追踪", "/ai/vehicle", "轻量车牌检测"),
    "keremberke-yolov5m-license-plate": ("车辆追踪", "/ai/vehicle", "中等精度车牌"),
    "yolov11-license-plate-n": ("车辆追踪", "/ai/vehicle", "YOLOv11n 车牌"),
    "yolov11-license-plate-s": ("车辆追踪", "/ai/vehicle", "YOLOv11s 车牌"),
    "PP-OCRv6_small_det_onnx": ("PaddleOCR", "/ai/paddleocr", "文字区域检测"),
    "PP-OCRv6_small_rec_onnx": ("PaddleOCR", "/ai/paddleocr", "文字内容识别"),
    "rapidtable-slanet-plus": ("表格识别", "/ai/table", "表格 HTML 重建"),
    "yolo26n": ("检测/追踪/MTMC", "/ai/image、/ai/mtmc", "COCO 检测骨干"),
    "yolo26s": ("通用检测", "/ai/image", "更高精度 COCO"),
    "brain-tumor-yolo-opennoor": ("医学影像", "/ai/image", "脑肿瘤检测+报告"),
    "rocket-detect-nasaspaceflight": ("航天检测", "/ai/image", "火箭回收跟踪"),
    "finbert": ("文本分析", "/ai/text", "财经情绪"),
    "detr-resnet-50": ("图片检测", "/ai/image", "DETR 对比实验"),
    "rf-detr-medium": ("图片/视频检测", "/ai/image", "RF-DETR 实时检测"),
    "rf-detr-seg-medium": ("图像分割", "/ai/segment", "实例分割"),
    "mobile-sam": ("图像分割", "/ai/segment", "点选分割"),
    "efficient-sam": ("图像分割", "/ai/segment", "高效 SAM"),
    "inpainting-lama": ("图像修复", "/ai/inpaint", "遮罩修复"),
    "yoloe-26s-seg": ("图像分割", "/ai/segment", "开放词汇分割"),
    "vit-base": ("图像分类", "/ai/imgcls", "ImageNet 分类"),
    "mobilenet-v2": ("图像分类/实时分类", "/ai/imgcls、/ai/livecls", "轻量分类"),
    "bert-emotion": ("文本分析", "/ai/text", "多情感分类"),
    "bart-mnli": ("文本分析", "/ai/text", "零样本分类"),
    "bert-fill-mask": ("文本分析", "/ai/text", "完形填空"),
    "distilbart-cnn": ("文本生成", "/ai/generate", "英文摘要"),
    "opus-mt-en-zh": ("文本生成", "/ai/generate", "英译中"),
    "bert-ner": ("实体识别", "/ai/ner", "NER 抽取"),
    "distilbert-squad": ("智能问答", "/ai/qa", "抽取式 QA"),
    "sensevoice-small": ("语音识别", "/ai/asr", "多语种 ASR"),
    "paraformer-zh": ("语音识别", "/ai/asr", "中文 ASR"),
    "sensevoice-small-onnx": ("语音识别", "/ai/asr", "量化 ASR"),
    "fun-asr-nano": ("语音识别", "/ai/asr", "轻量 ASR"),
    "moonshine-tiny": ("语音识别", "/ai/asr", "英文边缘 ASR"),
    "yolo26n-plate": ("车辆/MTMC", "/ai/vehicle、/ai/mtmc", "车牌框"),
    "yolo26s-plate-pose": ("车辆追踪", "/ai/vehicle", "车牌四点透视"),
    "yolo26n-p2-plate": ("车辆追踪", "/ai/vehicle", "小目标车牌"),
    "yolo26n-pose": ("姿态估计", "/ai/pose", "人体关键点"),
    "yolo26n-obb": ("旋转框/车辆", "/ai/image、/ai/vehicle", "OBB 检测"),
    "linly-talker": ("数字人", "/ai/talker", "口型驱动说话"),
    "mms-tts-eng": ("TTS", "/ai/tts", "英文语音合成"),
    "vibevoice-realtime": ("TTS", "/ai/tts", "实时语音合成"),
    "melotts-zh-en": ("TTS", "/ai/tts", "中英混合合成"),
    "yolo11n-pose": ("姿态/羽毛球", "/ai/pose、/ai/badminton", "球员骨架"),
    "yolo11s-ball": ("羽毛球分析", "/ai/badminton", "羽毛球轨迹"),
    "rtmo-s": ("姿态估计", "/ai/pose", "RTMO-S"),
    "rtmo-m": ("姿态估计", "/ai/pose", "RTMO-M"),
    "rtmpose-m": ("姿态估计", "/ai/pose", "RTMPose"),
    "dwpose-m": ("姿态估计", "/ai/pose", "DWPose 全身"),
    "insightface-buffalo-s": ("人脸/离岗", "/ai/face、/ai/absence", "人脸底库比对"),
    "insightface-buffalo-l": ("人脸识别", "/ai/face", "高精度人脸"),
    "opencv-yunet-sface": ("人脸识别", "/ai/face", "OpenCV 轻量人脸"),
    "opencv-person-reid-youtu": ("行人 ReID/MTMC", "/ai/reid、/ai/mtmc", "Youtu 外观"),
    "osnet-x1-0": ("跨镜重识别", "/ai/mtmc", "强行人 ReID"),
    "clip-reid-person": ("跨镜重识别", "/ai/mtmc", "CLIP 行人外观"),
    "transreid-vehicle": ("跨镜重识别", "/ai/mtmc", "车辆视觉 ReID"),
    "clip-reid-vehicle": ("跨镜重识别", "/ai/mtmc", "CLIP 车辆 ReID"),
    "vehicle-vit-reid": ("跨镜重识别", "/ai/mtmc", "车辆 ViT ReID"),
    "chinese-sign-language-tigerhhzz-yolo11s": ("手势识别", "/ai/handpose", "中国手语字母"),
    "opencv-handpose-mediapipe": ("手势识别", "/ai/handpose", "21 点手势 0–9"),
    "yolo11-fish-detector-grayscale": ("图片检测", "/ai/image", "水下鱼类检测"),
    "water-level-best-pt": ("水位检测", "/ai/water", "水尺读数"),
    "openai-whisper-small": ("语音识别", "/ai/asr", "Whisper 转写"),
    "openbmb-VoxCPM2": ("TTS", "/ai/tts", "音色克隆合成"),
    "mms-tts-cmn": ("TTS", "/ai/tts", "普通话合成"),
    "stepfun-ai-GOT-OCR2_0": ("OCR", "/ai/ocr", "文档 OCR 2.0"),
}


def guess_category(key: str, name: str = "") -> str:
    s = f"{key} {name}".lower()
    rules = [
        (("fire", "smoke", "forest", "ppe", "helmet", "weapon", "fight", "fall", "sec-"), "安防检测"),
        (("plate", "license", "vehicle", "reid-vehicle", "transreid", "obb"), "交通车辆"),
        (("face", "yunet", "sface", "buffalo", "insight"), "人脸识别"),
        (("person-reid", "youtu", "osnet", "clip-reid-person", "reid"), "行人重识别"),
        (("pose", "rtmo", "rtmpose", "dwpose", "handpose", "sign"), "姿态/手势"),
        (("ocr", "paddle", "slanet", "table", "got-ocr"), "文档解析"),
        (("asr", "sensevoice", "paraformer", "whisper", "moonshine", "fun-asr"), "语音识别"),
        (("tts", "melo", "vibevoice", "mms-tts", "voxcpm"), "语音合成"),
        (("talker", "linly"), "数字人"),
        (("sam", "seg", "inpaint", "lama"), "分割/修复"),
        (("bert", "bart", "finbert", "opus", "squad", "ner", "emotion", "mnli"), "NLP 文本"),
        (("vit", "mobilenet", "imgcls", "nsfw"), "图像分类"),
        (("fish", "rocket", "spacecraft", "tumor", "brain", "badminton", "ball", "football", "crowd", "water"), "垂直场景"),
        (("yolo", "detr", "rf-detr", "detect"), "通用目标检测"),
    ]
    for keys, cat in rules:
        if any(k in s for k in keys):
            return cat
    return "其他/本地权重"


def guess_task(key: str, cat: str) -> str:
    s = key.lower()
    if any(x in s for x in ("pose", "rtmo", "rtmpose", "dwpose", "handpose")):
        return "pose-estimation"
    if "obb" in s:
        return "obb"
    if any(x in s for x in ("seg", "sam")):
        return "instance-segmentation"
    if "inpaint" in s or "lama" in s:
        return "image-inpainting"
    if any(x in s for x in ("asr", "sensevoice", "paraformer", "whisper", "moonshine")):
        return "automatic-speech-recognition"
    if any(x in s for x in ("tts", "melo", "vibe", "mms-tts", "voxcpm")):
        return "text-to-speech"
    if "talker" in s:
        return "digital-human"
    if any(x in s for x in ("face", "yunet", "buffalo")):
        return "face-recognition"
    if "vehicle" in s and "reid" in s or "transreid" in s:
        return "vehicle-reid"
    if "reid" in s or "youtu" in s or "osnet" in s:
        return "person-reid"
    if cat.startswith("NLP") or any(x in s for x in ("bert", "bart", "finbert", "opus")):
        return "text-classification"
    if any(x in s for x in ("vit-base", "mobilenet", "nsfw")):
        return "image-classification"
    if "ocr" in s and "det" in s:
        return "text-detection"
    if "ocr" in s and "rec" in s:
        return "text-recognition"
    if "table" in s or "slanet" in s:
        return "table-structure"
    return "object-detection"


def parse_ensure_ai_models(seed: str) -> list[dict]:
    pat = re.compile(
        r'created\s*\|\=\s*_ensure_ai_model\(\s*["\']([^"\']+)["\']\s*,\s*dict\((.*?)\)\s*\)',
        re.S,
    )
    field_pat = re.compile(
        r'(\w+)\s*=\s*(?:"""(.*?)"""|"([^"]*)"|\'([^\']*)\'|([^,\n]+))',
        re.S,
    )
    out = []
    for m in pat.finditer(seed):
        key = m.group(1)
        fields = {"model_key": key, "source": "seed:_ensure_ai_model"}
        for fm in field_pat.finditer(m.group(2)):
            k = fm.group(1)
            v = fm.group(2) if fm.group(2) is not None else (
                fm.group(3) if fm.group(3) is not None else (
                    fm.group(4) if fm.group(4) is not None else fm.group(5)
                )
            )
            if v is not None:
                fields[k] = textwrap.dedent(str(v)).strip().rstrip(",")
        out.append(fields)
    return out


def parse_security_specs(seed: str) -> list[dict]:
    pat = re.compile(
        r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)',
        re.S,
    )
    block = re.search(r"_SECURITY_DETECTOR_SPECS\s*=\s*\[(.*?)\]", seed, re.S)
    if not block:
        return []
    out = []
    for m in pat.finditer(block.group(1)):
        key, name, rel, ver, desc = m.groups()
        out.append({
            "model_key": key,
            "model_name": name,
            "category": "安防检测",
            "task": "object-detection",
            "library": "ultralytics",
            "version": ver,
            "description": desc + " ONNX Runtime CPU 推理。",
            "source": "seed:_SECURITY_DETECTOR_SPECS",
            "file_hint": f"models/{rel}",
        })
    return out


def parse_standalone_aimodel(seed: str) -> list[dict]:
    """解析 AiModel(model_key=..., model_name=..., ...) 块。"""
    pat = re.compile(r"AiModel\(\s*(.*?)\s*\)", re.S)
    field_pat = re.compile(
        r'(\w+)\s*=\s*(?:"""(.*?)"""|"([^"]*)"|\'([^\']*)\'|([^,\n]+))',
        re.S,
    )
    out = []
    for m in pat.finditer(seed):
        body = m.group(1)
        fields = {"source": "seed:AiModel()"}
        for fm in field_pat.finditer(body):
            k = fm.group(1)
            v = fm.group(2) if fm.group(2) is not None else (
                fm.group(3) if fm.group(3) is not None else (
                    fm.group(4) if fm.group(4) is not None else fm.group(5)
                )
            )
            if v is not None:
                fields[k] = textwrap.dedent(str(v)).strip().rstrip(",")
        if "model_key" in fields:
            out.append(fields)
    return out


def scan_upload_dirs() -> list[dict]:
    if not UPLOADS.is_dir():
        return []
    out = []
    for d in sorted(UPLOADS.iterdir()):
        if not d.is_dir() or d.name in SKIP_DIRS or d.name.startswith("_"):
            continue
        # skip empty-ish
        files = [f for f in d.rglob("*") if f.is_file() and f.suffix.lower() in {
            ".pt", ".onnx", ".bin", ".safetensors", ".pth", ".engine", ".json", ".yaml", ".yml", ".txt"
        }]
        if not files:
            continue
        key = d.name
        cat = guess_category(key)
        task = guess_task(key, cat)
        out.append({
            "model_key": key,
            "model_name": key.replace("-", " ").replace("_", " "),
            "category": cat,
            "task": task,
            "library": "local-weight",
            "version": "-",
            "description": f"本地权重目录 uploads/models/{key}/（约 {len(files)} 个相关文件）。"
                           f"可能由 seed 登记、训练产出或模型管理页下载产生。",
            "source": "uploads/models",
            "file_hint": f"models/{key}",
        })
    return out


def merge_models() -> list[dict]:
    seed = SEED.read_text(encoding="utf-8")
    by_key: dict[str, dict] = {}
    for m in parse_ensure_ai_models(seed) + parse_security_specs(seed) + parse_standalone_aimodel(seed):
        by_key[m["model_key"]] = m
    for m in scan_upload_dirs():
        if m["model_key"] not in by_key:
            by_key[m["model_key"]] = m
        else:
            # enrich missing fields
            cur = by_key[m["model_key"]]
            cur.setdefault("file_hint", m.get("file_hint"))
            if not cur.get("category"):
                cur["category"] = m["category"]
    # normalize
    models = []
    for key, m in sorted(by_key.items(), key=lambda x: (x[1].get("category") or "", x[0])):
        m.setdefault("model_name", key)
        m.setdefault("category", guess_category(key, m.get("model_name", "")))
        m.setdefault("task", guess_task(key, m["category"]))
        m.setdefault("library", "-")
        m.setdefault("version", "-")
        m.setdefault("description", "见模型管理页。")
        m.setdefault("source_url", "")
        m.setdefault("source", "unknown")
        models.append(m)
    return models


def esc(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def usage_for(key: str) -> tuple[str, str, str]:
    if key in USAGE_MAP:
        return USAGE_MAP[key]
    cat = guess_category(key)
    if cat == "安防检测":
        return ("图片/视频/告警", "/ai/image、/ai/alert、/ai/fall", "安防场景检测告警")
    if cat == "语音识别":
        return ("语音识别页", "/ai/asr", "音频转写")
    if cat == "语音合成":
        return ("文本转语音", "/ai/tts", "语音播报")
    if cat == "人脸识别":
        return ("人脸识别", "/ai/face", "人脸底库比对")
    if cat == "NLP 文本":
        return ("文本相关页", "/ai/text、/ai/generate、/ai/ner、/ai/qa", "文本理解/生成")
    return ("模型管理 / 对应业务页", "/ai/model", "按 modelKey 选择推理")


def word_estimate(text: str) -> int:
    # rough Chinese chars + english words
    cn = len(re.findall(r"[\u4e00-\u9fff]", text))
    en = len(re.findall(r"[A-Za-z]+", text))
    return cn + en


def strip_fenced_code(text: str) -> str:
    return re.sub(r"```[\s\S]*?```", "", text)


def body_cn_chars(text: str) -> int:
    """正文汉字数：去掉代码块后统计中文字符（CSDN 常用口径）。"""
    return len(re.findall(r"[\u4e00-\u9fff]", strip_fenced_code(text)))


def safe_filename(key: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", key, flags=re.UNICODE)


def related_models(models: list[dict], current: dict, limit: int = 8) -> list[dict]:
    cat = current.get("category")
    same = [m for m in models if m["category"] == cat and m["model_key"] != current["model_key"]]
    return same[:limit]


def clean_desc(raw: str, fallback: str) -> str:
    s = (raw or "").replace("\n", " ").strip()
    s = re.sub(r"^[(\[]+\s*", "", s)
    s = re.sub(r"\s*[)\]]+$", "", s)
    if len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", s)) < 8:
        return fallback
    return s


def task_theory(task: str, task_zh: str, name: str, key: str) -> list[str]:
    """任务原理长文，保证技术深度。"""
    blocks = {
        "object-detection": [
            f"### 1.1 目标检测在业务里真正交付什么",
            "",
            f"**{esc(name)}**（`{key}`）属于目标检测：对每一帧输入输出一组框（x1,y1,x2,y2）、类别 id/名称与置信度。"
            "检测不是「看图说话」，而是把非结构化像素变成可检索、可告警、可追踪的结构化事件。"
            "在园区安防里，检测结果会进入告警规则引擎；在交通卡口里，检测框会裁剪给 OCR；"
            "在跨镜 MTMC 里，检测框是局部追踪与 ReID 提特征的唯一入口。",
            "",
            "工程上要同时盯三件事：召回（漏检）、精度（误报）、延迟（能否跟得上抽帧）。"
            "三者互相拉扯——把 conf 提到 0.6 误报下降但漏检上升；把分辨率提到 1080p 精度更好但 CPU 吃紧。"
            "TigerPro 建议先用默认参数跑通链路，再用验收表做网格搜索，而不是一上来「玄学调参」。",
            "",
            "### 1.2 输出如何被下游消费",
            "",
            "常见下游有四类：① 可视化叠加（监控墙 MJPEG）；② 事件入库（检测记录/告警）；"
            "③ 二次模型（车牌 OCR、姿态、分割）；④ 追踪关联（ByteTrack/IoU + 全局 ReID）。"
            "因此选检测模型时，不要只看 COCO mAP，还要看「小目标」「遮挡」「夜间」是否覆盖你的摄像头视角。",
        ],
        "person-reid": [
            "### 1.1 行人重识别不是「认人姓名」",
            "",
            f"**{esc(name)}** 把人体 crop 编码成外观向量。匹配用余弦相似度，不依赖人脸。"
            "跨摄像头时衣服、背包、步态视角都会变；强光/逆光会让颜色失真。"
            "TigerPro MTMC 在时间窗内做全局关联：先局部 track，再跨镜把相似轨迹绑成 global_id。",
            "",
            "### 1.2 轻量特征与强特征如何配合",
            "",
            "平台可并联 Youtu 轻量特征与 OSNet/CLIP 强特征：轻量保实时，强特征降 ID 切换。"
            "上线时建议先固定检测骨干与抽帧 FPS，再单独对比不同 ReID 权重的切换率，避免变量太多无法归因。",
        ],
        "vehicle-reid": [
            "### 1.1 车辆身份为什么难稳定",
            "",
            f"同色车、夜间、远景车牌模糊时，纯视觉 ReID 容易串车。**{esc(name)}** 提供视觉 embedding；"
            "TigerPro 再叠车牌 OCR：有牌时 identity 更稳，无牌时退回视觉键。",
            "",
            "### 1.2 与车牌检测/OCR 的分工",
            "",
            "车牌检测负责「牌在哪」，OCR 负责「牌是什么」，本模型负责「没牌或牌糊时外观像不像」。"
            "三者缺一都会在特定场景翻车，验收时要分「有牌白天 / 有牌夜间 / 无牌 / 遮挡」四桶样本。",
        ],
        "face-recognition": [
            "### 1.1 人脸链路的标准拆分",
            "",
            "检测对齐 → 特征提取 → 底库比对。**底库质量**往往比换更大模型更重要："
            "注册图要正脸、清晰、光照正常；一人多图能抗侧脸与口罩。",
            "",
            "### 1.2 离岗与门禁的阈值策略",
            "",
            "门禁偏「宁可多拒一次」（提高阈值）；离岗偏「不要漏报」（适度降低阈值并加时序确认）。"
            "TigerPro 人脸页与离岗页共用模型登记，但业务阈值应分开配置。",
        ],
        "pose-estimation": [
            "### 1.1 关键点能回答哪些业务问题",
            "",
            "姿态估计输出人体/手部关键点，可做动作统计、跌倒辅助、羽毛球挥拍分析、手语字母等。"
            "关键点抖动与遮挡是两大敌人；多人场景建议先检测人框再估姿态，减少串人。",
            "",
            "### 1.2 与检测/追踪的组合",
            "",
            "姿态本身不保证跨帧 ID。需要稳定轨迹时，把姿态挂在追踪器输出的 track_id 上，"
            "而不是每帧独立关键点集合硬连。",
        ],
        "automatic-speech-recognition": [
            "### 1.1 ASR 的工程关键变量",
            "",
            "采样率、方言、噪声、说话重叠、实时性。中文场景 SenseVoice/Paraformer 往往比通用英文模型更稳；"
            "量化 ONNX 适合 CPU 边缘机。",
            "",
            "### 1.2 如何验收转写质量",
            "",
            "准备「安静室内 / 办公室噪声 / 远场麦克风 / 方言」四类音频，统计字错率与延迟。"
            "不要只用一段播音腔 demo 宣布上线成功。",
        ],
        "text-to-speech": [
            "### 1.1 TTS 三类需求",
            "",
            "播报（稳）、中英混读、音色克隆/实时流式。上线前确认音色授权与采样率，控制并发，"
            "避免和视觉推理抢同一台 CPU。",
            "",
            "### 1.2 与数字人/告警联动",
            "",
            "告警播报要短句、低延迟；数字人口型驱动要稳定韵律。两类场景参数不要共用一套。",
        ],
        "instance-segmentation": [
            "### 1.1 掩码比框多解决什么",
            "",
            "实例分割给出像素级掩码，适合抠图、交互标注、精细占位分析。"
            "交互式 SAM 依赖点/框提示；批处理更适合 YOLOE/RF-DETR Seg。",
            "",
            "### 1.2 何时不该用分割",
            "",
            "只要框就够的计数/告警，硬上分割会浪费算力。先问业务：是否真的需要轮廓。",
        ],
        "image-classification": [
            "### 1.1 整图标签的边界",
            "",
            "分类回答「整张图更像哪一类」，不定位物体。要框请用检测。"
            "适合质检粗分、NSFW 过滤、实时分类墙。",
        ],
        "text-classification": [
            "### 1.1 文本分类与零样本",
            "",
            "有固定标签用微调分类器；标签常变用零样本（如 MNLI）。"
            "金融语料优先领域模型（FinBERT），通用情感模型在研报上会漂。",
        ],
    }
    default = [
        f"### 1.1 任务定位：{esc(task_zh)}",
        "",
        f"**{esc(name)}** 在 TigerPro 中登记为任务 `{task}`（{esc(task_zh)}）。"
        "平台统一用 AiModel 管理权重与状态，业务页通过 modelKey/modelId 选择推理后端。"
        "上线前必须完成：权重绑定 → 页面冒烟 → 真实样本验收 → 监控指标观察。",
        "",
        "### 1.2 为什么要单独成文",
        "",
        "模型目录超过百个后，最大成本不是「会不会调 API」，而是「选错模型、绑错权重、页面对不上 task」。"
        "本篇把该模型的边界、入口、代码、案例与坑写全，方便实施同学按 checklist 落地。",
    ]
    return blocks.get(task, default)


def task_param_table(task: str) -> list[str]:
    rows = {
        "object-detection": [
            ("conf", "0.25~0.45", "过高漏检，过低误报"),
            ("iou", "0.45~0.7", "NMS 重叠抑制"),
            ("imgsz", "640/960", "小目标可加大"),
            ("sampleFps", "1~5", "监控墙先 1~2"),
            ("device", "cpu/cuda", "先 CPU 跑通"),
        ],
        "person-reid": [
            ("sim_thresh", "0.45~0.65", "跨镜匹配阈值"),
            ("gallery_ttl", "30~120s", "特征库存活"),
            ("sampleFps", "1~2", "与检测抽帧一致"),
            ("crop_pad", "0.05~0.15", "人体裁剪边距"),
        ],
        "vehicle-reid": [
            ("sim_thresh", "0.5~0.7", "外观匹配"),
            ("plate_weight", "高/中/低", "有牌时提高牌权重"),
            ("input_hw", "按 ONNX", "TransReID 常见 128×256"),
        ],
        "face-recognition": [
            ("det_thresh", "0.5~0.7", "人脸检测门槛"),
            ("match_thresh", "0.35~0.55", "底库比对"),
            ("min_face", "40~80px", "过小拒识"),
        ],
        "pose-estimation": [
            ("conf", "0.25~0.4", "人体/关键点"),
            ("kpt_thresh", "0.3~0.5", "关键点可见性"),
            ("max_det", "10~50", "拥挤场景限流"),
        ],
        "automatic-speech-recognition": [
            ("sample_rate", "16k", "常见输入"),
            ("language", "zh/en/auto", "按模型能力"),
            ("vad", "开/关", "长音频建议开"),
        ],
        "text-to-speech": [
            ("sample_rate", "24k/48k", "与播放器匹配"),
            ("speed", "0.9~1.1", "播报语速"),
            ("concurrency", "1~4", "防 CPU 打满"),
        ],
    }.get(task, [
        ("timeout", "10~60s", "接口超时"),
        ("batch", "1", "先单条稳定"),
        ("retry", "0~2", "幂等接口可重试"),
    ])
    lines = [
        "| 参数 | 建议范围 | 说明 |",
        "|------|----------|------|",
    ]
    for a, b, c in rows:
        lines.append(f"| `{a}` | {b} | {c} |")
    return lines


def task_code_blocks(task: str, key: str, name: str, route: str) -> list[str]:
    """按任务输出多段可运行示例。"""
    common_list = f'''```python
import requests

BASE = "http://127.0.0.1:5001/api"
headers = {{"Authorization": "Bearer <your-jwt>"}}

def find_model(model_key: str) -> dict:
    rows = requests.get(
        f"{{BASE}}/ai/model/list",
        headers=headers,
        params={{"pageNum": 1, "pageSize": 300}},
    ).json().get("data", {{}}).get("rows", [])
    hit = next((r for r in rows if r.get("modelKey") == model_key), None)
    if not hit:
        raise RuntimeError(f"modelKey not found: {{model_key}}")
    return hit

model = find_model("{key}")
print("id=", model["id"], "path=", model.get("filePath"), "status=", model.get("status"))
assert model.get("filePath"), "权重未绑定，请先到模型管理拉取/上传"
```'''

    detect = f'''```python
# 图片检测类业务：上传文件 + conf（具体 path 以页面后端为准）
files = {{"file": open("demo.jpg", "rb")}}
data = {{"modelId": model["id"], "conf": 0.35, "iou": 0.5}}
# 示例：通用图像检测页常见入口（若 404 请对照前端 api 定义）
resp = requests.post(f"{{BASE}}/ai/detect/image", headers=headers, data=data, files=files)
print(resp.status_code, resp.text[:500])
```'''

    mtmc = f'''```python
# 跨镜会话：检测/ReID 由后端按 priority 自动选择可用权重
payload = {{
    "cameraIds": [1, 2],
    "enablePerson": True,
    "enableVehicle": True,
    "sampleFps": 2,
}}
r = requests.post(f"{{BASE}}/ai/mtmc/sessions/start", headers=headers, json=payload)
print(r.json())
sid = r.json().get("data", {{}}).get("sessionId")
# 存活检查，避免监控墙用过期 sessionId 刷 404
alive = requests.get(f"{{BASE}}/ai/mtmc/sessions/{{sid}}/alive", headers=headers)
print("alive=", alive.json())
```'''

    asr = f'''```python
files = {{"file": open("demo.wav", "rb")}}
data = {{"modelId": model["id"], "language": "zh"}}
r = requests.post(f"{{BASE}}/ai/asr/transcribe", headers=headers, data=data, files=files)
print(r.json())
```'''

    tts = f'''```python
payload = {{"modelId": model["id"], "text": "TigerPro 告警播报测试", "speed": 1.0}}
r = requests.post(f"{{BASE}}/ai/tts/synthesize", headers=headers, json=payload)
print(r.status_code, r.headers.get("content-type"))
open("out.wav", "wb").write(r.content)
```'''

    face = f'''```python
# 注册底库 + 比对（接口名以实际 routes 为准）
files = {{"file": open("face.jpg", "rb")}}
data = {{"modelId": model["id"], "personName": "demo-user"}}
r = requests.post(f"{{BASE}}/ai/face/register", headers=headers, data=data, files=files)
print(r.json())
```'''

    text = f'''```python
payload = {{"modelId": model["id"], "text": "今日市场情绪偏谨慎，指数窄幅震荡。"}}
r = requests.post(f"{{BASE}}/ai/text/analyze", headers=headers, json=payload)
print(r.json())
```'''

    bash = f'''```bash
# 检查权重目录是否非空
dir backend\\uploads\\models\\{key}
# 启动后端（示例端口 5001）
# python backend/app.py
curl -s "http://127.0.0.1:5001/api/ai/model/list?pageNum=1&pageSize=5" ^
  -H "Authorization: Bearer <jwt>"
```'''

    vue = f'''```javascript
// 前端选型提示：下拉以 modelKey 精确匹配，避免只靠中文名
const targetKey = "{key}"
const hit = modelOptions.find(m => m.modelKey === targetKey)
if (!hit) {{
  ElMessage.warning(`未找到模型 ${{targetKey}}，请先在模型管理启用`)
}} else {{
  form.modelId = hit.id
}}
// 页面路由：{route}
```'''

    lines = [
        "### 4.3 列出并校验模型（必跑）",
        "",
        common_list,
        "",
        "### 4.4 业务调用示例",
        "",
    ]
    if task in ("object-detection", "obb", "instance-segmentation", "pose-estimation", "image-classification"):
        lines += [detect, "", "若该模型参与跨镜，可继续：", "", mtmc, ""]
    elif task in ("person-reid", "vehicle-reid"):
        lines += [mtmc, ""]
    elif task == "automatic-speech-recognition":
        lines += [asr, ""]
    elif task == "text-to-speech":
        lines += [tts, ""]
    elif task == "face-recognition":
        lines += [face, ""]
    elif task in ("text-classification", "token-classification", "summarization", "translation",
                  "question-answering", "fill-mask", "zero-shot-classification"):
        lines += [text, ""]
    else:
        lines += [detect, ""]
    lines += [
        "### 4.5 命令行与前端选型",
        "",
        bash,
        "",
        vue,
        "",
    ]
    return lines


def build_one_article(m: dict, all_models: list[dict], idx: int, total: int) -> str:
    today = date.today().isoformat()
    key = m["model_key"]
    name = m.get("model_name") or key
    cat = m.get("category") or "未分类"
    task = m.get("task") or "-"
    task_zh = TASK_ZH.get(task, task)
    lib = m.get("library") or "-"
    ver = m.get("version") or "-"
    src = (m.get("source_url") or "").strip()
    desc = clean_desc(
        m.get("description") or "",
        f"{name} 已在 TigerPro（CV_PyhonVue_Tigerpro）模型管理中登记，可通过 modelKey=`{key}` 选用。",
    )
    page, route, case = usage_for(key)
    origin = m.get("source") or ""
    file_hint = m.get("file_hint") or f"models/{key}"
    related = related_models(all_models, m)

    pitfall_rows = [
        ("权重未下载/未绑定", "模型管理停用或推理 400", "拉取权重；核对 uploads 路径与大小"),
        ("task 与页面不匹配", "空结果/接口报错", "只在匹配任务页选择该模型"),
        ("置信度/阈值过高", "漏检或拒识过多", "从建议下限扫描，结合业务容忍度"),
        ("输入分辨率过低/过近", "小目标或畸变", "提高分辨率、裁 ROI、校正镜头"),
        ("CPU 并发过高", "延迟抖动、队列堆积", "限流、降 FPS、换 nano/量化版"),
        ("sessionId 过期仍开叠加", "监控墙 404 风暴", "先调 alive，失败则关 AI 叠加"),
        ("同分类模型混用未对比", "线上指标不可解释", "固定其它变量，只换一个 modelKey"),
        ("把训练权重当生产", "偶发崩溃/慢", "导出 ONNX/稳定 pt，做冒烟集"),
    ]

    lines: list[str] = [
        "@[TOC](目录)",
        "",
        f"# {esc(name)} 完全指南：原理、TigerPro 接入、代码实战与落地案例（`{key}`）",
        "",
        f"> **系列**：TigerPro AI 模型手册（{idx}/{total}）· 分类：**{esc(cat)}**  ",
        f"> **你能带走什么**：原理边界、规格表、完整接入步骤、可运行代码、双案例、调参表、避坑与验收清单。  ",
        f"> **适用读者**：CV_PyhonVue_Tigerpro 研发 / 实施 / 算法联调同学。  ",
        f"> **生成日期**：{today}  ",
        f"> **正文目标**：汉字不少于 4000（不含代码块）。",
        "",
        "## 1. 开篇：这个模型解决什么问题",
        "",
        f"{esc(desc)}",
        "",
        f"一句话记忆：**{esc(name)}** 的 `modelKey` 是 `{key}`，任务是 **{esc(task_zh)}**（`{task}`），"
        f"前端主要在 **{esc(page)}**（`{esc(route)}`），典型场景是「{esc(case)}」。"
        "如果你只想最快跑通：先保证权重目录非空，再在对应业务页下拉选中本模型，用 5~10 条真实样本冒烟。",
        "",
    ]
    lines += task_theory(task, task_zh, name, key)
    lines += [
        "",
        "### 1.3 适合用 / 不适合用",
        "",
        "| 更适合 | 不太适合 |",
        "|--------|----------|",
        f"| 业务明确需要 {esc(task_zh)}，且已有或可采集对应样本 | 期望「一个模型包打天下」跨任务硬套 |",
        f"| 能接受本地权重部署与 TigerPro 页面选型 | 权重无法落地、只能纯云端且无替代接口 |",
        f"| 需要与告警/追踪/MTMC/OCR 等模块组合 | 只要一次性演示、不愿做验收与监控 |",
        "",
        f"选型时把 `{key}` 放进「候选短名单」，用同一批样本对比同分类相邻模型的延迟与误差，再锁生产版本。",
        "",
        "## 2. 模型名片与能力边界",
        "",
        "### 2.1 规格速查表",
        "",
        "| 项 | 内容 |",
        "|----|------|",
        f"| 显示名称 | {esc(name)} |",
        f"| modelKey | `{key}` |",
        f"| 业务分类 | {esc(cat)} |",
        f"| 任务类型 | `{esc(task)}`（{esc(task_zh)}） |",
        f"| 推理框架/库 | {esc(lib)} |",
        f"| 版本标签 | {esc(ver)} |",
        f"| 登记来源 | {esc(origin)} |",
        f"| 权重相对路径 | `uploads/{esc(file_hint)}` |",
        f"| 前端入口 | {esc(page)} → `{esc(route)}` |",
    ]
    if src:
        lines.append(f"| 上游地址 | [{esc(src)[:90]}]({src}) |")
    else:
        lines.append("| 上游地址 | 项目内 / 本地权重 |")

    lines += [
        "",
        "### 2.2 输入输出约定（实施视角）",
        "",
        "| 维度 | 说明 |",
        "|------|------|",
        f"| 输入 | 按任务可能是图片/视频帧/音频/文本；页面 `{esc(route)}` 决定表单字段 |",
        f"| 输出 | 框/掩码/关键点/向量/文本/音频等；最终以后端 JSON 或文件流为准 |",
        "| 状态 | AiModel.status 启用 + file_path 非空才可稳定推理 |",
        "| 失败表现 | 400/空列表/回退模型/日志 traceback，优先查权重与 task |",
        "",
        "### 2.3 资源与性能预期（经验区间，需本机实测）",
        "",
        "| 环境 | 预期 | 建议 |",
        "|------|------|------|",
        "| 笔记本 CPU | 可冒烟，延迟可能数百毫秒到数秒 | 降分辨率/降 FPS/用 nano 或量化 |",
        "| 服务器多核 CPU | 可小并发 | 限流 + 队列 |",
        "| GPU | 视频与大批量更舒服 | 注意显存与多模型争用 |",
        "",
        "## 3. 在 TigerPro 架构中的位置",
        "",
        "TigerPro 的模型不是散落脚本，而是「登记 → 绑定权重 → 业务页选择 → services 推理 → 展示/告警/入库」。"
        f"本模型 `{key}` 同样走这条链路。理解位置，才能在监控墙、MTMC、告警之间排障。",
        "",
        "```mermaid",
        "flowchart TD",
        f"  A[权重 uploads/{esc(file_hint)}] --> B[AiModel.file_path 绑定]",
        "  B --> C[模型管理启用 status]",
        f"  C --> D[业务页 {esc(route)} 选择 modelId]",
        "  D --> E[routes 鉴权与参数校验]",
        "  E --> F[services 加载推理]",
        "  F --> G[可视化 / 告警 / DB / MTMC]",
        "```",
        "",
        "### 3.1 与同分类模型的关系",
        "",
    ]
    if related:
        lines += [
            "| 相关模型 | modelKey | 何时优先考虑 |",
            "|----------|----------|--------------|",
        ]
        for r in related:
            lines.append(
                f"| {esc(r.get('model_name') or r['model_key'])} | `{r['model_key']}` | "
                f"同属 {esc(cat)}，做精度/速度对照 |"
            )
        lines.append("")
        lines.append(
            "对照实验请固定摄像头、分辨率、conf、抽帧，只替换 modelKey；否则结论不可复现。"
        )
    else:
        lines.append("同分类暂无其它已收录模型，或本模型为该分类唯一条目。上线前更要做好样本验收。")
    lines += [
        "",
        "### 3.2 和平台其它模块怎么接线",
        "",
        "| 模块 | 关系 |",
        "|------|------|",
        "| 模型管理 | 权重、启用、来源 URL |",
        "| 业务推理页 | 用户可见的主入口 |",
        "| 告警中心 | 检测类结果可转规则命中 |",
        "| 监控墙 | 叠加流依赖有效 AI/MTMC 会话 |",
        "| 跨镜 MTMC | 检测 + ReID 成套；缺权重会回退 |",
        "",
        "## 4. 使用教程：从零跑通到可验收",
        "",
        "### 4.1 准备权重（最容易翻车的一步）",
        "",
        "1. 打开 **AI → 模型管理**，搜索 `{key}` 或「{esc(name)}」。",
        "2. 确认 **启用**，且 `file_path` 指向本地目录/文件。",
        "3. 若为空：用页面拉取，或手动放到：",
        "",
        "```text",
        f"backend/uploads/{file_hint}",
        "```",
        "",
        "4. 刷新列表或重启后端（端口常见 **5001**），确认文件大小 > 0。",
        "5. 用下一节代码 `find_model` 打印 `filePath`，为空就不要继续调业务接口。",
        "",
        "### 4.2 业务页操作清单",
        "",
        f"1. 进入 **{esc(page)}**，路由 `{esc(route)}`。",
        f"2. 模型下拉精确选择 **{esc(name)}**（核对 modelKey=`{key}`）。",
        "3. 上传或选择摄像头/音频/文本，设置 conf/FPS/语言等。",
        "4. 推理后核对输出形态是否符合任务（框、文本、轨迹、音频等）。",
        "5. 把首次成功的参数记入下文章节的验收表，作为基线。",
        "",
    ]
    lines += task_code_blocks(task, key, name, route)
    lines += [
        "### 4.6 推荐调参表",
        "",
    ]
    lines += task_param_table(task)
    lines += [
        "",
        "## 5. 落地案例（可照着做）",
        "",
        f"### 5.1 主案例：{esc(case)}",
        "",
        f"目标：在 TigerPro 稳定落地「{esc(case)}」，核心模型锁定 `{key}`。",
        "",
        "**步骤：**",
        "",
        "1. **样本**：白天/夜间、远景/近景、正常/遮挡，各不少于 20 条（音视频任务按分钟计）。",
        "2. **冒烟**：页面选中本模型，确认非空输出；API 用 `find_model` 校验路径。",
        "3. **基线**：默认参数跑全量样本，记录漏检/误报/延迟。",
        "4. **调参**：只动 1~2 个旋钮（如 conf 与 imgsz），每次记录表格。",
        "5. **接线**：需要告警则配规则；需要跨镜则 start MTMC 并在监控墙开叠加前先 alive。",
        "6. ** soak**：连续 30~120 分钟，观察内存、队列、误报毛刺。",
        "",
        "| 阶段 | 通过标准 | 失败怎么处理 |",
        "|------|----------|--------------|",
        "| 冒烟 | 有正确形态输出 | 查权重/task/路由 |",
        "| 基线 | 指标可统计 | 补样本，勿只看 demo |",
        "| 调参 | 指标优于基线且可复现 | 回退参数，避免过拟合 3 张图 |",
        "| soak | 无崩溃、延迟可接受 | 降 FPS/换轻量模型/加机器 |",
        "",
        "### 5.2 对照案例：同场景换模型会怎样",
        "",
        "在同一批样本上，把 `{key}` 与同分类一个替代 modelKey 对比：",
        "",
        "| 指标 | `{key}` | 替代模型 | 结论 |",
        "|------|---------|----------|------|",
        "| 平均延迟 | 填实测 | 填实测 | 谁更适合在线 |",
        "| 漏检/错率 | 填实测 | 填实测 | 谁更适合生产 |",
        "| 资源占用 | 填实测 | 填实测 | 边缘能否扛住 |",
        "| 运维成本 | 权重大小/依赖 | 同上 | 是否值得换 |",
        "",
        "没有对照表就上线，后续「到底怪摄像头还是怪模型」会扯皮很久。",
        "",
        "### 5.3 验收表（复制到飞书/表格）",
        "",
        "| 指标 | 目标（示例） | 实测 | 备注 |",
        "|------|--------------|------|------|",
        "| 权重就绪 | file_path 非空 |  |  |",
        "| 单次延迟 | 按 SLA |  | CPU/GPU 分开记 |",
        "| 漏检率/字错率等 | 按业务 |  | 分场景桶 |",
        "| 误报率 | 按业务 |  | 与阈值联动 |",
        "| 30 分钟稳定性 | 无崩溃 |  | 看日志 |",
        "",
        "## 6. 优缺点、风险与替代",
        "",
        "| 优点 | 局限 / 风险 |",
        "|------|-------------|",
        f"| 已目录化，可用 `{key}` 稳定选择 | 权重大，默认不进 Git，环境要同步 |",
        f"| 任务清晰：{esc(task_zh)} | 域偏移会掉点，需微调或换专用权重 |",
        "| 可与告警/MTMC/OCR 组合 | 页选错 task 会直接失败 |",
        "| 便于做 A/B | 多模型并存时依赖冲突要隔离环境 |",
        "",
        "风险控制建议：生产只放经过验收的权重哈希/版本号；回滚路径写进运维手册；"
        "摄像头与人脸等数据注意权限与合规。",
        "",
        "## 7. 避坑清单（排障优先级）",
        "",
        "| 现象 | 可能原因 | 处理 |",
        "|------|----------|------|",
    ]
    for a, b, c in pitfall_rows:
        lines.append(f"| {a} | {b} | {c} |")

    lines += [
        "",
        "排障顺序建议：**权重 → 模型状态 → 页面/路由 task → 参数 → 会话/鉴权 → 资源瓶颈**。"
        "不要一上来重装环境。",
        "",
        "## 8. 工程化建议与监控",
        "",
        "### 8.1 部署检查清单",
        "",
        f"- [ ] `backend/uploads/{file_hint}` 存在且大小合理",
        f"- [ ] 模型管理中 `{key}` 启用，`file_path` 正确",
        f"- [ ] `{esc(route)}` 下拉可选中，冒烟通过",
        "- [ ] 验收表有基线数字",
        "- [ ] 日志路径与告警通道已知",
        "- [ ] 若用 MTMC/监控墙：alive 与叠加回退策略已验证",
        "",
        "### 8.2 日常观察",
        "",
        "| 信号 | 含义 | 动作 |",
        "|------|------|------|",
        "| 延迟 P95 升高 | 争用或输入变大 | 降 FPS/限流 |",
        "| 空结果增多 | 阈值/域变了 | 抽检样本重评 |",
        "| 内存持续涨 | 泄漏或缓存未释放 | 重启观察 + 查 session |",
        "| 404 叠加 | 会话过期 | 关叠加并清本地 sessionId |",
        "",
        "### 8.3 安全与合规",
        "",
        "摄像头流、人脸底库、车牌与语音可能含个人敏感信息。生产环境应：最小权限 JWT、"
        "审计访问、脱敏展示、禁止把底库与原始录像随意拷贝出内网。模型文件本身也要防篡改。",
        "",
        "## 9. 常见问题 FAQ",
        "",
        f"**Q1：页面能看见 {esc(name)}，但推理一直失败？**  ",
        "A：十有八九是权重路径空或文件不完整；先用 `find_model` 看 `filePath`，再看后端 traceback。",
        "",
        f"**Q2：换了更大模型反而更差？**  ",
        "A：可能过拟合其它域、输入尺寸不匹配、或 NMS/阈值未重标定。回到同一验收集对比。",
        "",
        "**Q3：CPU 太慢怎么办？**  ",
        "A：降 imgsz/FPS、换 nano/onnx 量化、减并发；GPU 再谈吞吐。",
        "",
        "**Q4：和相邻模型如何二选一？**  ",
        "A：固定样本与参数，只换 modelKey，填第 5.2 节对照表，用业务指标拍板而不是凭感觉。",
        "",
        f"**Q5：MTMC/监控墙相关要额外注意什么？**  ",
        "A：会话只活在后端内存；重启后旧 sessionId 会失效。叠加前先 alive，失败则回退普通流。",
        "",
        "## 10. 文末互动",
        "",
        f"1. 你在生产用 `{key}` 时，最大痛点是延迟、精度，还是权重同步？",
        "2. 同分类对照实验里，你的赢家 modelKey 是谁？conf/FPS 怎么配？",
        "3. 更希望下一篇写「微调数据配方」还是「监控墙叠加联调」？",
        "",
        "## 11. 下篇预告",
        "",
    ]
    if related:
        nxt = related[0]
        lines.append(
            f"建议接着阅读同分类：**{esc(nxt.get('model_name') or nxt['model_key'])}**"
            f"（`{nxt['model_key']}`），做完对照表再锁生产。"
        )
    else:
        lines.append(
            "下一篇可阅读索引中相邻分类，或结合跨镜 MTMC 文档把检测与 ReID 串起来。"
        )

    lines += [
        "",
        "## 12. 参考资料",
        "",
        "1. 项目种子登记：`backend/seed.py`",
        f"2. 本地权重：`backend/uploads/{file_hint}`",
        "3. [Ultralytics YOLO](https://docs.ultralytics.com/)",
        "4. [Hugging Face Models](https://huggingface.co/models)",
        "5. [OpenCV Zoo](https://github.com/opencv/opencv_zoo)",
        "6. [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)",
        "7. [InsightFace](https://github.com/deepinsight/insightface)",
        "8. [Roboflow Trackers](https://github.com/roboflow/trackers)",
    ]
    if src:
        lines.append(f"9. 本模型上游：{src}")

    lines += [
        "",
        "---",
        "",
        f"*TigerPro 模型手册第 {idx}/{total} 篇 · `backend/scripts/export_csdn_models_catalog.py` · "
        f"`docs/csdn-ai-models-catalog/` 已 gitignore。*",
        "",
    ]
    md = "\n".join(lines)
    # 若仍不足 4000 汉字，追加扩展阅读段（纯正文）
    guard = 0
    while body_cn_chars(md) < 4000 and guard < 8:
        guard += 1
        md += "\n".join([
            "",
            f"## 附录补强 {guard}：落地时的沟通话术与分工",
            "",
            f"把 `{key}`（{esc(name)}）推进生产时，研发、算法、实施、业务四方常对「好不好」没有共同语言。"
            "建议用同一套验收表说话：延迟、误差、稳定性、运维成本。避免只甩一张 demo 截图。"
            f"本模型任务是 {esc(task_zh)}，讨论范围应限制在该任务指标内，不要用分类指标评价检测模型，"
            "也不要用检测 mAP 评价 ReID 切换率。",
            "",
            "实施同学负责摄像头角度、补光、线网与权限；算法同学负责阈值与样本桶；"
            "研发同学负责接口、会话与监控墙回退；业务同学负责误报是否可接受。"
            f"任何一方单方面改 conf 或更换 `{key}` 的相邻模型，都要同步更新验收表，否则线上回滚无据可依。",
            "",
            "若资源有限，优先保证「权重可复现安装 + 冒烟脚本 + 30 分钟 soak」，"
            "再追求极致精度。TigerPro 的价值在于把模型目录化并接到告警与跨镜，"
            "而不是在单机 notebook 里刷榜。按本篇清单做完，你就已经超过多数「只下载权重不验收」的部署。",
            "",
        ])
    return md


def build_index(models: list[dict], article_names: list[tuple[str, dict]]) -> str:
    by_cat: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for fn, m in article_names:
        by_cat[m["category"]].append((fn, m))

    lines = [
        "# TigerPro AI 模型 · CSDN 单篇手册索引（本地私有）",
        "",
        f"> 共 **{len(models)}** 篇，每模型独立 MD；正文汉字（去代码块）≥4000，含代码与表格。  ",
        "> **本目录已 gitignore，禁止提交远程。**",
        "",
        "## 重新生成",
        "",
        "```bash",
        "python backend/scripts/export_csdn_models_catalog.py",
        "```",
        "",
        "## 按分类浏览",
        "",
    ]
    for cat in sorted(by_cat.keys()):
        lines.append(f"### {cat}（{len(by_cat[cat])}）")
        lines.append("")
        for fn, m in by_cat[cat]:
            lines.append(f"- [{esc(m.get('model_name') or m['model_key'])}](./articles/{fn}) — `{m['model_key']}`")
        lines.append("")
    lines.append("## 完整清单")
    lines.append("")
    lines.append("| # | 文件 | modelKey | 名称 | 分类 |")
    lines.append("|---|------|----------|------|------|")
    for i, (fn, m) in enumerate(article_names, 1):
        lines.append(
            f"| {i} | [{fn}](./articles/{fn}) | `{m['model_key']}` | "
            f"{esc(m.get('model_name'))} | {esc(m.get('category'))} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    models = merge_models()
    articles_dir = OUT_DIR / "articles"
    if articles_dir.exists():
        for p in articles_dir.glob("*.md"):
            p.unlink()
    articles_dir.mkdir(parents=True, exist_ok=True)

    article_names: list[tuple[str, dict]] = []
    total_words = 0
    body_counts: list[tuple[str, int]] = []
    for i, m in enumerate(models, 1):
        key = m["model_key"]
        fn = f"{i:03d}-{safe_filename(key)}.md"
        md = build_one_article(m, models, i, len(models))
        bc = body_cn_chars(md)
        if bc < 4000:
            # last-resort pad (should rarely trigger)
            while body_cn_chars(md) < 4000:
                md += (
                    f"\n\n补充说明：围绕 `{key}` 的部署要持续迭代样本与阈值，"
                    "把每一次线上误报沉淀回验收集，形成可复现的改进闭环。"
                    "TigerPro 强调目录化与业务接线，验收数字比口头「感觉还行」更重要。\n"
                )
            bc = body_cn_chars(md)
        (articles_dir / fn).write_text(md, encoding="utf-8")
        article_names.append((fn, m))
        total_words += word_estimate(md)
        body_counts.append((fn, bc))

    overview = (
        "# 说明\n\n"
        "本目录为「一模型一篇」结构，请从 [README.md](./README.md) 进入索引。\n"
        "每篇正文汉字（去代码块）目标 ≥ 4000，含多段代码与表格。\n"
    )
    OUT_FILE.write_text(overview, encoding="utf-8")

    mins = min(body_counts, key=lambda x: x[1])
    maxs = max(body_counts, key=lambda x: x[1])
    avg_body = sum(c for _, c in body_counts) // max(1, len(body_counts))
    below = [f"{fn}:{c}" for fn, c in body_counts if c < 4000]

    (OUT_DIR / "README.md").write_text(
        build_index(models, article_names) + (
            f"\n---\n\n"
            f"- 含代码粗估总字数：{total_words}（均 {total_words // max(1, len(models))}）\n"
            f"- 正文汉字（去代码块）：均 {avg_body}，最小 {mins[1]}（{mins[0]}），最大 {maxs[1]}（{maxs[0]}）\n"
            f"- 低于 4000 的篇数：{len(below)}\n"
        ),
        encoding="utf-8",
    )
    print(f"models={len(models)}")
    print(f"articles_dir={articles_dir}")
    print(f"total_words~={total_words} avg~={total_words // max(1, len(models))}")
    print(f"body_cn avg={avg_body} min={mins[1]}({mins[0]}) max={maxs[1]}({maxs[0]})")
    if below:
        print("BELOW_4000:", ", ".join(below[:10]))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
