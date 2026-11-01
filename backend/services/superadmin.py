"""Reconcile the reserved owner without creating another privileged identity."""
from extensions import db
from models import User, Role, Menu
from services.organization_auth import audit, bump


def bridge_business_menus():
    return [m for m in Menu.query.filter(Menu.status == "0").all()
            if m.perms and not m.perms.startswith(("system:", "auth:")) and "*" not in m.perms]


def ensure_single_superadmin():
    owner = db.session.get(User, 1)
    if owner is None:
        raise RuntimeError("内置超级管理员 ID=1 缺失，请从备份恢复账号后启动；不会自动提升其他账号")
    role = Role.query.filter_by(role_key="admin").first()
    if role is None:
        raise RuntimeError("内置 admin 角色缺失，请恢复角色后启动")
    # Refuse to silently elevate a different historical account in a nonstandard DB.
    if role not in owner.roles and owner.username != "admin":
        raise RuntimeError("ID=1 不是原超级管理员，请人工核对历史账号映射后启动")
    changed = owner.status != "0" or owner.del_flag != "0" or role not in owner.roles
    owner.status = owner.del_flag = "0"
    role.status = role.del_flag = "0"
    role.business_domain = "SYSTEM"
    role.data_scope = 4
    if role not in owner.roles:
        owner.roles.append(role)
    if changed:
        bump(owner)
        audit(1, 1, "SUPERADMIN_RESTORED", {"userId": 1})
    for user in User.query.filter(User.id != 1).all():
        if role in user.roles:
            user.roles.remove(role)
            bump(user)
            audit(1, user.id, "EXTRA_SUPERADMIN_REMOVED", {"roleId": role.id})
    # The noninteractive bridge has explicit AI capabilities, never system authority.
    bridge = User.query.filter_by(username="openapi_bridge").first()
    if bridge:
        bridge.menus = bridge_business_menus()
    db.session.commit()
