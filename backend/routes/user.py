from flask import Blueprint, request, jsonify, g, abort
from datetime import datetime

from extensions import db
from models import User, Role, Job, Dept
from security import (
    permission_required, current_user, apply_user_data_scope, data_scope_dept_ids,
)
from models.organization import OrgMembership, OrgGrant
from services.organization_auth import user_view, audit, bump, scope_user_query, managed

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
    return jsonify(code=0, data={"rows": [user_view(u, current_user(), "system:user:list") for u in rows], "total": total})


@user_bp.get("/<int:uid>")
@permission_required("system:user:query")
def get_user(uid):
    user = _scoped_user(uid)
    data = user_view(user, current_user(), "system:user:query")
    if current_user().is_admin:
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


def _validate_admin_relations(data):
    if "deptId" in data and data["deptId"] is not None:
        dept = db.session.get(Dept, data["deptId"]) if isinstance(data["deptId"], int) else None
        from services.organization_auth import active_org
        if not dept or dept.org_type != "ADMIN" or not active_org(dept.id):
            abort(400, description="主部门必须是有效行政组织；党组织请在任职管理中登记")
    for key, model in (("roleIds", Role), ("postIds", Job), ("deptIds", Dept)):
        if key not in data:
            continue
        ids = data[key]
        if not isinstance(ids, list) or not all(type(i) is int for i in ids):
            abort(400, description="关联记录格式错误")
        rows = model.query.filter(model.id.in_(ids), model.status == "0").all()
        if len(rows) != len(set(ids)) or any(getattr(r, "del_flag", "0") != "0" for r in rows):
            abort(400, description="关联记录不存在或已停用")
        if model is Dept and any(r.org_type != "ADMIN" for r in rows):
            abort(400, description="请通过任职管理登记党组织，不可混入旧部门关联")
        if model is Role and any(r.business_domain == "PARTY" for r in rows):
            abort(400, description="党务角色必须通过党组织任职单独授权")


def _sync_primary_grants(user, old_dept=None, role_change=False):
    """Compatibility form updates only primary ADMIN/LEGACY sources."""
    if old_dept != user.dept_id:
        for m in OrgMembership.query.filter_by(user_id=user.id, is_primary=True, status="0"):
            if m.org.org_type != "ADMIN":
                continue
            m.status = "1"
            m.valid_to = datetime.utcnow()
            for grant in OrgGrant.query.filter_by(membership_id=m.id, status="0"):
                grant.status = "1"
    if not user.dept_id:
        return
    member = OrgMembership.query.filter_by(user_id=user.id, org_id=user.dept_id,
                                          is_primary=True, status="0").first()
    if not member:
        member = OrgMembership(user_id=user.id, org_id=user.dept_id, is_primary=True, member_kind="PRIMARY_ADMIN")
        db.session.add(member)
        db.session.flush()
    if role_change or old_dept != user.dept_id:
        for grant in OrgGrant.query.filter_by(membership_id=member.id, source_type="LEGACY", status="0"):
            grant.status = "1"
        for role in user.roles:
            if role.role_key == "admin":
                continue
            db.session.add(OrgGrant(membership_id=member.id, role_id=role.id,
                scope_type={1: "SELF", 2: "ORG", 3: "ORG_SUBTREE", 4: "DOMAIN_ALL"}.get(role.data_scope, "SELF"),
                scope_anchor_org_id=user.dept_id if role.data_scope != 4 else None,
                source_type="LEGACY", source_ref=str(member.id), valid_to=member.valid_to,
                granted_by=current_user().id))
    user.org_auth_migrated = True


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
    if not current_user().is_admin:
        return jsonify(code=403, message="创建统一账号需要平台管理员；组织成员请使用已有账号登记任职"), 403
    _validate_admin_relations(data)
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
    db.session.flush()
    _sync_primary_grants(user, role_change=True)
    audit(current_user().id, user.id, "USER_CREATED", {"deptId": user.dept_id, "roleIds": [r.id for r in user.roles]})
    db.session.commit()
    return jsonify(code=0, message="新增成功", data=user.to_dict()), 201


@user_bp.put("/<int:uid>")
@permission_required("system:user:edit")
def update_user(uid):
    user = _scoped_user(uid)
    data = request.get_json(silent=True) or {}
    if not current_user().is_admin:
        protected = {"password", "status", "deptId", "deptIds", "roleIds", "postIds"}
        if protected.intersection(data):
            return jsonify(code=403, message="组织范围权限不能修改统一账号安全信息或其他任职，请联系平台管理员"), 403
        if {"phone", "email"}.intersection(data) and user.id != current_user().id and not scope_user_query(
                User.query.filter_by(id=user.id), current_user(), "system:user:edit", sensitive=True).first():
            return jsonify(code=403, message="缺少此组织范围的用户敏感字段权限"), 403
    else:
        _validate_admin_relations(data)
    if ((user.is_admin and not current_user().is_admin)
            or ("deptId" in data and not _allowed_dept(data["deptId"]))
            or not _allowed_depts(data)
            or not _can_assign_roles(data, user)):
        return jsonify(code=403, message="不能修改授权范围外的部门或角色"), 403
    if data.get("password") and (not isinstance(data["password"], str) or len(data["password"]) < 6):
        return jsonify(code=400, message="密码至少 6 位"), 400
    before = {"deptId": user.dept_id, "roleIds": [r.id for r in user.roles], "status": user.status}
    old_dept = user.dept_id
    for field, attr in [("nickname", "nickname"), ("email", "email"),
                        ("phone", "phone"), ("sex", "sex"), ("status", "status")]:
        if field in data:
            setattr(user, attr, data[field])
    if "deptId" in data:
        user.dept_id = data["deptId"]
    if data.get("password"):
        user.set_password(data["password"])
    _apply_relations(user, data)
    if current_user().is_admin and ("deptId" in data or "roleIds" in data):
        _sync_primary_grants(user, old_dept, role_change="roleIds" in data)
    bump(user)
    audit(current_user().id, user.id, "USER_UPDATED", {"before": before,
        "after": {"deptId": user.dept_id, "roleIds": [r.id for r in user.roles], "status": user.status}})
    db.session.commit()
    return jsonify(code=0, message="修改成功", data=user_view(user, current_user(), "system:user:edit"))


@user_bp.delete("/<int:uid>")
@permission_required("system:user:remove")
def delete_user(uid):
    user = _scoped_user(uid)
    if not current_user().is_admin:
        return jsonify(code=403, message="删除统一账号会影响全部组织，仅限平台管理员"), 403
    if user.is_admin:
        return jsonify(code=400, message="超级管理员不可删除"), 400
    user.del_flag = "2"  # 软删除
    bump(user)
    audit(current_user().id, user.id, "USER_DELETED", {"userId": uid})
    db.session.commit()
    return jsonify(code=0, message="删除成功")
