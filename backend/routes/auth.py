from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token

from extensions import db
from models import User, Role, Menu
from security import login_required, current_user

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _menu_tree(menus):
    """把目录/菜单(M/C)列表构造成前端路由树。"""
    nodes = {
        m.id: {
            "id": m.id,
            "name": m.menu_name,
            "path": m.path,
            "component": m.component,
            "icon": m.icon,
            "menuType": m.menu_type,
            "perms": m.perms,
            "children": [],
        }
        for m in menus
    }
    roots = []
    for m in menus:
        node = nodes[m.id]
        parent = nodes.get(m.parent_id)
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify(code=400, message="用户名和密码不能为空"), 400

    user = User.query.filter_by(username=username, del_flag="0").first()
    if not user or not user.check_password(password):
        return jsonify(code=401, message="用户名或密码错误"), 401
    if user.status != "0":
        return jsonify(code=403, message="账号已停用"), 403

    token = create_access_token(identity=str(user.id))
    return jsonify(code=0, message="登录成功", data={"token": token})


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if len(username) < 3 or len(password) < 6:
        return jsonify(code=400, message="用户名至少3位，密码至少6位"), 400
    if User.query.filter_by(username=username).first():
        return jsonify(code=409, message="用户名已存在"), 409

    user = User(username=username, nickname=username)
    user.set_password(password)
    common = Role.query.filter_by(role_key="common").first()
    if common:
        user.roles = [common]
    db.session.add(user)
    db.session.commit()
    return jsonify(code=0, message="注册成功", data=user.to_dict()), 201


@auth_bp.get("/info")
@login_required
def info():
    """登录用户身份：基本信息 + 角色标识 + 权限标识集合。"""
    user = current_user()
    return jsonify(code=0, data={
        "user": user.to_dict(),
        "roles": user.role_keys(),
        "permissions": sorted(user.perms()),
    })


@auth_bp.get("/routers")
@login_required
def routers():
    """侧边栏路由：当前用户可见的目录/菜单(M/C)树。"""
    user = current_user()
    if user.is_admin:
        menus = Menu.query.filter(Menu.menu_type.in_(["M", "C"]), Menu.status == "0").all()
    else:
        menus = [m for m in user.all_menus() if m.menu_type in ("M", "C") and m.status == "0"]
    menus.sort(key=lambda m: (m.parent_id, m.order_num))
    return jsonify(code=0, data=_menu_tree(menus))


@auth_bp.post("/logout")
def logout():
    return jsonify(code=0, message="退出成功")
