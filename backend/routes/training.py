"""模型训练接口 /api/ai/training。"""
import os
import shutil
import threading
import zipfile
from pathlib import Path

from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename

from extensions import db
from models.training import TrainingDataset, TrainingJob
from security import permission_required
from services.training import (
    build_yolo_dataset,
    build_dataset_unified,
    write_data_yaml,
    detect_dataset_format,
    extract_zip_dataset,
    scan_dataset_structure,
    DATASET_FORMATS,
    get_format_specs_list,
    is_allowed_import_path,
    run_training_worker,
    request_cancel,
    validate_model,
    test_predict,
    export_model,
    deploy_to_ai_model,
    read_metrics_history,
    parse_results_csv,
    run_validate_worker,
    IMG_EXTENSIONS,
)

training_bp = Blueprint("training", __name__, url_prefix="/api/ai/training")

_IMG_EXT = set(IMG_EXTENSIONS) | {".xml", ".txt", ".yaml", ".yml", ".zip"}
_XML_EXT = {".xml"}

_val_jobs = {}
_val_lock = threading.Lock()


def _upload_root():
    return Path(current_app.config["UPLOAD_FOLDER"])


def _dataset_dir(ds_id):
    return _upload_root() / "datasets" / str(ds_id)


def _run_dir(job):
    return _upload_root() / job.log_dir / (job.run_name or f"train_{job.id}")


def _log_dir(job_id: int):
    return _upload_root() / "training" / "logs" / str(job_id)


def _tail_text(path: Path, offset: int, limit: int):
    if offset < 0:
        offset = 0
    limit = max(256, min(int(limit or 4000), 20000))
    if not path.exists():
        return {"text": "", "nextOffset": offset, "exists": False}
    data = path.read_bytes()
    if offset > len(data):
        offset = len(data)
    chunk = data[offset: offset + limit]
    return {
        "text": chunk.decode("utf-8", errors="replace"),
        "nextOffset": offset + len(chunk),
        "exists": True,
        "size": len(data),
    }


@training_bp.get("/jobs/<int:jid>/logs")
@permission_required("ai:training:query")
def job_logs(jid):
    """增量读取训练/验证日志。query: type=train|val offset limit"""
    t = (request.args.get("type") or "train").strip().lower()
    offset = int(request.args.get("offset") or 0)
    limit = int(request.args.get("limit") or 4000)
    name = "train.log" if t != "val" else "val.log"
    path = _log_dir(jid) / name
    return jsonify(code=0, data=_tail_text(path, offset, limit))


# ── 数据集 ────────────────────────────────────────────

@training_bp.get("/datasets/formats")
@permission_required("ai:training:query")
def list_dataset_formats():
    """返回支持的数据集格式列表（含详细说明）。"""
    return jsonify(code=0, data=get_format_specs_list())


@training_bp.get("/datasets")
@permission_required("ai:training:list")
def list_datasets():
    page = int(request.args.get("pageNum", 1))
    size = int(request.args.get("pageSize", 10))
    name = request.args.get("name", "").strip()
    q = TrainingDataset.query
    if name:
        q = q.filter(TrainingDataset.name.like(f"%{name}%"))
    total = q.count()
    rows = q.order_by(TrainingDataset.id.desc()).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": total})


@training_bp.get("/datasets/<int:did>")
@permission_required("ai:training:query")
def get_dataset(did):
    ds = TrainingDataset.query.get_or_404(did)
    return jsonify(code=0, data=ds.to_dict())


@training_bp.post("/datasets")
@permission_required("ai:training:add")
def create_dataset():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(code=400, message="请输入数据集名称"), 400

    fmt = (data.get("format") or "auto").strip().lower()
    if fmt not in DATASET_FORMATS:
        return jsonify(code=400, message=f"不支持的格式: {fmt}"), 400

    class_names = data.get("classNames") or []
    source_path = (data.get("sourcePath") or "").strip()

    if fmt == "import":
        if not source_path:
            return jsonify(code=400, message="import 格式请填写本地数据集路径 sourcePath"), 400
        src = Path(source_path)
        if not src.exists():
            return jsonify(code=400, message=f"源路径不存在: {source_path}"), 400
        if not is_allowed_import_path(src, Path(current_app.config["BASE_DIR"])):
            return jsonify(code=400, message="仅允许导入项目目录内的数据集路径"), 400
    elif not class_names and fmt not in ("yolo", "auto", "coco", "labelme", "import"):
        return jsonify(code=400, message="请至少填写一个类别名称（YOLO/COCO/LabelMe 可从标注文件推断）"), 400

    ds = TrainingDataset(
        name=name,
        format=fmt,
        source_path=source_path or None,
        split_ratio=float(data.get("splitRatio") or 0.8),
        description=(data.get("description") or "").strip(),
        status="draft",
    )
    ds.set_class_list(class_names)
    db.session.add(ds)
    db.session.flush()

    ds_root = _dataset_dir(ds.id)
    raw_dir = ds_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    ds.storage_path = str(raw_dir.relative_to(_upload_root())).replace("\\", "/")
    db.session.commit()
    return jsonify(code=0, message="创建成功", data=ds.to_dict())


@training_bp.put("/datasets/<int:did>")
@permission_required("ai:training:edit")
def update_dataset(did):
    ds = TrainingDataset.query.get_or_404(did)
    data = request.get_json(silent=True) or {}
    if data.get("name"):
        ds.name = data["name"].strip()
    if "classNames" in data:
        ds.set_class_list(data["classNames"])
    if "splitRatio" in data:
        ds.split_ratio = float(data["splitRatio"])
    if "format" in data:
        fmt = (data.get("format") or "auto").strip().lower()
        if fmt in DATASET_FORMATS:
            ds.format = fmt
    if "sourcePath" in data:
        ds.source_path = (data.get("sourcePath") or "").strip() or None
    if "description" in data:
        ds.description = (data.get("description") or "").strip()
    db.session.commit()
    return jsonify(code=0, message="更新成功", data=ds.to_dict())


@training_bp.delete("/datasets/<int:did>")
@permission_required("ai:training:remove")
def delete_dataset(did):
    ds = TrainingDataset.query.get_or_404(did)
    if TrainingJob.query.filter_by(dataset_id=did).first():
        return jsonify(code=400, message="该数据集已被训练任务引用，无法删除"), 400
    root = _upload_root() / "datasets" / str(did)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    db.session.delete(ds)
    db.session.commit()
    return jsonify(code=0, message="删除成功")


@training_bp.post("/datasets/<int:did>/upload")
@permission_required("ai:training:add")
def upload_dataset_files(did):
    """上传数据集文件：图片、XML、YOLO txt、data.yaml 或 zip 压缩包。"""
    ds = TrainingDataset.query.get_or_404(did)
    if ds.format == "import":
        return jsonify(code=400, message="import 格式无需上传，请直接构建"), 400

    raw_dir = _dataset_dir(did) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        f = request.files.get("file")
        files = [f] if f and f.filename else []

    if not files:
        return jsonify(code=400, message="未接收到文件"), 400

    saved, zip_extracted = 0, 0
    for f in files:
        if not f or not f.filename:
            continue
        fname = secure_filename(f.filename)
        ext = Path(fname).suffix.lower()

        if ext == ".zip":
            zip_path = raw_dir / fname
            f.save(str(zip_path))
            saved += 1
            try:
                zip_extracted += extract_zip_dataset(zip_path, raw_dir)
            except zipfile.BadZipFile:
                return jsonify(code=400, message=f"无效的 zip 文件: {fname}"), 400
            continue

        if ext not in _IMG_EXT:
            continue

        # 支持 zip 内相对路径（如 images/train/xxx.jpg）
        rel_path = request.form.get("relativePath") or fname
        rel_path = rel_path.replace("\\", "/").lstrip("/")
        if ".." in rel_path:
            continue
        target = raw_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        f.save(str(target))
        saved += 1

    detected = detect_dataset_format(raw_dir)
    return jsonify(code=0, message=f"已上传 {saved} 个文件" + (f"，解压 {zip_extracted} 个" if zip_extracted else ""),
                    data={"saved": saved, "zipExtracted": zip_extracted, "detectedFormat": detected})


@training_bp.post("/datasets/<int:did>/build")
@permission_required("ai:training:edit")
def build_dataset(did):
    """多格式数据集 → YOLO 统一格式并生成 data.yaml。"""
    ds = TrainingDataset.query.get_or_404(did)
    yolo_dir = _dataset_dir(did) / "yolo"
    raw_dir = _dataset_dir(did) / "raw"
    fmt = (ds.format or "auto").lower()
    class_names = ds.class_list()

    source_path = Path(ds.source_path) if ds.source_path else None
    work_dir = raw_dir

    if fmt == "import":
        if not source_path or not source_path.exists():
            return jsonify(code=400, message="import 格式请填写有效的 sourcePath"), 400
        work_dir = source_path
    elif fmt != "import" and not raw_dir.exists():
        return jsonify(code=400, message="请先上传标注数据"), 400

    try:
        train_n, val_n, diag = build_dataset_unified(
            fmt=fmt,
            source_dir=work_dir,
            yolo_dir=yolo_dir,
            class_names=class_names,
            split_ratio=ds.split_ratio or 0.8,
            source_path=source_path,
            app_base_dir=Path(current_app.config["BASE_DIR"]),
        )
    except ValueError as e:
        ds.status = "error"
        db.session.commit()
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        ds.status = "error"
        db.session.commit()
        return jsonify(code=500, message=f"构建失败：{e}"), 500

    if train_n + val_n == 0:
        ds.status = "error"
        db.session.commit()
        found = diag.get("foundClasses") or []
        hint = ""
        if found and class_names and not set(found).intersection(set(class_names)):
            hint = f"；标注类别={found} 与填写类别={class_names} 不匹配（区分大小写）"
        fmt_used = diag.get("format", fmt)
        if fmt_used == "voc" or fmt_used == "voc_standard":
            msg = (
                f"无有效样本（XML {diag.get('xmlTotal', 0)}，跳过 {diag.get('skip', 0)}："
                f"缺图片 {diag.get('skipNoImage', 0)}，无有效框 {diag.get('skipNoBoxes', 0)}，"
                f"解析失败 {diag.get('skipParseError', 0)}）{hint}"
            )
        elif fmt_used in ("coco", "labelme"):
            msg = (
                f"无有效样本（格式={fmt_used}，跳过 {diag.get('skip', 0)}）"
                f"{hint}"
            )
        else:
            msg = f"无有效样本（检测格式={fmt_used}）{hint}"
        return jsonify(code=400, message=msg, data=diag), 400

    # 若构建时从 yaml 推断出类别，回写数据库
    inferred = diag.get("classNames")
    if inferred and not class_names:
        ds.set_class_list(inferred)
        class_names = inferred

    yaml_path = yolo_dir / "data.yaml"
    if not yaml_path.exists():
        yaml_path = write_data_yaml(yolo_dir, class_names)

    ds.train_count = train_n
    ds.val_count = val_n
    ds.yaml_path = str(yaml_path.relative_to(_upload_root())).replace("\\", "/")
    ds.status = "ready"
    db.session.commit()

    fmt_label = DATASET_FORMATS.get(diag.get("format", fmt), diag.get("format", fmt))
    skip = diag.get("skip", 0)
    msg = f"构建完成（{fmt_label}）：训练 {train_n} / 验证 {val_n}"
    if skip:
        msg += f"（跳过 {skip}）"
    return jsonify(code=0, message=msg, data={**ds.to_dict(), "buildInfo": diag})


@training_bp.get("/datasets/<int:did>/samples")
@permission_required("ai:training:query")
def dataset_samples(did):
    """预览数据集文件列表与结构检测。"""
    ds = TrainingDataset.query.get_or_404(did)
    if ds.format == "import" and ds.source_path:
        scan_dir = Path(ds.source_path)
    else:
        scan_dir = _dataset_dir(did) / "raw"
    info = scan_dataset_structure(scan_dir)
    return jsonify(code=0, data={"dataset": ds.to_dict(), **info})


# ── 训练任务 ──────────────────────────────────────────

@training_bp.get("/jobs")
@permission_required("ai:training:list")
def list_jobs():
    page = int(request.args.get("pageNum", 1))
    size = int(request.args.get("pageSize", 10))
    status = request.args.get("status", "").strip()
    q = TrainingJob.query
    if status:
        q = q.filter(TrainingJob.status == status)
    total = q.count()
    rows = q.order_by(TrainingJob.id.desc()).offset((page - 1) * size).limit(size).all()
    return jsonify(code=0, data={"rows": [r.to_dict() for r in rows], "total": total})


@training_bp.get("/jobs/<int:jid>")
@permission_required("ai:training:query")
def get_job(jid):
    job = TrainingJob.query.get_or_404(jid)
    return jsonify(code=0, data=job.to_dict(detail=True))


@training_bp.get("/jobs/<int:jid>/progress")
@permission_required("ai:training:query")
def job_progress(jid):
    job = TrainingJob.query.get_or_404(jid)
    data = job.to_dict(detail=True)
    # 补充训练曲线图资源路径
    charts = {}
    if job.log_dir:
        log_abs = _run_dir(job)
        for name in ("results.png", "confusion_matrix.png", "F1_curve.png", "PR_curve.png"):
            p = log_abs / name
            if p.exists():
                charts[name] = f"/api/ai/training/jobs/{jid}/artifact/{name}"
    data["charts"] = charts
    return jsonify(code=0, data=data)


@training_bp.get("/jobs/<int:jid>/artifact/<path:filename>")
@permission_required("ai:training:query")
def job_artifact(jid, filename):
    job = TrainingJob.query.get_or_404(jid)
    if not job.log_dir:
        return jsonify(code=404, message="产物不存在"), 404
    log_abs = _run_dir(job)
    path = (log_abs / filename).resolve()
    if not str(path).startswith(str(log_abs.resolve())):
        return jsonify(code=403, message="非法路径"), 403
    if not path.exists():
        return jsonify(code=404, message="文件不存在"), 404
    return send_file(path)


@training_bp.post("/jobs")
@permission_required("ai:training:add")
def create_job():
    data = request.get_json(silent=True) or {}
    name = (data.get("jobName") or "").strip()
    dataset_id = data.get("datasetId")
    if not name:
        return jsonify(code=400, message="请输入任务名称"), 400
    if not dataset_id:
        return jsonify(code=400, message="请选择数据集"), 400
    ds = TrainingDataset.query.get(dataset_id)
    if not ds or ds.status != "ready":
        return jsonify(code=400, message="数据集未就绪，请先构建"), 400

    hp = {
        "epochs": int(data.get("epochs") or 100),
        "batch": int(data.get("batch") or 8),
        "imgsz": int(data.get("imgsz") or 640),
        "device": data.get("device") or "cpu",
        "patience": int(data.get("patience") or 20),
    }
    job = TrainingJob(
        job_name=name,
        dataset_id=dataset_id,
        base_model=data.get("baseModel") or "yolov8n.pt",
        framework="ultralytics",
        status="pending",
        total_epochs=hp["epochs"],
    )
    job.set_hyperparams(hp)
    db.session.add(job)
    db.session.flush()
    job.run_name = f"train_{job.id}"
    db.session.commit()
    return jsonify(code=0, message="创建成功", data=job.to_dict())


@training_bp.post("/jobs/<int:jid>/start")
@permission_required("ai:training:edit")
def start_job(jid):
    job = TrainingJob.query.get_or_404(jid)
    if job.status == "running":
        return jsonify(code=400, message="任务正在训练中"), 400
    if job.status == "done":
        return jsonify(code=400, message="任务已完成，请新建任务"), 400

    job.status = "pending"
    job.error_message = None
    job.progress = 0
    job.current_epoch = 0
    db.session.commit()

    app = current_app._get_current_object()
    threading.Thread(target=run_training_worker, args=(app, jid), daemon=True).start()
    return jsonify(code=0, message="训练已启动", data=job.to_dict())


@training_bp.post("/jobs/<int:jid>/cancel")
@permission_required("ai:training:edit")
def cancel_job(jid):
    job = TrainingJob.query.get_or_404(jid)
    if job.status != "running":
        return jsonify(code=400, message="仅运行中的任务可取消"), 400
    request_cancel(jid)
    return jsonify(code=0, message="已发送取消请求")


@training_bp.delete("/jobs/<int:jid>")
@permission_required("ai:training:remove")
def delete_job(jid):
    job = TrainingJob.query.get_or_404(jid)
    if job.status == "running":
        return jsonify(code=400, message="请先取消运行中的任务"), 400
    root = _upload_root() / "training" / "runs" / str(jid)
    wroot = _upload_root() / "training" / "weights" / str(jid)
    for p in (root, wroot):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    db.session.delete(job)
    db.session.commit()
    return jsonify(code=0, message="删除成功")


# ── 验证 / 测试 / 导出 / 部署 ─────────────────────────

@training_bp.post("/jobs/<int:jid>/validate")
@permission_required("ai:training:query")
def validate_job(jid):
    """启动后台验证任务（写 val.log），并用 validate-progress 查询结果。"""
    job = TrainingJob.query.get_or_404(jid)
    if not job.output_weight_path:
        return jsonify(code=400, message="任务尚无训练权重"), 400

    with _val_lock:
        j = _val_jobs.get(jid)
        if j and j.get("status") == "running":
            return jsonify(code=400, message="验证正在进行中"), 400
        _val_jobs[jid] = {"status": "running", "progress": 0, "result": None, "error": None}

    app = current_app._get_current_object()

    def _worker():
        try:
            with _val_lock:
                _val_jobs[jid]["progress"] = 10
            metrics = run_validate_worker(app, jid)
            with _val_lock:
                _val_jobs[jid].update(status="done" if metrics is not None else "error",
                                      progress=100 if metrics is not None else 100,
                                      result=metrics, error=None if metrics is not None else "验证失败")
        except Exception as e:  # noqa: BLE001
            with _val_lock:
                _val_jobs[jid].update(status="error", progress=100, error=str(e))

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify(code=0, message="验证已启动")


@training_bp.get("/jobs/<int:jid>/validate-progress")
@permission_required("ai:training:query")
def validate_progress(jid):
    with _val_lock:
        j = _val_jobs.get(jid)
        if not j:
            return jsonify(code=0, data={"status": "idle", "progress": 0})
        return jsonify(code=0, data=j)


@training_bp.post("/jobs/<int:jid>/test")
@permission_required("ai:training:query")
def test_job(jid):
    job = TrainingJob.query.get_or_404(jid)
    if not job.output_weight_path:
        return jsonify(code=400, message="任务尚无训练权重"), 400
    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify(code=400, message="请上传测试图片"), 400
    conf = float(request.form.get("conf") or 0.25)
    weight_abs = _upload_root() / job.output_weight_path
    try:
        data = test_predict(weight_abs, file.read(), conf=conf)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"测试失败：{e}"), 500
    return jsonify(code=0, message="测试完成", data=data)


@training_bp.post("/jobs/<int:jid>/export")
@permission_required("ai:training:edit")
def export_job(jid):
    job = TrainingJob.query.get_or_404(jid)
    if not job.output_weight_path:
        return jsonify(code=400, message="任务尚无训练权重"), 400
    data = request.get_json(silent=True) or {}
    fmt = (data.get("format") or "onnx").lower()
    weight_abs = _upload_root() / job.output_weight_path
    out_dir = _upload_root() / "training" / "exports" / str(jid)
    try:
        dest = export_model(weight_abs, out_dir, fmt=fmt)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"导出失败：{e}"), 500
    rel = str(dest.relative_to(_upload_root())).replace("\\", "/")
    return jsonify(code=0, message="导出成功", data={
        "path": rel,
        "fileName": dest.name,
        "size": dest.stat().st_size,
        "downloadUrl": f"/api/ai/training/jobs/{jid}/download-export?file={dest.name}",
    })


@training_bp.get("/jobs/<int:jid>/download-export")
@permission_required("ai:training:query")
def download_export(jid):
    job = TrainingJob.query.get_or_404(jid)
    fname = request.args.get("file", "")
    if not fname:
        return jsonify(code=400, message="缺少 file 参数"), 400
    path = (_upload_root() / "training" / "exports" / str(jid) / secure_filename(fname)).resolve()
    export_root = (_upload_root() / "training" / "exports" / str(jid)).resolve()
    if not str(path).startswith(str(export_root)) or not path.exists():
        return jsonify(code=404, message="文件不存在"), 404
    return send_file(path, as_attachment=True)


@training_bp.post("/jobs/<int:jid>/deploy")
@permission_required("ai:training:edit")
def deploy_job(jid):
    """将 best.pt 注册到模型管理（ai_model）。"""
    job = TrainingJob.query.get_or_404(jid)
    if job.status != "done":
        return jsonify(code=400, message="仅已完成的训练任务可部署"), 400
    data = request.get_json(silent=True) or {}
    model_name = (data.get("modelName") or job.job_name).strip()
    model_key = (data.get("modelKey") or f"custom-{jid}").strip()
    category = (data.get("category") or "自定义训练").strip()
    description = (data.get("description") or "").strip()
    if not model_name or not model_key:
        return jsonify(code=400, message="请填写模型名称与标识"), 400
    try:
        m = deploy_to_ai_model(
            current_app._get_current_object(), job,
            model_name, model_key, category, description,
        )
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"部署失败：{e}"), 500
    return jsonify(code=0, message="已部署到模型管理", data={"modelId": m.id, "modelKey": m.model_key})
