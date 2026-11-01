from flask import g, abort
from models.organization_type import OrgType


SHARED_DOMAINS = {"SYSTEM", "COMMON"}


def catalog():
    if "organization_type_catalog" not in g:
        g.organization_type_catalog = {t.code: t for t in OrgType.query.order_by(OrgType.order_num, OrgType.code)}
    return g.organization_type_catalog


def type_enabled(code):
    item = catalog().get(code) if isinstance(code, str) else None
    return bool(item and not item.archived and item.status == "0")


def primary_type(code):
    item = catalog().get(code)
    return bool(item and not item.archived and item.status == "0" and item.supports_primary)


def default_type():
    return next((t.code for t in catalog().values() if primary_type(t.code)), None)


def type_name(code):
    item = catalog().get(code)
    return item.name if item else code


def lock_enabled_type(code):
    """Serialize reference creation with type deletion/disable in the same transaction."""
    if not isinstance(code, str):
        abort(400, description="请选择有效组织类型")
    row = OrgType.query.filter_by(code=code).populate_existing().with_for_update().first()
    if not row or row.archived or row.status != "0":
        abort(400, description="组织类型不存在或已停用")
    return row


def migrate_type_catalog():
    """Preserve existing custom codes from older installations, including history."""
    from extensions import db
    from models import Dept, Role
    codes = {x[0] for x in db.session.query(Dept.org_type).distinct()}
    codes |= {x[0] for x in db.session.query(Role.business_domain).distinct()} - SHARED_DOMAINS
    for code in codes:
        if code and not db.session.get(OrgType, code):
            db.session.add(OrgType(code=code, name=code))
    db.session.commit()
