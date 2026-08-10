"""初始化种子数据（幂等：已有用户则跳过）。

可独立运行： python seed.py
启动时 app.py 也会自动调用 init_seed()。
"""
import os
import shutil

from extensions import db
from models import User, Role, Dept, Job, Menu, AiModel
from models.open_app import OpenApp, OpenApiKey
from security_open import hash_api_key, key_prefix
from services.openapi_catalog import (
    list_domains,
    scopes_for_all_bridgeable_domains,
    scopes_for_domain,
)
from services.openapi_bridge import BRIDGE_USER
import secrets


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
        (206, 230, "/ai/imgcls"), (284, 230, "/ai/livecls"), (213, 230, "/ai/track"), (214, 230, "/ai/pose"),
        (250, 230, "/ai/water"), (270, 230, "/ai/badminton"), (272, 230, "/ai/segment"),
        (274, 230, "/ai/face"),
        (288, 230, "/ai/reid"),
        (276, 230, "/ai/alert"),
        (278, 230, "/ai/table"),
        (286, 230, "/ai/inpaint"),
        # 280/282 已并入目标追踪场景
        (280, 230, "/ai/track"),
        (282, 230, "/ai/track"),
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


def _patch_vehicle_menu_merged_into_track():
    """车辆追踪并入目标追踪场景：侧栏隐藏菜单 280，保留 ai:vehicle:list 权限（幂等）。

    visible: 0=显示 1=隐藏。隐藏后仍可通过角色菜单授予车辆 API 权限。
    """
    changed = False
    m280 = Menu.query.get(280)
    if m280:
        if m280.visible != "1":
            m280.visible = "1"
            changed = True
        # 组件指向目标追踪壳；路径保留便于权限/兼容
        if m280.component != "ai/track/index":
            m280.component = "ai/track/index"
            changed = True
        if m280.path != "/ai/track":
            # 侧栏已隐藏；path 对齐目标追踪，避免误点动态路由落到旧页
            m280.path = "/ai/track"
            changed = True
        tip = "（已并入目标追踪·车辆场景）"
        if tip not in (m280.menu_name or ""):
            # 菜单管理里仍可见名称时便于识别；侧栏因 visible=1 不展示
            if "车辆追踪" in (m280.menu_name or ""):
                m280.menu_name = "车辆追踪" + tip
                changed = True
    m2801 = Menu.query.get(2801)
    if m2801 and m2801.visible != "1":
        m2801.visible = "1"
        changed = True
    if changed:
        db.session.commit()


def _patch_absence_menu_merged_into_track():
    """人员离岗并入目标追踪：侧栏隐藏菜单 282，保留 ai:absence:list。"""
    changed = False
    m282 = Menu.query.get(282)
    if m282:
        if m282.visible != "1":
            m282.visible = "1"
            changed = True
        if m282.component != "ai/track/index":
            m282.component = "ai/track/index"
            changed = True
        if m282.path != "/ai/track":
            m282.path = "/ai/track"
            changed = True
        tip = "（已并入目标追踪·离岗场景）"
        if tip not in (m282.menu_name or "") and "人员离岗" in (m282.menu_name or ""):
            m282.menu_name = "人员离岗检测" + tip
            changed = True
    m2821 = Menu.query.get(2821)
    if m2821 and m2821.visible != "1":
        m2821.visible = "1"
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
    _ensure_ai_menu(284, 230, "实时分类", "C", "ai:livecls:list",
                    path="/ai/livecls", component="ai/livecls/index", icon="View",
                    order=5, grant_common=True)
    _ensure_ai_menu(2841, 284, "实时分类查询", "F", "ai:livecls:query", grant_common=True)
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
    _ensure_ai_menu(280, 230, "车辆追踪", "C", "ai:vehicle:list",
                    path="/ai/track", component="ai/track/index", icon="Van",
                    order=10, grant_common=True)
    _ensure_ai_menu(2801, 280, "车辆追踪查询", "F", "ai:vehicle:query", grant_common=True)
    # 已并入「目标追踪」场景：侧栏隐藏，保留权限标识供 /api/ai/vehicle 鉴权
    _patch_vehicle_menu_merged_into_track()
    _ensure_ai_menu(282, 230, "人员离岗检测", "C", "ai:absence:list",
                    path="/ai/track", component="ai/track/index", icon="User",
                    order=11, grant_common=True)
    _ensure_ai_menu(2821, 282, "人员离岗查询", "F", "ai:absence:query", grant_common=True)
    _patch_absence_menu_merged_into_track()
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
    # 图像修复 LaMa（视觉识别 230 下）
    _ensure_ai_menu(286, 230, "图像修复", "C", "ai:inpaint:list",
                    path="/ai/inpaint", component="ai/inpaint/index", icon="Brush",
                    order=12, grant_common=True)
    _ensure_ai_menu(2861, 286, "图像修复查询", "F", "ai:inpaint:query", grant_common=True)
    # 人脸识别（视觉识别 230 下）
    _ensure_ai_menu(274, 230, "人脸识别", "C", "ai:face:list",
                    path="/ai/face", component="ai/face/index", icon="User",
                    order=13, grant_common=True)
    _ensure_ai_menu(2741, 274, "人脸识别查询", "F", "ai:face:query", grant_common=True)
    _ensure_ai_menu(2742, 274, "人脸底库新增", "F", "ai:face:add")
    _ensure_ai_menu(2743, 274, "人脸底库修改", "F", "ai:face:edit")
    _ensure_ai_menu(2744, 274, "人脸底库删除", "F", "ai:face:remove")
    # 行人重识别（视觉识别 230 下）
    _ensure_ai_menu(288, 230, "行人重识别", "C", "ai:reid:list",
                    path="/ai/reid", component="ai/reid/index", icon="Avatar",
                    order=13, grant_common=True)
    _ensure_ai_menu(2881, 288, "行人重识别查询", "F", "ai:reid:query", grant_common=True)
    _ensure_ai_menu(2882, 288, "行人底库新增", "F", "ai:reid:add")
    _ensure_ai_menu(2883, 288, "行人底库修改", "F", "ai:reid:edit")
    _ensure_ai_menu(2884, 288, "行人底库删除", "F", "ai:reid:remove")
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


def _bind_local_efficient_sam_weight():
    """若 uploads/models/efficient-sam 已含 ONNX，绑定 file_path（幂等）。"""
    m = AiModel.query.filter_by(model_key="efficient-sam").first()
    if not m:
        return False
    rel = "models/efficient-sam"
    base = os.path.dirname(os.path.abspath(__file__))
    abs_dir = os.path.join(base, "uploads", rel.replace("/", os.sep))
    try:
        from efficient_sam_dnn import assets_ready
        ready = assets_ready(abs_dir) if os.path.isdir(abs_dir) else False
    except Exception:  # noqa: BLE001
        ready = False
    changed = False
    if ready:
        size = 0
        for root, _dirs, files in os.walk(abs_dir):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    size += os.path.getsize(fp)
        if m.file_path != rel:
            m.file_path = rel
            changed = True
        if size > 0 and m.file_size != size:
            m.file_size = size
            changed = True
        if m.status != "0":
            m.status = "0"
            changed = True
    if changed:
        db.session.commit()
    return changed


def _bind_local_lama_weight():
    """若 uploads/models/inpainting-lama 已含 ONNX，绑定 file_path（幂等）。"""
    m = AiModel.query.filter_by(model_key="inpainting-lama").first()
    if not m:
        return False
    rel = "models/inpainting-lama"
    base = os.path.dirname(os.path.abspath(__file__))
    abs_dir = os.path.join(base, "uploads", rel.replace("/", os.sep))
    try:
        from lama_dnn import assets_ready
        ready = assets_ready(abs_dir) if os.path.isdir(abs_dir) else False
    except Exception:  # noqa: BLE001
        ready = False
    changed = False
    if ready:
        size = 0
        for root, _dirs, files in os.walk(abs_dir):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    size += os.path.getsize(fp)
        if m.file_path != rel:
            m.file_path = rel
            changed = True
        if size > 0 and m.file_size != size:
            m.file_size = size
            changed = True
        if m.status != "0":
            m.status = "0"
            changed = True
    if changed:
        db.session.commit()
    return changed


def _bind_local_yunet_sface_weight():
    """若 uploads/models/opencv-yunet-sface 已含 YuNet+SFace，绑定 file_path（幂等）。"""
    m = AiModel.query.filter_by(model_key="opencv-yunet-sface").first()
    if not m:
        return False
    rel = "models/opencv-yunet-sface"
    base = os.path.dirname(os.path.abspath(__file__))
    abs_dir = os.path.join(base, "uploads", rel.replace("/", os.sep))
    try:
        from yunet_sface import assets_ready
        ready = assets_ready(abs_dir) if os.path.isdir(abs_dir) else False
    except Exception:  # noqa: BLE001
        ready = False
    changed = False
    if ready:
        size = 0
        for root, _dirs, files in os.walk(abs_dir):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    size += os.path.getsize(fp)
        if m.file_path != rel:
            m.file_path = rel
            changed = True
        if size > 0 and m.file_size != size:
            m.file_size = size
            changed = True
        if m.status != "0":
            m.status = "0"
            changed = True
    if changed:
        db.session.commit()
    return changed


def _bind_local_person_reid_weight():
    """若 uploads/models/opencv-person-reid-youtu 已含 ONNX，绑定 file_path（幂等）。"""
    m = AiModel.query.filter_by(model_key="opencv-person-reid-youtu").first()
    if not m:
        return False
    rel = "models/opencv-person-reid-youtu"
    base = os.path.dirname(os.path.abspath(__file__))
    abs_dir = os.path.join(base, "uploads", rel.replace("/", os.sep))
    try:
        from person_reid_dnn import assets_ready
        ready = assets_ready(abs_dir) if os.path.isdir(abs_dir) else False
    except Exception:  # noqa: BLE001
        ready = False
    changed = False
    if ready:
        size = 0
        for root, _dirs, files in os.walk(abs_dir):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    size += os.path.getsize(fp)
        if m.file_path != rel:
            m.file_path = rel
            changed = True
        if size > 0 and m.file_size != size:
            m.file_size = size
            changed = True
        if m.status != "0":
            m.status = "0"
            changed = True
    if changed:
        db.session.commit()
    return changed


def _bind_local_mobilenet_weight():
    """若 uploads/models/mobilenet-v2 已含双 ONNX + labels，绑定 file_path（幂等）。"""
    m = AiModel.query.filter_by(model_key="mobilenet-v2").first()
    if not m:
        return False
    rel = "models/mobilenet-v2"
    base = os.path.dirname(os.path.abspath(__file__))
    abs_dir = os.path.join(base, "uploads", rel.replace("/", os.sep))
    try:
        from mobilenet_dnn import assets_ready
        ready = assets_ready(abs_dir) if os.path.isdir(abs_dir) else False
    except Exception:  # noqa: BLE001
        ready = False
    changed = False
    if ready:
        size = 0
        for root, _dirs, files in os.walk(abs_dir):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    size += os.path.getsize(fp)
        if m.file_path != rel:
            m.file_path = rel
            changed = True
        if size > 0 and m.file_size != size:
            m.file_size = size
            changed = True
        if m.status != "0":
            m.status = "0"
            changed = True
    else:
        # 无本地资产时保持可拉取；不强制停用（与 vit-base 一致，前端提示拉取）
        if m.file_path and not os.path.exists(os.path.join(base, "uploads", (m.file_path or "").replace("/", os.sep))):
            m.file_path = None
            m.file_size = None
            changed = True
    if changed:
        db.session.commit()
    return changed


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
    # 车牌检测（车辆追踪）：YOLOv8（Koushim）+ YOLOv5n/m（keremberke）
    created |= _ensure_ai_model("yolov8-license-plate", dict(
        model_name="车牌检测 YOLOv8（Koushim）", category="交通车辆",
        task="object-detection", library="ultralytics", version="v8",
        source_url="https://huggingface.co/Koushim/yolov8-license-plate-detection",
        description="YOLOv8n 车牌定位（Koushim/yolov8-license-plate-detection，Ultralytics）。车辆追踪车牌检测可用。", status="0",
    ))
    created |= _ensure_ai_model("keremberke-yolov5n-license-plate", dict(
        model_name="车牌检测 YOLOv5n（keremberke）", category="交通车辆",
        task="object-detection", library="ultralytics", version="v5",
        source_url="https://huggingface.co/keremberke/yolov5n-license-plate",
        description="YOLOv5n 车牌定位（keremberke）。车辆追踪兼容项，经专用加载器推理。", status="0",
    ))
    created |= _ensure_ai_model("keremberke-yolov5m-license-plate", dict(
        model_name="车牌检测 YOLOv5m（keremberke）", category="交通车辆",
        task="object-detection", library="ultralytics", version="v5",
        source_url="https://huggingface.co/keremberke/yolov5m-license-plate",
        description="YOLOv5m 车牌定位（keremberke，精度高于 n）。车辆追踪兼容项，经专用加载器推理。", status="0",
    ))
    # YOLOv11 车牌检测（morsetechlab，车辆追踪推荐；单仓多权重靠锚点选 n/s）
    created |= _ensure_ai_model("yolov11-license-plate-n", dict(
        model_name="车牌检测 YOLOv11n（推荐·CPU）", category="交通车辆",
        task="object-detection", library="ultralytics", version="v11",
        source_url="https://huggingface.co/morsetechlab/yolov11-license-plate-detection#license-plate-finetune-v1n.pt",
        description="YOLOv11 nano 车牌定位（morsetechlab）。CPU 友好，车辆追踪号牌检测推荐。", status="0",
    ))
    created |= _ensure_ai_model("yolov11-license-plate-s", dict(
        model_name="车牌检测 YOLOv11s（推荐·精度）", category="交通车辆",
        task="object-detection", library="ultralytics", version="v11",
        source_url="https://huggingface.co/morsetechlab/yolov11-license-plate-detection#license-plate-finetune-v1s.pt",
        description="YOLOv11 small 车牌定位（morsetechlab）。精度更高，CPU 仍可用。", status="0",
    ))
    # RapidOCR PP-OCRv6 small（CPU/ONNX，行驶号牌推荐）
    created |= _ensure_ai_model("PP-OCRv6_small_det_onnx", dict(
        model_name="PP-OCRv6 small 检测（推荐）", category="文档解析",
        task="text-detection", library="rapidocr", version="v6",
        source_url="https://www.modelscope.cn/models/RapidAI/RapidOCR",
        file_path="models/PP-OCRv6_small_det_onnx",
        description="PP-OCRv6 small 文本检测 ONNX（CPU）。车辆追踪/PaddleOCR/表格识别推荐。", status="0",
    ))
    created |= _ensure_ai_model("PP-OCRv6_small_rec_onnx", dict(
        model_name="PP-OCRv6 small 识别（推荐）", category="文档解析",
        task="text-recognition", library="rapidocr", version="v6",
        source_url="https://www.modelscope.cn/models/RapidAI/RapidOCR",
        file_path="models/PP-OCRv6_small_rec_onnx",
        description="PP-OCRv6 small 文本识别 ONNX（CPU）。与 det 配对用于号牌 OCR。", status="0",
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
        description="Ultralytics YOLO26 nano（COCO 通用目标检测，轻量）。", status="0",
    ))
    created |= _ensure_ai_model("yolo26s", dict(
        model_name="YOLO26s 通用检测", category="通用目标检测",
        task="object-detection", library="ultralytics", version="v26",
        source_url="https://huggingface.co/Ultralytics/YOLO26#yolo26s.pt",
        description="Ultralytics YOLO26 small（COCO 通用目标检测）。", status="0",
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
    # OpenCV Zoo EfficientSAM-Ti（纯 DNN ONNX，点/框交互）
    created |= _ensure_ai_model("efficient-sam", dict(
        model_name="EfficientSAM-Ti（OpenCV）", category="交互分割",
        task="interactive-segmentation", library="opencv-sam", version="2025april",
        source_url="https://huggingface.co/opencv/image_segmentation_efficientsam",
        description=(
            "OpenCV Zoo EfficientSAM-Ti：点选/框选交互分割，cv2.dnn ONNX（无 PyTorch）。"
            "推荐 2025april；最多 6 个 prompt 点；可选 int8。Apache-2.0。"
        ),
        status="0",
    ))
    created |= _bind_local_efficient_sam_weight()
    # OpenCV Zoo LaMa 图像修复（DNN ONNX）
    created |= _ensure_ai_model("inpainting-lama", dict(
        model_name="LaMa 图像修复（OpenCV）", category="图像修复",
        task="image-inpainting", library="opencv-lama", version="2025jan",
        source_url="https://huggingface.co/opencv/inpainting_lama",
        description=(
            "OpenCV Zoo LaMa：涂抹遮罩区域后进行图像修复/补全，cv2.dnn ONNX（失败回退 ORT）。"
            "权重约 88MB；输入 512；Apache-2.0。"
        ),
        status="0",
    ))
    created |= _bind_local_lama_weight()
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
    # OpenCV DNN：MobileNet V2 fp32 + int8（ONNX Model Zoo）+ ImageNet 1000 标签
    created |= _ensure_ai_model("mobilenet-v2", dict(
        model_name="MobileNet V2（OpenCV DNN）", category="图像分类",
        task="image-classification", library="opencv-dnn", version="v2",
        source_url=(
            "https://github.com/onnx/models/raw/main/validated/vision/classification/"
            "mobilenet/model/mobilenetv2-12.onnx"
        ),
        description=(
            "MobileNet V2 ImageNet-1000 分类（OpenCV DNN）。拉取后含 fp32/int8 双 ONNX "
            "与 imagenet_classes.txt；用于图像分类页与摄像头实时分类页。"
        ),
        status="0",
    ))
    created |= _bind_local_mobilenet_weight()
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
    # 语音识别（Moonshine Tiny，HF transformers，英文 ASR，27M，边缘/低资源友好）
    created |= _ensure_ai_model("moonshine-tiny", dict(
        model_name="Moonshine Tiny 语音识别", category="语音识别",
        task="automatic-speech-recognition", library="transformers", version="v1",
        source_url="https://huggingface.co/UsefulSensors/moonshine-tiny",
        description="Useful Sensors Moonshine Tiny（27M，英文 ASR，transformers）。面向实时转写与低资源设备，CPU 友好。语音识别页使用。", status="0",
    ))
    # 车牌检测（YOLO26n 社区微调 bbox，车辆追踪可用）
    created |= _ensure_ai_model("yolo26n-plate", dict(
        model_name="车牌检测 YOLO26n（CodexParas）", category="交通车辆",
        task="object-detection", library="ultralytics", version="v26",
        source_url="https://huggingface.co/CodexParas/car-plate-detection-yolov26#best.pt",
        description="YOLO26n 车牌 bbox（CodexParas/car-plate-detection-yolov26）。适合车辆 ROI 内定位；可与透视近似联用。", status="0",
    ))
    # 车牌四点 pose（中文车牌场景，透视矫正优先）
    created |= _ensure_ai_model("yolo26s-plate-pose", dict(
        model_name="车牌四点 YOLO26s-pose（推荐·透视）", category="交通车辆",
        task="pose-estimation", library="ultralytics", version="v26",
        source_url="https://raw.githubusercontent.com/we0091234/yolo26-plate/main/weights/yolo26s-plate-detect.pt",
        description="YOLO26 pose 车牌框+4角点（we0091234/yolo26-plate）。车辆追踪透视矫正优先路径。", status="0",
    ))
    # YOLO26n-P2：官方仅架构 YAML，无预训练；作小目标车牌自训脚手架
    created |= _ensure_ai_model("yolo26n-p2-plate", dict(
        model_name="车牌检测 YOLO26n-P2（自训脚手架）", category="交通车辆",
        task="object-detection", library="ultralytics", version="v26-p2",
        source_url="https://docs.ultralytics.com/models/yolo26/",
        description="官方无 yolo26n-p2.pt。请用 YOLO('yolo26n-p2.yaml') 自训后把 best.pt 放到 models/yolo26n-p2-plate/。面向远距小车牌。", status="0",
    ))
    # YOLO26n-pose / OBB 基座（HF openvision）
    created |= _ensure_ai_model("yolo26n-pose", dict(
        model_name="YOLO26n 姿态估计", category="姿态估计",
        task="pose-estimation", library="ultralytics", version="v26",
        source_url="https://huggingface.co/openvision/yolo26-n-pose#model.pt",
        description="openvision/yolo26-n-pose 人体关键点。可作为自定义车牌 4-kpt 微调基座。", status="0",
    ))
    created |= _ensure_ai_model("yolo26n-obb", dict(
        model_name="YOLO26n 旋转框 OBB", category="交通车辆",
        task="obb", library="ultralytics", version="v26",
        source_url="https://huggingface.co/openvision/yolo26-n-obb#model.pt",
        description="openvision/yolo26-n-obb 旋转目标检测。车辆 ROI 内可用于车牌定向四点透视（通用权重，需 ROI 约束）。", status="0",
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
    # OpenCV Zoo：YuNet 检测 + SFace 识别（轻量，原生 FaceDetectorYN / FaceRecognizerSF）
    created |= _ensure_ai_model("opencv-yunet-sface", dict(
        model_name="OpenCV YuNet+SFace", category="人脸识别",
        task="face-recognition", library="opencv-face", version="2023mar+2021dec",
        source_url="https://huggingface.co/opencv/face_detection_yunet",
        description=(
            "OpenCV Model Zoo：YuNet(face_detection_yunet_2023mar.onnx) 人脸检测 "
            "+ SFace(face_recognition_sface_2021dec.onnx) 特征识别。"
            "与 InsightFace 特征空间不兼容，须用同一模型重新登记底库。"
        ),
        status="0",
    ))
    created |= _bind_local_yunet_sface_weight()
    # OpenCV Zoo：腾讯优图行人重识别（外观 768-d）
    created |= _ensure_ai_model("opencv-person-reid-youtu", dict(
        model_name="OpenCV Youtu Person ReID", category="行人重识别",
        task="person-reid", library="opencv-reid", version="2021nov",
        source_url="https://huggingface.co/opencv/person_reid_youtureid",
        description=(
            "OpenCV Model Zoo / 腾讯优图：person_reid_youtu_2021nov.onnx 行人外观特征（768维）。"
            "需配合 YOLO 行人检测裁剪；与人脸特征空间不互通，使用独立行人底库。"
            "远距/背影用外观，近距正脸可混合人脸识别。"
        ),
        status="0",
    ))
    created |= _bind_local_person_reid_weight()
    _bind_local_brain_tumor_weight()
    _bind_local_rocket_detect_weight()
    _bind_local_insightface()
    _bind_local_yoloe_seg_weight()
    _bind_local_yolo11s_ball_weight()
    _bind_vehicle_track_models()
    _ensure_security_detector_models()
    _ensure_fish_detector_model()
    return created


def _ensure_fish_detector_model():
    """鱼类检测（灰度水下）YOLO11n：幂等登记并绑定本地权重目录（pt + onnx，onnx 优先推理）。"""
    key = "yolo11-fish-detector-grayscale"
    rel = "models/yolo11-fish-detector-grayscale"
    base = os.path.dirname(os.path.abspath(__file__))
    abs_dir = os.path.join(base, "uploads", rel.replace("/", os.sep))
    m = AiModel.query.filter_by(model_key=key).first()
    if not m:
        m = AiModel(
            model_key=key,
            model_name="鱼类检测（灰度水下·YOLO11n）",
            category="海洋-鱼类检测",
            task="object-detection", library="ultralytics", version="11n",
            source_url="https://huggingface.co/akridge/yolo11-fish-detector-grayscale#yolo11n_fish_trained.pt",
            description="水下灰度影像鱼类检测（fish 单类，640 输入，YOLO11n）。"
                        "目录含 pt 与 onnx 双权重，推理自动优先 ONNX Runtime。",
            status="1",
        )
        db.session.add(m)
    size = 0
    if os.path.isdir(abs_dir):
        for root, _dirs, files in os.walk(abs_dir):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    size += os.path.getsize(fp)
    changed = False
    if size > 0:
        if m.file_path != rel:
            m.file_path = rel
            changed = True
        if m.file_size != size:
            m.file_size = size
            changed = True
        if m.status != "0":
            m.status = "0"
            changed = True
    if changed or m.id is None:
        db.session.commit()
    return changed


# ── 安防检测器模型包：11 个本地 onnx（均内嵌 ultralytics 元数据，ONNX Runtime 推理）──
_SECURITY_DETECTOR_SPECS = [
    ("sec-fire-yolov8n", "烟火检测-轻量（YOLOv8n）", "sec-fire-yolov8n/fire_smoke_yolov8n.onnx", "v8n",
     "烟火/烟雾检测（fire、smoke 2 类，640 输入，CPU 约 39ms）。安防检测器包·烟火 01。"),
    ("sec-fire-forest-yolov8", "森林火灾检测（YOLOv8s）", "sec-fire-forest-yolov8/forest_fire_yolov8.onnx", "v8s",
     "森林火灾 Fire/Smoke 2 类检测（640 输入）。安防检测器包·烟火 02。"),
    ("sec-fire-collision-yolo11", "碰撞/灾害/烟火检测（YOLO11n·88类）", "sec-fire-collision-yolo11/collision_fire_yolo11.onnx", "11n",
     "COCO80 + collision/deformed car/spinning car/debris/fire/smoke/flood/landslide 共 88 类（640 输入）。安防检测器包·烟火 03。"),
    ("sec-ppe-yolo", "PPE 安全装备检测（YOLO）", "sec-ppe-yolo/ppe_yolo.onnx", "v8",
     "工地 PPE 10 类：Hardhat/Mask/NO-Hardhat/NO-Mask/NO-Safety Vest/Person/Safety Cone/Safety Vest/machinery/vehicle。安防检测器包·安全帽 01。"),
    ("sec-helmet-yolov8s", "安全帽/防护装备检测（YOLOv8s·18类）", "sec-helmet-yolov8s/helmet_yolov8s.onnx", "v8s",
     "Helmet/No-Helmet/Vest/Gloves/Goggles/worker 等 18 类防护装备（640 输入）。安防检测器包·安全帽 02。"),
    ("sec-fall-coco-yolov12m", "通用检测 COCO80（YOLOv12m·安防包）", "sec-fall-coco-yolov12m/coco_yolov12m.onnx", "v12m",
     "原包命名「跌倒检测」，实测元数据为 COCO 80 类通用检测（无跌倒类别），可作高精度人形/通用检测（CPU 约 136ms）。安防检测器包 01。"),
    ("sec-fall-yolo11n", "跌倒/行为检测（YOLO11n·7类）", "sec-fall-yolo11n/fall_behavior_yolo11n.onnx", "11n",
     "行为 7 类：fall/sit/sleep/standing/Violence/violence 等，含跌倒类别（640 输入）。安防检测器包·跌倒 03。"),
    ("sec-fight-nano", "打架检测-轻量（YOLO nano）", "sec-fight-nano/fight_yolo_nano.onnx", "nano",
     "暴力行为 2 类：non_violence/violence（640 输入，CPU 约 25ms）。安防检测器包·打架 01。"),
    ("sec-fight-small", "打架检测（YOLO small）", "sec-fight-small/fight_yolo_small.onnx", "small",
     "暴力行为 2 类：non_violence/violence（640 输入，精度更高）。安防检测器包·打架 02。"),
    ("sec-weapon-yolov8", "武器检测（YOLOv8·枪/刀）", "sec-weapon-yolov8/weapon_yolov8.onnx", "v8",
     "武器 2 类：guns/knife（640 输入）。安防检测器包·武器 02。"),
    ("sec-plate-yolov8", "车牌检测（YOLOv8n·安防包）", "sec-plate-yolov8/plate_yolov8.onnx", "v8n",
     "license_plate 单类车牌检测（640 输入），可配合车辆追踪车牌 OCR。安防检测器包·车牌 01。"),
]


def _ensure_security_detector_models():
    """安防检测器包：幂等登记 11 个模型并绑定本地 onnx 权重（缺权重则停用）。"""
    base = os.path.dirname(os.path.abspath(__file__))
    changed = False
    for key, name, rel_file, ver, desc in _SECURITY_DETECTOR_SPECS:
        rel = f"models/{rel_file}"
        abs_p = os.path.join(base, "uploads", rel.replace("/", os.sep))
        exists = os.path.isfile(abs_p)
        size = os.path.getsize(abs_p) if exists else 0
        m = AiModel.query.filter_by(model_key=key).first()
        if not m:
            m = AiModel(
                model_key=key, model_name=name, category="安防检测",
                task="object-detection", library="ultralytics", version=ver,
                description=desc + " ONNX Runtime CPU 推理。",
                status="0" if exists else "1",
            )
            db.session.add(m)
            changed = True
        if exists and (m.file_path != rel or m.file_size != size):
            m.file_path = rel
            m.file_size = size
            m.status = "0"
            changed = True
    if changed:
        db.session.commit()
    return changed


def _bind_vehicle_track_models():
    """绑定车辆追踪推荐权重元信息与本地 PP-OCRv6 目录（幂等）。"""
    base = os.path.dirname(os.path.abspath(__file__))
    uploads = os.path.join(base, "uploads")
    changed = False

    meta = {
        "yolo26s": {
            "model_name": "YOLO26s 通用检测",
            "category": "通用目标检测",
            "description": "Ultralytics YOLO26 small（COCO 通用目标检测）。",
        },
        "yolo26n": {
            "model_name": "YOLO26n 通用检测",
            "category": "通用目标检测",
            "description": "Ultralytics YOLO26 nano（COCO 通用目标检测，轻量）。",
        },
        "yolov8-license-plate": {
            "model_name": "车牌检测 YOLOv8（Koushim）",
            "category": "交通车辆",
            "description": "YOLOv8n 车牌定位（Koushim/yolov8-license-plate-detection，Ultralytics）。车辆追踪车牌检测可用。",
            "source_url": "https://huggingface.co/Koushim/yolov8-license-plate-detection",
        },
        "keremberke-yolov5n-license-plate": {
            "model_name": "车牌检测 YOLOv5n（keremberke）",
            "category": "交通车辆",
            "description": "YOLOv5n 车牌定位（keremberke）。车辆追踪兼容项，经专用加载器推理。",
            "source_url": "https://huggingface.co/keremberke/yolov5n-license-plate",
        },
        "keremberke-yolov5m-license-plate": {
            "model_name": "车牌检测 YOLOv5m（keremberke）",
            "category": "交通车辆",
            "description": "YOLOv5m 车牌定位（keremberke，精度高于 n）。车辆追踪兼容项，经专用加载器推理。",
            "source_url": "https://huggingface.co/keremberke/yolov5m-license-plate",
        },
        "yolov11-license-plate-n": {
            "model_name": "车牌检测 YOLOv11n（推荐·CPU）",
            "category": "交通车辆",
            "description": "YOLOv11 nano 车牌定位（morsetechlab）。CPU 友好，车辆追踪号牌检测推荐。",
            "source_url": "https://huggingface.co/morsetechlab/yolov11-license-plate-detection#license-plate-finetune-v1n.pt",
        },
        "yolov11-license-plate-s": {
            "model_name": "车牌检测 YOLOv11s（推荐·精度）",
            "category": "交通车辆",
            "description": "YOLOv11 small 车牌定位（morsetechlab）。精度更高，CPU 仍可用。",
            "source_url": "https://huggingface.co/morsetechlab/yolov11-license-plate-detection#license-plate-finetune-v1s.pt",
        },
        "yolo26n-plate": {
            "model_name": "车牌检测 YOLO26n（CodexParas）",
            "category": "交通车辆",
            "description": "YOLO26n 车牌 bbox（CodexParas）。车辆 ROI 内定位推荐。",
            "source_url": "https://huggingface.co/CodexParas/car-plate-detection-yolov26#best.pt",
        },
        "yolo26s-plate-pose": {
            "model_name": "车牌四点 YOLO26s-pose（推荐·透视）",
            "category": "交通车辆",
            "description": "YOLO26 pose 车牌框+4角点，透视矫正优先。",
            "source_url": "https://raw.githubusercontent.com/we0091234/yolo26-plate/main/weights/yolo26s-plate-detect.pt",
        },
        "yolo26n-obb": {
            "model_name": "YOLO26n 旋转框 OBB",
            "category": "交通车辆",
            "description": "旋转框 → 四点透视（通用 OBB，建议在车辆 ROI 内使用）。",
            "source_url": "https://huggingface.co/openvision/yolo26-n-obb#model.pt",
        },
    }
    for key, fields in meta.items():
        m = AiModel.query.filter_by(model_key=key).first()
        if not m:
            continue
        for k, v in fields.items():
            if getattr(m, k, None) != v:
                setattr(m, k, v)
                changed = True

    ocr_specs = [
        ("PP-OCRv6_small_det_onnx", "PP-OCRv6 small 检测（推荐）", "text-detection", "models/PP-OCRv6_small_det_onnx"),
        ("PP-OCRv6_small_rec_onnx", "PP-OCRv6 small 识别（推荐）", "text-recognition", "models/PP-OCRv6_small_rec_onnx"),
    ]
    for key, name, task, rel in ocr_specs:
        m = AiModel.query.filter_by(model_key=key).first()
        if not m:
            continue
        abs_dir = os.path.join(uploads, rel.replace("/", os.sep))
        if not os.path.isdir(abs_dir):
            continue
        size = 0
        for root, _dirs, files in os.walk(abs_dir):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    size += os.path.getsize(fp)
        if m.model_name != name:
            m.model_name = name
            changed = True
        if m.task != task:
            m.task = task
            changed = True
        if (m.library or "").lower() != "rapidocr":
            m.library = "rapidocr"
            changed = True
        if m.file_path != rel:
            m.file_path = rel
            changed = True
        if m.file_size != size:
            m.file_size = size
            changed = True
        if m.status != "0":
            m.status = "0"
            changed = True

    if changed:
        db.session.commit()
    return changed


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
    zone_overlay = {
        "fillColor": "#CF1322",
        "borderColor": "#A8071A",
        "textColor": "#FFFFFF",
        "titleLines": ["ZONE ALARM"],
        "subtitleLines": ["区域越界", "请勿闯入/离开"],
        "panelWidthRatio": 0.72,
        "panelHeightRatio": 0.36,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#FFFFFF",
        "triangleMark": "#A8071A",
    }
    zone_cfg = {
        "classes": [
            "person", "Person", "people", "human", "pedestrian", "人", "行人",
            "car", "bus", "truck", "motorcycle", "bicycle", "车辆", "汽车",
        ],
        "region": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
        "direction": "both",
        "min_confidence": 0.25,
        "consecutive_frames": 1,
        "cooldown_sec": 30,
        "title_template": "区域越界：{crossCount} 次穿越",
        "message_template": "核查区域越界人员/车辆身份与事由；必要时广播劝离并联动门禁/安保。",
        "overlay": zone_overlay,
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
            rule_key="zone-intrusion",
            name="区域越界告警",
            description="目标进出 TrackZone 多边形区域时触发（目标追踪页自定义多边形可覆盖默认区域）",
            rule_type="zone_crossing",
            config_json=json.dumps(zone_cfg, ensure_ascii=False),
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
        "zone-intrusion": zone_cfg,
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


def seed_open_platform():
    """开放平台菜单 + 演示应用 + 桥接服务账号（幂等）。

    演示 Key（仅开发）：tp_live_demo_change_me_in_production_01
    """
    # 系统管理下挂「开放平台」
    _ensure_ai_menu(190, 1, "开放平台", "C", "system:openapp:list",
                    path="/system/open-app", component="system/openApp/index",
                    icon="Key", order=90, grant_common=True)
    _ensure_ai_menu(1901, 190, "开放应用查询", "F", "system:openapp:query", grant_common=True)
    _ensure_ai_menu(1902, 190, "开放应用新增", "F", "system:openapp:add")
    _ensure_ai_menu(1903, 190, "开放应用修改", "F", "system:openapp:edit")
    _ensure_ai_menu(1904, 190, "开放应用删除", "F", "system:openapp:remove")

    # 桥接服务账号（admin 权限，仅内调，不可登录业务）
    bridge = User.query.filter_by(username=BRIDGE_USER).first()
    if bridge is None:
        bridge = User(
            username=BRIDGE_USER,
            nickname="OpenAPI Bridge",
            status="0",
            del_flag="0",
            email="openapi-bridge@localhost",
        )
        bridge.set_password(secrets.token_urlsafe(32))
        admin_role = Role.query.filter_by(role_key="admin").first()
        if admin_role:
            bridge.roles = [admin_role]
        db.session.add(bridge)
        db.session.commit()

    # 演示应用：全量域
    domain_scopes = scopes_for_all_bridgeable_domains()

    demo = OpenApp.query.filter_by(app_id="app_demo").first()
    if demo is None:
        app = OpenApp(
            app_id="app_demo",
            name="演示开放应用",
            status="0",
            qps_limit=20,
            daily_limit=10000,
            domain_id="full",
            category="platform",
            remark="本地开发演示（含全量域 Scope），生产务必轮换密钥并收敛授权",
        )
        app.set_scopes(domain_scopes)
        db.session.add(app)
        db.session.flush()
        demo_key = "tp_live_demo_change_me_in_production_01"
        db.session.add(OpenApiKey(
            app_pk=app.id,
            name="demo",
            key_prefix=key_prefix(demo_key),
            key_hash=hash_api_key(demo_key),
            status="0",
        ))
        db.session.commit()
    else:
        cur = set(demo.scope_list())
        legacy = {"vision:detect", "vision:ocr", "face:recognize", "water:read", "jobs:read"}
        if cur <= legacy or not any(s.startswith("domain:") for s in cur):
            demo.set_scopes(domain_scopes)
            demo.domain_id = demo.domain_id or "full"
            demo.category = demo.category or "platform"
            db.session.commit()

    # 按 Blueprint 域各建一个应用（幂等，覆盖全部接口分类）
    for d in list_domains():
        if d["id"] == "other":
            continue
        app_id = d["suggestedAppId"]
        scopes = scopes_for_domain(d["id"], include_fine=True)
        existing = OpenApp.query.filter_by(app_id=app_id).first()
        if existing:
            existing.domain_id = d["id"]
            existing.category = d["group"]
            existing.set_scopes(scopes)
            existing.name = d["suggestedName"]
            continue
        row = OpenApp(
            app_id=app_id,
            name=d["suggestedName"],
            status="0",
            qps_limit=20,
            daily_limit=10000,
            domain_id=d["id"],
            category=d["group"],
            remark=f"域全覆盖 · Blueprint={d.get('blueprint') or '-'} · 接口 {d['endpointCount']}",
        )
        row.set_scopes(scopes)
        db.session.add(row)
        db.session.flush()
        # 每域一把开发 Key（明文不入库；正式环境请在控制台重新签发）
        raw = f"tp_live_domain_{d['id']}_dev_only_change_me"
        db.session.add(OpenApiKey(
            app_pk=row.id,
            name="domain-default",
            key_prefix=key_prefix(raw),
            key_hash=hash_api_key(raw),
            status="0",
        ))
    db.session.commit()


def init_seed():
    if User.query.first():
        seed_ai_menus()   # 用户已存在也补齐 AI 菜单种子
        seed_ai_models()  # 用户已存在也补齐 AI 模型种子
        seed_alert_rules()
        seed_open_platform()
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
    seed_open_platform()
    return True


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        created = init_seed()
        print("种子数据已写入" if created else "已存在数据，跳过")
