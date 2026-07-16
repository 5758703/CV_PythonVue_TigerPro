"""人脸识别接口 /api/ai/face。

底库 CRUD + 登记 enroll + 实时 recognize。
"""
from __future__ import annotations

import os
import uuid

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from extensions import db
from models import AiModel, FaceEmbedding, FacePerson
from security import permission_required
from services.face_gallery import (
    avg_embeddings,
    invalidate_gallery,
    pack_embedding,
)

face_bp = Blueprint("face", __name__, url_prefix="/api/ai/face")


def _insightface_root():
    return os.path.join(current_app.config["UPLOAD_FOLDER"], "insightface")


def _pack_name(m: AiModel) -> str:
    """pack 名优先 version（buffalo_s / buffalo_l），否则从 model_key 推断。"""
    ver = (m.version or "").strip().lower()
    if ver.startswith("buffalo"):
        return ver
    key = (m.model_key or "").lower()
    if "buffalo_l" in key or "buffalo-l" in key:
        return "buffalo_l"
    return "buffalo_s"


def _resolve_face_model(mid: int):
    m = AiModel.query.get(mid)
    if m is None:
        return None, "模型不存在"
    if (m.library or "").lower() != "insightface":
        return None, "请选择 library=insightface 的人脸识别模型"
    if (m.task or "") != "face-recognition":
        return None, "请选择 task=face-recognition 的模型"
    if m.status != "0":
        return None, "模型已停用"
    root = _insightface_root()
    pack = _pack_name(m)
    pack_dir = os.path.join(root, "models", pack)
    if not os.path.isdir(pack_dir):
        return None, f"模型包未就绪（{pack}），请先在模型管理页拉取权重"
    return (m, root, pack), None


def _save_enroll_image(person_id: int, file_storage) -> str | None:
    """保存登记原图，返回相对 UPLOAD_FOLDER 路径。"""
    raw = file_storage.filename or "face.jpg"
    ext = os.path.splitext(secure_filename(raw))[1] or ".jpg"
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "faces", str(person_id))
    os.makedirs(folder, exist_ok=True)
    fname = f"{uuid.uuid4().hex}{ext}"
    abs_path = os.path.join(folder, fname)
    file_storage.save(abs_path)
    return f"faces/{person_id}/{fname}"


# ---------------- 人员底库 CRUD ----------------

@face_bp.get("/persons")
@permission_required("ai:face:list")
def list_persons():
    q = (request.args.get("name") or "").strip()
    query = FacePerson.query
    if q:
        query = query.filter(FacePerson.name.contains(q))
    rows = query.order_by(FacePerson.id.desc()).all()
    return jsonify(code=0, data={"rows": [p.to_dict() for p in rows], "total": len(rows)})


@face_bp.get("/persons/<int:pid>")
@permission_required("ai:face:list")
def get_person(pid):
    p = FacePerson.query.get_or_404(pid)
    return jsonify(code=0, data=p.to_dict(with_embeddings=True))


@face_bp.post("/persons")
@permission_required("ai:face:add")
def create_person():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(code=400, message="姓名不能为空"), 400
    p = FacePerson(
        name=name,
        employee_no=(data.get("employeeNo") or "").strip() or None,
        remark=(data.get("remark") or "").strip() or None,
        status=data.get("status") or "0",
    )
    db.session.add(p)
    db.session.commit()
    return jsonify(code=0, message="已创建", data=p.to_dict())


@face_bp.put("/persons/<int:pid>")
@permission_required("ai:face:edit")
def update_person(pid):
    p = FacePerson.query.get_or_404(pid)
    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify(code=400, message="姓名不能为空"), 400
        p.name = name
    if "employeeNo" in data:
        p.employee_no = (data.get("employeeNo") or "").strip() or None
    if "remark" in data:
        p.remark = (data.get("remark") or "").strip() or None
    if "status" in data and data["status"] in ("0", "1"):
        p.status = data["status"]
    db.session.commit()
    invalidate_gallery()
    return jsonify(code=0, message="已更新", data=p.to_dict())


@face_bp.delete("/persons/<int:pid>")
@permission_required("ai:face:remove")
def delete_person(pid):
    p = FacePerson.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    invalidate_gallery()
    return jsonify(code=0, message="已删除")


# ---------------- 登记 / 识别 ----------------

@face_bp.post("/persons/<int:pid>/enroll")
@permission_required("ai:face:add")
def enroll(pid):
    """为人员登记人脸：multipart files[] + modelId。可多图取平均特征。"""
    p = FacePerson.query.get_or_404(pid)
    try:
        mid = int(request.form.get("modelId") or 0)
    except (TypeError, ValueError):
        return jsonify(code=400, message="modelId 无效"), 400
    resolved, err = _resolve_face_model(mid)
    if err:
        return jsonify(code=400, message=err), 400
    m, root, pack = resolved

    files = request.files.getlist("files") or []
    if not files:
        one = request.files.get("file")
        if one and one.filename:
            files = [one]
    if not files:
        return jsonify(code=400, message="请上传至少一张人脸照片（files）"), 400

    from inference import extract_face_embeddings

    vectors = []
    source_paths = []
    for f in files:
        if not f or not f.filename:
            continue
        raw = f.read()
        f.stream.seek(0)
        faces, _img = extract_face_embeddings(root, pack, raw)
        if not faces:
            return jsonify(code=400, message=f"图片未检测到人脸：{f.filename}"), 400
        # 多脸时取检测分最高的一张
        best = max(faces, key=lambda x: x["detScore"])
        vectors.append(best["embedding"])
        rel = _save_enroll_image(p.id, f)
        if rel:
            source_paths.append(rel)

    if not vectors:
        return jsonify(code=400, message="未提取到有效人脸特征"), 400

    emb_vec = avg_embeddings(vectors)
    # 同 model_key 覆盖旧特征（一人一模型一条主特征）
    old = FaceEmbedding.query.filter_by(person_id=p.id, model_key=m.model_key).all()
    for o in old:
        db.session.delete(o)

    row = FaceEmbedding(
        person_id=p.id,
        model_key=m.model_key,
        dim=int(emb_vec.size),
        vector=pack_embedding(emb_vec),
        source_path=source_paths[0] if source_paths else None,
    )
    db.session.add(row)
    db.session.commit()
    invalidate_gallery(m.model_key)
    return jsonify(
        code=0,
        message=f"登记成功（{len(vectors)} 张）",
        data=p.to_dict(with_embeddings=True),
    )


@face_bp.post("/recognize")
@permission_required("ai:face:list")
def recognize():
    """上传一帧做 1:N 识别。form: file, modelId, threshold, detThresh, draw。"""
    file = request.files.get("file") or request.files.get("image")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片（file）"), 400
    try:
        mid = int(request.form.get("modelId") or 0)
    except (TypeError, ValueError):
        return jsonify(code=400, message="modelId 无效"), 400
    resolved, err = _resolve_face_model(mid)
    if err:
        return jsonify(code=400, message=err), 400
    m, root, pack = resolved

    try:
        threshold = float(request.form.get("threshold", 0.4))
    except (TypeError, ValueError):
        threshold = 0.4
    try:
        det_thresh = float(request.form.get("detThresh", 0.5))
    except (TypeError, ValueError):
        det_thresh = 0.5
    draw = (request.form.get("draw") or "0") in ("1", "true", "True")

    from inference import recognize_faces

    try:
        data = recognize_faces(
            root,
            pack,
            m.model_key,
            file.read(),
            threshold=threshold,
            det_thresh=det_thresh,
            draw=draw,
        )
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"识别失败：{e}"), 500
    return jsonify(code=0, message="识别完成", data=data)
