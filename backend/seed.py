"""初始化种子数据（幂等：已有用户则跳过）。

可独立运行： python seed.py
启动时 app.py 也会自动调用 init_seed()。
"""
import os
import shutil

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
    menus.append(_menu(1, 0, "系统管理", "M", path="/system", icon="Setting", order=2))
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


def _regroup_ai_menus():
    """把 AI 叶子菜单重挂到分组目录，并将 path 改为绝对（幂等）。

    _ensure_ai_menu 只新增不更新，故重挂单列。叶子 path 改绝对 /ai/<biz>，
    使其无论挂在哪个分组下 MenuItem.fullPath 都等于现有静态路由，路由/高亮不变。
    """
    # (leaf_id, group_id, abs_path)
    moves = [
        (202, 230, "/ai/image"), (203, 230, "/ai/video"), (204, 230, "/ai/camera"),
        (206, 230, "/ai/imgcls"), (213, 230, "/ai/track"), (214, 230, "/ai/pose"),
        (250, 230, "/ai/water"), (270, 230, "/ai/badminton"), (272, 230, "/ai/segment"),
        (274, 230, "/ai/face"),
        (276, 230, "/ai/alert"),
        (278, 230, "/ai/table"),
        (205, 231, "/ai/text"), (207, 231, "/ai/generate"),
        (208, 231, "/ai/ner"), (209, 231, "/ai/qa"),
        (210, 232, "/ai/asr"), (212, 232, "/ai/tts"),
        (211, 233, "/ai/talker"),
    ]
    changed = False
    for leaf_id, group_id, abs_path in moves:
        m = Menu.query.get(leaf_id)
        if m and (m.parent_id != group_id or m.path != abs_path):
            m.parent_id = group_id
            m.path = abs_path
            changed = True
    if changed:
        db.session.commit()


def _regroup_model_menus():
    """「模型管理」升级为目录：下挂模型列表(2010) + 模型训练(260)。"""
    changed = False
    m201 = Menu.query.get(201)
    if not m201:
        return

    if m201.menu_type != "M" or m201.path != "/ai/model-center":
        m201.menu_type = "M"
        m201.path = "/ai/model-center"
        m201.component = None
        m201.perms = None
        m201.icon = m201.icon or "Files"
        changed = True

    if not Menu.query.get(2010):
        m2010 = _menu(2010, 201, "模型列表", "C", perms="ai:model:list",
                      path="/ai/model", component="ai/model/index", icon="Files", order=1)
        db.session.add(m2010)
        db.session.flush()
        admin = Role.query.filter_by(role_key="admin").first()
        if admin:
            admin.menus = list(admin.menus) + [m2010]
        common = Role.query.filter_by(role_key="common").first()
        if common:
            common.menus = list(common.menus) + [m2010]
        changed = True
    else:
        m2010 = Menu.query.get(2010)
        if m2010.parent_id != 201 or m2010.path != "/ai/model":
            m2010.parent_id = 201
            m2010.path = "/ai/model"
            m2010.component = m2010.component or "ai/model/index"
            m2010.perms = m2010.perms or "ai:model:list"
            changed = True

    m2010 = Menu.query.get(2010)
    if m2010:
        for bid in (2011, 2012, 2013, 2014, 2015, 2016):
            b = Menu.query.get(bid)
            if b and b.parent_id != m2010.id:
                b.parent_id = m2010.id
                changed = True
        for role in Role.query.all():
            ids = {m.id for m in role.menus}
            if 201 in ids and m2010.id not in ids:
                role.menus = list(role.menus) + [m2010]
                changed = True

    m260 = Menu.query.get(260)
    if m260 and m260.parent_id != 201:
        m260.parent_id = 201
        m260.order_num = 2
        changed = True

    if changed:
        db.session.commit()


def _patch_video_surveillance_menu():
    """「摄像头」目录更名为「视频监控」；监控墙菜单命名对齐（幂等）。"""
    changed = False
    m245 = Menu.query.get(245)
    if m245:
        if m245.menu_name != "视频监控":
            m245.menu_name = "视频监控"
            changed = True
        if m245.order_num != 1:
            m245.order_num = 1
            changed = True
    m241 = Menu.query.get(241)
    if m241 and m241.menu_name != "监控墙":
        m241.menu_name = "监控墙"
        changed = True
    m1 = Menu.query.get(1)
    if m1 and m1.order_num != 2:
        m1.order_num = 2
        changed = True
    if changed:
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
    _ensure_ai_menu(214, 200, "姿态估计", "C", "ai:pose:list",
                    path="pose", component="ai/pose/index", icon="Avatar",
                    order=14, grant_common=True)
    # 分组目录（menu_type M）：把扁平 AI 菜单归类
    _ensure_ai_menu(230, 200, "视觉识别", "M", None, path="vision",
                    icon="View", order=2, grant_common=True)
    _ensure_ai_menu(231, 200, "文本处理", "M", None, path="text-suite",
                    icon="Document", order=3, grant_common=True)
    _ensure_ai_menu(232, 200, "语音处理", "M", None, path="speech",
                    icon="Microphone", order=4, grant_common=True)
    _ensure_ai_menu(233, 200, "多模态", "M", None, path="multimodal",
                    icon="MagicStick", order=5, grant_common=True)
    _regroup_ai_menus()
    _ensure_ai_menu(215, 230, "文字识别 OCR", "C", "ai:ocr:list",
                    path="/ai/ocr", component="ai/ocr/index", icon="Document",
                    order=7, grant_common=True)
    _ensure_ai_menu(216, 230, "PaddleOCR 识别", "C", "ai:paddleocr:list",
                    path="/ai/paddleocr", component="ai/paddleocr/index", icon="Document",
                    order=8, grant_common=True)
    _ensure_ai_menu(278, 230, "表格识别", "C", "ai:table:list",
                    path="/ai/table", component="ai/table/index", icon="Grid",
                    order=9, grant_common=True)
    _ensure_ai_menu(2781, 278, "表格识别查询", "F", "ai:table:query", grant_common=True)
    # 视频监控（顶级目录，order=1 排在 AI(0) 与系统管理(2) 之间）
    _ensure_ai_menu(240, 0, "摄像头管理", "C", "camera:list",
                    path="/camera", component="camera/index", icon="VideoCamera",
                    order=1, grant_common=True)
    _ensure_ai_menu(2401, 240, "摄像头查询", "F", "camera:query", grant_common=True)
    _ensure_ai_menu(2402, 240, "摄像头新增", "F", "camera:add")
    _ensure_ai_menu(2403, 240, "摄像头修改", "F", "camera:edit")
    _ensure_ai_menu(2404, 240, "摄像头删除", "F", "camera:remove")
    # 升级为「视频监控」目录，下挂 摄像头管理(240) + 实时监控大屏(241)
    _ensure_ai_menu(245, 0, "视频监控", "M", None, path="/camera-center",
                    icon="VideoCamera", order=1, grant_common=True)
    _m240 = Menu.query.get(240)
    if _m240 and _m240.parent_id != 245:   # 把已存在的「摄像头管理」归入分组（幂等）
        _m240.parent_id = 245
        db.session.commit()
    _ensure_ai_menu(241, 245, "监控墙", "C", "camera:list",
                    path="/camera/wall", component="camera/wall/index", icon="Monitor",
                    order=2, grant_common=True)
    _patch_video_surveillance_menu()
    # 水位检测（视觉识别分组 230 下，order=9）
    _ensure_ai_menu(250, 230, "水位检测", "C", "ai:water:list",
                    path="/ai/water", component="ai/water/index", icon="Pouring",
                    order=9, grant_common=True)
    _ensure_ai_menu(2501, 250, "水位检测查询", "F", "ai:water:query", grant_common=True)
    # 羽毛球视频分析（视觉识别 230 下，order=10）
    _ensure_ai_menu(270, 230, "羽毛球分析", "C", "ai:badminton:list",
                    path="/ai/badminton", component="ai/badminton/index", icon="Trophy",
                    order=10, grant_common=True)
    _ensure_ai_menu(2701, 270, "羽毛球分析查询", "F", "ai:badminton:query", grant_common=True)

    _ensure_ai_menu(272, 230, "图像分割", "C", "ai:segment:list",
                    path="/ai/segment", component="ai/segment/index", icon="Crop",
                    order=12, grant_common=True)
    _ensure_ai_menu(2721, 272, "图像分割查询", "F", "ai:segment:query", grant_common=True)
    # 人脸识别（视觉识别 230 下）
    _ensure_ai_menu(274, 230, "人脸识别", "C", "ai:face:list",
                    path="/ai/face", component="ai/face/index", icon="User",
                    order=13, grant_common=True)
    _ensure_ai_menu(2741, 274, "人脸识别查询", "F", "ai:face:query", grant_common=True)
    _ensure_ai_menu(2742, 274, "人脸底库新增", "F", "ai:face:add")
    _ensure_ai_menu(2743, 274, "人脸底库修改", "F", "ai:face:edit")
    _ensure_ai_menu(2744, 274, "人脸底库删除", "F", "ai:face:remove")
    # 检测告警（视觉识别 230 下）
    _ensure_ai_menu(276, 230, "检测告警", "C", "ai:alert:list",
                    path="/ai/alert", component="ai/alert/index", icon="Bell",
                    order=14, grant_common=True)
    _ensure_ai_menu(2761, 276, "告警查询", "F", "ai:alert:query", grant_common=True)
    _ensure_ai_menu(2762, 276, "告警确认", "F", "ai:alert:edit")
    _ensure_ai_menu(2763, 276, "告警删除", "F", "ai:alert:remove")
    _ensure_ai_menu(2764, 276, "规则配置", "F", "ai:alert:edit")  # 与确认共用 edit 权限，管理员可改规则/样式
    # 老库曾误写 WaterMelon（非 Element Plus 图标名），修正为 Pouring
    _m250 = Menu.query.get(250)
    if _m250 and _m250.icon in (None, "", "WaterMelon", "Watermelon"):
        _m250.icon = "Pouring"
        db.session.commit()
    # 模型训练（模型管理目录 201 下，order=2）
    _ensure_ai_menu(260, 201, "模型训练", "C", "ai:training:list",
                    path="/ai/training", component="ai/training/index", icon="Cpu",
                    order=2, grant_common=True)
    _ensure_ai_menu(2601, 260, "训练查询", "F", "ai:training:query", grant_common=True)
    _ensure_ai_menu(2602, 260, "训练新增", "F", "ai:training:add")
    _ensure_ai_menu(2603, 260, "训练修改", "F", "ai:training:edit")
    _ensure_ai_menu(2604, 260, "训练删除", "F", "ai:training:remove")
    _regroup_model_menus()
    return True


def _ensure_ai_model(key, fields):
    """按 model_key 幂等补充单个模型种子。"""
    if AiModel.query.filter_by(model_key=key).first():
        return False
    db.session.add(AiModel(model_key=key, **fields))
    db.session.commit()
    return True


def _bind_local_brain_tumor_weight():
    """绑定本地已下载的脑肿瘤模型目录（幂等更新 file_path/file_size/status）。"""
    m = AiModel.query.filter_by(model_key="brain-tumor-yolo-opennoor").first()
    if not m:
        return False
    rel = "models/OpenNoorIlmNoor-Ul-Ilm-Brain-Tumor-Yolo"
    base = os.path.dirname(os.path.abspath(__file__))
    abs_dir = os.path.join(base, "uploads", rel.replace("/", os.sep))
    if not os.path.isdir(abs_dir):
        # 权重目录不存在：先停用，避免前端显示后再报“暂无本地权重”
        if m.status != "1":
            m.status = "1"
            db.session.commit()
            return True
        return False
    size = 0
    for root, _dirs, files in os.walk(abs_dir):
        for f in files:
            fp = os.path.join(root, f)
            if os.path.isfile(fp):
                size += os.path.getsize(fp)
    changed = False
    if m.file_path != rel:
        m.file_path = rel
        changed = True
    # 允许补齐分类/名称等元信息，保证报告提示词触发“医学场景”
    if m.model_name != "脑肿瘤医学影像检测（OpenNoorIlm）":
        m.model_name = "脑肿瘤医学影像检测（OpenNoorIlm）"
        changed = True
    if m.category != "医学影像-脑肿瘤":
        m.category = "医学影像-脑肿瘤"
        changed = True
    if size > 0 and m.file_size != size:
        m.file_size = size
        changed = True
    # 根据权重目录大小决定是否启用
    if size <= 0:
        if m.status != "1":
            m.status = "1"
            changed = True
    else:
        if m.status != "0":
            m.status = "0"
            changed = True
    if changed:
        db.session.commit()
    return changed


def _bind_local_rocket_detect_weight():
    """绑定本地 NASASpaceflight Rocket Detect 权重目录（幂等）。"""
    m = AiModel.query.filter_by(model_key="rocket-detect-nasaspaceflight").first()
    if not m:
        return False
    rel = "models/rocket-detect-nasaspaceflight"
    base = os.path.dirname(os.path.abspath(__file__))
    abs_dir = os.path.join(base, "uploads", rel.replace("/", os.sep))
    if not os.path.isdir(abs_dir):
        if m.status != "1":
            m.status = "1"
            db.session.commit()
            return True
        return False
    wp = None
    for root, _dirs, files in os.walk(abs_dir):
        for f in files:
            if f.lower().endswith((".pt", ".onnx", ".pth")):
                wp = os.path.join(root, f)
                break
        if wp:
            break
    if not wp:
        if m.status != "1":
            m.status = "1"
            db.session.commit()
            return True
        return False
    rel_file = os.path.relpath(wp, os.path.join(base, "uploads")).replace(os.sep, "/")
    size = os.path.getsize(wp)
    changed = False
    if m.file_path != rel_file:
        m.file_path = rel_file
        changed = True
    if m.model_name != "火箭回收跟踪检测（NASASpaceflight）":
        m.model_name = "火箭回收跟踪检测（NASASpaceflight）"
        changed = True
    if m.category != "航天-火箭回收":
        m.category = "航天-火箭回收"
        changed = True
    if size > 0 and m.file_size != size:
        m.file_size = size
        changed = True
    if m.status != "0":
        m.status = "0"
        changed = True
    # 补齐 Roboflow 推理元信息（老库仅有 onnx 权重时自动写入）
    meta_path = os.path.join(abs_dir, "roboflow_meta.json")
    if not os.path.isfile(meta_path):
        from inference import save_roboflow_meta
        save_roboflow_meta(abs_dir, "rocket-detect/2",
                           classes=["Engine Flames", "Rocket Body", "Space"])
        changed = True
    if changed:
        db.session.commit()
    return changed


def _bind_local_insightface():
    """若 uploads/insightface/models/<pack> 已存在，绑定 file_path=insightface。"""
    base = os.path.dirname(os.path.abspath(__file__))
    root = os.path.join(base, "uploads", "insightface")
    mapping = (
        ("insightface-buffalo-s", "buffalo_s"),
        ("insightface-buffalo-l", "buffalo_l"),
    )
    any_changed = False
    for key, pack in mapping:
        m = AiModel.query.filter_by(model_key=key).first()
        if not m:
            continue
        pack_dir = os.path.join(root, "models", pack)
        size = 0
        if os.path.isdir(pack_dir):
            for r, _d, files in os.walk(pack_dir):
                for f in files:
                    size += os.path.getsize(os.path.join(r, f))
        changed = False
        if size > 0:
            if m.file_path != "insightface":
                m.file_path = "insightface"
                changed = True
            if m.file_size != size:
                m.file_size = size
                changed = True
            if m.version != pack:
                m.version = pack
                changed = True
            if m.status != "0":
                m.status = "0"
                changed = True
        if changed:
            db.session.commit()
            any_changed = True
    return any_changed


def _purge_cosyvoice_models():
    """删除 CosyVoice 模型记录及本地权重（幂等）。"""
    keys = ("cosyvoice-300m-sft", "cosyvoice2-0.5b")
    rows = AiModel.query.filter(
        (AiModel.model_key.in_(keys)) | (AiModel.library == "cosyvoice")
    ).all()
    if not rows:
        return False
    base = os.path.dirname(os.path.abspath(__file__))
    upload = os.path.join(base, "uploads")
    for m in rows:
        if m.file_path:
            abs_path = os.path.join(upload, m.file_path)
            try:
                if os.path.isdir(abs_path):
                    shutil.rmtree(abs_path, ignore_errors=True)
                elif os.path.isfile(abs_path):
                    os.remove(abs_path)
            except OSError:
                pass
        db.session.delete(m)
    db.session.commit()
    return True


def seed_ai_models():
    """AI 模型种子（按标识幂等，老库也会补齐新增的范例模型）。"""
    _purge_cosyvoice_models()
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
    # YOLOv8 文档表格检测（表格识别流水线 + 图片/视频/摄像头检测页）
    created |= _ensure_ai_model("yolov8m-table-extraction", dict(
        model_name="文档表格检测", category="文档解析",
        task="object-detection", library="ultralytics", version="v1",
        source_url="https://huggingface.co/keremberke/yolov8m-table-extraction",
        description="YOLOv8 文档表格检测（bordered/borderless），用于表格识别流水线及图片/视频/摄像头检测页。", status="0",
    ))
    # SLANet_plus 表格结构（rapid-table / ONNX，CPU）
    created |= _ensure_ai_model("rapidtable-slanet-plus", dict(
        model_name="SLANet_plus 表格结构", category="文档解析",
        task="table-structure", library="rapidtable", version="v2",
        source_url="https://www.modelscope.cn/models/RapidAI/RapidTable/resolve/v2.0.0/slanet-plus.onnx",
        description="PaddleOCR SLANet_plus 表格结构识别（ONNX）。与 YOLO 检表 + RapidOCR 组合输出 HTML/CSV。", status="0",
    ))
    # YOLO26 官方通用检测权重（单仓多权重，靠来源链接锚点 #yolo26X.pt 精确拉取）
    created |= _ensure_ai_model("yolo26n", dict(
        model_name="YOLO26n 通用检测", category="通用目标检测",
        task="object-detection", library="ultralytics", version="v26",
        source_url="https://huggingface.co/Ultralytics/YOLO26#yolo26n.pt",
        description="Ultralytics YOLO26 nano 通用目标检测权重（最轻量，CPU 友好），用于检测/追踪/视频页。", status="0",
    ))
    created |= _ensure_ai_model("yolo26s", dict(
        model_name="YOLO26s 通用检测", category="通用目标检测",
        task="object-detection", library="ultralytics", version="v26",
        source_url="https://huggingface.co/Ultralytics/YOLO26#yolo26s.pt",
        description="Ultralytics YOLO26 small 通用目标检测权重（精度更高），用于检测/追踪/视频页。", status="0",
    ))
    created |= _ensure_ai_model("brain-tumor-yolo-opennoor", dict(
        model_name="脑肿瘤医学影像检测（OpenNoorIlm）", category="医学影像-脑肿瘤",
        task="object-detection", library="ultralytics", version="v1",
        source_url="https://huggingface.co/OpenNoorIlm/Noor-Ul-Ilm-Brain-Tumor-Yolo-1.0-24-06-2026",
        file_path="models/OpenNoorIlmNoor-Ul-Ilm-Brain-Tumor-Yolo",
        description="脑肿瘤医学影像检测模型（best.pt / best.onnx），用于图片检测并生成 DeepSeek 诊断辅助报告。", status="0",
    ))
    created |= _ensure_ai_model("rocket-detect-nasaspaceflight", dict(
        model_name="火箭回收跟踪检测（NASASpaceflight）", category="航天-火箭回收",
        task="object-detection", library="ultralytics", version="v2",
        source_url="https://universe.roboflow.com/nasaspaceflight/rocket-detect/model/2",
        description="NASASpaceflight Rocket Detect（YOLOv5）：识别 Engine Flames、Rocket Body 等，"
                    "适用于 Falcon 9 等火箭发射与回收过程视觉跟踪。权重为 Roboflow ONNX 格式。", status="0",
    ))
    created |= _ensure_ai_model("finbert", dict(
        model_name="FinBERT 金融情感分析", category="文本分类",
        task="text-classification", library="transformers", version="v1",
        source_url="https://huggingface.co/ProsusAI/finbert",
        description="FinBERT 金融文本情感分析模型，输出 positive/negative/neutral 三类概率。", status="0",
    ))
    # 阶段B 示例：transformers 目标检测（复用检测页）
    created |= _ensure_ai_model("detr-resnet-50", dict(
        model_name="DETR 通用目标检测", category="通用目标检测",
        task="object-detection", library="transformers", version="v1",
        source_url="https://huggingface.co/facebook/detr-resnet-50",
        description="Facebook DETR 通用目标检测(COCO 80类)，transformers 引擎，可用于图片/视频/摄像头检测页。", status="0",
    ))
    created |= _ensure_ai_model("rf-detr-medium", dict(
        model_name="RF-DETR Medium 目标检测", category="通用目标检测",
        task="object-detection", library="rfdetr", version="v1",
        source_url="https://huggingface.co/Roboflow/rf-detr-medium",
        description="Roboflow RF-DETR Medium(COCO 80类)，rfdetr 引擎，可用于图片/视频/摄像头检测页。", status="0",
    ))
    created |= _ensure_ai_model("rf-detr-seg-medium", dict(
        model_name="RF-DETR Seg Medium 实例分割", category="实例分割",
        task="instance-segmentation", library="rfdetr", version="v1",
        source_url="https://huggingface.co/Roboflow/rf-detr-seg-medium",
        description="Roboflow RF-DETR-Seg Medium(COCO 80类)，rfdetr 引擎，图像分割页。", status="0",
    ))
    created |= _ensure_ai_model("mobile-sam", dict(
        model_name="MobileSAM 交互分割", category="交互分割",
        task="interactive-segmentation", library="mobilesam", version="v1",
        source_url="https://github.com/ChaoningZhang/MobileSAM",
        description="MobileSAM 轻量 SAM，支持点击/框选/全自动分割，CPU 可用。图像分割页。", status="0",
    ))
    # Ultralytics YOLOE-26s 开放词汇实例分割（本地权重目录已预置）
    created |= _ensure_ai_model("yoloe-26s-seg", dict(
        model_name="YOLOE-26s 开放词汇分割", category="实例分割",
        task="instance-segmentation", library="ultralytics", version="v26",
        source_url="https://github.com/ultralytics/assets/releases/download/v8.4.0/yoloe-26s-seg.pt",
        file_path="models/yoloe-26s-seg/yoloe-26s-seg.pt",
        description="Ultralytics YOLOE-26s-seg 开放词汇实例分割；图像分割页可自定义文本提示类别，默认 COCO 常用类。",
        status="0",
    ))
    # 阶段C 示例：transformers 图像分类
    created |= _ensure_ai_model("vit-base", dict(
        model_name="ViT 通用图像分类", category="图像分类",
        task="image-classification", library="transformers", version="v1",
        source_url="https://huggingface.co/google/vit-base-patch16-224",
        description="Google ViT 图像分类(ImageNet 1000类)，transformers 引擎，用于图像分类页。", status="0",
    ))
    # NLP 任务示例（A 文本分类 / B 零样本·完形 / C 翻译·摘要 / D NER·QA）
    created |= _ensure_ai_model("bert-emotion", dict(
        model_name="BERT 情绪识别", category="文本分类",
        task="text-classification", library="transformers", version="v1",
        source_url="https://huggingface.co/bhadresh-savani/bert-base-uncased-emotion",
        description="文本情绪识别(anger/joy/sadness/fear/surprise/love)，文本分析页使用。", status="0",
    ))
    created |= _ensure_ai_model("bart-mnli", dict(
        model_name="BART 零样本分类", category="文本理解",
        task="zero-shot-classification", library="transformers", version="v1",
        source_url="https://huggingface.co/facebook/bart-large-mnli",
        description="零样本文本分类：自定义候选标签，无需训练。文本分析页使用。", status="0",
    ))
    created |= _ensure_ai_model("bert-fill-mask", dict(
        model_name="BERT 完形填空", category="文本理解",
        task="fill-mask", library="transformers", version="v1",
        source_url="https://huggingface.co/bert-base-uncased",
        description="预测 [MASK] 处词语。文本分析页使用。", status="0",
    ))
    created |= _ensure_ai_model("distilbart-cnn", dict(
        model_name="DistilBART 文本摘要", category="文本生成",
        task="summarization", library="transformers", version="v1",
        source_url="https://huggingface.co/sshleifer/distilbart-cnn-12-6",
        description="长文本摘要。文本生成页使用。", status="0",
    ))
    created |= _ensure_ai_model("opus-mt-en-zh", dict(
        model_name="Opus 英译中", category="文本生成",
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
    # 语音识别（Fun-ASR-Nano，通义 LLM-ASR 800M，中/英/日+方言，纯 CPU）
    created |= _ensure_ai_model("fun-asr-nano", dict(
        model_name="Fun-ASR-Nano 语音识别", category="语音识别",
        task="automatic-speech-recognition", library="funasr-nano", version="v1",
        source_url="https://modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512",
        description="通义 Fun-ASR-Nano 端到端大模型(800M)，中/英/日及多方言口音，支持热词/歌词场景，纯 CPU 推理(funasr+model.py)。语音识别页使用。", status="0",
    ))
    # 数字人合成（Linly-Talker/SadTalker，脚手架：生成需 GPU + SadTalker 运行环境）
    created |= _ensure_ai_model("linly-talker", dict(
        model_name="Linly-Talker 数字人", category="数字人",
        task="talking-head", library="linly", version="v1",
        source_url="https://huggingface.co/Kedreamix/Linly-Talker",
        description="人像图 + 驱动音频 → 说话头像视频(SadTalker)。需 GPU 运行环境，当前为脚手架。", status="0",
    ))
    # 文本转语音（MMS-TTS / VITS，transformers 原生 pipeline，CPU 直接可用）
    created |= _ensure_ai_model("mms-tts-eng", dict(
        model_name="MMS-TTS 英文语音合成", category="语音合成",
        task="text-to-speech", library="transformers", version="v1",
        source_url="https://huggingface.co/facebook/mms-tts-eng",
        description="Facebook MMS-TTS 英文(VITS)文本转语音，transformers 引擎，CPU 可用。文本转语音页使用。", status="0",
    ))
    # 文本转语音（VibeVoice-Realtime-0.5B；需 uploads/models/third_party/VibeVoice 官方代码）
    created |= _ensure_ai_model("vibevoice-realtime", dict(
        model_name="VibeVoice 实时语音合成", category="语音合成",
        task="text-to-speech", library="vibevoice", version="v1",
        source_url="https://modelscope.cn/models/microsoft/VibeVoice-Realtime-0.5B",
        description="微软 VibeVoice-Realtime-0.5B，预置多音色(en/de/fr/jp/kr 等)，实时高拟真。需官方代码(uploads/models/third_party/VibeVoice)。", status="0",
    ))
    # 文本转语音（MeloTTS 中英混合 onnx，sherpa-onnx 引擎，纯 onnx、小而快、CPU）
    created |= _ensure_ai_model("melotts-zh-en", dict(
        model_name="MeloTTS 中英混合合成", category="语音合成",
        task="text-to-speech", library="sherpa-onnx", version="v1",
        source_url="https://huggingface.co/wolfofbackstreet/melotts_chinese_mix_english_onnx",
        description="MeloTTS 中英混合 onnx(sherpa-onnx 引擎)，纯 onnx、小而快、CPU 秒级，中英混读。文本转语音页使用。", status="0",
    ))
    # 姿态估计（YOLO11n Pose，羽毛球分析等页使用）
    created |= _ensure_ai_model("yolo11n-pose", dict(
        model_name="YOLO11n 姿态估计", category="姿态估计",
        task="pose-estimation", library="ultralytics", version="v11",
        source_url="https://huggingface.co/Ultralytics/YOLO11#yolo11n-pose.pt",
        description="Ultralytics YOLO11n Pose，球员骨架检测。姿态估计页 / 羽毛球分析页使用。", status="0",
    ))
    # 羽毛球专用检测（Good-Badminton yolo11s-ball，本地权重幂等绑定）
    created |= _ensure_ai_model("yolo11s-ball", dict(
        model_name="YOLO11s 羽毛球检测", category="目标检测",
        task="object-detection", library="ultralytics", version="v11",
        source_url="https://github.com/yo-WASSUP/Good-Badminton/releases/download/v0.1.0/yolo11s-ball.pt",
        file_path="models/yolo11s-ball/yolo11s-ball.pt",
        description="Good-Badminton 发布的 YOLO11s 羽毛球（shuttlecock）检测权重，Apache-2.0。"
                    "羽毛球分析页「羽毛球模型」推荐选用。",
        status="0",
    ))
    # RTMO 姿态（rtmlib ONNX，羽毛球分析推荐）
    created |= _ensure_ai_model("rtmo-s", dict(
        model_name="RTMO-S 姿态估计", category="姿态估计",
        task="pose-estimation", library="rtmlib", version="v1",
        source_url="https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/rtmo-s_8xb32-600e_body7-640x640-dac2bf74_20231211.zip",
        description="OpenMMLab RTMO-S 单阶段姿态（rtmlib+ONNX），COCO-17 关键点。羽毛球分析页推荐使用。", status="0",
    ))
    created |= _ensure_ai_model("rtmo-m", dict(
        model_name="RTMO-M 姿态估计", category="姿态估计",
        task="pose-estimation", library="rtmlib", version="v1",
        source_url="https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/rtmo-m_16xb16-600e_body7-640x640-39e78cc4_20231211.zip",
        description="OpenMMLab RTMO-M 单阶段姿态（rtmlib+ONNX），精度更高、略慢。羽毛球分析页可用。", status="0",
    ))
    # RTMPose Top-Down 姿态（rtmlib Body + YOLOX，姿态估计页推荐高精度）
    created |= _ensure_ai_model("rtmpose-m", dict(
        model_name="RTMPose-M 姿态估计", category="姿态估计",
        task="pose-estimation", library="rtmlib", version="v1",
        source_url="https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip",
        description="OpenMMLab RTMPose-M Top-Down（rtmlib+YOLOX），COCO-17，精度高于 RTMO/YOLO。", status="0",
    ))
    # DWPose 全身 133 关键点（rtmlib Wholebody）
    created |= _ensure_ai_model("dwpose-m", dict(
        model_name="DWPose-M 全身姿态", category="姿态估计",
        task="wholebody-pose-estimation", library="rtmlib", version="v1",
        source_url="https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmpose-m_simcc-ucoco_dw-ucoco_270e-256x192-c8b76419_20230728.zip",
        description="DWPose-M 全身 133 关键点（rtmlib Wholebody），含手/脸/脚。姿态估计页全身模式。", status="0",
    ))
    # InsightFace 人脸识别（SCRFD + ArcFace；version=pack 名）
    created |= _ensure_ai_model("insightface-buffalo-s", dict(
        model_name="InsightFace Buffalo-S", category="人脸识别",
        task="face-recognition", library="insightface", version="buffalo_s",
        source_url="https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip",
        description="InsightFace buffalo_s（轻量，CPU 友好）：SCRFD 检测 + MobileFace ArcFace。"
                    "许可请参阅 InsightFace 仓库；人脸数据请合规留存。", status="0",
    ))
    created |= _ensure_ai_model("insightface-buffalo-l", dict(
        model_name="InsightFace Buffalo-L", category="人脸识别",
        task="face-recognition", library="insightface", version="buffalo_l",
        source_url="https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
        description="InsightFace buffalo_l（高精度）：SCRFD + ResNet50 ArcFace。"
                    "建议 GPU/CUDA EP；许可与隐私合规同上。", status="0",
    ))
    _bind_local_brain_tumor_weight()
    _bind_local_rocket_detect_weight()
    _bind_local_insightface()
    _bind_local_yoloe_seg_weight()
    _bind_local_yolo11s_ball_weight()
    return created


def _bind_local_yolo11s_ball_weight():
    """绑定本地 Good-Badminton yolo11s-ball.pt（幂等）。"""
    m = AiModel.query.filter_by(model_key="yolo11s-ball").first()
    if not m:
        return False
    base = os.path.dirname(os.path.abspath(__file__))
    uploads = os.path.join(base, "uploads")
    rel_file = "models/yolo11s-ball/yolo11s-ball.pt"
    abs_file = os.path.join(uploads, rel_file.replace("/", os.sep))
    if not os.path.isfile(abs_file):
        if m.status != "1":
            m.status = "1"
            db.session.commit()
            return True
        return False
    size = os.path.getsize(abs_file)
    changed = False
    if m.file_path != rel_file:
        m.file_path = rel_file
        changed = True
    if m.model_name != "YOLO11s 羽毛球检测":
        m.model_name = "YOLO11s 羽毛球检测"
        changed = True
    if m.category != "目标检测":
        m.category = "目标检测"
        changed = True
    if (m.task or "") != "object-detection":
        m.task = "object-detection"
        changed = True
    if (m.library or "") != "ultralytics":
        m.library = "ultralytics"
        changed = True
    if size > 0 and m.file_size != size:
        m.file_size = size
        changed = True
    if size > 0 and m.status != "0":
        m.status = "0"
        changed = True
    # 来源 URL 对齐 Release，便于「拉取权重」回退下载
    src = "https://github.com/yo-WASSUP/Good-Badminton/releases/download/v0.1.0/yolo11s-ball.pt"
    if (m.source_url or "") != src:
        m.source_url = src
        changed = True
    if changed:
        db.session.commit()
    return changed


def _bind_local_yoloe_seg_weight():
    """绑定本地已下载的 YOLOE-26s-seg 权重（幂等更新 file_path/file_size/status）。"""
    m = AiModel.query.filter_by(model_key="yoloe-26s-seg").first()
    if not m:
        return False
    base = os.path.dirname(os.path.abspath(__file__))
    uploads = os.path.join(base, "uploads")
    rel_file = "models/yoloe-26s-seg/yoloe-26s-seg.pt"
    abs_file = os.path.join(uploads, rel_file.replace("/", os.sep))
    if not os.path.isfile(abs_file):
        # 目录内再找任意 .pt
        abs_dir = os.path.join(uploads, "models", "yoloe-26s-seg")
        wp = None
        if os.path.isdir(abs_dir):
            for root, _dirs, files in os.walk(abs_dir):
                for f in files:
                    if f.lower().endswith(".pt"):
                        wp = os.path.join(root, f)
                        break
                if wp:
                    break
        if not wp:
            if m.status != "1":
                m.status = "1"
                db.session.commit()
                return True
            return False
        abs_file = wp
        rel_file = os.path.relpath(wp, uploads).replace(os.sep, "/")
    size = os.path.getsize(abs_file)
    changed = False
    if m.file_path != rel_file:
        m.file_path = rel_file
        changed = True
    if m.model_name != "YOLOE-26s 开放词汇分割":
        m.model_name = "YOLOE-26s 开放词汇分割"
        changed = True
    if m.category != "实例分割":
        m.category = "实例分割"
        changed = True
    if (m.task or "") != "instance-segmentation":
        m.task = "instance-segmentation"
        changed = True
    if (m.library or "") != "ultralytics":
        m.library = "ultralytics"
        changed = True
    if size > 0 and m.file_size != size:
        m.file_size = size
        changed = True
    if size > 0 and m.status != "0":
        m.status = "0"
        changed = True
    if size <= 0 and m.status != "1":
        m.status = "1"
        changed = True
    if changed:
        db.session.commit()
    return changed


def seed_alert_rules():
    """默认告警规则：烟火 / 聚集 / PPE 未戴帽 / 越线入侵（幂等补齐缺失键；默认停用）。"""
    import json
    from models import AlertRule

    fire_overlay = {
        "enabled": True,
        "priority": 0,
        "fillColor": "#FF1A1A",
        "borderColor": "#CC0000",
        "textColor": "#FFFFFF",
        "titleLines": ["FIRE", "DANGEROUS", "ALERT"],
        "subtitleLines": [],
        "panelWidthRatio": 0.72,
        "panelHeightRatio": 0.36,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#FFFFFF",
        "triangleMark": "#B00000",
    }
    crowd_overlay = {
        "enabled": True,
        "priority": 10,
        "fillColor": "#FFD400",
        "borderColor": "#E6B800",
        "textColor": "#1A1A1A",
        "titleLines": ["CROWD ALERT"],
        "subtitleLines": ["注意安全", "防止拥挤踩踏"],
        "panelWidthRatio": 0.72,
        "panelHeightRatio": 0.36,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#1A1A1A",
        "triangleMark": "#FFFFFF",
    }
    ppe_overlay = {
        "enabled": True,
        "priority": 5,
        "fillColor": "#FF7A00",
        "borderColor": "#CC6200",
        "textColor": "#FFFFFF",
        "titleLines": ["NO HARDHAT"],
        "subtitleLines": ["未佩戴安全帽", "立即纠正"],
        "panelWidthRatio": 0.72,
        "panelHeightRatio": 0.36,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#FFFFFF",
        "triangleMark": "#CC6200",
    }
    line_overlay = {
        "enabled": True,
        "priority": 15,
        "fillColor": "#9254DE",
        "borderColor": "#722ED1",
        "textColor": "#FFFFFF",
        "titleLines": ["INTRUSION"],
        "subtitleLines": ["越线告警", "请勿闯入"],
        "panelWidthRatio": 0.72,
        "panelHeightRatio": 0.36,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#FFFFFF",
        "triangleMark": "#722ED1",
    }
    stranger_overlay = {
        "enabled": True,
        "priority": 8,
        "fillColor": "#409EFF",
        "borderColor": "#1D6FBF",
        "textColor": "#FFFFFF",
        "titleLines": ["STRANGER"],
        "subtitleLines": ["陌生人脸", "请核验身份"],
        "panelWidthRatio": 0.68,
        "panelHeightRatio": 0.32,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#FFFFFF",
        "triangleMark": "#1D6FBF",
    }
    fire_cfg = {
        "classes": ["fire", "smoke", "flame"],
        "min_confidence": 0.35,
        "consecutive_frames": 2,
        "cooldown_sec": 30,
        "title_template": "疑似烟火：检测到 {classes}",
        "message_template": "立即核实火情、就近取用灭火器并启动应急预案；确认消防通道畅通。",
        "overlay": fire_overlay,
    }
    crowd_cfg = {
        "class_names": ["person", "people", "human", "pedestrian", "人", "行人"],
        "class_name": "person",
        "min_count": 4,
        "video_min_count": 3,
        "min_confidence": 0.25,
        "consecutive_frames": 2,
        "cooldown_sec": 60,
        "title_template": "人员聚集：当前 {count} 人（阈值 {minCount}）",
        "message_template": "注意安全，防止拥挤踩踏；评估区域承载并做人流疏导。",
        "overlay": crowd_overlay,
    }
    ppe_cfg = {
        "classes": ["NO-Hardhat", "no-hardhat"],
        "min_confidence": 0.35,
        "consecutive_frames": 2,
        "cooldown_sec": 45,
        "title_template": "未戴安全帽：检测到 {classes}",
        "message_template": "立即提醒未戴安全帽人员补戴或撤离危险区域；入口增设佩戴检查。",
        "overlay": ppe_overlay,
    }
    line_cfg = {
        "classes": ["person", "Person", "people", "human", "pedestrian", "人", "行人"],
        "line": [0.1, 0.5, 0.9, 0.5],
        "direction": "both",
        "min_confidence": 0.25,
        "consecutive_frames": 1,
        "cooldown_sec": 30,
        "title_template": "越线入侵：{crossCount} 次穿越",
        "message_template": "核查越线人员身份与事由；必要时广播劝离并联动门禁/安保。",
        "overlay": line_overlay,
    }
    stranger_cfg = {
        "min_confidence": 0.0,
        "consecutive_frames": 2,
        "cooldown_sec": 60,
        "title_template": "陌生人脸：检测到 {count} 张未匹配人脸",
        "message_template": "核查现场人员身份；必要时登记访客或联动门禁/安保。",
        "overlay": stranger_overlay,
    }
    defaults = [
        dict(
            rule_key="fire-smoke",
            name="烟火告警",
            description="检测到 fire/smoke 类目标时触发（建议配合 fire-smoke-detection 模型）",
            rule_type="class_presence",
            config_json=json.dumps(fire_cfg, ensure_ascii=False),
            severity="high",
            status="1",  # 默认不启用，需在检测告警页手动打开单项开关
        ),
        dict(
            rule_key="crowd-gathering",
            name="人员聚集告警",
            description="画面中 person 数量超过阈值时触发（建议配合 YOLO 等含 person 的通用检测模型）",
            rule_type="count_threshold",
            config_json=json.dumps(crowd_cfg, ensure_ascii=False),
            severity="medium",
            status="1",
        ),
        dict(
            rule_key="ppe-no-hardhat",
            name="PPE未戴安全帽",
            description="检测到 NO-Hardhat 时触发（建议配合 ppe-detection / PPE穿戴识别模型）",
            rule_type="class_presence",
            config_json=json.dumps(ppe_cfg, ensure_ascii=False),
            severity="high",
            status="1",
        ),
        dict(
            rule_key="line-intrusion",
            name="越线/入侵告警",
            description="目标穿越警戒线时触发（需带 trackId 的追踪结果；目标追踪页画线可覆盖默认线）",
            rule_type="line_crossing",
            config_json=json.dumps(line_cfg, ensure_ascii=False),
            severity="high",
            status="1",
        ),
        dict(
            rule_key="stranger-face",
            name="陌生人脸告警",
            description="人脸识别未匹配底库时触发（建议在「人脸识别」页开启启用告警）",
            rule_type="unmatched_face",
            config_json=json.dumps(stranger_cfg, ensure_ascii=False),
            severity="high",
            status="1",
        ),
    ]
    created = False
    updated = False
    merge_map = {
        "fire-smoke": fire_cfg,
        "crowd-gathering": crowd_cfg,
        "ppe-no-hardhat": ppe_cfg,
        "line-intrusion": line_cfg,
        "stranger-face": stranger_cfg,
    }
    for fields in defaults:
        existing = AlertRule.query.filter_by(rule_key=fields["rule_key"]).first()
        if existing:
            cfg = existing.config()
            desired = merge_map[fields["rule_key"]]
            # 仅补齐缺失键，不覆盖管理员已改字段（overlay 子键也仅补缺失）
            changed = False
            for k, v in desired.items():
                if k == "overlay":
                    ov = dict(cfg.get("overlay") or {})
                    for ok, ovv in v.items():
                        if ok not in ov:
                            ov[ok] = ovv
                            changed = True
                    if changed or "overlay" not in cfg:
                        cfg["overlay"] = ov
                        changed = True
                elif k not in cfg:
                    cfg[k] = v
                    changed = True
            if changed:
                existing.config_json = json.dumps(cfg, ensure_ascii=False)
                updated = True
            continue
        db.session.add(AlertRule(**fields))
        created = True

    # 一次性：将旧种子「默认启用」对齐为「默认停用」（之后保留管理员手动设置）
    align_default_off = False
    try:
        import os
        from config import Config

        flag_path = os.path.join(Config.ALERT_RULES_DIR, ".alert_rules_default_off_v1")
        legacy_flag = os.path.join(os.path.dirname(Config.BASE_DIR), "instance", ".alert_rules_default_off_v1")
        if not os.path.exists(flag_path) and os.path.exists(legacy_flag):
            os.makedirs(Config.ALERT_RULES_DIR, exist_ok=True)
            shutil.copy2(legacy_flag, flag_path)
        if not os.path.exists(flag_path):
            for fields in defaults:
                row = AlertRule.query.filter_by(rule_key=fields["rule_key"]).first()
                if row and row.status == "0":
                    row.status = "1"
                    updated = True
            align_default_off = True
            _alert_off_flag = flag_path
        else:
            _alert_off_flag = None
    except Exception:
        _alert_off_flag = None
        align_default_off = False

    if created or updated:
        db.session.commit()
    if align_default_off and _alert_off_flag:
        try:
            import os
            os.makedirs(os.path.dirname(os.path.abspath(_alert_off_flag)) or ".", exist_ok=True)
            with open(_alert_off_flag, "w", encoding="utf-8") as f:
                f.write("1\n")
        except Exception:
            pass
    return created or updated


def init_seed():
    if User.query.first():
        seed_ai_menus()   # 用户已存在也补齐 AI 菜单种子
        seed_ai_models()  # 用户已存在也补齐 AI 模型种子
        seed_alert_rules()
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
    seed_alert_rules()
    return True


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        created = init_seed()
        print("种子数据已写入" if created else "已存在数据，跳过")
