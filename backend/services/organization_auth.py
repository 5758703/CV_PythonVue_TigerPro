"""Request-local organization authorization. No cross-request permission cache.

Only matching action grants contribute their own scopes. Hierarchy is computed
from parent IDs, never trusted from the denormalized ancestors display column.
"""
from datetime import datetime
from types import SimpleNamespace

from flask import g, request, abort
from sqlalchemy import and_, or_, exists

from extensions import db
from models import Dept, User
from models.organization import OrgMembership, OrgGrant, OrgAuthAudit

ORG_TYPES = {"ADMIN", "PARTY"}
DOMAINS = {"SYSTEM", "ADMIN", "PARTY", "COMMON"}
SCOPES = {"SELF", "ORG", "ORG_SUBTREE", "CUSTOM_ORG", "DOMAIN_ALL"}


def in_period(obj, now=None):
    now = now or datetime.utcnow()
    return obj.status == "0" and obj.valid_from <= now and (obj.valid_to is None or now < obj.valid_to)


def org_map():
    if "org_auth_tree" not in g:
        g.org_auth_tree = {d.id: d for d in Dept.query.all()}
    return g.org_auth_tree


def active_org(org_id):
    tree = org_map()
    node = tree.get(org_id)
    if not node or node.org_type not in ORG_TYPES:
        return False
    kind, seen = node.org_type, set()
    while node:
        if node.id in seen or node.status != "0" or node.del_flag != "0" or node.org_type != kind:
            return False
        seen.add(node.id)
        if not node.parent_id:
            return True
        node = tree.get(node.parent_id)
    return False


def subtree(org_id, include_inactive=False):
    tree = org_map()
    root = tree.get(org_id)
    if not root or (not include_inactive and not active_org(org_id)):
        return set()
    ids, pending = set(), [org_id]
    while pending:
        oid = pending.pop()
        if oid in ids:
            continue
        ids.add(oid)
        pending.extend(d.id for d in tree.values() if d.parent_id == oid and d.org_type == root.org_type
                       and (include_inactive or active_org(d.id)))
    return ids


def managed(user):
    return user.org_auth_migrated or OrgMembership.query.filter_by(user_id=user.id).first() is not None


def valid_memberships(user):
    return [m for m in OrgMembership.query.filter_by(user_id=user.id).all()
            if in_period(m) and active_org(m.org_id)]


def current_context(user):
    key = f"org_context_{user.id}"
    if key in g:
        return g.get(key)
    raw = request.headers.get("X-Org-Id")
    memberships = valid_memberships(user)
    if raw is not None:
        try:
            oid = int(raw)
        except (TypeError, ValueError):
            abort(403, description="工作身份无效，请重新选择")
        if not any(m.org_id == oid for m in memberships):
            abort(403, description="任职已失效或无权使用此组织身份")
    elif user.is_admin:
        oid = None  # Platform configuration session; not an assumed PARTY identity.
    elif managed(user):
        # Do not silently switch from an expired primary identity into another
        # active organization. A single remaining identity is safe to default.
        primary = [m for m in memberships if m.is_primary and m.org.org_type == "ADMIN"]
        choices = primary or memberships
        oid = choices[0].org_id if len({m.org_id for m in choices}) == 1 else None
    else:
        oid = user.dept_id if active_org(user.dept_id) else None
        if oid and org_map()[oid].org_type != "ADMIN":
            oid = None
    setattr(g, key, oid)
    return oid


def role_allowed(role, org_type):
    return role.status == "0" and role.del_flag == "0" and role.role_key != "admin" and (
        role.business_domain in ("SYSTEM", "COMMON", org_type))


def grant_effective(grant):
    m = grant.membership
    if not m or not m.user or m.user.status != "0" or m.user.del_flag != "0" or not grant.role:
        return False
    if not (in_period(grant) and in_period(m) and active_org(m.org_id)
            and role_allowed(grant.role, m.org.org_type)):
        return False
    if grant.source_type not in {"MEMBERSHIP", "MANUAL", "LEGACY"}:
        return False
    if grant.source_type in {"MEMBERSHIP", "LEGACY"} and grant.source_ref != str(m.id):
        return False
    if grant.valid_from < m.valid_from or (m.valid_to and (not grant.valid_to or grant.valid_to > m.valid_to)):
        return False
    return bool(grant_org_ids(grant))


def grant_org_ids(grant):
    m = grant.membership
    kind = m.org.org_type
    tree = org_map()
    if grant.scope_type == "DOMAIN_ALL":
        ids = {d.id for d in tree.values() if d.org_type == kind and active_org(d.id)}
    elif grant.scope_type == "CUSTOM_ORG":
        ids = set(grant.scope_org_ids or [])
        if not ids:
            return set()
    elif grant.scope_type in {"SELF", "ORG", "ORG_SUBTREE"}:
        anchor = grant.scope_anchor_org_id
        if grant.scope_type == "SELF" and anchor != m.org_id:
            return set()
        ids = subtree(anchor) if grant.scope_type == "ORG_SUBTREE" else {anchor}
    else:
        return set()
    if not all(i in tree and tree[i].org_type == kind and active_org(i) for i in ids):
        return set()
    return ids


def action_grants(user, perm=None):
    from security import _match
    oid = current_context(user)
    if not oid:
        return []
    if managed(user):
        grants = OrgGrant.query.join(OrgMembership).filter(
            OrgMembership.user_id == user.id, OrgMembership.org_id == oid).all()
        return [x for x in grants if grant_effective(x) and (not perm or _match(
            perm, {m.perms for m in x.role.menus if m.status == "0" and m.perms}))]
    # Transitional legacy path only for accounts with NO membership history.
    # It is restricted to ADMIN and still pairs each role with its own scope.
    if org_map()[oid].org_type != "ADMIN":
        return []
    m = SimpleNamespace(org_id=oid, org=org_map()[oid])
    return [SimpleNamespace(role=r, membership=m, scope_type={1: "SELF", 2: "ORG", 3: "ORG_SUBTREE", 4: "DOMAIN_ALL"}.get(r.data_scope, "SELF"),
                            scope_anchor_org_id=oid, scope_org_ids=[])
            for r in user.roles if role_allowed(r, "ADMIN") and (not perm or _match(
                perm, {x.perms for x in r.menus if x.status == "0" and x.perms}))]


def effective_menus(user):
    current_context(user)  # Validate even for platform administrators.
    if user.is_admin:
        return user.all_menus()
    result = {}
    for grant in action_grants(user):
        for menu in grant.role.menus:
            if menu.status == "0":
                result[menu.id] = menu
    if not managed(user) and current_context(user):
        # Old direct capability grants never create a wider row scope.
        result.update({m.id: m for m in user.menus if m.status == "0"})
    elif not managed(user) and not user.dept_id and request.headers.get("X-Org-Id") is None:
        # Existing unorganized public/demo accounts may use AI capabilities;
        # absence of an organization never grants system-management access.
        result.update({m.id: m for m in user.all_menus()
                       if not m.perms or not m.perms.startswith("system:")})
    return list(result.values())


def effective_permissions(user):
    current_context(user)
    return {"*:*:*"} if user.is_admin else {m.perms for m in effective_menus(user) if m.perms}


def operation_org_ids(user, perm):
    if user.is_admin:
        current_context(user)
        return None
    ids = set()
    for grant in action_grants(user, perm):
        if grant.scope_type != "SELF":
            ids.update(grant_org_ids(grant))
    return ids


def user_in_orgs(ids, kind):
    now = datetime.utcnow()
    membership = exists().where(and_(
        OrgMembership.user_id == User.id, OrgMembership.org_id.in_(ids),
        OrgMembership.status == "0", OrgMembership.valid_from <= now,
        or_(OrgMembership.valid_to.is_(None), OrgMembership.valid_to > now)))
    if kind == "ADMIN":
        # Compatibility primary field only where no explicit ADMIN history exists.
        admin_history = exists().where(and_(OrgMembership.user_id == User.id,
            OrgMembership.org_id == Dept.id, Dept.org_type == "ADMIN"))
        return or_(membership, and_(~admin_history, User.dept_id.in_(ids)))
    return membership


def scope_user_query(query, user, perm, sensitive=False):
    from security import _match
    if not user:
        return query.filter(False)
    current_context(user)
    if user.is_admin:
        return query
    conditions = []
    for grant in action_grants(user, perm):
        if sensitive and not _match("system:user:sensitive", {
                m.perms for m in grant.role.menus if m.status == "0" and m.perms}):
            continue
        ids = grant_org_ids(grant)
        condition = user_in_orgs(ids, grant.membership.org.org_type)
        if grant.scope_type == "SELF":
            condition = and_(User.id == user.id, condition)
        conditions.append(condition)
    return query.filter(or_(*conditions) if conditions else False)


def user_view(target, actor, perm):
    data = target.to_dict()
    if actor.is_admin:
        return data
    # Global account associations belong to all work identities; do not expose
    # administrative department, other roles or posts through a PARTY view.
    for key in ("deptId", "deptName", "roleIds", "postIds"):
        data.pop(key, None)
    oid = current_context(actor)
    kind = org_map()[oid].org_type if oid else None
    allowed = set()
    for grant in action_grants(actor, perm):
        allowed.update(grant_org_ids(grant))
    data["orgNames"] = [m.org.dept_name for m in valid_memberships(target)
                        if m.org_id in allowed and m.org.org_type == kind]
    target_query = User.query.filter_by(id=target.id)
    data["canEdit"] = not target.is_admin and bool(scope_user_query(target_query, actor, "system:user:edit").first())
    sensitive_read = actor.id == target.id or bool(scope_user_query(target_query, actor, perm, sensitive=True).first())
    sensitive_write = actor.id == target.id or bool(scope_user_query(target_query, actor, "system:user:edit", sensitive=True).first())
    # An edit form must not write a masked placeholder back to the database.
    data["canEditSensitive"] = data["canEdit"] and sensitive_read and sensitive_write
    if not sensitive_read:
        phone = data.get("phone") or ""
        data["phone"] = phone[:3] + "****" + phone[-4:] if len(phone) >= 7 else ("***" if phone else None)
        data["email"] = "***" if data.get("email") else None
    return data


def audit(actor_id, subject_id, event, detail):
    db.session.add(OrgAuthAudit(actor_id=actor_id, subject_id=subject_id, event_type=event, detail=detail))


def bump(user):
    # Atomic increment; not a read/modify/write susceptible to lost updates.
    db.session.query(User).filter_by(id=user.id).update({User.auth_version: User.auth_version + 1},
                                                       synchronize_session="fetch")
