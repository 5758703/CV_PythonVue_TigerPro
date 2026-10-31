from flask import Flask
from sqlalchemy import text, inspect
from sqlalchemy.schema import CreateTable

from extensions import db
from models import Dept, Menu, Role, User
from models.organization import OrgMembership, OrgGrant
from schema_migrations import migrate_schema
from services.organization_migration import migrate_legacy_organization_auth


def test_old_schema_upgrade_and_grants_are_idempotent_and_admin_only(tmp_path):
    app = Flask("old-organization-schema")
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'old.db'}", SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        # Genuine pre-upgrade tables lacking all four newly added columns.
        for model, excluded in ((Dept, {"org_type"}), (Role, {"business_domain"}),
                                (User, {"auth_version", "org_auth_migrated"})):
            ddl = str(CreateTable(model.__table__).compile(db.engine))
            ddl = "\n".join(line for line in ddl.splitlines() if not any(
                line.strip().startswith(name + " ") for name in excluded))
            with db.engine.begin() as con:
                con.execute(text(ddl))
        db.create_all()
        migrate_schema(db)
        migrate_schema(db)
        assert {"auth_version", "org_auth_migrated"} <= {c["name"] for c in inspect(db.engine).get_columns("sys_user")}
        a = Dept(id=110, dept_name="Legacy administrative")
        p = Dept(id=210, dept_name="Party", org_type="PARTY")
        r = Role(role_name="Reader", role_key="reader", data_scope=4,
                 menus=[Menu(menu_name="read", menu_type="F", perms="system:user:list")])
        u = User(username="legacy", dept_id=110, password_hash="unused", roles=[r], depts=[a, p])
        db.session.add_all([a, p, r, u])
        db.session.commit()
        migrate_legacy_organization_auth()
        migrate_legacy_organization_auth()
        members = OrgMembership.query.filter_by(user_id=u.id).all()
        grants = OrgGrant.query.all()
        assert len(members) == 1 and members[0].org_id == 110
        assert len(grants) == 1 and grants[0].membership_id == members[0].id
        assert grants[0].source_type == "LEGACY"
        assert grants[0].scope_type == "DOMAIN_ALL"
        assert db.session.get(User, u.id).org_auth_migrated is True
        # Revocation must survive another startup; never re-create from user_role.
        members[0].status = "1"
        db.session.commit()
        migrate_legacy_organization_auth()
        assert OrgMembership.query.count() == 1 and OrgGrant.query.count() == 1
        db.session.remove()
        db.drop_all()
