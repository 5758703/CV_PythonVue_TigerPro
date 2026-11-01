from backend.unittests.test_dual_organization import env, headers
from extensions import db
from models import Dept, Role, User


def client(env):
    app, c, tokens = env
    from routes.organization_type import organization_type_bp
    app.register_blueprint(organization_type_bp)
    return app, c, headers(tokens, user=1, org=None), tokens


def test_custom_type_crud_and_reference_protection(env):
    app, c, h, _ = client(env)
    url = '/api/system/org-type'
    assert c.post(url, headers=h, json={'code': 'UNION', 'name': '工会组织'}).status_code == 201
    assert c.put(url + '/UNION', headers=h, json={'name': '工会体系', 'orderNum': 1}).status_code == 200
    assert c.get(url, headers=h).get_json()['data'][0]['name'] == '工会体系'
    assert c.post('/api/system/dept', headers=h, json={'deptName': '总工会', 'orgType': 'UNION'}).status_code == 201
    assert c.delete(url + '/UNION', headers=h).status_code == 400
    assert c.put(url + '/UNION', headers=h, json={'supportsPrimary': True}).status_code == 400
    assert c.post(url, headers=h, json={'code': 'TEMP', 'name': '临时组织'}).status_code == 201
    assert c.delete(url + '/TEMP', headers=h).status_code == 200
    assert c.post('/api/system/dept', headers=h, json={'deptName': '无效', 'orgType': 'TEMP'}).status_code == 400


def test_custom_scope_end_to_end_and_disable_revokes_existing_token(env):
    app, c, h, tokens = client(env)
    assert c.post('/api/system/org-type', headers=h, json={'code': 'UNION', 'name': '工会'}).status_code == 201
    oid = c.post('/api/system/dept', headers=h, json={'deptName': '工会', 'orgType': 'UNION'}).get_json()['data']['id']
    with app.app_context():
        rid = db.session.get(Role, 2).id
    mid = c.post('/api/system/organization/users/2/memberships', headers=h,
                 json={'orgId': oid}).get_json()['data']['id']
    assert c.post('/api/system/organization/users/2/grants', headers=h, json={
        'membershipId': mid, 'roleId': rid, 'scopeType': 'DOMAIN_ALL'}).status_code == 201
    own = headers(tokens, org=oid)
    result = c.get('/api/system/user', headers=own)
    assert result.status_code == 200
    assert {x['id'] for x in result.get_json()['data']['rows']} == {2}
    contexts = c.get('/api/auth/contexts', headers=h).get_json()['data']['contexts']
    assert any(x.get('orgTypeName') == '工会' for x in contexts)
    assert c.put('/api/system/org-type/UNION', headers=h, json={'status': '1'}).status_code == 200
    assert c.get('/api/system/user', headers=own).status_code == 403
    assert c.post('/api/system/dept', headers=h, json={'deptName': '无效', 'orgType': 'UNION'}).status_code == 400
    assert c.put('/api/system/org-type/UNION', headers=h, json={'status': '0'}).status_code == 200
    assert c.get('/api/system/user', headers=own).status_code == 200


def test_catalog_admin_only_writes_and_dynamic_role_domains(env):
    _, c, h, tokens = client(env)
    other = headers(tokens)
    assert c.post('/api/system/org-type', headers=other, json={'code': 'X', 'name': 'X'}).status_code == 403
    assert c.post('/api/system/org-type', headers=h, json={'code': 'SYSTEM', 'name': 'X'}).status_code == 400
    assert c.post('/api/system/org-type', headers=h, json={'code': 'TEAM', 'name': '团队', 'supportsPrimary': True}).status_code == 201
    assert c.post('/api/system/role', headers=h, json={'roleName': '团队角色', 'roleKey': 'team', 'businessDomain': 'TEAM'}).status_code == 201
    assert c.delete('/api/system/org-type/TEAM', headers=h).status_code == 400
    assert c.put('/api/system/org-type/TEAM', headers=h, json={'code': 'NEW'}).status_code == 400
    assert c.post('/api/system/role', headers=h, json={'roleName': '错误', 'roleKey': 'bad', 'businessDomain': 'UNKNOWN'}).status_code == 400


def test_configured_primary_type_replaces_fixed_administrative_check(env):
    _, c, h, _ = client(env)
    assert c.post('/api/system/org-type', headers=h, json={
        'code': 'TEAM', 'name': '团队', 'supportsPrimary': True}).status_code == 201
    oid = c.post('/api/system/dept', headers=h, json={'deptName': '研发团队', 'orgType': 'TEAM'}).get_json()['data']['id']
    result = c.post('/api/system/user', headers=h, json={
        'username': 'team-member', 'password': 'test-only-password', 'deptId': oid, 'roleIds': [2]})
    assert result.status_code == 201
    uid = result.get_json()['data']['id']
    result = c.get(f'/api/system/organization/users/{uid}', headers=h).get_json()['data']
    assert result['memberships'][0]['orgType'] == 'TEAM'
    assert result['memberships'][0]['isPrimary'] is True
    assert result['grants'][0]['effective'] is True
    # Moving away from a disabled type must still end the old primary source.
    assert c.put('/api/system/org-type/TEAM', headers=h, json={'status': '1'}).status_code == 200
    assert c.put(f'/api/system/user/{uid}', headers=h, json={'deptId': 110}).status_code == 200
    assert c.put('/api/system/org-type/TEAM', headers=h, json={'status': '0'}).status_code == 200
    memberships = c.get(f'/api/system/organization/users/{uid}', headers=h).get_json()['data']['memberships']
    assert [m['orgId'] for m in memberships if m['isPrimary'] and m['effective']] == [110]


def test_catalog_initialization_preserves_edits_and_deletions():
    from flask import Flask
    from models.organization_type import OrgType
    from services.organization_types import migrate_type_catalog
    app = Flask('catalog-migration')
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        db.session.get(OrgType, 'ADMIN').name = '公司组织'
        db.session.delete(db.session.get(OrgType, 'PARTY'))
        db.session.add(Dept(dept_name='旧自定义组织', org_type='LEGACY'))
        db.session.commit()
        for _ in range(2):
            db.create_all()
            migrate_type_catalog()
        assert db.session.get(OrgType, 'ADMIN').name == '公司组织'
        assert db.session.get(OrgType, 'PARTY') is None
        assert db.session.get(OrgType, 'LEGACY') is not None
        assert OrgType.query.count() == 2
        db.session.remove()
        db.drop_all()
