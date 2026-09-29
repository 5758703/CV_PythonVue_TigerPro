from flask import Blueprint, request, jsonify

from extensions import db
from models import User, Role, Job, Dept
from security import (
    permission_required, current_user, apply_user_data_scope, data_scope_dept_ids,
)

user_bp = Blueprint("sys_user", __name__, url_prefix="/api/system/user")


@user_bp.get("")
@permission_required("system:user:list")
def list_users():
    page = int(request.args.get("pageNum", 1))
    size = int(request.args.get("pageSize", 10))
    username = request.args.get("username", "").strip()
    status = request.args.get("status", "").strip()

    query = User.query.filter(User.del_flag == "0")
    query = apply_user_data_scope(query, current_user())  # 数据权限
    if username:
        query = query.filter(User.username.like(f"%{username}%"))
    if status:
        query = query.filter(User.status == status)

    total = query.count()
    rows = query.order_by(User.id).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [u.to_dict() for u in rows], "total": total})


@user_bp.get("/<int:uid>")
@permission_required("system:user:query")
def get_user(uid):
    user = _scoped_user(uid)
    data = user.to_dict()
    data["deptIds"] = [d.id for d in user.depts]
    return jsonify(code=0, data=data)


def _scoped_user(uid):
    query = User.query.filter(User.id == uid, User.del_flag == "0")
    return apply_user_data_scope(query, current_user()).first_or_404()


def _allowed_dept(dept_id):
    actor = current_user()
    allowed = data_scope_dept_ids(actor)
    return allowed is None or dept_id in allowed


def _allowed_depts(data):
    if "deptIds" not in data:
        return True
    ids = data["deptIds"]
    return isinstance(ids, list) and all(_allowed_dept(dept_id) for dept_id in ids)


def _can_assign_roles(data, existing=None):
    if "roleIds" in data and not isinstance(data["roleIds"], list):
        return False
    if "roleIds" not in data or current_user().is_admin:
        return True
    requested = set(data.get("roleIds") or [])
    assigned = {role.id for role in existing.roles} if existing else set()
    return requested == assigned


def _apply_relations(user, data):
    if "roleIds" in data:
        user.roles = Role.query.filter(Role.id.in_(data.get("roleIds") or [])).all()
    if "postIds" in data:
        user.posts = Job.query.filter(Job.id.in_(data.get("postIds") or [])).all()
    if "deptIds" in data:
        user.depts = Dept.query.filter(Dept.id.in_(data.get("deptIds") or [])).all()


@user_bp.post("")
@permission_required("system:user:add")
def create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify(code=400, message="用户名必填"), 400
    password = data.get("password") or ""
    if not isinstance(password, str) or len(password) < 6:
        return jsonify(code=400, message="密码至少 6 位"), 400
    if User.query.filter_by(username=username).first():
        return jsonify(code=409, message="用户名已存在"), 409
    if not _allowed_dept(data.get("deptId")) or not _allowed_depts(data) or not _can_assign_roles(data):
        return jsonify(code=403, message="不能在授权范围外创建用户或授予角色"), 403

    user = User(
        username=username,
        nickname=data.get("nickname") or username,
        dept_id=data.get("deptId"),
        email=data.get("email"),
        phone=data.get("phone"),
        sex=data.get("sex", "0"),
        status=data.get("status", "0"),
    )
    user.set_password(password)
    _apply_relations(user, data)
    db.session.add(user)
    db.session.commit()
    return jsonify(code=0, message="新增成功", data=user.to_dict()), 201


@user_bp.put("/<int:uid>")
@permission_required("system:user:edit")
def update_user(uid):
    user = _scoped_user(uid)
    data = request.get_json(silent=True) or {}
    if ((user.is_admin and not current_user().is_admin)
            or ("deptId" in data and not _allowed_dept(data["deptId"]))
            or not _allowed_depts(data)
            or not _can_assign_roles(data, user)):
        return jsonify(code=403, message="不能修改授权范围外的部门或角色"), 403
    if data.get("password") and (not isinstance(data["password"], str) or len(data["password"]) < 6):
        return jsonify(code=400, message="密码至少 6 位"), 400
    for field, attr in [("nickname", "nickname"), ("email", "email"),
                        ("phone", "phone"), ("sex", "sex"), ("status", "status")]:
        if field in data:
            setattr(user, attr, data[field])
    if "deptId" in data:
        user.dept_id = data["deptId"]
    if data.get("password"):
        user.set_password(data["password"])
    _apply_relations(user, data)
    db.session.commit()
    return jsonify(code=0, message="修改成功", data=user.to_dict())


@user_bp.delete("/<int:uid>")
@permission_required("system:user:remove")
def delete_user(uid):
    user = _scoped_user(uid)
    if user.is_admin:
        return jsonify(code=400, message="超级管理员不可删除"), 400
    user.del_flag = "2"  # 软删除
    db.session.commit()
    return jsonify(code=0, message="删除成功")
