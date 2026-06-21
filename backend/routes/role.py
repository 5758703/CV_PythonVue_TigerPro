from flask import Blueprint, request, jsonify

from extensions import db
from models import Role, Menu
from security import permission_required

role_bp = Blueprint("sys_role", __name__, url_prefix="/api/system/role")


@role_bp.get("")
@permission_required("system:role:list")
def list_roles():
    page = int(request.args.get("pageNum", 1))
    size = int(request.args.get("pageSize", 10))
    name = request.args.get("roleName", "").strip()

    query = Role.query.filter(Role.del_flag == "0")
    if name:
        query = query.filter(Role.role_name.like(f"%{name}%"))
    total = query.count()
    rows = query.order_by(Role.role_sort).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": total})


@role_bp.get("/<int:rid>")
@permission_required("system:role:query")
def get_role(rid):
    role = Role.query.get_or_404(rid)
    return jsonify(code=0, data=role.to_dict(with_menus=True))


def _apply_menus(role, data):
    if "menuIds" in data:
        role.menus = Menu.query.filter(Menu.id.in_(data.get("menuIds") or [])).all()


@role_bp.post("")
@permission_required("system:role:add")
def create_role():
    data = request.get_json(silent=True) or {}
    role_key = (data.get("roleKey") or "").strip()
    if not role_key or not data.get("roleName"):
        return jsonify(code=400, message="角色名和权限字符必填"), 400
    if Role.query.filter_by(role_key=role_key).first():
        return jsonify(code=409, message="权限字符已存在"), 409

    role = Role(
        role_name=data["roleName"],
        role_key=role_key,
        role_sort=data.get("roleSort", 0),
        data_scope=data.get("dataScope", 1),
        status=data.get("status", "0"),
        remark=data.get("remark"),
    )
    _apply_menus(role, data)
    db.session.add(role)
    db.session.commit()
    return jsonify(code=0, message="新增成功", data=role.to_dict()), 201


@role_bp.put("/<int:rid>")
@permission_required("system:role:edit")
def update_role(rid):
    role = Role.query.get_or_404(rid)
    if role.role_key == "admin":
        return jsonify(code=400, message="超级管理员角色不可修改"), 400
    data = request.get_json(silent=True) or {}
    for field, attr in [("roleName", "role_name"), ("roleSort", "role_sort"),
                        ("dataScope", "data_scope"), ("status", "status"), ("remark", "remark")]:
        if field in data:
            setattr(role, attr, data[field])
    _apply_menus(role, data)
    db.session.commit()
    return jsonify(code=0, message="修改成功", data=role.to_dict())


@role_bp.delete("/<int:rid>")
@permission_required("system:role:remove")
def delete_role(rid):
    role = Role.query.get_or_404(rid)
    if role.role_key == "admin":
        return jsonify(code=400, message="超级管理员角色不可删除"), 400
    role.del_flag = "2"
    db.session.commit()
    return jsonify(code=0, message="删除成功")
