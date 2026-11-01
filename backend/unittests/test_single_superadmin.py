"""The reserved account is unique and cannot lose its platform authority."""
from backend.unittests.test_dual_organization import env, headers
from extensions import db
from models import User, Role, Menu


def test_admin_role_does_not_create_second_superadmin(env):
    app, c, tokens = env
    with app.app_context():
        other = db.session.get(User, 3)
        other.roles = [db.session.get(Role, 1)]
        db.session.commit()
        assert not other.is_admin
    h = headers(tokens, user=1, org=None)
    assert c.put('/api/system/user/3', headers=h, json={'roleIds': [1]}).status_code == 400
    assert c.post('/api/system/user', headers=h, json={
        'username': 'second-root', 'password': 'test-password', 'roleIds': [1]}).status_code == 400


def test_superadmin_cannot_be_disabled_demoted_or_deleted(env):
    _, c, tokens = env
    h = headers(tokens, user=1, org=None)
    for payload in ({'status': '1'}, {'roleIds': []}, {'roleIds': [2]}):
        assert c.put('/api/system/user/1', headers=h, json=payload).status_code == 400
    assert c.delete('/api/system/user/1', headers=h).status_code == 400
    assert c.put('/api/system/user/1', headers=h, json={'nickname': 'Owner'}).status_code == 200


def test_superadmin_has_all_scopes_without_memberships(env):
    _, c, tokens = env
    for org in (None, 110, 200, 220):
        h = headers(tokens, user=1, org=org)
        response = c.get('/api/system/user', headers=h)
        assert response.status_code == 200
        assert response.get_json()['data']['total'] == 4
        assert c.get('/api/auth/info', headers=h).get_json()['data']['permissions'] == ['*:*:*']
    choices = c.get('/api/auth/contexts', headers=headers(tokens, user=1, org=None)).get_json()['data']['contexts']
    assert {x['orgType'] for x in choices} == {'ADMIN', 'PARTY'}


def test_reconcile_is_idempotent_and_removes_legacy_admins(env):
    from services.superadmin import ensure_single_superadmin
    app, _, _ = env
    with app.app_context():
        root = db.session.get(User, 1)
        other = db.session.get(User, 3)
        role = db.session.get(Role, 1)
        other.roles = [role]
        root.status = '1'
        root.del_flag = '2'
        db.session.commit()
        ensure_single_superadmin()
        ensure_single_superadmin()
        assert root.is_admin
        assert not other.is_admin
        assert role not in other.roles
        assert sum(u.is_admin for u in User.query.all()) == 1


def test_bridge_keeps_business_permissions_without_system_authority(env):
    from services.superadmin import ensure_single_superadmin
    from services.organization_auth import effective_permissions
    app, _, _ = env
    with app.app_context():
        bridge = User(username='openapi_bridge', password_hash='unused', roles=[db.session.get(Role, 1)])
        db.session.add_all([bridge, Menu(menu_name='Camera', perms='camera:list'),
                            Menu(menu_name='AI', perms='ai:asr:list'),
                            Menu(menu_name='Wildcard', perms='*:*:*')])
        db.session.commit()
        ensure_single_superadmin()
        with app.test_request_context():
            permissions = effective_permissions(bridge)
            assert {'camera:list', 'ai:asr:list'} <= permissions
            assert '*:*:*' not in permissions
            assert not any(p.startswith('system:') for p in permissions)
            assert not bridge.is_admin


def test_reconcile_refuses_to_promote_unrelated_reserved_id(env):
    import pytest
    from services.superadmin import ensure_single_superadmin
    app, _, _ = env
    with app.app_context():
        root = db.session.get(User, 1)
        root.roles = []
        db.session.commit()
        with pytest.raises(RuntimeError, match='历史账号映射'):
            ensure_single_superadmin()


def test_superadmin_role_is_protected_and_invalid_context_is_rejected(env):
    _, c, tokens = env
    h = headers(tokens, user=1, org=None)
    assert c.put('/api/system/role/1', headers=h, json={'status': '1'}).status_code == 400
    assert c.delete('/api/system/role/1', headers=h).status_code == 400
    assert c.get('/api/system/user', headers=headers(tokens, user=1, org=99999)).status_code == 403
