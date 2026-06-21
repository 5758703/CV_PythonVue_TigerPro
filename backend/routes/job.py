from flask import Blueprint, request, jsonify

from extensions import db
from models import Job
from security import permission_required

job_bp = Blueprint("sys_job", __name__, url_prefix="/api/system/job")


@job_bp.get("")
@permission_required("system:job:list")
def list_jobs():
    page = int(request.args.get("pageNum", 1))
    size = int(request.args.get("pageSize", 10))
    name = request.args.get("postName", "").strip()

    query = Job.query
    if name:
        query = query.filter(Job.post_name.like(f"%{name}%"))
    total = query.count()
    rows = query.order_by(Job.post_sort).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [j.to_dict() for j in rows], "total": total})


@job_bp.get("/<int:jid>")
@permission_required("system:job:query")
def get_job(jid):
    return jsonify(code=0, data=Job.query.get_or_404(jid).to_dict())


@job_bp.post("")
@permission_required("system:job:add")
def create_job():
    data = request.get_json(silent=True) or {}
    if not data.get("postCode") or not data.get("postName"):
        return jsonify(code=400, message="岗位编码和名称必填"), 400
    job = Job(
        post_code=data["postCode"],
        post_name=data["postName"],
        post_sort=data.get("postSort", 0),
        status=data.get("status", "0"),
    )
    db.session.add(job)
    db.session.commit()
    return jsonify(code=0, message="新增成功", data=job.to_dict()), 201


@job_bp.put("/<int:jid>")
@permission_required("system:job:edit")
def update_job(jid):
    job = Job.query.get_or_404(jid)
    data = request.get_json(silent=True) or {}
    for field, attr in [("postCode", "post_code"), ("postName", "post_name"),
                        ("postSort", "post_sort"), ("status", "status")]:
        if field in data:
            setattr(job, attr, data[field])
    db.session.commit()
    return jsonify(code=0, message="修改成功", data=job.to_dict())


@job_bp.delete("/<int:jid>")
@permission_required("system:job:remove")
def delete_job(jid):
    job = Job.query.get_or_404(jid)
    db.session.delete(job)
    db.session.commit()
    return jsonify(code=0, message="删除成功")
