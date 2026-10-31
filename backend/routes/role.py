from flask import Blueprint, request, jsonify, abort

from extensions import db
from models import Role, Menu
from security import permission_required, platform_admin_required, current_user
from services.organization_auth import DOMAINS, audit

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
        ids = data["menuIds"]
        if not isinstance(ids, list) or not all(type(i) is int for i in ids):
            abort(400, description="菜单权限格式错误")
        menus = Menu.query.filter(Menu.id.in_(ids), Menu.status == "0").all()
        if len(menus) != len(set(ids)):
            abort(400, description="菜单权限不存在或已停用")
        role.menus = menus


def _validate(data):
    if "businessDomain" in data and data["businessDomain"] not in DOMAINS:
        abort(400, description="未知业务域")
    if "dataScope" in data and (type(data["dataScope"]) is not int or data["dataScope"] not in (1, 2, 3, 4)):
        abort(400, description="未知旧版默认数据范围")
    if "status" in data and data["status"] not in ("0", "1"):
        abort(400, description="未知角色状态")


@role_bp.post("")
@permission_required("system:role:add")
@platform_admin_required
def create_role():
    data = request.get_json(silent=True) or {}
    _validate(data)
    role_key = (data.get("roleKey") or "").strip()
    if not role_key or not data.get("roleName"):
        return jsonify(code=400, message="角色名和权限字符必填"), 400
    if Role.query.filter_by(role_key=role_key).first():
        return jsonify(code=409, message="权限字符已存在"), 409

    role = Role(
        role_name=data["roleName"],
        role_key=role_key,
        role_sort=data.get("roleSort", 0),
        business_domain=data.get("businessDomain", "SYSTEM"),
        data_scope=data.get("dataScope", 1),
        status=data.get("status", "0"),
        remark=data.get("remark"),
    )
    _apply_menus(role, data)
    db.session.add(role)
    db.session.flush()
    audit(current_user().id, None, "ROLE_CREATED", {"after": role.to_dict(with_menus=True)})
    db.session.commit()
    return jsonify(code=0, message="新增成功", data=role.to_dict()), 201


@role_bp.put("/<int:rid>")
@permission_required("system:role:edit")
@platform_admin_required
def update_role(rid):
    role = Role.query.get_or_404(rid)
    if role.role_key == "admin":
        return jsonify(code=400, message="超级管理员角色不可修改"), 400
    data = request.get_json(silent=True) or {}
    _validate(data)
    before = role.to_dict(with_menus=True)
    if "businessDomain" in data and data["businessDomain"] != role.business_domain:
        from models.organization import OrgGrant
        if OrgGrant.query.filter_by(role_id=rid, status="0").first():
            abort(400, description="角色仍有授权，变更业务域前请先审核并撤销旧授权")
    for field, attr in [("roleName", "role_name"), ("roleSort", "role_sort"),
                        ("dataScope", "data_scope"), ("businessDomain", "business_domain"),
                        ("status", "status"), ("remark", "remark")]:
        if field in data:
            setattr(role, attr, data[field])
    _apply_menus(role, data)
    audit(current_user().id, None, "ROLE_UPDATED", {"before": before, "after": role.to_dict(with_menus=True)})
    db.session.commit()
    return jsonify(code=0, message="修改成功", data=role.to_dict())


@role_bp.delete("/<int:rid>")
@permission_required("system:role:remove")
@platform_admin_required
def delete_role(rid):
    role = Role.query.get_or_404(rid)
    if role.role_key == "admin":
        return jsonify(code=400, message="超级管理员角色不可删除"), 400
    role.del_flag = "2"
    audit(current_user().id, None, "ROLE_DELETED", {"roleId": rid})
    db.session.commit()
    return jsonify(code=0, message="删除成功")
