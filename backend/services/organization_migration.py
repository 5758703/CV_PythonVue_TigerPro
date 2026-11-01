"""Idempotent legacy mapping; never infer memberships of another organization type."""
from datetime import datetime

from extensions import db
from models import Dept, User
from models.organization import OrgMembership, OrgGrant
from services.organization_auth import audit
from services.organization_types import primary_type


def migrate_legacy_organization_auth():
    for user in User.query.filter_by(org_auth_migrated=False, del_flag="0").with_for_update():
        # No stable source: leave the unorganized legacy account for review.
        # Row scopes remain default-deny; legacy AI capability grants are retained.
        primary = db.session.get(Dept, user.dept_id) if user.dept_id else None
        if not primary or not primary_type(primary.org_type) or primary.del_flag != "0":
            continue
        if OrgMembership.query.filter_by(user_id=user.id).first():
            user.org_auth_migrated = True
            continue
        now = datetime.utcnow()
        depts = {d.id: d for d in user.depts if d.org_type == primary.org_type and d.del_flag == "0"}
        depts[primary.id] = primary
        main = None
        for org in depts.values():
            member = OrgMembership(user_id=user.id, org_id=org.id, member_kind="LEGACY_MEMBER",
                                   is_primary=org.id == primary.id, valid_from=now)
            db.session.add(member)
            db.session.flush()
            if member.is_primary:
                main = member
        for role in user.roles:
            if role.role_key == "admin" or role.del_flag != "0" or role.status != "0":
                continue
            db.session.add(OrgGrant(membership_id=main.id, role_id=role.id,
                scope_type={1: "SELF", 2: "ORG", 3: "ORG_SUBTREE", 4: "DOMAIN_ALL"}.get(role.data_scope, "SELF"),
                scope_anchor_org_id=primary.id if role.data_scope != 4 else None,
                source_type="LEGACY", source_ref=str(main.id), valid_from=now, granted_by=user.id))
        user.org_auth_migrated = True
        audit(user.id, user.id, "LEGACY_MIGRATED", {
            "contextOrgId": primary.id, "roleIds": [r.id for r in user.roles],
            "reviewRequired": True, "directMenuIdsNotMigrated": [m.id for m in user.menus],
            "note": "旧角色仅绑定主组织任职；全部范围限制在同类型组织，直接菜单授权需重新审核"})
    db.session.commit()
