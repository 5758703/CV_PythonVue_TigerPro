"""行人重识别接口 /api/ai/reid。

底库 CRUD + 外观登记 enroll + 实时 recognize（框旁像谁/未知）
+ 底库检索 search + 录像片段检索 search-video
+ 可选 hybrid：近距正脸用人脸，远距/背影用外观。
"""
from __future__ import annotations

import os
import tempfile
import uuid

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from extensions import db
from models import AiModel, ReidEmbedding, ReidPerson
from security import permission_required
from services.reid_gallery import (
    avg_embeddings,
    invalidate_gallery,
    pack_embedding,
)

reid_bp = Blueprint("reid", __name__, url_prefix="/api/ai/reid")

REID_LIBS = ("opencv-reid", "youtu-reid", "youtureid", "person-reid")
MODALITY_APPEARANCE = "appearance"


def _resolve_reid_model(mid: int):
    m = AiModel.query.get(mid)
    if m is None:
        return None, "模型不存在"
    lib = (m.library or "").strip().lower()
    if (m.task or "") not in ("person-reid", "reid", "person_reidentification"):
        return None, "请选择 task=person-reid 的模型"
    if m.status != "0":
        return None, "模型已停用"
    if lib not in REID_LIBS:
        return None, "请选择 library=opencv-reid 的行人重识别模型"
    if not m.file_path:
        return None, "ReID 模型未就绪，请先在模型管理页拉取权重"
    root = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    if not os.path.isdir(root) and not os.path.isfile(root):
        return None, f"权重目录不存在：{m.file_path}"
    try:
        from person_reid_dnn import assets_ready, resolve_model_dir
        d = resolve_model_dir(root)
        if not assets_ready(d):
            return None, "Youtu ReID ONNX 未就绪，请重新拉取"
        root = d
    except Exception as e:  # noqa: BLE001
        return None, f"ReID 模型检查失败：{e}"
    return (m, root), None


def _resolve_detector(mid: int | None):
    """可选行人检测器（Ultralytics COCO person）。mid 为空时默认首选 yolo26n。"""
    m = None
    if mid:
        m = AiModel.query.get(mid)
    if m is None:
        # 默认优先级：yolo26n > winedarksea-yolo26n_person > simoswish-PersonDetector_YOLO26_PRW
        for key in (
            "yolo26n",
            "winedarksea-yolo26n_person",
            "simoswish-PersonDetector_YOLO26_PRW",
            "yolo11n",
            "yolov8n",
        ):
            m = AiModel.query.filter_by(
                model_key=key, task="object-detection", status="0",
            ).filter(AiModel.file_path.isnot(None)).first()
            if m is not None:
                break
        if m is None:
            m = (
                AiModel.query.filter(
                    AiModel.task == "object-detection",
                    AiModel.library == "ultralytics",
                    AiModel.status == "0",
                    AiModel.file_path.isnot(None),
                )
                .order_by(AiModel.id.asc())
                .first()
            )
    if m is None:
        return None, None, "未找到可用的行人检测模型，请先在模型管理拉取 YOLO"
    if m.status != "0" or not m.file_path:
        return None, None, "检测模型未就绪"
    abs_path = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    if os.path.isdir(abs_path):
        preferred = (
            "yolo26n.pt", "yolo26n.onnx", "yolo11n.pt", "yolo11n.onnx",
            "yolov8n.pt", "yolov8n.onnx", "best.pt", "best.onnx",
        )
        picked = None
        for name in preferred:
            cand = os.path.join(abs_path, name)
            if os.path.isfile(cand):
                picked = cand
                break
        if picked is None:
            for root, _dirs, files in os.walk(abs_path):
                for f in files:
                    if f.lower().endswith((".pt", ".onnx", ".engine")):
                        picked = os.path.join(root, f)
                        break
                if picked:
                    break
        abs_path = picked or abs_path
    if not os.path.isfile(abs_path):
        return None, None, f"检测权重不存在：{m.file_path}"
    return m, abs_path, None


def _resolve_face_model(mid: int | None):
    if not mid:
        return None, None
    from routes.face import _resolve_face_model as _rf
    resolved, err = _rf(int(mid))
    if err:
        return None, err
    return resolved, None


def _save_enroll_image(person_id: int, file_storage) -> str | None:
    raw = file_storage.filename or "person.jpg"
    ext = os.path.splitext(secure_filename(raw))[1] or ".jpg"
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "reid", str(person_id))
    os.makedirs(folder, exist_ok=True)
    fname = f"{uuid.uuid4().hex}{ext}"
    abs_path = os.path.join(folder, fname)
    file_storage.save(abs_path)
    return f"reid/{person_id}/{fname}"


# ---------------- 人员底库 CRUD ----------------

@reid_bp.get("/persons")
@permission_required("ai:reid:list")
def list_persons():
    q = (request.args.get("name") or "").strip()
    query = ReidPerson.query
    if q:
        query = query.filter(ReidPerson.name.contains(q))
    rows = query.order_by(ReidPerson.id.desc()).all()
    return jsonify(code=0, data={"rows": [p.to_dict() for p in rows], "total": len(rows)})


@reid_bp.get("/persons/<int:pid>")
@permission_required("ai:reid:list")
def get_person(pid):
    p = ReidPerson.query.get_or_404(pid)
    return jsonify(code=0, data=p.to_dict(with_embeddings=True))


@reid_bp.post("/persons")
@permission_required("ai:reid:add")
def create_person():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(code=400, message="姓名不能为空"), 400
    face_pid = data.get("facePersonId")
    try:
        face_pid = int(face_pid) if face_pid not in (None, "") else None
    except (TypeError, ValueError):
        face_pid = None
    p = ReidPerson(
        name=name,
        employee_no=(data.get("employeeNo") or "").strip() or None,
        remark=(data.get("remark") or "").strip() or None,
        face_person_id=face_pid,
        status=data.get("status") or "0",
    )
    db.session.add(p)
    db.session.commit()
    return jsonify(code=0, message="已创建", data=p.to_dict())


@reid_bp.put("/persons/<int:pid>")
@permission_required("ai:reid:edit")
def update_person(pid):
    p = ReidPerson.query.get_or_404(pid)
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
    if "facePersonId" in data:
        fp = data.get("facePersonId")
        try:
            p.face_person_id = int(fp) if fp not in (None, "") else None
        except (TypeError, ValueError):
            p.face_person_id = None
    if "status" in data and data["status"] in ("0", "1"):
        p.status = data["status"]
    db.session.commit()
    invalidate_gallery()
    return jsonify(code=0, message="已更新", data=p.to_dict())


@reid_bp.delete("/persons/<int:pid>")
@permission_required("ai:reid:remove")
def delete_person(pid):
    p = ReidPerson.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    invalidate_gallery()
    return jsonify(code=0, message="已删除")


# ---------------- 登记 ----------------

@reid_bp.post("/persons/<int:pid>/enroll")
@permission_required("ai:reid:add")
def enroll(pid):
    """登记全身/半身外观：multipart files[] + modelId + 可选 detectorModelId。"""
    p = ReidPerson.query.get_or_404(pid)
    try:
        mid = int(request.form.get("modelId") or 0)
    except (TypeError, ValueError):
        return jsonify(code=400, message="modelId 无效"), 400
    resolved, err = _resolve_reid_model(mid)
    if err:
        return jsonify(code=400, message=err), 400
    m, root = resolved

    det_mid = request.form.get("detectorModelId") or request.form.get("detModelId")
    try:
        det_mid = int(det_mid) if det_mid not in (None, "") else None
    except (TypeError, ValueError):
        det_mid = None
    _dm, det_path, det_err = _resolve_detector(det_mid)
    # 登记允许无检测器（整图）
    if det_err:
        det_path = None

    files = request.files.getlist("files") or []
    if not files:
        one = request.files.get("file")
        if one and one.filename:
            files = [one]
    if not files:
        return jsonify(code=400, message="请上传至少一张行人全身照片（files）"), 400

    from inference import _crop_person, _decode_bgr, _detect_persons_yolo
    from person_reid_dnn import extract_feature
    from services.reid_gallery import l2_normalize
    import numpy as np

    vectors = []
    source_paths = []
    for f in files:
        if not f or not f.filename:
            continue
        raw = f.read()
        f.stream.seek(0)
        img = _decode_bgr(raw)
        crop = img
        if det_path:
            persons = _detect_persons_yolo(det_path, img, conf=0.3)
            if persons:
                best = max(
                    persons,
                    key=lambda x: (x["bbox"][2] - x["bbox"][0]) * (x["bbox"][3] - x["bbox"][1]),
                )
                c = _crop_person(img, best["bbox"])
                if c is not None:
                    crop = c
        feat, _meta = extract_feature(root, crop)
        vectors.append(l2_normalize(np.asarray(feat, dtype=np.float32)))
        rel = _save_enroll_image(p.id, f)
        if rel:
            source_paths.append(rel)

    if not vectors:
        return jsonify(code=400, message="未提取到有效外观特征"), 400

    emb_vec = avg_embeddings(vectors)
    old = ReidEmbedding.query.filter_by(
        person_id=p.id, model_key=m.model_key, modality=MODALITY_APPEARANCE,
    ).all()
    for o in old:
        db.session.delete(o)

    row = ReidEmbedding(
        person_id=p.id,
        model_key=m.model_key,
        model_version=(_meta.get("modelVersion") or _meta.get("onnx") or m.version or "").strip() or None,
        modality=MODALITY_APPEARANCE,
        dim=int(emb_vec.size),
        vector=pack_embedding(emb_vec),
        source_path=source_paths[0] if source_paths else None,
    )
    db.session.add(row)
    db.session.commit()
    invalidate_gallery(m.model_key, MODALITY_APPEARANCE)
    return jsonify(
        code=0,
        message=f"外观登记成功（{len(vectors)} 张）",
        data=p.to_dict(with_embeddings=True),
    )


def _parse_float(name, default):
    try:
        return float(request.form.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _parse_int(name, default=None):
    raw = request.form.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# ---------------- 识别 / 检索 ----------------

@reid_bp.post("/recognize")
@permission_required("ai:reid:list")
def recognize():
    """上传一帧：检测行人并在框旁显示「像谁 / 未知」。

    form: file, modelId, detectorModelId?, threshold, detConf, draw,
          hybrid, faceModelId（近距正脸用人脸）
    """
    file = request.files.get("file") or request.files.get("image")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片（file）"), 400
    mid = _parse_int("modelId")
    if not mid:
        return jsonify(code=400, message="modelId 无效"), 400
    resolved, err = _resolve_reid_model(mid)
    if err:
        return jsonify(code=400, message=err), 400
    m, root = resolved

    det_mid = _parse_int("detectorModelId") or _parse_int("detModelId")
    _dm, det_path, det_err = _resolve_detector(det_mid)
    if det_err:
        # 仍允许整图识别
        det_path = None

    threshold = _parse_float("threshold", 0.45)
    det_conf = _parse_float("detConf", 0.35)
    draw = (request.form.get("draw") or "1") in ("1", "true", "True")
    hybrid = (request.form.get("hybrid") or "0") in ("1", "true", "True")

    face_root = face_pack = face_library = None
    face_model_key = None
    face_threshold = _parse_float("faceThreshold", 0.4)
    if hybrid:
        face_mid = _parse_int("faceModelId")
        fres, ferr = _resolve_face_model(face_mid)
        if ferr or not fres:
            return jsonify(code=400, message=ferr or "混合模式需要有效的 faceModelId"), 400
        fm, face_root, face_pack, face_library = fres
        face_model_key = fm.model_key

    from inference import recognize_persons

    try:
        data = recognize_persons(
            root,
            m.model_key,
            file.read(),
            det_abs_path=det_path,
            threshold=threshold,
            det_conf=det_conf,
            draw=draw,
            hybrid=hybrid,
            face_root=face_root,
            face_pack=face_pack or "",
            face_library=face_library or "opencv-face",
            face_model_key=face_model_key,
            face_threshold=face_threshold,
        )
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"识别失败：{e}"), 500
    return jsonify(code=0, message="识别完成", data=data)


@reid_bp.post("/search")
@permission_required("ai:reid:list")
def search_gallery():
    """指定行人图在底库中检索 Top-K。form: file, modelId, topk, detectorModelId?"""
    file = request.files.get("file") or request.files.get("image")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到查询图（file）"), 400
    mid = _parse_int("modelId")
    if not mid:
        return jsonify(code=400, message="modelId 无效"), 400
    resolved, err = _resolve_reid_model(mid)
    if err:
        return jsonify(code=400, message=err), 400
    m, root = resolved
    topk = _parse_int("topk", 5) or 5
    det_mid = _parse_int("detectorModelId") or _parse_int("detModelId")
    _dm, det_path, _ = _resolve_detector(det_mid)

    from inference import search_reid_gallery

    try:
        data = search_reid_gallery(
            root, m.model_key, file.read(),
            topk=topk, det_abs_path=det_path, det_conf=_parse_float("detConf", 0.35),
        )
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"检索失败：{e}"), 500
    return jsonify(code=0, message="检索完成", data=data)


@reid_bp.post("/search-video")
@permission_required("ai:reid:list")
def search_video():
    """指定行人图在录像片段中检索。form: query/file + video, modelId, threshold, sampleFps…"""
    qfile = request.files.get("query") or request.files.get("file") or request.files.get("image")
    vfile = request.files.get("video")
    if qfile is None or not qfile.filename:
        return jsonify(code=400, message="请上传查询行人图（query）"), 400
    if vfile is None or not vfile.filename:
        return jsonify(code=400, message="请上传录像片段（video）"), 400
    mid = _parse_int("modelId")
    if not mid:
        return jsonify(code=400, message="modelId 无效"), 400
    resolved, err = _resolve_reid_model(mid)
    if err:
        return jsonify(code=400, message=err), 400
    m, root = resolved
    det_mid = _parse_int("detectorModelId") or _parse_int("detModelId")
    _dm, det_path, _ = _resolve_detector(det_mid)

    suffix = os.path.splitext(secure_filename(vfile.filename))[1] or ".mp4"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = tmp.name
    tmp.close()
    try:
        vfile.save(tmp_path)
        from inference import search_reid_in_video

        data = search_reid_in_video(
            root,
            m.model_key,
            qfile.read(),
            tmp_path,
            threshold=_parse_float("threshold", 0.45),
            topk=_parse_int("topk", 20) or 20,
            sample_fps=_parse_float("sampleFps", 1.0),
            max_frames=_parse_int("maxFrames", 120) or 120,
            det_abs_path=det_path,
            det_conf=_parse_float("detConf", 0.35),
        )
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"录像检索失败：{e}"), 500
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    return jsonify(code=0, message="录像检索完成", data=data)
