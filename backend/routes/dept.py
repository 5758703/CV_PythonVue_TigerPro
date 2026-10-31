from flask import Blueprint, request, jsonify, abort, g

from extensions import db
from models import Dept, User
from models.organization import OrgMembership
from security import permission_required, current_user
from services.organization_auth import ORG_TYPES, operation_org_ids, subtree, audit

dept_bp = Blueprint("sys_dept", __name__, url_prefix="/api/system/dept")


def _tree(depts, parent_id=0):
    nodes = {d.id: d.to_dict() for d in depts}
    roots = []
    for item in nodes.values():
        parent = nodes.get(item["parentId"])
        if parent and parent is not item:
            parent.setdefault("children", []).append(item)
        else:
            roots.append(item)
    def sort(items):
        items.sort(key=lambda x: (x["orderNum"], x["id"]))
        for item in items:
            sort(item.get("children", []))
    sort(roots)
    return roots


def _allowed(did, perm):
    ids = operation_org_ids(current_user(), perm)
    if ids is not None and did not in ids:
        abort(404)
    return Dept.query.filter_by(id=did, del_flag="0").first_or_404()


def _parent(pid, kind):
    if type(pid) is not int or pid < 0:
        abort(400, description="上级组织格式错误")
    if not pid:
        return None
    parent = Dept.query.filter_by(id=pid, del_flag="0", status="0").first()
    if not parent or parent.org_type != kind:
        abort(400, description="上级组织不存在、已停用或组织类型不匹配")
    return parent


def _lock_tree():
    # Serialize structural edits in MySQL; cycle detection must use current rows
    # even if this request has already loaded the user's context tree.
    nodes = Dept.query.order_by(Dept.id).populate_existing().with_for_update().all()
    g.org_auth_tree = {d.id: d for d in nodes}


def _ancestors(dept):
    ids, seen = [], {dept.id}
    node = dept
    while node.parent_id:
        node = db.session.get(Dept, node.parent_id)
        if not node or node.id in seen or node.org_type != dept.org_type:
            abort(400, description="组织关系存在环或非法上级")
        seen.add(node.id)
        ids.append(node.id)
    return ",".join(str(i) for i in [0] + list(reversed(ids)))


@dept_bp.get("")
@permission_required("system:dept:list")
def list_depts():
    name = request.args.get("deptName", "").strip()
    kind = request.args.get("orgType")
    if kind and kind not in ORG_TYPES:
        abort(400, description="未知组织类型")
    query = Dept.query.filter_by(del_flag="0")
    if kind:
        query = query.filter_by(org_type=kind)
    allowed = operation_org_ids(current_user(), "system:dept:list")
    if allowed is not None:
        query = query.filter(Dept.id.in_(allowed))
    depts = query.all()
    if name:
        matching = {d.id for d in depts if name in d.dept_name}
        by_id = {d.id: d for d in depts}
        for oid in list(matching):
            seen = set()
            while oid in by_id and oid not in seen:
                seen.add(oid)
                matching.add(oid)
                oid = by_id[oid].parent_id
        depts = [d for d in depts if d.id in matching]
    return jsonify(code=0, data=_tree(depts))


@dept_bp.get("/<int:did>")
@permission_required("system:dept:query")
def get_dept(did):
    return jsonify(code=0, data=_allowed(did, "system:dept:query").to_dict())


@dept_bp.post("")
@permission_required("system:dept:add")
def create_dept():
    _lock_tree()
    data = request.get_json(silent=True) or {}
    name, kind = data.get("deptName"), data.get("orgType", "ADMIN")
    if not isinstance(name, str) or not name.strip() or len(name) > 64 or kind not in ORG_TYPES:
        abort(400, description="组织名称必填且不超过64字，类型应为 ADMIN 或 PARTY")
    pid = data.get("parentId", 0)
    parent = _parent(pid, kind)
    if not current_user().is_admin:
        if not parent:
            abort(403, description="创建根组织仅限平台管理员")
        _allowed(pid, "system:dept:add")
    dept = Dept(parent_id=pid, org_type=kind, dept_name=name.strip(), order_num=data.get("orderNum", 0),
                leader=data.get("leader"), phone=data.get("phone"), email=data.get("email"),
                status=data.get("status", "0"))
    if dept.status not in {"0", "1"}:
        abort(400, description="未知组织状态")
    db.session.add(dept)
    db.session.flush()
    dept.ancestors = _ancestors(dept)
    audit(current_user().id, None, "ORG_CREATED", {"after": dept.to_dict()})
    db.session.commit()
    return jsonify(code=0, message="组织已新增", data=dept.to_dict()), 201


@dept_bp.put("/<int:did>")
@permission_required("system:dept:edit")
def update_dept(did):
    _lock_tree()
    dept = _allowed(did, "system:dept:edit")
    data = request.get_json(silent=True) or {}
    before = dept.to_dict()
    if "orgType" in data and data["orgType"] != dept.org_type:
        abort(400, description="组织类型不可直接变更，请新建组织并办理成员移交")
    if "status" in data and data["status"] not in {"0", "1"}:
        abort(400, description="未知组织状态")
    changed_parent = "parentId" in data and data["parentId"] != dept.parent_id
    if not current_user().is_admin and (changed_parent or data.get("status", dept.status) != dept.status):
        abort(403, description="移动或停用组织会影响授权，仅限平台管理员")
    if changed_parent:
        pid = data["parentId"]
        _parent(pid, dept.org_type)
        if pid in subtree(did, include_inactive=True):
            abort(400, description="上级组织不能是自己或自己的下级")
        dept.parent_id = pid
        db.session.flush()
        for node in Dept.query.filter_by(org_type=dept.org_type, del_flag="0"):
            node.ancestors = _ancestors(node)
    if "deptName" in data and (not isinstance(data["deptName"], str) or not data["deptName"].strip()
                               or len(data["deptName"]) > 64):
        abort(400, description="组织名称必填且不超过64字")
    for field, attr in [("deptName", "dept_name"), ("orderNum", "order_num"), ("leader", "leader"),
                        ("phone", "phone"), ("email", "email"), ("status", "status")]:
        if field in data:
            setattr(dept, attr, data[field])
    audit(current_user().id, None, "ORG_UPDATED", {"before": before, "after": dept.to_dict()})
    db.session.commit()
    return jsonify(code=0, message="组织已修改", data=dept.to_dict())


@dept_bp.delete("/<int:did>")
@permission_required("system:dept:remove")
def delete_dept(did):
    _lock_tree()
    dept = _allowed(did, "system:dept:remove")
    if not current_user().is_admin:
        abort(403, description="删除组织会影响授权，仅限平台管理员")
    if Dept.query.filter_by(parent_id=did, del_flag="0").first():
        abort(400, description="存在下级组织，不可删除")
    if (User.query.filter_by(dept_id=did, del_flag="0").first()
            or OrgMembership.query.filter_by(org_id=did, status="0").first()
            or User.query.filter(User.depts.any(id=did), User.del_flag == "0").first()):
        abort(400, description="组织下存在用户或未结束任职，请先移交")
    dept.del_flag = "2"
    audit(current_user().id, None, "ORG_DELETED", {"orgId": did})
    db.session.commit()
    return jsonify(code=0, message="组织已删除")
