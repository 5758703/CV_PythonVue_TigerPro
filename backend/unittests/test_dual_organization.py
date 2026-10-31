"""Real database/API regression coverage for independent organization grants."""
from datetime import datetime, timedelta

import pytest
from flask import Flask
from flask_jwt_extended import create_access_token

from extensions import db, jwt
from models import Dept, Menu, Role, User


@pytest.fixture()
def env(tmp_path):
    from models.organization import OrgMembership, OrgGrant
    from routes.organization import organization_bp
    from routes.auth import auth_bp
    from routes.user import user_bp
    from routes.dept import dept_bp
    from routes.role import role_bp
    from routes.menu import menu_bp
    from routes.job import job_bp
    from routes.open_app_admin import open_app_bp
    app = Flask("dual-organization")
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, JWT_SECRET_KEY="test-secret-organization-32bytes")
    db.init_app(app)
    jwt.init_app(app)
    for bp in (auth_bp, user_bp, dept_bp, role_bp, menu_bp, job_bp, open_app_bp, organization_bp):
        app.register_blueprint(bp)
    with app.app_context():
        db.create_all()
        orgs = [Dept(id=i, dept_name=n, org_type=t, parent_id=p, ancestors="0") for i, n, t, p in (
            (110, "设备部", "ADMIN", 0), (120, "生产部", "ADMIN", 0),
            (200, "党委", "PARTY", 0), (210, "一支部", "PARTY", 200),
            (220, "二支部", "PARTY", 200))]
        ps = ["system:user:list", "system:user:query", "system:user:edit", "system:user:remove",
              "system:user:add", "system:dept:list", "system:dept:query", "system:dept:edit",
              "system:dept:add", "system:dept:remove", "system:role:edit", "system:menu:edit",
              "system:job:edit", "system:openapp:list", "system:openapp:add"]
        menus = {p: Menu(menu_name=p, menu_type="F", perms=p) for p in ps}
        admin = Role(id=1, role_name="Platform", role_key="admin", data_scope=4)
        read = Role(id=2, role_name="Read", role_key="read", business_domain="SYSTEM", data_scope=4,
                    menus=[menus[p] for p in ("system:user:list", "system:user:query")])
        edit = Role(id=3, role_name="Edit", role_key="edit", business_domain="SYSTEM", data_scope=2,
                    menus=[m for p, m in menus.items() if p not in ("system:user:list", "system:user:query")])
        actor = User(id=2, username="actor", dept_id=110, roles=[read, edit])
        root = User(id=1, username="root", roles=[admin])
        u1 = User(id=3, username="branch-one", dept_id=120, phone="13812345678", email="private@example.com")
        u2 = User(id=4, username="branch-two", dept_id=110)
        for u in (actor, root, u1, u2):
            u.password_hash = "not-used-by-these-JWT-authorization-tests"
        db.session.add_all(orgs + [root, actor, u1, u2])
        db.session.flush()
        memberships = [OrgMembership(id=i, user_id=u, org_id=o, member_kind="MEMBER")
                       for i, u, o in ((1, 2, 110), (2, 2, 200), (3, 3, 210), (4, 4, 220))]
        db.session.add_all(memberships)
        db.session.flush()
        db.session.add_all([
            OrgGrant(id=1, membership_id=1, role_id=3, scope_type="ORG", scope_anchor_org_id=110,
                     source_type="MEMBERSHIP", source_ref="1", granted_by=1),
            OrgGrant(id=2, membership_id=2, role_id=2, scope_type="ORG_SUBTREE", scope_anchor_org_id=200,
                     source_type="MEMBERSHIP", source_ref="2", granted_by=1),
            OrgGrant(id=3, membership_id=2, role_id=3, scope_type="ORG", scope_anchor_org_id=210,
                     source_type="MEMBERSHIP", source_ref="2", granted_by=1),
        ])
        db.session.commit()
        tokens = {i: create_access_token(identity=str(i)) for i in (1, 2, 3)}
    yield app, app.test_client(), tokens
    with app.app_context():
        db.session.remove()
        db.drop_all()


def headers(tokens, user=2, org=200):
    h = {"Authorization": f"Bearer {tokens[user]}"}
    if org is not None:
        h["X-Org-Id"] = str(org)
    return h


def test_wide_read_does_not_widen_update_or_delete(env):
    _, c, t = env
    view = c.get("/api/system/user/4", headers=headers(t))
    assert view.status_code == 200
    assert view.get_json()["data"]["canEdit"] is False
    assert c.get("/api/system/user/3", headers=headers(t)).get_json()["data"]["canEdit"] is True
    assert c.put("/api/system/user/4", headers=headers(t), json={"nickname": "HACK"}).status_code == 404
    assert c.delete("/api/system/user/4", headers=headers(t)).status_code == 404
    assert c.put("/api/system/user/3", headers=headers(t), json={"nickname": "OK"}).status_code == 200


def test_membership_not_primary_admin_department_controls_party_scope(env):
    _, c, t = env
    r = c.get("/api/system/user", headers=headers(t)).get_json()["data"]
    assert r["total"] == 3
    assert {u["id"] for u in r["rows"]} == {2, 3, 4}
    # ADMIN has no read grant, even though PARTY has one.
    assert c.get("/api/system/user", headers=headers(t, org=110)).status_code == 403
    assert c.get("/api/system/user", headers=headers(t, org=220)).status_code == 403


@pytest.mark.parametrize("change", ["expired", "ended", "role-disabled", "org-disabled", "ancestor-disabled"])
def test_old_token_cannot_reuse_invalid_grant_source(env, change):
    from models.organization import OrgMembership
    app, c, t = env
    with app.app_context():
        if change == "expired":
            db.session.get(OrgMembership, 2).valid_to = datetime.utcnow() - timedelta(seconds=1)
        elif change == "ended":
            db.session.get(OrgMembership, 2).status = "1"
        elif change == "role-disabled":
            db.session.get(Role, 2).status = "1"
        else:
            db.session.get(Dept, 200).status = "1"
        db.session.commit()
    assert c.get("/api/system/user", headers=headers(t)).status_code == 403


def test_no_context_role_fallback_after_membership_ended(env):
    from models.organization import OrgMembership
    app, c, t = env
    with app.app_context():
        for m in OrgMembership.query.filter_by(user_id=2):
            m.status = "1"
        db.session.commit()
    assert c.get("/api/system/user", headers=headers(t, org=None)).status_code == 403


def test_non_admin_cannot_change_global_account_or_authorization_templates(env):
    _, c, t = env
    h = headers(t)
    for data in ({"roleIds": [1]}, {"password": "hacked-password"}, {"status": "1"}, {"deptId": 110}):
        assert c.put("/api/system/user/3", headers=h, json=data).status_code == 403
    assert c.put("/api/system/role/2", headers=h, json={"menuIds": []}).status_code == 403
    assert c.put("/api/system/menu/1", headers=h, json={"perms": "*:*:*"}).status_code == 403
    assert c.post("/api/system/organization/users/3/grants", headers=h, json={}).status_code == 403
    assert c.put("/api/system/job/9999", headers=h, json={"postName": "HACK"}).status_code == 403
    assert c.get("/api/system/open-app", headers=h).status_code == 403
    assert c.post("/api/system/open-app", headers=h, json={}).status_code == 403


def test_other_identity_fields_are_not_disclosed(env):
    _, c, t = env
    data = c.get("/api/system/user/3", headers=headers(t)).get_json()["data"]
    assert data.get("deptId") is None
    assert data.get("roleIds", []) == []
    assert data["phone"] != "13812345678"
    assert data.get("email") != "private@example.com"


def test_org_trees_reject_cross_type_parent_and_cycles_and_refresh_descendants(env):
    app, c, t = env
    h = headers(t, user=1, org=None)
    assert c.put("/api/system/dept/210", headers=h, json={"parentId": 110}).status_code == 400
    assert c.put("/api/system/dept/200", headers=h, json={"parentId": 210}).status_code == 400
    assert c.post("/api/system/dept", headers=h,
                  json={"deptName": "wrong", "parentId": 110, "orgType": "PARTY"}).status_code == 400
    r = c.post("/api/system/dept", headers=h, json={"deptName": "sub", "parentId": 210, "orgType": "PARTY"})
    child = r.get_json()["data"]["id"]
    assert c.put("/api/system/dept/210", headers=h, json={"parentId": 220}).status_code == 200
    with app.app_context():
        assert db.session.get(Dept, child).ancestors == "0,200,220,210"


def test_end_one_membership_keeps_other_identity_and_audit(env):
    app, c, t = env
    h = headers(t, user=1, org=None)
    r = c.delete("/api/system/organization/memberships/1", headers=h)
    assert r.status_code == 200
    assert c.get("/api/system/user", headers=headers(t)).status_code == 200
    assert c.get("/api/system/user", headers=headers(t, org=110)).status_code == 403
    r = c.get("/api/system/organization/users/2", headers=h).get_json()["data"]
    assert r["audit"]
    assert any(g["membershipId"] == 2 and g["effective"] for g in r["grants"])


def test_grant_validation_and_revoke_one_source_keeps_another(env):
    _, c, t = env
    h = headers(t, user=1, org=None)
    base = {"membershipId": 2, "roleId": 2, "scopeType": "ORG", "scopeAnchorOrgId": 210,
            "sourceType": "MANUAL", "approvalRef": "审批-001"}
    for extra in ({"scopeAnchorOrgId": 110}, {"scopeType": "CUSTOM_ORG", "scopeOrgIds": []},
                  {"roleId": 1}, {"scopeType": "SELF", "scopeAnchorOrgId": 210},
                  {"validTo": "2020-01-01T00:00:00"}):
        r = c.post("/api/system/organization/users/2/grants", headers=h, json={**base, **extra})
        assert r.status_code == 400, r.get_json()
    r = c.post("/api/system/organization/users/2/grants", headers=h, json=base)
    assert r.status_code == 201
    assert c.delete("/api/system/organization/grants/2", headers=h).status_code == 200
    assert c.get("/api/system/user/3", headers=headers(t)).status_code == 200
    assert c.get("/api/system/user/4", headers=headers(t)).status_code == 404


def test_sensitive_fields_use_only_grants_covering_this_record(env):
    from models.organization import OrgGrant
    app, c, t = env
    with app.app_context():
        sensitive = Menu(menu_name="sensitive", menu_type="F", perms="system:user:sensitive")
        role = Role(role_name="Sensitive", role_key="sensitive", business_domain="SYSTEM", menus=[
            sensitive, Menu.query.filter_by(perms="system:user:query").first()])
        db.session.add(role)
        db.session.flush()
        db.session.add(OrgGrant(membership_id=2, role_id=role.id, scope_type="ORG", scope_anchor_org_id=210,
                               source_type="MEMBERSHIP", source_ref="2", granted_by=1))
        db.session.get(User, 4).phone = "13987654321"
        db.session.commit()
    one = c.get("/api/system/user/3", headers=headers(t)).get_json()["data"]
    two = c.get("/api/system/user/4", headers=headers(t)).get_json()["data"]
    assert one["phone"] == "13812345678"
    assert two["phone"] != "13987654321"
    # Sensitive read grant must not combine with another role's edit permission.
    assert c.put("/api/system/user/3", headers=headers(t), json={"phone": "13911112222"}).status_code == 403


def test_self_does_not_become_organization_wide_from_another_role(env):
    from models.organization import OrgGrant
    app, c, t = env
    with app.app_context():
        g = db.session.get(OrgGrant, 3)
        g.scope_type, g.scope_anchor_org_id = "SELF", 200
        db.session.commit()
    assert c.put("/api/system/user/3", headers=headers(t), json={"nickname": "bad"}).status_code == 404
    assert c.put("/api/system/user/2", headers=headers(t), json={"nickname": "self"}).status_code == 200


def test_stopped_child_hidden_from_list_count_and_detail(env):
    app, c, t = env
    with app.app_context():
        db.session.get(Dept, 210).status = "1"
        db.session.commit()
    data = c.get("/api/system/user", headers=headers(t)).get_json()["data"]
    assert data["total"] == 2
    assert {u["id"] for u in data["rows"]} == {2, 4}
    assert c.get("/api/system/user/3", headers=headers(t)).status_code == 404


def test_context_discovery_recovers_from_a_stale_header_without_granting_permissions(env):
    _, c, t = env
    h = headers(t, org=99999)
    assert c.get("/api/auth/info", headers=h).status_code == 403
    r = c.get("/api/auth/contexts", headers=h)
    assert r.status_code == 200
    assert {x["orgId"] for x in r.get_json()["data"]["contexts"]} == {110, 200}


def test_invalid_grant_period_and_disabled_menu_are_rechecked(env):
    from models.organization import OrgGrant
    app, c, t = env
    with app.app_context():
        db.session.get(OrgGrant, 2).valid_to = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
    assert c.get("/api/system/user", headers=headers(t)).status_code == 403
    with app.app_context():
        db.session.get(OrgGrant, 2).valid_to = None
        Menu.query.filter_by(perms="system:user:list").first().status = "1"
        db.session.commit()
    assert c.get("/api/system/user", headers=headers(t)).status_code == 403


def test_membership_creation_does_not_grant_role_and_primary_must_be_admin(env):
    _, c, t = env
    h = headers(t, user=1, org=None)
    assert c.post("/api/system/organization/users/3/memberships", headers=h, json={
        "orgId": 220, "memberKind": "委员", "isPrimary": True}).status_code == 400
    assert c.post("/api/system/organization/users/3/memberships", headers=h, json={
        "orgId": 220, "memberKind": "委员"}).status_code == 201
    # Existing JWT can select the new membership but has no functional grant.
    assert c.get("/api/system/user", headers=headers(t, user=3, org=220)).status_code == 403


def test_legacy_unorganized_ai_capabilities_retained_without_system_access(env):
    app, c, t = env
    with app.app_context():
        u = db.session.get(User, 1)
        u.roles = [Role(role_name="demo", role_key="demo", menus=[
            Menu(menu_name="AI", perms="ai:model:list", menu_type="C"),
            Menu(menu_name="users", perms="system:user:list", menu_type="C")])]
        db.session.commit()
    data = c.get("/api/auth/info", headers=headers(t, user=1, org=None)).get_json()["data"]
    assert "ai:model:list" in data["permissions"]
    assert "system:user:list" not in data["permissions"]
