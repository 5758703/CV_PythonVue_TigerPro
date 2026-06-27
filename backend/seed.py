"""初始化种子数据（幂等：已有用户则跳过）。

可独立运行： python seed.py
启动时 app.py 也会自动调用 init_seed()。
"""
from extensions import db
from models import User, Role, Dept, Job, Menu, AiModel


def _dept(id, parent_id, ancestors, name, order, leader=None):
    return Dept(id=id, parent_id=parent_id, ancestors=ancestors,
                dept_name=name, order_num=order, leader=leader, status="0", del_flag="0")


def _menu(id, parent_id, name, mtype, perms=None, path=None,
          component=None, icon=None, order=0):
    return Menu(id=id, parent_id=parent_id, menu_name=name, menu_type=mtype,
                perms=perms, path=path, component=component, icon=icon,
                order_num=order, visible="0", status="0")


def _seed_depts():
    depts = [
        _dept(100, 0, "0", "总公司", 0, "Tiger"),
        _dept(101, 100, "0,100", "研发部", 1),
        _dept(102, 101, "0,100,101", "前端组", 1),
        _dept(103, 101, "0,100,101", "后端组", 2),
        _dept(104, 100, "0,100", "市场部", 2),
    ]
    db.session.add_all(depts)


def _seed_jobs():
    jobs = [
        Job(id=1, post_code="ceo", post_name="董事长", post_sort=1, status="0"),
        Job(id=2, post_code="se", post_name="项目经理", post_sort=2, status="0"),
        Job(id=3, post_code="hr", post_name="人力资源", post_sort=3, status="0"),
        Job(id=4, post_code="user", post_name="普通员工", post_sort=4, status="0"),
    ]
    db.session.add_all(jobs)


def _seed_menus():
    menus = []
    # 目录
    menus.append(_menu(1, 0, "系统管理", "M", path="/system", icon="Setting", order=1))
    # 菜单 + 按钮 + API
    modules = [
        # (mid, name, biz, icon)
        (100, "用户管理", "user", "User"),
        (101, "角色管理", "role", "UserFilled"),
        (102, "部门管理", "dept", "OfficeBuilding"),
        (103, "岗位管理", "job", "Postcard"),
        (104, "菜单管理", "menu", "Menu"),
    ]
    for mid, name, biz, icon in modules:
        menus.append(_menu(mid, 1, name, "C", perms=f"system:{biz}:list",
                           path=biz, component=f"system/{biz}/index", icon=icon, order=mid - 99))
        base = mid * 10
        # 按钮权限（前端 v-permission）
        menus.append(_menu(base + 1, mid, f"{name}查询", "F", perms=f"system:{biz}:query"))
        menus.append(_menu(base + 2, mid, f"{name}新增", "F", perms=f"system:{biz}:add"))
        menus.append(_menu(base + 3, mid, f"{name}修改", "F", perms=f"system:{biz}:edit"))
        menus.append(_menu(base + 4, mid, f"{name}删除", "F", perms=f"system:{biz}:remove"))
        # API 接口权限（后端校验）
        menus.append(_menu(base + 5, mid, f"{name}接口", "A", perms=f"system:{biz}:api"))
    db.session.add_all(menus)
    return menus


def _ensure_ai_menu(mid, parent_id, name, mtype, perms, path=None,
                    component=None, icon=None, order=0, grant_common=False):
    """增量补丁：按 id 幂等补充单个 AI 菜单（老库升级新菜单/按钮用）。"""
    if Menu.query.get(mid):
        return
    m = _menu(mid, parent_id, name, mtype, perms=perms, path=path,
              component=component, icon=icon, order=order)
    db.session.add(m)
    db.session.flush()
    admin = Role.query.filter_by(role_key="admin").first()
    if admin:
        admin.menus = list(admin.menus) + [m]
    if grant_common:
        common = Role.query.filter_by(role_key="common").first()
        if common:
            common.menus = list(common.menus) + [m]
    db.session.commit()


def seed_ai_menus():
    """AI 智能识别菜单种子（独立幂等：菜单不存在才写，已初始化项目也会补齐）。

    超级管理员 is_admin 自动可见；普通角色授予只读(菜单 + 查询)。
    """
    if not Menu.query.get(200):
        menus = []
        # 目录：order=0 排在「系统管理」(order=1)之前
        menus.append(_menu(200, 0, "AI智能识别", "M", path="/ai", icon="Cpu", order=0))
        pages = [
            # (id, name, biz, icon)
            (201, "模型管理", "model", "Files"),
            (202, "图片检测", "image", "Picture"),
            (203, "视频检测", "video", "VideoCamera"),
            (204, "摄像头实时检测", "camera", "Monitor"),
            (205, "文本分析", "text", "ChatLineSquare"),
            (206, "图像分类", "imgcls", "PictureFilled"),
        ]
        for mid, name, biz, icon in pages:
            menus.append(_menu(mid, 200, name, "C", perms=f"ai:{biz}:list",
                               path=biz, component=f"ai/{biz}/index", icon=icon, order=mid - 200))
        # 模型管理按钮 / 接口权限（与后端 ai:model:* 校验对应）
        menus.append(_menu(2011, 201, "模型查询", "F", perms="ai:model:query"))
        menus.append(_menu(2012, 201, "模型新增", "F", perms="ai:model:add"))
        menus.append(_menu(2013, 201, "模型修改", "F", perms="ai:model:edit"))
        menus.append(_menu(2014, 201, "模型删除", "F", perms="ai:model:remove"))
        menus.append(_menu(2015, 201, "模型接口", "A", perms="ai:model:api"))
        menus.append(_menu(2016, 201, "模型下载", "F", perms="ai:model:download"))
        db.session.add_all(menus)
        db.session.flush()

        # 授权：管理员全量；普通角色只读（菜单 + 查询）
        admin = Role.query.filter_by(role_key="admin").first()
        if admin:
            admin.menus = list(admin.menus) + menus
        common = Role.query.filter_by(role_key="common").first()
        if common:
            view = [m for m in menus if m.menu_type in ("M", "C")
                    or (m.perms and m.perms.endswith(":query"))]
            common.menus = list(common.menus) + view
        db.session.commit()

    # 增量补丁：老库补齐后续新增的菜单/按钮（幂等）
    _ensure_ai_menu(2016, 201, "模型下载", "F", "ai:model:download")
    _ensure_ai_menu(205, 200, "文本分析", "C", "ai:text:list",
                    path="text", component="ai/text/index", icon="ChatLineSquare",
                    order=5, grant_common=True)
    _ensure_ai_menu(206, 200, "图像分类", "C", "ai:imgcls:list",
                    path="imgcls", component="ai/imgcls/index", icon="PictureFilled",
                    order=6, grant_common=True)
    _ensure_ai_menu(207, 200, "文本生成", "C", "ai:generate:list",
                    path="generate", component="ai/generate/index", icon="ChatDotRound",
                    order=7, grant_common=True)
    _ensure_ai_menu(208, 200, "实体识别", "C", "ai:ner:list",
                    path="ner", component="ai/ner/index", icon="Connection",
                    order=8, grant_common=True)
    _ensure_ai_menu(209, 200, "智能问答", "C", "ai:qa:list",
                    path="qa", component="ai/qa/index", icon="QuestionFilled",
                    order=9, grant_common=True)
    _ensure_ai_menu(210, 200, "语音识别", "C", "ai:asr:list",
                    path="asr", component="ai/asr/index", icon="Microphone",
                    order=10, grant_common=True)
    _ensure_ai_menu(211, 200, "数字人合成", "C", "ai:talker:list",
                    path="talker", component="ai/talker/index", icon="VideoCamera",
                    order=11, grant_common=True)
    _ensure_ai_menu(212, 200, "文本转语音", "C", "ai:tts:list",
                    path="tts", component="ai/tts/index", icon="Headset",
                    order=12, grant_common=True)
    _ensure_ai_menu(213, 200, "目标追踪", "C", "ai:track:list",
                    path="track", component="ai/track/index", icon="Aim",
                    order=13, grant_common=True)
    return True


def _ensure_ai_model(key, fields):
    """按 model_key 幂等补充单个模型种子。"""
    if AiModel.query.filter_by(model_key=key).first():
        return False
    db.session.add(AiModel(model_key=key, **fields))
    db.session.commit()
    return True


def seed_ai_models():
    """AI 模型种子（按标识幂等，老库也会补齐新增的范例模型）。"""
    created = False
    created |= _ensure_ai_model("fire-smoke-detection", dict(
        model_name="烟雾探测", category="烟火检测",
        task="object-detection", library="ultralytics", version="v1",
        source_url="https://huggingface.co/SalahALHaismawi/yolov26-fire-detection",
        description="基于 YOLO 的烟雾/火焰检测模型，用于火灾隐患预警。", status="0",
    ))
    created |= _ensure_ai_model("ppe-detection", dict(
        model_name="PPE穿戴识别", category="安全防护",
        task="object-detection", library="ultralytics", version="v1",
        source_url="https://huggingface.co/Hexmon/vyra-yolo-ppe-detection",
        description="基于 YOLO 的个人防护装备(PPE)穿戴检测模型，识别安全帽、反光衣等。", status="0",
    ))
    # YOLOv8 文档表格检测（drop-in，复用图片/视频/摄像头检测页）
    created |= _ensure_ai_model("yolov8m-table-extraction", dict(
        model_name="文档表格检测", category="文档解析",
        task="object-detection", library="ultralytics", version="v1",
        source_url="https://huggingface.co/keremberke/yolov8m-table-extraction",
        description="YOLOv8 文档表格检测（bordered/borderless），用于图片/视频/摄像头检测页。", status="0",
    ))
    created |= _ensure_ai_model("finbert", dict(
        model_name="FinBERT 金融情感分析", category="金融NLP",
        task="text-classification", library="transformers", version="v1",
        source_url="https://huggingface.co/ProsusAI/finbert",
        description="FinBERT 金融文本情感分析模型，输出 positive/negative/neutral 三类概率。", status="0",
    ))
    # 阶段B 示例：transformers 目标检测（复用检测页）
    created |= _ensure_ai_model("detr-resnet-50", dict(
        model_name="DETR 通用目标检测", category="通用检测",
        task="object-detection", library="transformers", version="v1",
        source_url="https://huggingface.co/facebook/detr-resnet-50",
        description="Facebook DETR 通用目标检测(COCO 80类)，transformers 引擎，可用于图片/视频/摄像头检测页。", status="0",
    ))
    # 阶段C 示例：transformers 图像分类
    created |= _ensure_ai_model("vit-base", dict(
        model_name="ViT 通用图像分类", category="通用分类",
        task="image-classification", library="transformers", version="v1",
        source_url="https://huggingface.co/google/vit-base-patch16-224",
        description="Google ViT 图像分类(ImageNet 1000类)，transformers 引擎，用于图像分类页。", status="0",
    ))
    # NLP 任务示例（A 文本分类 / B 零样本·完形 / C 翻译·摘要 / D NER·QA）
    created |= _ensure_ai_model("bert-emotion", dict(
        model_name="BERT 情绪识别", category="情感NLP",
        task="text-classification", library="transformers", version="v1",
        source_url="https://huggingface.co/bhadresh-savani/bert-base-uncased-emotion",
        description="文本情绪识别(anger/joy/sadness/fear/surprise/love)，文本分析页使用。", status="0",
    ))
    created |= _ensure_ai_model("bart-mnli", dict(
        model_name="BART 零样本分类", category="通用NLP",
        task="zero-shot-classification", library="transformers", version="v1",
        source_url="https://huggingface.co/facebook/bart-large-mnli",
        description="零样本文本分类：自定义候选标签，无需训练。文本分析页使用。", status="0",
    ))
    created |= _ensure_ai_model("bert-fill-mask", dict(
        model_name="BERT 完形填空", category="通用NLP",
        task="fill-mask", library="transformers", version="v1",
        source_url="https://huggingface.co/bert-base-uncased",
        description="预测 [MASK] 处词语。文本分析页使用。", status="0",
    ))
    created |= _ensure_ai_model("distilbart-cnn", dict(
        model_name="DistilBART 文本摘要", category="文本摘要",
        task="summarization", library="transformers", version="v1",
        source_url="https://huggingface.co/sshleifer/distilbart-cnn-12-6",
        description="长文本摘要。文本生成页使用。", status="0",
    ))
    created |= _ensure_ai_model("opus-mt-en-zh", dict(
        model_name="Opus 英译中", category="机器翻译",
        task="translation", library="transformers", version="v1",
        source_url="https://huggingface.co/Helsinki-NLP/opus-mt-en-zh",
        description="英文→中文机器翻译。文本生成页使用。", status="0",
    ))
    created |= _ensure_ai_model("bert-ner", dict(
        model_name="BERT 命名实体识别", category="实体识别",
        task="token-classification", library="transformers", version="v1",
        source_url="https://huggingface.co/dslim/bert-base-NER",
        description="英文 NER(人名/地名/机构/其他)。实体识别页使用。", status="0",
    ))
    created |= _ensure_ai_model("distilbert-squad", dict(
        model_name="DistilBERT 抽取式问答", category="智能问答",
        task="question-answering", library="transformers", version="v1",
        source_url="https://huggingface.co/distilbert-base-cased-distilled-squad",
        description="给定上下文回答问题(抽取式)。智能问答页使用。", status="0",
    ))
    # 语音识别（funasr SenseVoice，ModelScope 原生来源，验证 ModelScope 下载源）
    created |= _ensure_ai_model("sensevoice-small", dict(
        model_name="SenseVoice 语音识别", category="语音识别",
        task="automatic-speech-recognition", library="funasr", version="v1",
        source_url="https://modelscope.cn/models/iic/SenseVoiceSmall",
        description="多语种语音识别 + 语音情感 + 音频事件检测（中/英/粤/日/韩）。语音识别页使用。", status="0",
    ))
    # 语音识别（Paraformer 中英，funasr 引擎，非自回归、工业级准确率，复用 SenseVoice 同款推理）
    created |= _ensure_ai_model("paraformer-zh", dict(
        model_name="Paraformer 中英语音识别", category="语音识别",
        task="automatic-speech-recognition", library="funasr", version="v1",
        source_url="https://huggingface.co/funasr/paraformer-zh",
        description="Paraformer 中英语音识别(funasr)，非自回归、工业级准确率(中文 CER ~1-2%)，CPU 快。语音识别页使用。", status="0",
    ))
    # 语音识别（SenseVoice 量化 onnx，242MB，更小更快；funasr_onnx 引擎）
    created |= _ensure_ai_model("sensevoice-small-onnx", dict(
        model_name="SenseVoice 语音识别(onnx量化)", category="语音识别",
        task="automatic-speech-recognition", library="funasr-onnx", version="v1",
        source_url="https://modelscope.cn/models/iic/SenseVoiceSmall-onnx",
        description="SenseVoice 量化 onnx 版（242MB，约 1/4 体积），CPU 更快。中/英/粤/日/韩。语音识别页使用。", status="0",
    ))
    # 数字人合成（Linly-Talker/SadTalker，脚手架：生成需 GPU + SadTalker 运行环境）
    created |= _ensure_ai_model("linly-talker", dict(
        model_name="Linly-Talker 数字人", category="数字人",
        task="talking-head", library="linly", version="v1",
        source_url="https://huggingface.co/Kedreamix/Linly-Talker",
        description="人像图 + 驱动音频 → 说话头像视频(SadTalker)。需 GPU 运行环境，当前为脚手架。", status="0",
    ))
    # 文本转语音（CosyVoice-300M-SFT，ModelScope 来源；本地推理需官方 CosyVoice 代码）
    created |= _ensure_ai_model("cosyvoice-300m-sft", dict(
        model_name="CosyVoice 文本转语音", category="语音合成",
        task="text-to-speech", library="cosyvoice", version="v1",
        source_url="https://modelscope.cn/models/iic/CosyVoice-300M-SFT",
        description="文本 + 预置音色(中/英/粤/日/韩) → 语音(SFT)。需官方 CosyVoice 推理代码接入 PYTHONPATH。", status="0",
    ))
    # 文本转语音 / 零样本音色克隆（CosyVoice2-0.5B，ModelScope；需 third_party/CosyVoice 官方代码）
    created |= _ensure_ai_model("cosyvoice2-0.5b", dict(
        model_name="CosyVoice2 零样本克隆", category="语音合成",
        task="text-to-speech", library="cosyvoice", version="v2",
        source_url="https://modelscope.cn/models/iic/CosyVoice2-0.5B",
        description="零样本音色克隆：上传参考音频(+其文本) → 用该音色读新文本(中/英/粤/日/韩)。需官方 CosyVoice 代码(third_party/CosyVoice)。", status="0",
    ))
    # 文本转语音（MMS-TTS / VITS，transformers 原生 pipeline，CPU 直接可用）
    # 注：Facebook MMS-TTS 无 Mandarin(cmn) 仓库，中文 TTS 走 CosyVoice。
    created |= _ensure_ai_model("mms-tts-eng", dict(
        model_name="MMS-TTS 英文语音合成", category="语音合成",
        task="text-to-speech", library="transformers", version="v1",
        source_url="https://huggingface.co/facebook/mms-tts-eng",
        description="Facebook MMS-TTS 英文(VITS)文本转语音，transformers 引擎，CPU 可用。文本转语音页使用。", status="0",
    ))
    # 文本转语音（VibeVoice-Realtime-0.5B，预置音色，~300ms 首字延迟；需 third_party/VibeVoice 官方代码）
    created |= _ensure_ai_model("vibevoice-realtime", dict(
        model_name="VibeVoice 实时语音合成", category="语音合成",
        task="text-to-speech", library="vibevoice", version="v1",
        source_url="https://modelscope.cn/models/microsoft/VibeVoice-Realtime-0.5B",
        description="微软 VibeVoice-Realtime-0.5B，预置多音色(en/de/fr/jp/kr 等)，实时高拟真。需官方代码(third_party/VibeVoice)。", status="0",
    ))
    # 文本转语音（MeloTTS 中英混合 onnx，sherpa-onnx 引擎，纯 onnx、小而快、CPU）
    created |= _ensure_ai_model("melotts-zh-en", dict(
        model_name="MeloTTS 中英混合合成", category="语音合成",
        task="text-to-speech", library="sherpa-onnx", version="v1",
        source_url="https://huggingface.co/wolfofbackstreet/melotts_chinese_mix_english_onnx",
        description="MeloTTS 中英混合 onnx(sherpa-onnx 引擎)，纯 onnx、小而快、CPU 秒级，中英混读。文本转语音页使用。", status="0",
    ))
    return created
    return True


def init_seed():
    if User.query.first():
        seed_ai_menus()   # 用户已存在也补齐 AI 菜单种子
        seed_ai_models()  # 用户已存在也补齐 AI 模型种子
        return False  # 已初始化

    _seed_depts()
    _seed_jobs()
    _seed_menus()
    db.session.flush()

    all_menus = Menu.query.all()
    # 普通角色：只读（list/query 菜单与按钮）
    view_menus = [m for m in all_menus
                  if m.menu_type in ("M", "C")
                  or (m.perms and m.perms.endswith(":query"))]

    admin_role = Role(id=1, role_name="超级管理员", role_key="admin", role_sort=1,
                      data_scope=4, status="0", remark="拥有全部权限")
    admin_role.menus = all_menus

    common_role = Role(id=2, role_name="普通角色", role_key="common", role_sort=2,
                       data_scope=2, status="0", remark="本部门数据 + 只读")
    common_role.menus = view_menus

    db.session.add_all([admin_role, common_role])
    db.session.flush()

    dept100 = Dept.query.get(100)
    dept102 = Dept.query.get(102)
    job_ceo = Job.query.get(1)
    job_user = Job.query.get(4)

    admin = User(username="admin", nickname="管理员", dept_id=100,
                 email="admin@tigerpro.com", phone="13800000000", sex="0", status="0")
    admin.set_password("admin123")
    admin.roles = [admin_role]
    admin.depts = [dept100]
    admin.posts = [job_ceo]

    tiger = User(username="tiger", nickname="测试用户", dept_id=102,
                 email="tiger@tigerpro.com", phone="13900000000", sex="0", status="0")
    tiger.set_password("123456")
    tiger.roles = [common_role]
    tiger.depts = [dept102]
    tiger.posts = [job_user]

    db.session.add_all([admin, tiger])
    db.session.commit()

    seed_ai_menus()
    seed_ai_models()
    return True


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        created = init_seed()
        print("种子数据已写入" if created else "已存在数据，跳过")
