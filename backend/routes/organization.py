"""Platform-managed membership lifecycle and explainable organization grants."""
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, abort

from extensions import db
from models import Dept, Role, User
from models.organization import OrgMembership, OrgGrant, OrgAuthAudit
from security import login_required, platform_admin_required, current_user
from services.organization_auth import (
    SCOPES, active_org, valid_memberships, grant_effective, grant_org_ids,
    role_allowed, in_period, audit, bump,
)

organization_bp = Blueprint("organization", __name__, url_prefix="/api/system/organization")


def _error(message):
    abort(400, description=message)


def _time(value, default=None):
    if value in (None, ""):
        return default
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, TypeError, AttributeError):
        _error("有效期必须是 ISO 日期时间（UTC）")


def _period(data, member=None):
    start = _time(data.get("validFrom"), datetime.utcnow())
    end = _time(data.get("validTo"), member.valid_to if member else None)
    if end and (end <= start or end <= datetime.utcnow()):
        _error("结束时间必须晚于开始时间和当前时间")
    if member and (start < member.valid_from or (member.valid_to and (not end or end > member.valid_to))):
        _error("授权有效期不得超过任职有效期")
    return start, end


def _user(uid):
    user = User.query.filter_by(id=uid, del_flag="0").with_for_update().first_or_404()
    if user.is_admin:
        _error("平台管理员账号不使用业务组织授权，请使用普通账号登记任职")
    return user


def _grant_view(grant):
    data = grant.to_dict()
    data["effective"] = grant_effective(grant)
    data["resolvedOrgIds"] = sorted(grant_org_ids(grant)) if data["effective"] else []
    data["permissions"] = sorted({m.perms for m in grant.role.menus if m.status == "0" and m.perms})
    data["reason"] = "有效：任职、角色、来源、有效期及组织范围均通过" if data["effective"] else "未生效：请检查任职、角色、组织状态、来源及有效期"
    return data


@organization_bp.get("/users/<int:uid>")
@login_required
@platform_admin_required
def overview(uid):
    user = User.query.filter_by(id=uid, del_flag="0").first_or_404()
    memberships = OrgMembership.query.filter_by(user_id=uid).order_by(OrgMembership.id).all()
    grants = OrgGrant.query.join(OrgMembership).filter(OrgMembership.user_id == uid).order_by(OrgGrant.id).all()
    return jsonify(code=0, data=dict(user=user.to_dict(), authVersion=user.auth_version,
        memberships=[dict(m.to_dict(), effective=in_period(m) and active_org(m.org_id)) for m in memberships],
        grants=[_grant_view(g) for g in grants],
        audit=[a.to_dict() for a in OrgAuthAudit.query.filter_by(subject_id=uid)
               .order_by(OrgAuthAudit.id.desc()).limit(100)]))


@organization_bp.post("/users/<int:uid>/memberships")
@login_required
@platform_admin_required
def create_membership(uid):
    user = _user(uid)
    data = request.get_json(silent=True) or {}
    org_id = data.get("orgId")
    org = db.session.get(Dept, org_id) if isinstance(org_id, int) and not isinstance(org_id, bool) else None
    if not org or not active_org(org.id):
        _error("请选择有效组织")
    kind = data.get("memberKind", "MEMBER")
    if not isinstance(kind, str) or not kind.strip() or len(kind) > 64:
        _error("任职名称必填且不超过64字")
    start, end = _period(data)
    for m in OrgMembership.query.filter_by(user_id=uid, org_id=org.id, member_kind=kind, status="0"):
        if (not m.valid_to or start < m.valid_to) and (not end or m.valid_from < end):
            _error("同组织、同任职的有效期不能重叠")
    primary = data.get("isPrimary", False)
    if not isinstance(primary, bool):
        _error("主行政部门标记必须是布尔值")
    if primary and (org.org_type != "ADMIN" or start > datetime.utcnow()):
        _error("主部门只能选择当前生效的行政任职")
    if primary and any(m.is_primary for m in valid_memberships(user)):
        _error("已有有效主行政任职，请先结束旧任职，再登记新任职")
    m = OrgMembership(user_id=uid, org_id=org.id, member_kind=kind.strip(), is_primary=primary,
                      valid_from=start, valid_to=end)
    db.session.add(m)
    db.session.flush()
    user.org_auth_migrated = True
    if primary:
        user.dept_id = org.id
    bump(user)
    audit(current_user().id, uid, "MEMBERSHIP_CREATED", {"after": m.to_dict()})
    db.session.commit()
    return jsonify(code=0, data=m.to_dict(), message="任职已登记；请为此任职单独授权"), 201


@organization_bp.delete("/memberships/<int:mid>")
@login_required
@platform_admin_required
def end_membership(mid):
    member = db.session.get(OrgMembership, mid) or abort(404)
    user = _user(member.user_id)
    before = member.to_dict()
    member.status = "1"
    now = datetime.utcnow()
    if member.valid_from < now:
        member.valid_to = min(member.valid_to, now) if member.valid_to else now
    grants = OrgGrant.query.filter_by(membership_id=mid, status="0").all()
    for grant in grants:
        grant.status = "1"
    if member.is_primary and user.dept_id == member.org_id:
        user.dept_id = None
    bump(user)
    audit(current_user().id, user.id, "MEMBERSHIP_ENDED", {
        "before": before, "after": member.to_dict(), "revokedGrantIds": [g.id for g in grants],
        "handover": "仅处理系统管理任职；本项目尚无审批待办引擎"})
    db.session.commit()
    return jsonify(code=0, message="任职及其关联授权已结束，其他任职保持有效")


@organization_bp.post("/users/<int:uid>/grants")
@login_required
@platform_admin_required
def create_grant(uid):
    user = _user(uid)
    data = request.get_json(silent=True) or {}
    mid, rid = data.get("membershipId"), data.get("roleId")
    if not all(isinstance(i, int) and not isinstance(i, bool) for i in (mid, rid)):
        _error("请选择任职和角色")
    member, role = db.session.get(OrgMembership, mid), db.session.get(Role, rid)
    if not member or member.user_id != uid or not in_period(member) or not active_org(member.org_id):
        _error("任职不属于此用户或已失效")
    if not role or not role_allowed(role, member.org.org_type):
        _error("角色停用、业务域不匹配或属于不可转授的平台管理员角色")
    scope = data.get("scopeType", "ORG")
    if scope not in SCOPES:
        _error("未知数据范围")
    anchor = data.get("scopeAnchorOrgId", member.org_id)
    ids = data.get("scopeOrgIds", [])
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        _error("自定义组织范围格式错误")
    if scope == "CUSTOM_ORG":
        if not ids:
            _error("自定义范围不可为空")
        anchor = None
    elif ids:
        _error("非自定义范围不能附带自定义组织")
    if scope == "DOMAIN_ALL":
        anchor = None
    check_ids = ids if scope == "CUSTOM_ORG" else ([anchor] if anchor is not None else [])
    for oid in check_ids:
        if not isinstance(oid, int) or isinstance(oid, bool) or not active_org(oid):
            _error("授权范围含无效组织")
        if db.session.get(Dept, oid).org_type != member.org.org_type:
            _error("授权范围不能跨越组织类型")
    if scope in {"SELF", "ORG", "ORG_SUBTREE"} and anchor is None:
        _error("此范围必须有锚点组织")
    if scope == "SELF" and anchor != member.org_id:
        _error("SELF 范围必须限定当前任职组织")
    source = data.get("sourceType", "MEMBERSHIP")
    if source not in {"MEMBERSHIP", "MANUAL"}:
        _error("不支持的授权来源")
    approval = data.get("approvalRef")
    if approval is not None and (not isinstance(approval, str) or len(approval) > 255):
        _error("批准依据格式错误")
    if source == "MANUAL" and (not approval or not approval.strip()):
        _error("人工授权需要批准依据")
    start, end = _period(data, member)
    grant = OrgGrant(membership_id=mid, role_id=rid, scope_type=scope, scope_anchor_org_id=anchor,
                     scope_org_ids=sorted(set(ids)), source_type=source, source_ref=str(mid),
                     approval_ref=approval, valid_from=start, valid_to=end, granted_by=current_user().id)
    db.session.add(grant)
    db.session.flush()
    bump(user)
    audit(current_user().id, uid, "GRANT_CREATED", {"after": grant.to_dict()})
    db.session.commit()
    return jsonify(code=0, data=_grant_view(grant)), 201


@organization_bp.delete("/grants/<int:gid>")
@login_required
@platform_admin_required
def revoke_grant(gid):
    grant = db.session.get(OrgGrant, gid) or abort(404)
    user = _user(grant.membership.user_id)
    before = grant.to_dict()
    grant.status = "1"
    bump(user)
    audit(current_user().id, user.id, "GRANT_REVOKED", {"before": before, "after": grant.to_dict()})
    db.session.commit()
    return jsonify(code=0, message="此来源授权已撤销；其他独立有效授权仍可能提供权限")
