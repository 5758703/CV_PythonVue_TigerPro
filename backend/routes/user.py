from flask import Blueprint, request, jsonify

from extensions import db
from models import User, Role, Job, Dept
from security import permission_required, current_user, apply_user_data_scope

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
    user = User.query.get_or_404(uid)
    data = user.to_dict()
    data["deptIds"] = [d.id for d in user.depts]
    return jsonify(code=0, data=data)


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
    if User.query.filter_by(username=username).first():
        return jsonify(code=409, message="用户名已存在"), 409

    user = User(
        username=username,
        nickname=data.get("nickname") or username,
        dept_id=data.get("deptId"),
        email=data.get("email"),
        phone=data.get("phone"),
        sex=data.get("sex", "0"),
        status=data.get("status", "0"),
    )
    user.set_password(data.get("password") or "123456")
    _apply_relations(user, data)
    db.session.add(user)
    db.session.commit()
    return jsonify(code=0, message="新增成功", data=user.to_dict()), 201


@user_bp.put("/<int:uid>")
@permission_required("system:user:edit")
def update_user(uid):
    user = User.query.get_or_404(uid)
    data = request.get_json(silent=True) or {}
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
    user = User.query.get_or_404(uid)
    if user.username == "admin":
        return jsonify(code=400, message="超级管理员不可删除"), 400
    user.del_flag = "2"  # 软删除
    db.session.commit()
    return jsonify(code=0, message="删除成功")
