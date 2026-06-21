from flask import Blueprint, request, jsonify

from extensions import db
from models import Dept, User
from security import permission_required

dept_bp = Blueprint("sys_dept", __name__, url_prefix="/api/system/dept")


def _tree(depts, parent_id=0):
    nodes = []
    for d in depts:
        if d.parent_id == parent_id:
            item = d.to_dict()
            children = _tree(depts, d.id)
            if children:
                item["children"] = children
            nodes.append(item)
    return sorted(nodes, key=lambda x: x["orderNum"])


@dept_bp.get("")
@permission_required("system:dept:list")
def list_depts():
    name = request.args.get("deptName", "").strip()
    depts = Dept.query.filter(Dept.del_flag == "0").all()
    if name:
        depts = [d for d in depts if name in (d.dept_name or "")]
    return jsonify(code=0, data=_tree(depts))


@dept_bp.get("/<int:did>")
@permission_required("system:dept:query")
def get_dept(did):
    return jsonify(code=0, data=Dept.query.get_or_404(did).to_dict())


@dept_bp.post("")
@permission_required("system:dept:add")
def create_dept():
    data = request.get_json(silent=True) or {}
    if not data.get("deptName"):
        return jsonify(code=400, message="部门名称必填"), 400
    parent_id = data.get("parentId", 0)
    if parent_id and parent_id != 0:
        parent = Dept.query.get_or_404(parent_id)
        ancestors = f"{parent.ancestors},{parent.id}"
    else:
        parent_id, ancestors = 0, "0"

    dept = Dept(
        parent_id=parent_id,
        ancestors=ancestors,
        dept_name=data["deptName"],
        order_num=data.get("orderNum", 0),
        leader=data.get("leader"),
        phone=data.get("phone"),
        email=data.get("email"),
        status=data.get("status", "0"),
    )
    db.session.add(dept)
    db.session.commit()
    return jsonify(code=0, message="新增成功", data=dept.to_dict()), 201


@dept_bp.put("/<int:did>")
@permission_required("system:dept:edit")
def update_dept(did):
    dept = Dept.query.get_or_404(did)
    data = request.get_json(silent=True) or {}
    if "parentId" in data and data["parentId"] != dept.parent_id:
        new_pid = data["parentId"]
        if new_pid == did:
            return jsonify(code=400, message="上级部门不能是自己"), 400
        if new_pid and new_pid != 0:
            parent = Dept.query.get_or_404(new_pid)
            dept.ancestors = f"{parent.ancestors},{parent.id}"
        else:
            new_pid, dept.ancestors = 0, "0"
        dept.parent_id = new_pid
    for field, attr in [("deptName", "dept_name"), ("orderNum", "order_num"),
                        ("leader", "leader"), ("phone", "phone"),
                        ("email", "email"), ("status", "status")]:
        if field in data:
            setattr(dept, attr, data[field])
    db.session.commit()
    return jsonify(code=0, message="修改成功", data=dept.to_dict())


@dept_bp.delete("/<int:did>")
@permission_required("system:dept:remove")
def delete_dept(did):
    dept = Dept.query.get_or_404(did)
    if Dept.query.filter_by(parent_id=did, del_flag="0").first():
        return jsonify(code=400, message="存在下级部门，不可删除"), 400
    if User.query.filter_by(dept_id=did, del_flag="0").first():
        return jsonify(code=400, message="部门下存在用户，不可删除"), 400
    dept.del_flag = "2"
    db.session.commit()
    return jsonify(code=0, message="删除成功")
