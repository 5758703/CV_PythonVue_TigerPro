from flask import Blueprint, request, jsonify

from extensions import db
from models import Menu
from security import permission_required

menu_bp = Blueprint("sys_menu", __name__, url_prefix="/api/system/menu")


def _tree(menus, parent_id=0):
    nodes = []
    for m in menus:
        if m.parent_id == parent_id:
            item = m.to_dict()
            children = _tree(menus, m.id)
            if children:
                item["children"] = children
            nodes.append(item)
    return sorted(nodes, key=lambda x: x["orderNum"])


@menu_bp.get("")
@permission_required("system:menu:list")
def list_menus():
    name = request.args.get("menuName", "").strip()
    menus = Menu.query.all()
    if name:
        menus = [m for m in menus if name in (m.menu_name or "")]
    return jsonify(code=0, data=_tree(menus))


@menu_bp.get("/<int:mid>")
@permission_required("system:menu:query")
def get_menu(mid):
    return jsonify(code=0, data=Menu.query.get_or_404(mid).to_dict())


@menu_bp.post("")
@permission_required("system:menu:add")
def create_menu():
    data = request.get_json(silent=True) or {}
    if not data.get("menuName") or not data.get("menuType"):
        return jsonify(code=400, message="菜单名称和类型必填"), 400
    menu = Menu(
        parent_id=data.get("parentId", 0),
        menu_name=data["menuName"],
        menu_type=data["menuType"],
        perms=data.get("perms"),
        path=data.get("path"),
        component=data.get("component"),
        icon=data.get("icon"),
        order_num=data.get("orderNum", 0),
        visible=data.get("visible", "0"),
        status=data.get("status", "0"),
    )
    db.session.add(menu)
    db.session.commit()
    return jsonify(code=0, message="新增成功", data=menu.to_dict()), 201


@menu_bp.put("/<int:mid>")
@permission_required("system:menu:edit")
def update_menu(mid):
    menu = Menu.query.get_or_404(mid)
    data = request.get_json(silent=True) or {}
    for field, attr in [("parentId", "parent_id"), ("menuName", "menu_name"),
                        ("menuType", "menu_type"), ("perms", "perms"),
                        ("path", "path"), ("component", "component"),
                        ("icon", "icon"), ("orderNum", "order_num"),
                        ("visible", "visible"), ("status", "status")]:
        if field in data:
            setattr(menu, attr, data[field])
    db.session.commit()
    return jsonify(code=0, message="修改成功", data=menu.to_dict())


@menu_bp.delete("/<int:mid>")
@permission_required("system:menu:remove")
def delete_menu(mid):
    menu = Menu.query.get_or_404(mid)
    if Menu.query.filter_by(parent_id=mid).first():
        return jsonify(code=400, message="存在子菜单，不可删除"), 400
    db.session.delete(menu)
    db.session.commit()
    return jsonify(code=0, message="删除成功")
