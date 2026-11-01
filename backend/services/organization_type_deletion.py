"""Read-only retirement plan. Historical rows are never rewritten to another type."""
from models import Dept, Role, User
from models.organization import OrgMembership, OrgGrant


def deletion_plan(row, lock=False):
    def current(query):
        # Locking reads also avoid a stale repeatable-read snapshot during deletion.
        return query.populate_existing().with_for_update() if lock else query
    orgs = current(Dept.query.filter_by(org_type=row.code).order_by(Dept.id)).all()
    roles = current(Role.query.filter_by(business_domain=row.code).order_by(Role.id)).all()
    org_ids, role_ids = {o.id for o in orgs}, {r.id for r in roles}
    members = current(OrgMembership.query.filter(OrgMembership.org_id.in_(org_ids)).order_by(OrgMembership.id)).all()
    member_ids = {m.id for m in members}
    grants = [g for g in current(OrgGrant.query.order_by(OrgGrant.id)) if
              g.membership_id in member_ids or g.role_id in role_ids or
              g.scope_anchor_org_id in org_ids or org_ids.intersection(g.scope_org_ids or [])]
    accounts = []
    for user in current(User.query.filter_by(del_flag="0").order_by(User.id)):
        reasons = []
        if user.dept_id in org_ids:
            reasons.append("主组织")
        if any(d.id in org_ids for d in user.depts):
            reasons.append("兼属组织")
        if any(r.id in role_ids for r in user.roles):
            reasons.append("账号直接关联角色")
        if reasons:
            accounts.append(dict(id=user.id, userId=user.id, name=user.username, reason="、".join(reasons)))

    def group(key, title, items, route, instruction):
        return dict(key=key, title=title, count=len(items), items=items[:200],
                    truncated=len(items) > 200, route=route, instruction=instruction)

    groups = [
        group("accounts", "账号关联", accounts, "/system/user",
              "先核对人员去向：在用户管理修改主组织、移除旧兼属组织和此类型的直接角色。需要继续工作的账号，应先在目标组织登记新任职并单独授权，确认可用后再结束旧任职；不要删除账号来规避关联。"),
        group("memberships", "未结束任职（含未来或已过期）", [dict(
            id=m.id, userId=m.user_id, name=m.org.dept_name, reason=m.member_kind) for m in members if m.status == "0"],
              "/system/user", "通过下方“处理任职”进入任职与授权，结束旧任职；系统仅撤销其关联授权，保留原任职记录。过期、停用组织或账号不等于已结束任职。"),
        group("grants", "未撤销授权（含角色及范围引用）", [dict(
            id=g.id, userId=g.membership.user_id, name=g.role.role_name,
            reason=f"任职 {g.membership_id} / {g.scope_type}") for g in grants if g.status == "0"],
              "/system/user", "在任职与授权中撤销剩余授权；检查范围锚点、自定义组织集合以及此类型角色的引用。不要改写旧授权的来源或组织类型。"),
        group("roles", "未删除角色（含停用）", [dict(id=r.id, name=r.role_name,
            reason=r.role_key) for r in roles if r.del_flag == "0"], "/system/role",
              "先移除账号直接角色和撤销关联授权，再在角色管理删除旧角色（逻辑删除）。需要同类能力时新建目标业务域角色，不要修改旧角色业务域来转移历史。"),
        group("organizations", "未删除组织（含停用）", [dict(id=o.id, name=o.dept_name,
            reason=f"上级组织 ID：{o.parent_id}") for o in orgs if o.del_flag == "0"], "/system/dept",
              "清理账号关联并结束任职后，在组织管理从最末级子组织开始逐级删除（逻辑删除）。停用组织不等于删除，不能直接更改其类型来迁移历史。"),
    ]
    return dict(type=row.to_dict(), canDelete=not row.archived and not any(x["count"] for x in groups),
                archived=row.archived, blockers=groups,
                retained=dict(organizations=len(orgs), roles=len(roles), memberships=len(members), grants=len(grants)),
                preservation="删除采用归档方式：保留类型编码与名称，以及原组织、角色、任职、授权和审计记录。归档后不能重新启用或复用编码，不会自动复制权限到其他组织。")
