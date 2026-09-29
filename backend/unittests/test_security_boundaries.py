"""Regression tests for account, data-scope, and model-file boundaries."""

from pathlib import Path

import pytest
from flask import Flask
from flask_jwt_extended import create_access_token

from extensions import db, jwt
from models import AiModel, Dept, Menu, Role, User
from routes.ai_model import ai_model_bp
from routes.auth import auth_bp
from routes.user import user_bp


@pytest.fixture(scope="module")
def secured_app(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("security-boundaries")
    app = Flask("security-boundaries")
    uploads = tmp_path / "uploads"
    (uploads / "models").mkdir(parents=True)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'security.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="test-only-secret",
        UPLOAD_FOLDER=str(uploads),
        MODEL_FOLDER=str(uploads / "models"),
    )
    db.init_app(app)
    jwt.init_app(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(ai_model_bp)
    with app.app_context():
        db.create_all()
        own = Dept(id=101, dept_name="Own", ancestors="0")
        other = Dept(id=102, dept_name="Other", ancestors="0")
        admin_role = Role(role_name="Admin", role_key="admin", data_scope=4)
        editor_role = Role(role_name="Editor", role_key="editor", data_scope=2)
        editor_role.menus = [
            Menu(menu_name=perm, menu_type="F", perms=perm)
            for perm in ("system:user:query", "system:user:edit", "system:user:add",
                         "system:user:remove")
        ]
        admin = User(username="admin", dept=own, roles=[admin_role])
        editor = User(username="editor", dept=own, roles=[editor_role])
        outsider = User(username="outsider", dept=other, roles=[editor_role],
                        email="private@example.com")
        for user in (admin, editor, outsider):
            user.set_password("test-password")
        db.session.add_all([own, other, admin_role, editor_role, admin, editor, outsider])
        db.session.commit()
        ids = {user.username: user.id for user in (admin, editor, outsider)}
        tokens = {name: create_access_token(identity=str(uid)) for name, uid in ids.items()}
    yield app, app.test_client(), ids, tokens, tmp_path
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("field,value", [("status", "1"), ("del_flag", "2")])
def test_existing_token_cannot_access_disabled_or_deleted_account(secured_app, field, value):
    app, client, ids, tokens, _ = secured_app
    with app.app_context():
        setattr(db.session.get(User, ids["editor"]), field, value)
        db.session.commit()
    assert client.get("/api/auth/info", headers=_auth(tokens["editor"])).status_code == 401
    with app.app_context():
        setattr(db.session.get(User, ids["editor"]), field, "0")
        db.session.commit()


def test_detail_and_mutations_obey_user_data_scope(secured_app):
    _app, client, ids, tokens, _ = secured_app
    headers = _auth(tokens["editor"])
    url = f"/api/system/user/{ids['outsider']}"
    assert client.get(url, headers=headers).status_code == 404
    assert client.put(url, json={"nickname": "changed"}, headers=headers).status_code == 404
    assert client.delete(url, headers=headers).status_code == 404


def test_delegated_user_editor_cannot_grant_admin_role_or_move_user_out_of_scope(secured_app):
    app, client, ids, tokens, _ = secured_app
    headers = _auth(tokens["editor"])
    with app.app_context():
        admin_role_id = Role.query.filter_by(role_key="admin").first().id
    url = f"/api/system/user/{ids['editor']}"
    assert client.put(url, json={"roleIds": [admin_role_id]}, headers=headers).status_code == 403
    assert client.put(url, json={"deptId": 102}, headers=headers).status_code == 403
    assert client.put(url, json={"deptIds": [102]}, headers=headers).status_code == 403
    assert client.post("/api/system/user", json={"username": "new", "deptId": 102,
                                                  "password": "test-password"},
                       headers=headers).status_code == 403


def test_new_user_requires_explicit_password(secured_app):
    _app, client, _ids, tokens, _ = secured_app
    response = client.post("/api/system/user", json={"username": "no-password", "deptId": 101},
                           headers=_auth(tokens["admin"]))
    assert response.status_code == 400


def test_password_update_rejects_short_value(secured_app):
    _app, client, ids, tokens, _ = secured_app
    response = client.put(f"/api/system/user/{ids['editor']}", json={"password": "123"},
                          headers=_auth(tokens["admin"]))
    assert response.status_code == 400


@pytest.mark.parametrize("path", ["../secret.pt", "models/../../secret.pt", "C:/secret.pt"])
def test_model_create_rejects_file_path_outside_managed_uploads(secured_app, path):
    _app, client, _ids, tokens, _ = secured_app
    response = client.post("/api/ai/model", json={"modelName": "bad", "filePath": path},
                           headers=_auth(tokens["admin"]))
    assert response.status_code == 400


def test_legacy_malicious_model_path_cannot_be_downloaded_or_deleted(secured_app):
    app, client, _ids, tokens, root = secured_app
    secret = root / "secret.pt"
    secret.write_bytes(b"private-data")
    with app.app_context():
        model = AiModel(model_name="legacy", file_path="../secret.pt")
        db.session.add(model)
        db.session.commit()
        model_id = model.id
    headers = _auth(tokens["admin"])
    assert client.get(f"/api/ai/model/{model_id}/download", headers=headers).status_code != 200
    assert client.delete(f"/api/ai/model/{model_id}", headers=headers).status_code == 200
    assert secret.read_bytes() == b"private-data"


def test_model_path_inside_managed_folder_remains_usable(secured_app):
    _app, client, _ids, tokens, root = secured_app
    weight = Path(root / "uploads" / "models" / "good.pt")
    weight.write_bytes(b"model-weight")
    headers = _auth(tokens["admin"])
    created = client.post("/api/ai/model", json={"modelName": "good", "filePath": "models/good.pt"},
                          headers=headers)
    assert created.status_code == 201
    model_id = created.get_json()["data"]["id"]
    downloaded = client.get(f"/api/ai/model/{model_id}/download", headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.data == b"model-weight"
