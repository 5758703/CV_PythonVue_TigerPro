import re
from flask import Blueprint, request, jsonify, abort, g
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import Dept, Role
from models.organization_type import OrgType
from security import login_required, platform_admin_required, current_user
from services.organization_auth import audit
from services.organization_types import SHARED_DOMAINS
from services.organization_type_deletion import deletion_plan

organization_type_bp = Blueprint("organization_type", __name__, url_prefix="/api/system/org-type")


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description="请求内容必须是 JSON 对象")
    return data


def references(code):
    # Include soft-deleted records: their history must retain its type identity.
    return Dept.query.filter_by(org_type=code).count() + Role.query.filter_by(business_domain=code).count()


def apply_values(row, data):
    name = data.get("name", row.name)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 64:
        abort(400, description="类型名称必填且不超过64字")
    status = data.get("status", row.status or "0")
    order = data.get("orderNum", row.order_num or 0)
    primary = data.get("supportsPrimary", bool(row.supports_primary))
    if status not in ("0", "1") or type(order) is not int or not 0 <= order <= 99999 or type(primary) is not bool:
        abort(400, description="状态、排序或主组织设置无效")
    if primary != bool(row.supports_primary) and references(row.code):
        abort(400, description="类型已有组织或角色引用，不能更改主组织用途")
    row.name, row.status, row.order_num, row.supports_primary = name.strip(), status, order, primary


def commit():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409, description="组织类型编码已存在")
    g.pop("organization_type_catalog", None)


@organization_type_bp.get("")
@login_required
def list_types():
    rows = OrgType.query.order_by(OrgType.order_num, OrgType.code).all()
    include_archived = current_user().is_admin and request.args.get("includeArchived") == "true"
    return jsonify(code=0, data=[r.to_dict() for r in rows if
        (not r.archived or include_archived) and (current_user().is_admin or r.status == "0")])


@organization_type_bp.post("")
@login_required
@platform_admin_required
def create_type():
    data = payload()
    code = data.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,15}", code) or code in SHARED_DOMAINS:
        abort(400, description="编码需为1至16位大写字母、数字、下划线，以字母开头；不能使用系统保留业务域")
    if db.session.get(OrgType, code):
        abort(409, description="组织类型编码已存在")
    row = OrgType(code=code)
    apply_values(row, data)
    db.session.add(row)
    audit(current_user().id, None, "ORG_TYPE_CREATED", {"after": row.to_dict()})
    commit()
    return jsonify(code=0, data=row.to_dict()), 201


@organization_type_bp.put("/<code>")
@login_required
@platform_admin_required
def update_type(code):
    row = OrgType.query.filter_by(code=code).with_for_update().first_or_404()
    if row.archived:
        abort(400, description="类型已归档，历史定义不可修改或重新启用")
    data = payload()
    if data.get("code", code) != code:
        abort(400, description="类型编码不可变更，请修改显示名称")
    before = row.to_dict()
    apply_values(row, data)
    audit(current_user().id, None, "ORG_TYPE_UPDATED", {"before": before, "after": row.to_dict()})
    commit()
    return jsonify(code=0, data=row.to_dict())


@organization_type_bp.delete("/<code>")
@login_required
@platform_admin_required
def delete_type(code):
    row = OrgType.query.filter_by(code=code).with_for_update().first_or_404()
    if row.archived:
        return jsonify(code=0, message="类型已归档，历史记录保留")
    plan = deletion_plan(row, lock=True)
    if not plan["canDelete"]:
        return jsonify(code=400, message="仍有当前引用，请按删除指引处理后重新检查", data=plan), 400
    audit(current_user().id, None, "ORG_TYPE_ARCHIVED", {"before": row.to_dict(), "retained": plan["retained"]})
    row.archived, row.status = True, "1"
    commit()
    return jsonify(code=0, message="组织类型已归档删除，历史权限记录完整保留")


@organization_type_bp.get("/<code>/deletion-plan")
@login_required
@platform_admin_required
def get_deletion_plan(code):
    return jsonify(code=0, data=deletion_plan(db.session.get(OrgType, code) or abort(404)))
