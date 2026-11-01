from backend.unittests.test_dual_organization import env, headers
from backend.unittests.test_organization_types import client
from extensions import db
from models import Dept, Role, User
from models.organization import OrgMembership, OrgGrant, OrgAuthAudit
from models.organization_type import OrgType


def test_guided_retirement_preserves_history_and_other_permissions(env):
    app, c, h, tokens = client(env)
    assert c.post('/api/system/org-type', headers=h, json={'code': 'OLD', 'name': '旧体系', 'supportsPrimary': True}).status_code == 201
    oid = c.post('/api/system/dept', headers=h, json={'orgType': 'OLD', 'deptName': '旧组织'}).get_json()['data']['id']
    rid = c.post('/api/system/role', headers=h, json={'roleName': '旧角色', 'roleKey': 'old', 'businessDomain': 'OLD'}).get_json()['data']['id']
    assert c.put('/api/system/user/3', headers=h, json={'deptId': oid, 'deptIds': [oid], 'roleIds': [rid]}).status_code == 200
    url = '/api/system/org-type/OLD'
    plan = c.get(url + '/deletion-plan', headers=h).get_json()['data']
    assert {b['key'] for b in plan['blockers'] if b['count']} == {'accounts', 'memberships', 'grants', 'roles', 'organizations'}
    blocked = c.delete(url, headers=h)
    assert blocked.status_code == 400
    assert blocked.get_json()['data']['blockers']
    # Current references are handled through their normal audited lifecycle.
    assert c.put('/api/system/user/3', headers=h, json={'deptId': None, 'deptIds': [], 'roleIds': []}).status_code == 200
    assert c.delete(f'/api/system/role/{rid}', headers=h).status_code == 200
    assert c.delete(f'/api/system/dept/{oid}', headers=h).status_code == 200
    assert c.get(url + '/deletion-plan', headers=h).get_json()['data']['canDelete'] is True
    with app.app_context():
        before = ([m.to_dict() for m in OrgMembership.query.order_by(OrgMembership.id)],
                  [g.to_dict() for g in OrgGrant.query.order_by(OrgGrant.id)])
    assert c.delete(url, headers=h).status_code == 200
    with app.app_context():
        assert db.session.get(OrgType, 'OLD').archived
        assert db.session.get(OrgType, 'OLD').name == '旧体系'
        after = ([m.to_dict() for m in OrgMembership.query.order_by(OrgMembership.id)],
                 [g.to_dict() for g in OrgGrant.query.order_by(OrgGrant.id)])
        assert before == after
        assert OrgAuthAudit.query.filter_by(event_type='ORG_TYPE_ARCHIVED').count() == 1
    # Unrelated organization remains accessible with the old token.
    assert c.get('/api/system/user', headers=headers(tokens, org=200)).status_code == 200
    assert all(t['code'] != 'OLD' for t in c.get('/api/system/org-type', headers=h).get_json()['data'])
    archived = c.get('/api/system/org-type?includeArchived=true', headers=h).get_json()['data']
    assert any(t['code'] == 'OLD' and t['archived'] for t in archived)
    assert c.put(url, headers=h, json={'status': '0'}).status_code == 400
    assert c.post('/api/system/org-type', headers=h, json={'code': 'OLD', 'name': '复用'}).status_code == 409
    assert c.delete(url, headers=h).status_code == 200
    from services.organization_types import migrate_type_catalog
    with app.app_context():
        migrate_type_catalog()
        assert db.session.get(OrgType, 'OLD').archived


def test_preview_is_read_only_and_delete_rechecks_new_references(env):
    app, c, h, tokens = client(env)
    assert c.get('/api/system/org-type/PARTY/deletion-plan', headers=headers(tokens)).status_code == 403
    c.post('/api/system/org-type', headers=h, json={'code': 'TEMP', 'name': '临时'})
    url = '/api/system/org-type/TEMP'
    assert c.get(url + '/deletion-plan', headers=h).get_json()['data']['canDelete']
    c.post('/api/system/dept', headers=h, json={'orgType': 'TEMP', 'deptName': '新增引用'})
    assert c.delete(url, headers=h).status_code == 400
    with app.app_context():
        assert not db.session.get(OrgType, 'TEMP').archived
        assert not OrgAuthAudit.query.filter_by(event_type='ORG_TYPE_ARCHIVED').count()


def test_cleanup_handles_deleted_accounts_and_owner_legacy_memberships(env):
    app, c, h, _ = client(env)
    with app.app_context():
        db.session.get(User, 3).del_flag = '2'
        m = OrgMembership(user_id=1, org_id=110, member_kind='LEGACY', is_primary=True)
        db.session.add(m)
        db.session.commit()
        mid = m.id
    result = c.get('/api/system/organization/users/3', headers=h).get_json()['data']
    assert result['canAssign'] is False
    assert c.delete('/api/system/organization/memberships/3', headers=h).status_code == 200
    assert c.delete(f'/api/system/organization/memberships/{mid}', headers=h).status_code == 200
    assert c.get('/api/auth/info', headers=h).get_json()['data']['permissions'] == ['*:*:*']


def test_scope_only_references_are_reported_even_if_already_expired(env):
    app, c, h, _ = client(env)
    with app.app_context():
        # Simulate a legacy cross-type scope that no longer passes current validation.
        g = db.session.get(OrgGrant, 2)
        g.scope_type, g.scope_org_ids = 'CUSTOM_ORG', [110]
        db.session.commit()
    groups = c.get('/api/system/org-type/ADMIN/deletion-plan', headers=h).get_json()['data']['blockers']
    assert 2 in [item['id'] for group in groups if group['key'] == 'grants' for item in group['items']]


def test_archived_column_upgrade_is_idempotent():
    from flask import Flask
    from sqlalchemy import text
    from schema_migrations import migrate_schema
    app = Flask('old-type-catalog')
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        with db.engine.begin() as con:
            con.execute(text('CREATE TABLE sys_org_type (code VARCHAR(16) PRIMARY KEY, name VARCHAR(64), order_num INTEGER, status VARCHAR(1), supports_primary BOOLEAN)'))
            con.execute(text("INSERT INTO sys_org_type VALUES ('OLD', 'Original name', 1, '0', 0)"))
        migrate_schema(db)
        migrate_schema(db)
        assert db.session.get(OrgType, 'OLD').name == 'Original name'
        assert db.session.get(OrgType, 'OLD').archived is False
        db.session.remove()
        db.drop_all()
