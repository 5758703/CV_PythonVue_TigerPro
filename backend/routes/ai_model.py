"""AI 检测模型管理接口（/api/ai/model）。

提供模型元信息 CRUD、权重文件上传、分类查询、启用/停用。
"""
import json
import os
import shutil
import threading
import time
import uuid
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename

from extensions import db
from models import AiModel
from security import permission_required

ai_model_bp = Blueprint("ai_model", __name__, url_prefix="/api/ai/model")


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


# 可排序列白名单：前端列 prop(驼峰) -> 模型字段，防 SQL 注入
_SORT_COLUMNS = {
    "id": AiModel.id,
    "modelName": AiModel.model_name,
    "category": AiModel.category,
    "task": AiModel.task,
    "version": AiModel.version,
    "fileSize": AiModel.file_size,
    "status": AiModel.status,
    "createTime": AiModel.create_time,
}


@ai_model_bp.get("")
@permission_required("ai:model:list")
def list_models():
    page = int(request.args.get("pageNum", 1))
    size = int(request.args.get("pageSize", 10))
    name = request.args.get("modelName", "").strip()
    category = request.args.get("category", "").strip()
    task = request.args.get("task", "").strip()
    source = request.args.get("source", "").strip()  # 来源：huggingface / modelscope / other
    order_by = request.args.get("orderBy", "").strip()
    order_dir = request.args.get("orderDir", "").strip().lower()

    query = AiModel.query
    if name:
        query = query.filter(AiModel.model_name.like(f"%{name}%"))
    if category:
        query = query.filter(AiModel.category == category)
    if task:
        query = query.filter(AiModel.task == task)
    if source == "huggingface":
        query = query.filter(db.or_(AiModel.source_url.like("%huggingface%"),
                                    AiModel.source_url.like("%hf.co%")))
    elif source == "modelscope":
        query = query.filter(AiModel.source_url.like("%modelscope%"))
    elif source == "other":
        query = query.filter(db.and_(AiModel.source_url.notlike("%huggingface%"),
                                     AiModel.source_url.notlike("%hf.co%"),
                                     AiModel.source_url.notlike("%modelscope%")))
    total = query.count()
    # 列排序：前端列 prop(驼峰) -> 模型字段，白名单防注入；非法列回退 id
    col = _SORT_COLUMNS.get(order_by, AiModel.id)
    col = col.desc() if order_dir == "desc" else col.asc()
    rows = (query.order_by(col)
            .offset((page - 1) * size).limit(size).all())
    return jsonify(code=0, data={"rows": [m.to_dict() for m in rows], "total": total})


@ai_model_bp.get("/categories")
@permission_required("ai:model:list")
def list_categories():
    rows = db.session.query(AiModel.category).distinct().all()
    cats = [r[0] for r in rows if r[0]]
    return jsonify(code=0, data=cats)


@ai_model_bp.get("/tasks")
@permission_required("ai:model:list")
def list_tasks():
    """库内实际出现的任务 slug 去重列表，供任务查询下拉。"""
    rows = db.session.query(AiModel.task).distinct().all()
    tasks = [r[0] for r in rows if r[0]]
    return jsonify(code=0, data=tasks)


@ai_model_bp.get("/<int:mid>")
@permission_required("ai:model:query")
def get_model(mid):
    return jsonify(code=0, data=AiModel.query.get_or_404(mid).to_dict())


@ai_model_bp.post("/upload")
@permission_required("ai:model:add")
def upload_weight():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到文件"), 400

    ext = os.path.splitext(file.filename)[1].lower()
    allowed = current_app.config["MODEL_ALLOWED_EXT"]
    if ext not in allowed:
        return jsonify(code=400, message=f"不支持的文件类型，仅允许 {', '.join(sorted(allowed))}"), 400

    # 以模型标识作为子文件夹名；新增时可能还没标识，回退到临时名
    key = (request.form.get("modelKey") or "").strip()
    sub = secure_filename(key) or f"_unkeyed_{int(time.time())}"
    folder = os.path.join(current_app.config["MODEL_FOLDER"], sub)
    _ensure_dir(folder)
    base = secure_filename(os.path.splitext(file.filename)[0]) or "model"
    fname = f"{base}{ext}"
    abs_path = os.path.join(folder, fname)
    file.save(abs_path)
    rel_path = f"models/{sub}/{fname}"
    return jsonify(code=0, message="上传成功", data={
        "fileName": file.filename,
        "filePath": rel_path,
        "fileSize": os.path.getsize(abs_path),
    })


@ai_model_bp.post("")
@permission_required("ai:model:add")
def create_model():
    data = request.get_json(silent=True) or {}
    if not data.get("modelName"):
        return jsonify(code=400, message="模型名称必填"), 400
    key = (data.get("modelKey") or "").strip()
    if key and AiModel.query.filter_by(model_key=key).first():
        return jsonify(code=400, message="模型标识已存在"), 400

    m = AiModel(
        model_name=data["modelName"],
        category=data.get("category"),
        model_key=key or None,
        task=data.get("task", "object-detection"),
        library=data.get("library", "ultralytics"),
        version=data.get("version", "v1"),
        source_url=data.get("sourceUrl"),
        file_path=data.get("filePath"),
        file_size=data.get("fileSize", 0),
        description=data.get("description"),
        status=data.get("status", "0"),
    )
    db.session.add(m)
    db.session.commit()
    return jsonify(code=0, message="新增成功", data=m.to_dict()), 201


@ai_model_bp.put("/<int:mid>")
@permission_required("ai:model:edit")
def update_model(mid):
    m = AiModel.query.get_or_404(mid)
    data = request.get_json(silent=True) or {}
    key = data.get("modelKey")
    if key and key != m.model_key and AiModel.query.filter_by(model_key=key).first():
        return jsonify(code=400, message="模型标识已存在"), 400

    for field, attr in [("modelName", "model_name"), ("category", "category"),
                        ("modelKey", "model_key"), ("task", "task"),
                        ("library", "library"), ("version", "version"),
                        ("sourceUrl", "source_url"), ("filePath", "file_path"),
                        ("fileSize", "file_size"), ("description", "description"),
                        ("status", "status")]:
        if field in data:
            setattr(m, attr, data[field])
    db.session.commit()
    return jsonify(code=0, message="修改成功", data=m.to_dict())


def _remove_weight_file(m):
    """删除模型本地权重（单文件或 transformers 目录）。"""
    if not m.file_path:
        return
    abs_path = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    try:
        if os.path.isdir(abs_path):
            shutil.rmtree(abs_path, ignore_errors=True)
        elif os.path.isfile(abs_path):
            os.remove(abs_path)
            parent = os.path.dirname(abs_path)
            if os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
    except OSError:
        pass


@ai_model_bp.delete("/<int:mid>")
@permission_required("ai:model:remove")
def delete_model(mid):
    m = AiModel.query.get_or_404(mid)
    _remove_weight_file(m)
    db.session.delete(m)
    db.session.commit()
    return jsonify(code=0, message="删除成功")


@ai_model_bp.post("/batch-delete")
@permission_required("ai:model:remove")
def batch_delete():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify(code=400, message="未选择要删除的模型"), 400
    models = AiModel.query.filter(AiModel.id.in_(ids)).all()
    for m in models:
        _remove_weight_file(m)
        db.session.delete(m)
    db.session.commit()
    return jsonify(code=0, message=f"已删除 {len(models)} 个模型")


def _abs_weight(m):
    """单文件权重(YOLO)绝对路径；无则 None。

    file_path 指向单文件则直接用；指向目录（如整库下载的 pose 仓库）时，
    从目录内挑单文件权重(.pt 优先)，使 ultralytics 仍能加载。
    """
    if not m.file_path:
        return None
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    if os.path.isfile(p):
        return p
    if os.path.isdir(p):
        return _pick_local_weight(p)
    return None


def _abs_model_path(m):
    """模型本地路径（文件或目录均可，transformers 为目录）；无则 None。"""
    if not m.file_path:
        return None
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)
    return p if os.path.exists(p) else None


@ai_model_bp.get("/<int:mid>/download")
@permission_required("ai:model:download")
def download_weight(mid):
    """下载本地权重文件到浏览器（仅单文件权重，目录型 transformers 模型不支持）。"""
    m = AiModel.query.get_or_404(mid)
    abs_path = _abs_weight(m)
    if abs_path is None:
        if _abs_model_path(m):
            return jsonify(code=400, message="目录型模型(transformers)不支持单文件下载"), 400
        return jsonify(code=400, message="该模型暂无本地权重文件"), 400
    return send_file(abs_path, as_attachment=True,
                     download_name=os.path.basename(abs_path))


def _hub_of(url):
    """按来源 URL 主机名判定下载源：modelscope / roboflow / huggingface。"""
    host = urlparse(url or "").netloc.lower()
    if "modelscope" in host:
        return "modelscope"
    if "roboflow.com" in host:
        return "roboflow"
    return "huggingface"


def _roboflow_project_from_url(url):
    """解析 Roboflow Universe/App 链接 -> (workspace, project, version|None)。"""
    if "roboflow.com" not in urlparse(url or "").netloc.lower():
        return None
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) < 2:
        return None
    workspace, project = parts[0], parts[1]
    version = None
    if len(parts) >= 4 and parts[2] == "model":
        try:
            version = int(parts[3])
        except ValueError:
            pass
    return workspace, project, version


def _repo_id_from_url(url):
    """从来源链接解析 repo_id（owner/name）。

    HuggingFace: huggingface.co/{owner}/{name}
    ModelScope : modelscope.cn/models/{owner}/{name} —— 去掉前导 'models' 段。
    """
    if not url:
        return None
    parts = [p for p in urlparse(url).path.split("/") if p]
    if parts and parts[0] == "models":   # ModelScope 路径前缀
        parts = parts[1:]
    if len(parts) < 2:
        return None
    return f"{parts[0]}/{parts[1]}"


def _weight_hint_from_url(url):
    """来源链接锚点指定具体权重文件名（如 .../YOLO26#yolo26n.pt）。

    单仓多权重（官方 Ultralytics/YOLO26 含 n/s/m/l/x）时用于精确选权重；
    无锚点则返回 None，回退原有“最短文件名”挑选逻辑。
    """
    frag = urlparse(url or "").fragment.strip()
    return frag or None


_WEIGHT_EXT = (".pt", ".onnx", ".pth")


def _pick_local_weight(folder):
    """从已下载目录里挑单文件权重（优先 best.pt，其次 .pt > .pth > .onnx，再路径最短）。"""
    cands = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(_WEIGHT_EXT):
                cands.append(os.path.join(root, f))
    if not cands:
        return None

    def _rank(p):
        name = os.path.basename(p).lower()
        ext = os.path.splitext(name)[1]
        ext_rank = {".pt": 0, ".pth": 1, ".onnx": 2}.get(ext, 9)
        return (0 if name.endswith("best.pt") else 1, ext_rank, len(p))

    cands.sort(key=_rank)
    return cands[0]


def _is_valid_transformers_dir(path):
    """目录是否为可加载的 transformers 模型（config.json 含 model_type）。"""
    cfg_path = os.path.join(path, "config.json")
    if not os.path.isfile(cfg_path):
        return False
    try:
        with open(cfg_path, encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("model_type"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _looks_like_diffusers_lora_dir(path):
    """目录是否像 Diffusers/LoRA 文生图权重（非检测模型）。"""
    if not os.path.isdir(path):
        return False
    files = os.listdir(path)
    has_safetensors = any(f.lower().endswith(".safetensors") for f in files)
    if not has_safetensors or _is_valid_transformers_dir(path):
        return False
    if _pick_local_weight(path):
        return False
    readme = os.path.join(path, "README.md")
    if os.path.isfile(readme):
        try:
            text = open(readme, encoding="utf-8", errors="ignore").read().lower()
        except OSError:
            text = ""
        if any(k in text for k in ("diffusers", "lora", "text-to-image", "pipeline_tag")):
            return True
    return True


def _resolve_detect_runtime(m):
    """解析检测/视频检测应使用的推理库与权重路径；不可用则抛 ValueError。"""
    if not m.file_path:
        raise ValueError("该模型暂无本地权重，请先上传或拉取权重")
    lib = _detect_lib(m)
    base = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path)

    if os.path.isfile(base):
        if lib == "transformers":
            raise ValueError("transformers 检测模型应为目录，当前为单文件权重")
        return lib, base

    if os.path.isdir(base):
        if _looks_like_diffusers_lora_dir(base):
            raise ValueError(
                "该模型为 Diffusers/LoRA 文生图权重，不支持图片/视频目标检测。"
                "请改用 YOLO 等检测模型（例如 DaniilMako-spacecraft-detection）。"
            )
        if lib == "transformers":
            if _is_valid_transformers_dir(base):
                return lib, base
            yolo = _pick_local_weight(base)
            if yolo:
                return "ultralytics", yolo
            raise ValueError(
                "本地模型目录缺少有效的 transformers config.json（需含 model_type），"
                "且未找到 .pt/.onnx/.pth 检测权重。"
            )
        yolo = _pick_local_weight(base)
        if yolo:
            return lib if lib in ("rfdetr", "rtmlib") else "ultralytics", yolo
        raise ValueError("目录内未找到可用检测权重（.pt/.onnx/.pth）")

    raise ValueError("该模型暂无本地权重，请先上传或拉取权重")


def _fetch_huggingface(repo_id, folder, sub, is_dir_model, want=None):
    """从 HuggingFace 拉取权重，返回 (rel_path, size)。

    want：可选的目标权重文件名（来源链接锚点），单仓多权重时精确选取。
    """
    token = current_app.config.get("HF_TOKEN")  # 受限/私有仓库需令牌认证
    if is_dir_model:
        # 目录型模型(transformers/funasr 等) = 整个仓库目录（config + 权重 + tokenizer）
        from huggingface_hub import snapshot_download
        _ensure_dir(folder)
        snapshot_download(repo_id=repo_id, local_dir=folder, token=token)
        return f"models/{sub}", _dir_size(folder)
    # ultralytics：单文件权重(.pt/.onnx/.pth)
    from huggingface_hub import list_repo_files, hf_hub_download
    files = list_repo_files(repo_id, token=token)
    pts = [f for f in files if f.lower().endswith(_WEIGHT_EXT)]
    if not pts:
        raise ValueError("仓库内未找到权重文件(.pt/.onnx/.pth)")
    match = None
    if want:
        match = next((f for f in pts if os.path.basename(f).lower() == want.lower()), None)
        if match is None:
            raise ValueError(f"仓库内未找到指定权重文件：{want}")
    if match:
        filename = match
    else:
        pts.sort(key=lambda f: (not f.lower().endswith("best.pt"), len(f)))
        filename = pts[0]
    cached = hf_hub_download(repo_id=repo_id, filename=filename, token=token)
    _ensure_dir(folder)
    dest_name = os.path.basename(filename)
    shutil.copy2(cached, os.path.join(folder, dest_name))
    return f"models/{sub}/{dest_name}", os.path.getsize(os.path.join(folder, dest_name))


def _fetch_modelscope(repo_id, folder, sub, is_dir_model):
    """从 ModelScope（模搭社区）拉取权重，返回 (rel_path, size)。

    ModelScope 仅作下载源：整库 snapshot 到本地，产物仍走现有 transformers/ultralytics 推理。
    """
    from modelscope import snapshot_download as ms_snapshot
    token = current_app.config.get("MODELSCOPE_TOKEN")
    if token:
        try:
            from modelscope.hub.api import HubApi
            HubApi().login(token)
        except Exception:  # noqa: BLE001  登录失败不阻断公开模型
            pass
    _ensure_dir(folder)
    ms_snapshot(repo_id, local_dir=folder)
    if is_dir_model:
        return f"models/{sub}", _dir_size(folder)
    wp = _pick_local_weight(folder)
    if wp is None:
        raise ValueError("仓库内未找到权重文件(.pt/.onnx/.pth)")
    rel = os.path.relpath(wp, current_app.config["UPLOAD_FOLDER"]).replace(os.sep, "/")
    return rel, os.path.getsize(wp)


def _fetch_rfdetr_weight(folder, sub, model_key):
    """拉取 RF-DETR 官方预训练 .pth（Roboflow CDN，与 HF 模型对应）。"""
    from inference import rfdetr_weight_filename
    from rfdetr.assets.model_weights import download_pretrain_weights
    fname = rfdetr_weight_filename(model_key)
    _ensure_dir(folder)
    dest = os.path.join(folder, fname)
    download_pretrain_weights(dest)
    if not os.path.isfile(dest):
        raise ValueError(f"RF-DETR 权重下载失败：{fname}")
    return f"models/{sub}/{fname}", os.path.getsize(dest)


MOBILESAM_WEIGHT_URL = (
    "https://github.com/ChaoningZhang/MobileSAM/raw/master/weights/mobile_sam.pt"
)


def _fetch_mobilesam_weight(folder, sub):
    """拉取 MobileSAM 官方 mobile_sam.pt（GitHub）。"""
    return _fetch_direct_weight(MOBILESAM_WEIGHT_URL, folder, sub, fname="mobile_sam.pt")


def _fetch_direct_weight(url, folder, sub, fname=None):
    """从直链下载单文件权重（.pt/.onnx/.pth），如 GitHub Release。"""
    import requests
    if not url:
        raise ValueError("缺少下载地址")
    name = fname or os.path.basename(urlparse(url).path) or "weight.pt"
    name = secure_filename(name) or "weight.pt"
    _ensure_dir(folder)
    dest = os.path.join(folder, name)
    resp = requests.get(url, stream=True, timeout=600, allow_redirects=True)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    if not os.path.isfile(dest) or os.path.getsize(dest) < 1024:
        raise ValueError(f"权重下载失败或文件过小：{url}")
    return f"models/{sub}/{name}", os.path.getsize(dest)


def _is_direct_weight_url(url):
    path = (urlparse(url or "").path or "").lower()
    return path.endswith((".pt", ".onnx", ".pth"))


def _roboflow_inference_model_id(api_key, workspace, project, version_num):
    """从 Roboflow 项目 API 解析 Inference 用的 model_id（如 rocket-detect/2）。"""
    import requests
    ver = version_num or 2
    r = requests.get(
        f"https://api.roboflow.com/{workspace}/{project}/{ver}",
        params={"api_key": api_key},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    model = (data.get("version") or {}).get("model") or {}
    mid = model.get("id")
    if mid:
        return mid
    return f"{project}/{ver}"


def _fetch_roboflow(source_url, folder, sub):
    """从 Roboflow Universe 拉取推理权重（ONNX），返回 (rel_path, size)。

    Universe 公开模型不支持 ptFile 直链下载，需走 Inference ORT 接口获取签名权重 URL。
    """
    import requests
    api_key = current_app.config.get("ROBOFLOW_API_KEY")
    if not api_key:
        raise ValueError(
            "请在后端 .env 配置 ROBOFLOW_API_KEY（https://app.roboflow.com/settings/api）后重启服务"
        )
    parsed = _roboflow_project_from_url(source_url)
    if not parsed:
        raise ValueError("无效的 Roboflow 来源地址，示例："
                         "https://universe.roboflow.com/nasaspaceflight/rocket-detect/model/2")
    workspace, project, version_num = parsed
    model_id = _roboflow_inference_model_id(api_key, workspace, project, version_num)
    ort_resp = requests.get(
        f"https://api.roboflow.com/serverless/ort/{model_id}",
        params={
            "api_key": api_key,
            "device": "tigerpro-fetch",
            "dynamic": "true",
            "nocache": "true",
        },
        timeout=60,
    )
    ort_resp.raise_for_status()
    ort = (ort_resp.json() or {}).get("ort") or {}
    weights_url = ort.get("model")
    if not weights_url:
        raise ValueError(f"Roboflow 未返回可下载权重（model_id={model_id}）")
    classes = ort.get("classes") or ["Engine Flames", "Rocket Body", "Space"]
    _ensure_dir(folder)
    url_lower = weights_url.lower()
    fname = "best.onnx" if ".onnx" in url_lower else "best.pt"
    dest = os.path.join(folder, fname)
    resp = requests.get(weights_url, stream=True, timeout=600)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    if not os.path.isfile(dest) or os.path.getsize(dest) < 1024:
        raise ValueError("Roboflow 权重下载失败：文件无效或过小")
    from inference import save_roboflow_meta
    save_roboflow_meta(folder, model_id, classes=classes)
    total_size = os.path.getsize(dest) + os.path.getsize(os.path.join(folder, "roboflow_meta.json"))
    return f"models/{sub}/{fname}", total_size


def _fetch_insightface_weight(m):
    """拉取 InsightFace buffalo 套件到 uploads/insightface/models/<pack>。"""
    from inference import ensure_insightface_pack

    pack = (m.version or "").strip().lower()
    if not pack.startswith("buffalo"):
        key = (m.model_key or "").lower()
        pack = "buffalo_l" if ("buffalo_l" in key or "buffalo-l" in key) else "buffalo_s"
    root = os.path.join(current_app.config["UPLOAD_FOLDER"], "insightface")
    _pack_dir, size = ensure_insightface_pack(root, pack)
    # file_path 指向 insightface root；pack 名存在 version
    if (m.version or "").strip().lower() != pack:
        m.version = pack
    return "insightface", size


def _fetch_rtmlib_weight(folder, sub, model_key):
    """拉取 rtmlib ONNX SDK（RTMO 单文件；RTMPose/DWPose 写 manifest 并预热）。"""
    import requests
    from inference import (
        extract_rtmlib_onnx_from_zip,
        rtmlib_variant,
        rtmlib_weight_url,
        write_rtmlib_manifest,
        _get_rtmlib_solver,
    )
    key = (model_key or "rtmo-s").lower()
    variant, _ = rtmlib_variant(key)
    _ensure_dir(folder)

    url = rtmlib_weight_url(key)
    fname = os.path.basename(url.split("?")[0])
    dest = os.path.join(folder, fname)
    if not os.path.isfile(dest) or os.path.getsize(dest) < 1024 * 100:
        resp = requests.get(url, stream=True, timeout=600)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    if not os.path.isfile(dest) or os.path.getsize(dest) < 1024 * 100:
        raise ValueError("rtmlib 权重下载失败")

    if variant == "rtmo":
        onnx_path = extract_rtmlib_onnx_from_zip(dest)
        onnx_fname = os.path.basename(onnx_path)
        return f"models/{sub}/{onnx_fname}", os.path.getsize(onnx_path)

    extract_rtmlib_onnx_from_zip(dest)
    manifest = write_rtmlib_manifest(folder, key)
    _get_rtmlib_solver(key, manifest)
    return f"models/{sub}/rtmlib_manifest.json", os.path.getsize(manifest)


def _detect_lib(m):
    return (m.library or "ultralytics").lower()


def _detect_model_path(m):
    """目标检测模型本地路径（ultralytics/rfdetr 单文件，transformers 目录）。"""
    lib = _detect_lib(m)
    if lib == "transformers":
        return _abs_model_path(m)
    return _abs_weight(m)


@ai_model_bp.post("/<int:mid>/fetch")
@permission_required("ai:model:add")
def fetch_weight(mid):
    """从模型来源拉取权重到服务器（按来源 URL 自动分流 HuggingFace / ModelScope / Roboflow）。"""
    m = AiModel.query.get_or_404(mid)
    lib = _detect_lib(m)
    sub = secure_filename(m.model_key or f"model{m.id}")
    folder = os.path.join(current_app.config["MODEL_FOLDER"], sub)
    try:
        if lib == "mobilesam":
            rel, size = _fetch_mobilesam_weight(folder, sub)
        elif lib == "rfdetr":
            rel, size = _fetch_rfdetr_weight(folder, sub, m.model_key)
        elif lib == "rtmlib":
            rel, size = _fetch_rtmlib_weight(folder, sub, m.model_key)
        elif lib == "insightface":
            rel, size = _fetch_insightface_weight(m)
        elif _is_direct_weight_url(m.source_url):
            rel, size = _fetch_direct_weight(m.source_url, folder, sub)
        else:
            hub = _hub_of(m.source_url)
            if hub == "roboflow":
                rel, size = _fetch_roboflow(m.source_url, folder, sub)
            else:
                repo_id = _repo_id_from_url(m.source_url)
                if repo_id is None:
                    return jsonify(code=400, message="来源地址无效，无法解析模型仓库(owner/name)"), 400
                if hub == "modelscope":
                    is_dir_model = lib != "ultralytics"
                    rel, size = _fetch_modelscope(repo_id, folder, sub, is_dir_model)
                else:
                    is_dir_model = lib != "ultralytics"
                    rel, size = _fetch_huggingface(
                        repo_id, folder, sub, is_dir_model, want=_weight_hint_from_url(m.source_url))
    except Exception as e:  # noqa: BLE001  网络/仓库错误统一回传
        msg = str(e)
        low = msg.lower()
        hub = _hub_of(m.source_url or "")
        if hub == "roboflow":
            if "404" in msg or "not found" in low:
                return jsonify(code=400, message=f"拉取失败：Roboflow 模型不存在或版本无效，请核对来源链接。{msg}"), 400
            if "401" in msg or "403" in msg or "not authorized" in low:
                return jsonify(code=403, message="拉取失败：Roboflow API Key 无效或无权限，请检查 .env 中 ROBOFLOW_API_KEY。"), 403
            return jsonify(code=500, message=f"拉取失败：{e}"), 500
        if "404" in msg or "not found" in low or "repositorynotfound" in low or "does not exist" in low:
            return jsonify(code=400, message="拉取失败：仓库不存在或来源地址有误，请核对模型链接(owner/name)"), 400
        if "401" in msg or "403" in msg or "gated" in low or "restricted" in low:
            hub = _hub_of(m.source_url or "")
            if hub == "roboflow":
                hint = ("Roboflow 认证失败，请检查 .env 中 ROBOFLOW_API_KEY 是否有效，"
                        "并在 https://app.roboflow.com/settings/api 获取。")
            elif hub == "modelscope":
                hint = ("该模型为受限/私有仓库，需先在 ModelScope 模型页申请访问权限，"
                        "再在后端 .env 配置 MODELSCOPE_TOKEN=<你的令牌> 并重启。")
            else:
                hint = ("该模型为受限(gated)/私有仓库，需先在 HuggingFace 模型页申请并获批访问权限，"
                        "再在后端 .env 配置 HF_TOKEN=<你的HF令牌> 并重启。")
            return jsonify(code=403, message=f"拉取失败：{hint}"), 403
        return jsonify(code=500, message=f"拉取失败：{e}"), 500

    m.file_path = rel
    m.file_size = size
    db.session.commit()
    return jsonify(code=0, message="权重拉取成功", data=m.to_dict())


@ai_model_bp.post("/<int:mid>/analyze-text")
@permission_required("ai:model:query")
def analyze_text(mid):
    """文本任务在线测试（transformers，如 FinBERT 情感分析）。"""
    m = AiModel.query.get_or_404(mid)
    path = _abs_model_path(m)
    if path is None:
        return jsonify(code=400, message="该模型暂无本地权重，请先拉取"), 400

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(code=400, message="请输入待分析文本"), 400

    try:
        from inference import classify_text
        result = classify_text(path, text, task=m.task or "text-classification")
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"分析失败：{e}"), 500
    return jsonify(code=0, message="分析完成", data=result)


@ai_model_bp.post("/<int:mid>/classify-image")
@permission_required("ai:model:query")
def classify_image_route(mid):
    """图像分类在线测试（transformers，如 ViT/ResNet）。"""
    m = AiModel.query.get_or_404(mid)
    path = _abs_model_path(m)
    if path is None:
        return jsonify(code=400, message="该模型暂无本地权重，请先拉取"), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400
    try:
        top_k = int(request.form.get("topK", 5))
    except (TypeError, ValueError):
        top_k = 5

    try:
        from inference import classify_image
        result = classify_image(path, file.read(), task=m.task or "image-classification", top_k=top_k)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"分类失败：{e}"), 500
    return jsonify(code=0, message="分类完成", data=result)


@ai_model_bp.post("/<int:mid>/ocr")
@permission_required("ai:model:query")
def ocr_route(mid):
    """文字识别（GOT-OCR2）：上传图片 -> 识别文本。"""
    m = AiModel.query.get_or_404(mid)
    if (m.task or "") != "ocr":
        return jsonify(code=400, message="文字识别仅支持 OCR 模型"), 400
    path = _abs_model_path(m)
    if path is None:
        return jsonify(code=400, message="该模型暂无本地权重，请先上传或拉取权重"), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400
    formatted = request.form.get("formatted", "0") == "1"

    try:
        from inference import recognize_text
        result = recognize_text(path, file.read(), formatted=formatted)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"文字识别失败：{e}"), 500
    return jsonify(code=0, message="识别完成", data=result)


@ai_model_bp.post("/ocr-paddle")
@permission_required("ai:model:query")
def ocr_paddle_route():
    """PaddleOCR（RapidOCR）：检测模型 + 识别模型 + 图片 -> 文本 + 框。"""
    try:
        det_id = int(request.form.get("detId", 0))
        rec_id = int(request.form.get("recId", 0))
    except (TypeError, ValueError):
        return jsonify(code=400, message="缺少检测/识别模型"), 400
    det_m = AiModel.query.get(det_id)
    rec_m = AiModel.query.get(rec_id)
    if det_m is None or rec_m is None or (det_m.library or "") != "rapidocr" or (rec_m.library or "") != "rapidocr":
        return jsonify(code=400, message="请选择 RapidOCR 检测与识别模型"), 400
    det_dir = _abs_model_path(det_m)
    rec_dir = _abs_model_path(rec_m)
    if det_dir is None or rec_dir is None:
        return jsonify(code=400, message="检测/识别模型暂无本地权重，请先拉取"), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400

    try:
        from inference import paddle_ocr
        result = paddle_ocr(det_dir, rec_dir, file.read())
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"PaddleOCR 识别失败：{e}"), 500
    return jsonify(code=0, message="识别完成", data=result)


@ai_model_bp.post("/<int:mid>/transcribe")
@permission_required("ai:model:query")
def transcribe_route(mid):
    """语音识别在线测试（funasr SenseVoice）：上传音频 → 转写 + 情感/事件。"""
    m = AiModel.query.get_or_404(mid)
    path = _abs_model_path(m)
    if path is None:
        return jsonify(code=400, message="该模型暂无本地权重，请先拉取"), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到音频"), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["AUDIO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的音频格式"), 400

    audio_folder = current_app.config["AUDIO_FOLDER"]
    _ensure_dir(audio_folder)
    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "audio"
    audio_path = os.path.join(audio_folder, f"{base}_{ts}{ext}")
    file.save(audio_path)

    try:
        if (m.library or "") == "funasr-onnx":
            from inference import transcribe_audio_onnx
            result = transcribe_audio_onnx(path, audio_path)
        elif (m.library or "") == "funasr-nano":
            from inference import transcribe_audio_nano
            lang = (request.form.get("language") or "auto").strip()
            result = transcribe_audio_nano(path, audio_path, language=lang)
        elif (m.library or "") == "transformers":
            from inference import transcribe_audio_whisper
            result = transcribe_audio_whisper(path, audio_path)
        else:
            from inference import transcribe_audio
            result = transcribe_audio(path, audio_path)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"识别失败：{e}"), 500
    finally:
        if os.path.isfile(audio_path):
            try:
                os.remove(audio_path)  # 处理完删除上传源
            except OSError:
                pass
    return jsonify(code=0, message="识别完成", data=result)


@ai_model_bp.get("/<int:mid>/tts-speakers")
@permission_required("ai:model:query")
def tts_speakers_route(mid):
    """文本转语音可用音色列表（VibeVoice 等有预置音色；transformers TTS 无）。"""
    m = AiModel.query.get_or_404(mid)
    if (m.library or "") == "vibevoice":
        from inference import list_vibevoice_voices
        return jsonify(code=0, data=list_vibevoice_voices())
    return jsonify(code=0, data=[])


@ai_model_bp.post("/<int:mid>/tts")
@permission_required("ai:model:query")
def tts_route(mid):
    """文本转语音在线测试：文本 -> wav(base64)。

    transformers(VITS/MMS-TTS) 单音色；VibeVoice 等按预置音色合成。
    """
    m = AiModel.query.get_or_404(mid)
    path = _abs_model_path(m)
    if path is None:
        return jsonify(code=400, message="该模型暂无本地权重，请先拉取"), 400

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    speaker = (data.get("speaker") or "中文女").strip()
    if not text:
        return jsonify(code=400, message="请输入待合成文本"), 400

    try:
        if (m.library or "") == "vibevoice":
            from inference import synthesize_speech_vibevoice
            result = synthesize_speech_vibevoice(path, text, speaker=speaker)
        elif (m.library or "") == "sherpa-onnx":
            from inference import synthesize_speech_melotts
            result = synthesize_speech_melotts(path, text)
        elif (m.library or "") == "voxcpm":
            from inference import synthesize_speech_voxcpm
            result = synthesize_speech_voxcpm(path, text)
        else:
            from inference import synthesize_speech_hf
            result = synthesize_speech_hf(path, text, task=m.task or "text-to-speech")
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"合成失败：{e}"), 500
    return jsonify(code=0, message="合成完成", data=result)


@ai_model_bp.post("/<int:mid>/tts-clone")
@permission_required("ai:model:query")
def tts_clone_route(mid):
    """零样本音色克隆（VoxCPM）：参考音频 + 参考文本 + 目标文本 -> wav(base64)。"""
    m = AiModel.query.get_or_404(mid)
    if (m.library or "") != "voxcpm":
        return jsonify(code=400, message="该模型不支持音色克隆"), 400
    path = _abs_model_path(m)
    if path is None:
        return jsonify(code=400, message="该模型暂无本地权重，请先拉取"), 400

    text = (request.form.get("text") or "").strip()
    prompt_text = (request.form.get("promptText") or "").strip()
    if not text or not prompt_text:
        return jsonify(code=400, message="请输入目标文本与参考音频文本"), 400

    file = request.files.get("promptAudio")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到参考音频"), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["AUDIO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的音频格式"), 400

    audio_folder = current_app.config["AUDIO_FOLDER"]
    _ensure_dir(audio_folder)
    ts = int(time.time())
    prompt_path = os.path.join(audio_folder, f"prompt_{ts}{ext}")
    file.save(prompt_path)

    try:
        from inference import synthesize_speech_voxcpm_clone
        result = synthesize_speech_voxcpm_clone(path, text, prompt_text, prompt_path)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"合成失败：{e}"), 500
    finally:
        if os.path.isfile(prompt_path):
            try:
                os.remove(prompt_path)
            except OSError:
                pass
    return jsonify(code=0, message="合成完成", data=result)


def _text_model_path(mid):
    """取文本任务模型本地目录；返回 (model, path, error_response)。"""
    m = AiModel.query.get_or_404(mid)
    path = _abs_model_path(m)
    if path is None:
        return m, None, (jsonify(code=400, message="该模型暂无本地权重，请先拉取"), 400)
    return m, path, None


@ai_model_bp.post("/<int:mid>/generate-text")
@permission_required("ai:model:query")
def generate_text_route(mid):
    """文本生成/翻译/摘要（transformers）。"""
    m, path, err = _text_model_path(mid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(code=400, message="请输入文本"), 400
    try:
        max_new = int(data.get("maxNewTokens", 256))
    except (TypeError, ValueError):
        max_new = 256
    try:
        from inference import generate_text
        result = generate_text(path, text, task=m.task or "summarization", max_new_tokens=max_new)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"生成失败：{e}"), 500
    return jsonify(code=0, message="完成", data=result)


@ai_model_bp.post("/<int:mid>/zero-shot")
@permission_required("ai:model:query")
def zero_shot_route(mid):
    """零样本分类（transformers）。"""
    m, path, err = _text_model_path(mid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    labels = [l.strip() for l in (data.get("labels") or []) if l and l.strip()]
    if not text or not labels:
        return jsonify(code=400, message="请输入文本与候选标签"), 400
    try:
        from inference import zero_shot
        result = zero_shot(path, text, labels, task=m.task or "zero-shot-classification")
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"分类失败：{e}"), 500
    return jsonify(code=0, message="完成", data=result)


@ai_model_bp.post("/<int:mid>/fill-mask")
@permission_required("ai:model:query")
def fill_mask_route(mid):
    """完形填空（transformers）。"""
    m, path, err = _text_model_path(mid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(code=400, message="请输入含 [MASK] 的文本"), 400
    try:
        top_k = int(data.get("topK", 5))
    except (TypeError, ValueError):
        top_k = 5
    try:
        from inference import fill_mask
        result = fill_mask(path, text, task=m.task or "fill-mask", top_k=top_k)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"预测失败：{e}"), 500
    return jsonify(code=0, message="完成", data=result)


@ai_model_bp.post("/<int:mid>/extract-entities")
@permission_required("ai:model:query")
def extract_entities_route(mid):
    """命名实体识别 NER（transformers）。"""
    m, path, err = _text_model_path(mid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(code=400, message="请输入文本"), 400
    try:
        from inference import extract_entities
        result = extract_entities(path, text, task=m.task or "token-classification")
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"识别失败：{e}"), 500
    return jsonify(code=0, message="完成", data=result)


@ai_model_bp.post("/<int:mid>/answer-question")
@permission_required("ai:model:query")
def answer_question_route(mid):
    """抽取式问答 QA（transformers）。"""
    m, path, err = _text_model_path(mid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    context = (data.get("context") or "").strip()
    if not question or not context:
        return jsonify(code=400, message="请输入问题与上下文"), 400
    try:
        from inference import answer_question
        result = answer_question(path, question, context, task=m.task or "question-answering")
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"问答失败：{e}"), 500
    return jsonify(code=0, message="完成", data=result)


@ai_model_bp.post("/<int:mid>/detect")
@permission_required("ai:model:query")
def detect(mid):
    """在线测试：用模型权重对上传图片做检测（YOLO 或 transformers）。"""
    m = AiModel.query.get_or_404(mid)
    try:
        lib, abs_path = _resolve_detect_runtime(m)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400

    try:
        conf = float(request.form.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25

    draw = request.form.get("draw", "1") != "0"  # 实时场景传 0，省服务端画框/编码
    try:
        if lib == "transformers":
            from inference import detect_image_hf
            result = detect_image_hf(abs_path, file.read(), conf=conf, draw=draw,
                                     task=m.task or "object-detection")
        elif lib == "rfdetr":
            from inference import detect_image_rfdetr
            result = detect_image_rfdetr(abs_path, file.read(), conf=conf, draw=draw,
                                         model_key=m.model_key or "rf-detr-medium")
        else:
            from inference import detect_image
            result = detect_image(abs_path, file.read(), conf=conf, draw=draw)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"推理失败：{e}"), 500
    return jsonify(code=0, message="检测完成", data=result)


def _is_pose_task(task):
    t = (task or "").lower()
    return t in ("pose-estimation", "wholebody-pose-estimation")


def _resolve_pose_runtime(m):
    """解析姿态估计运行时：(library, abs_path, task)。"""
    task = (m.task or "").lower()
    if not _is_pose_task(task):
        raise ValueError("该模型任务不是姿态估计类型")
    lib = _detect_lib(m)
    if lib == "ultralytics":
        if task != "pose-estimation":
            raise ValueError("全身姿态模型须使用 rtmlib（DWPose）")
        path = _abs_weight(m)
        if path is None:
            raise ValueError("该模型暂无本地权重，请先上传或拉取权重")
        return lib, path, task
    if lib == "rtmlib":
        key = (m.model_key or "").lower()
        if not key.startswith(("rtmo", "rtmpose", "dwpose")):
            raise ValueError("rtmlib 姿态 model_key 须为 rtmo-* / rtmpose-* / dwpose-*")
        path = _abs_model_path(m)
        return lib, path, task
    raise ValueError(f"姿态估计不支持 library={lib}")


@ai_model_bp.post("/<int:mid>/pose")
@permission_required("ai:model:query")
def pose_route(mid):
    """姿态估计（图片）：上传图片 -> 关键点 + 骨架图(base64)。"""
    m = AiModel.query.get_or_404(mid)
    try:
        lib, abs_path, task = _resolve_pose_runtime(m)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400
    try:
        conf = float(request.form.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25
    draw = request.form.get("draw", "1") != "0"

    try:
        if lib == "rtmlib":
            from inference import estimate_pose_rtmlib
            result = estimate_pose_rtmlib(
                m.model_key or "rtmo-s", abs_path, file.read(), conf=conf, draw=draw)
        else:
            from inference import estimate_pose
            result = estimate_pose(abs_path, file.read(), conf=conf, draw=draw)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"姿态估计失败：{e}"), 500
    return jsonify(code=0, message="姿态估计完成", data=result)


@ai_model_bp.post("/<int:mid>/segment")
@permission_required("ai:model:query")
def segment_route(mid):
    """实例/交互分割：RF-DETR-Seg / Ultralytics(YOLOE) / MobileSAM。"""
    m = AiModel.query.get_or_404(mid)
    lib = _detect_lib(m)
    task = (m.task or "").lower()
    if task not in ("instance-segmentation", "interactive-segmentation"):
        return jsonify(code=400, message="该模型任务不是分割类型"), 400
    abs_path = _detect_model_path(m)
    if abs_path is None:
        return jsonify(code=400, message="该模型暂无本地权重，请先上传或拉取权重"), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400

    try:
        conf = float(request.form.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25
    draw = request.form.get("draw", "1") != "0"

    try:
        if lib == "rfdetr":
            from inference import segment_image_rfdetr
            result = segment_image_rfdetr(abs_path, file.read(), conf=conf, draw=draw,
                                          model_key=m.model_key or "rf-detr-seg-medium")
        elif lib == "ultralytics":
            from inference import segment_image_ultralytics
            result = segment_image_ultralytics(
                abs_path, file.read(), conf=conf, draw=draw,
                classes=request.form.get("classes"),
            )
        elif lib == "mobilesam":
            import json
            from inference import segment_image_mobilesam
            mode = (request.form.get("mode") or "prompt").strip().lower()
            points = point_labels = box = None
            raw_pts = request.form.get("points")
            raw_lbl = request.form.get("pointLabels")
            raw_box = request.form.get("box")
            if raw_pts:
                points = json.loads(raw_pts)
            if raw_lbl:
                point_labels = json.loads(raw_lbl)
            if raw_box:
                box = json.loads(raw_box)
            result = segment_image_mobilesam(
                abs_path, file.read(), points=points, point_labels=point_labels,
                box=box, mode=mode, draw=draw)
        else:
            return jsonify(code=400, message="分割仅支持 rfdetr、ultralytics 或 mobilesam 引擎"), 400
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"分割失败：{e}"), 500
    return jsonify(code=0, message="分割完成", data=result)


def _segment_worker(job_id, abs_path, src_path, out_path, out_name, conf, model_key,
                    lib="rfdetr", classes=None):
    """后台线程：RF-DETR-Seg / Ultralytics 逐帧视频分割。"""
    def cb(processed, total):
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j["processed"] = processed
                j["total"] = total
    try:
        if lib == "ultralytics":
            from inference import segment_video_ultralytics
            stats = segment_video_ultralytics(
                abs_path, src_path, out_path, conf=conf, classes=classes, progress_cb=cb)
        else:
            from inference import segment_video_rfdetr
            stats = segment_video_rfdetr(abs_path, src_path, out_path, conf=conf,
                                         model_key=model_key or "rf-detr-seg-medium", progress_cb=cb)
        stats["output"] = out_name
        with _video_jobs_lock:
            _video_jobs[job_id].update(status="done", stats=stats,
                                       processed=stats["frames"], total=stats["frames"])
    except Exception as e:  # noqa: BLE001
        with _video_jobs_lock:
            _video_jobs[job_id].update(status="error", error=str(e))
    finally:
        if os.path.isfile(src_path):
            try:
                os.remove(src_path)
            except OSError:
                pass


@ai_model_bp.post("/<int:mid>/segment-video")
@permission_required("ai:model:query")
def segment_video_route(mid):
    """实例分割视频：RF-DETR-Seg 或 Ultralytics(YOLOE)，异步任务。"""
    m = AiModel.query.get_or_404(mid)
    lib = _detect_lib(m)
    if (m.task or "") != "instance-segmentation" or lib not in ("rfdetr", "ultralytics"):
        return jsonify(code=400, message="视频分割仅支持 RF-DETR-Seg 或 Ultralytics 实例分割模型"), 400
    abs_path = _detect_model_path(m)
    if abs_path is None:
        return jsonify(code=400, message="该模型暂无本地权重，请先上传或拉取权重"), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到视频"), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的视频格式"), 400

    try:
        conf = float(request.form.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25
    classes = request.form.get("classes")

    video_folder = current_app.config["VIDEO_FOLDER"]
    out_folder = current_app.config["OUTPUT_FOLDER"]
    _ensure_dir(video_folder)
    _ensure_dir(out_folder)

    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "video"
    src_path = os.path.join(video_folder, f"{base}_{ts}{ext}")
    out_name = f"{base}_{ts}_seg.mp4"
    out_path = os.path.join(out_folder, out_name)
    file.save(src_path)

    job_id = uuid.uuid4().hex
    with _video_jobs_lock:
        _video_jobs[job_id] = {"status": "running", "processed": 0, "total": 0,
                               "stats": None, "error": None}
    threading.Thread(
        target=_segment_worker,
        args=(job_id, abs_path, src_path, out_path, out_name, conf, m.model_key or "", lib, classes),
        daemon=True,
    ).start()
    return jsonify(code=0, message="任务已启动", data={"jobId": job_id})


@ai_model_bp.post("/<int:mid>/analyze-report")
@permission_required("ai:model:query")
def analyze_report(mid):
    """对已完成的图片检测结果做 DeepSeek AI 分析，生成正式检测报告。"""
    m = AiModel.query.get_or_404(mid)
    data = request.get_json(silent=True) or {}
    detections = data.get("detections")
    if not isinstance(detections, list):
        return jsonify(code=400, message="缺少检测结果 detections"), 400

    try:
        conf = float(data.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25

    try:
        from report import build_report
        result = build_report(
            model_name=m.model_name,
            model_category=m.category,
            detections=detections,
            width=data.get("width"),
            height=data.get("height"),
            conf=conf,
            image_name=data.get("imageName") or "未命名图片",
        )
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"报告生成失败：{e}"), 500
    return jsonify(code=0, message="报告生成完成", data=result)


# 视频检测异步任务进度表：jobId -> {status, processed, total, output, stats, error}
_video_jobs = {}
_video_jobs_lock = threading.Lock()


def _video_worker(
    job_id,
    library,
    task,
    abs_path,
    src_path,
    out_path,
    out_name,
    conf,
    model_key="",
    alert_rules_payload=None,
):
    """后台线程：逐帧检测，按帧上报进度，完成写结果。"""
    def cb(processed, total):
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j["processed"] = processed
                j["total"] = total
    try:
        lib = (library or "ultralytics").lower()
        if lib == "transformers":
            from inference import detect_video_hf
            stats = detect_video_hf(abs_path, src_path, out_path, conf=conf, task=task, progress_cb=cb,
                                    alert_rules=alert_rules_payload, alert_source_key=job_id)
        elif lib == "rfdetr":
            from inference import detect_video_rfdetr
            stats = detect_video_rfdetr(abs_path, src_path, out_path, conf=conf,
                                        model_key=model_key, progress_cb=cb,
                                        alert_rules=alert_rules_payload, alert_source_key=job_id)
        else:
            from inference import detect_video
            stats = detect_video(abs_path, src_path, out_path, conf=conf,
                                 progress_cb=cb, model_key=model_key,
                                 alert_rules=alert_rules_payload,
                                 alert_source_key=job_id)
        stats["output"] = out_name
        with _video_jobs_lock:
            _video_jobs[job_id].update(status="done", stats=stats,
                                       processed=stats["frames"], total=stats["frames"])
    except Exception as e:  # noqa: BLE001
        with _video_jobs_lock:
            _video_jobs[job_id].update(status="error", error=str(e))
    finally:
        if os.path.isfile(src_path):
            try:
                os.remove(src_path)  # 处理完删除上传源
            except OSError:
                pass


@ai_model_bp.post("/<int:mid>/detect-video")
@permission_required("ai:model:query")
def detect_video_route(mid):
    """视频检测：启动异步逐帧任务，立即返回 jobId（前端轮询进度）。"""
    m = AiModel.query.get_or_404(mid)
    try:
        lib, abs_path = _resolve_detect_runtime(m)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到视频"), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的视频格式"), 400

    try:
        conf = float(request.form.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25

    alert_enabled = str(request.form.get("alertEnabled", "0")).strip().lower() in ("1", "true", "on", "yes")
    rules_payload = None
    if alert_enabled:
        from services.alert_rules_query import (
            load_enabled_alert_rules,
            parse_rule_keys,
            serialize_alert_rules_payload,
        )
        # alertRuleKeys: JSON 数组；未传则全部启用规则
        raw_keys = request.form.get("alertRuleKeys")
        if raw_keys is None or str(raw_keys).strip() == "":
            rule_keys = None
        else:
            rule_keys = parse_rule_keys(raw_keys)
        enabled_rules = load_enabled_alert_rules(rule_keys)
        if not enabled_rules:
            return jsonify(
                code=400,
                message="当前没有启用中的告警规则；请到「检测告警」页启用至少一条规则",
            ), 400
        rules_payload = serialize_alert_rules_payload(enabled_rules)

    video_folder = current_app.config["VIDEO_FOLDER"]
    out_folder = current_app.config["OUTPUT_FOLDER"]
    _ensure_dir(video_folder)
    _ensure_dir(out_folder)

    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "video"
    src_path = os.path.join(video_folder, f"{base}_{ts}{ext}")
    out_name = f"{base}_{ts}_det.mp4"
    out_path = os.path.join(out_folder, out_name)
    file.save(src_path)

    job_id = uuid.uuid4().hex
    with _video_jobs_lock:
        _video_jobs[job_id] = {"status": "running", "processed": 0, "total": 0,
                               "stats": None, "error": None}
    threading.Thread(
        target=_video_worker,
        args=(job_id, lib, m.task or "object-detection", abs_path, src_path, out_path, out_name, conf,
              m.model_key or "", rules_payload),
        daemon=True,
    ).start()
    return jsonify(code=0, message="任务已启动", data={"jobId": job_id})


@ai_model_bp.get("/<int:mid>/video-progress/<job_id>")
@permission_required("ai:model:query")
def video_progress(mid, job_id):
    """查询视频检测任务进度。"""
    with _video_jobs_lock:
        j = _video_jobs.get(job_id)
        if j is None:
            return jsonify(code=404, message="任务不存在或已过期"), 404
        data = dict(j)
    # 进度轮询统一 HTTP 200，避免前端 axios 将业务失败误判为 Network Error
    if data["status"] == "error":
        return jsonify(code=0, message=data.get("error") or "视频处理失败", data=data)
    return jsonify(code=0, data=data)


def _pose_worker(job_id, library, model_key, abs_path, src_path, out_path, out_name, conf):
    """后台线程：逐帧姿态估计，按帧上报进度，完成写结果。"""
    def cb(processed, total):
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j["processed"] = processed
                j["total"] = total
    try:
        if (library or "ultralytics").lower() == "rtmlib":
            from inference import pose_video_rtmlib
            stats = pose_video_rtmlib(
                model_key or "rtmo-s", abs_path, src_path, out_path, conf=conf, progress_cb=cb)
        else:
            from inference import pose_video
            stats = pose_video(abs_path, src_path, out_path, conf=conf, progress_cb=cb)
        stats["output"] = out_name
        with _video_jobs_lock:
            _video_jobs[job_id].update(status="done", stats=stats,
                                       processed=stats["frames"], total=stats["frames"])
    except Exception as e:  # noqa: BLE001
        with _video_jobs_lock:
            _video_jobs[job_id].update(status="error", error=str(e))
    finally:
        if os.path.isfile(src_path):
            try:
                os.remove(src_path)
            except OSError:
                pass


@ai_model_bp.post("/<int:mid>/pose-video")
@permission_required("ai:model:query")
def pose_video_route(mid):
    """姿态估计（视频）：启动异步逐帧任务，返回 jobId（进度复用 video-progress）。"""
    m = AiModel.query.get_or_404(mid)
    try:
        lib, abs_path, _task = _resolve_pose_runtime(m)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到视频"), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的视频格式"), 400

    try:
        conf = float(request.form.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25

    video_folder = current_app.config["VIDEO_FOLDER"]
    out_folder = current_app.config["OUTPUT_FOLDER"]
    _ensure_dir(video_folder)
    _ensure_dir(out_folder)

    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "video"
    src_path = os.path.join(video_folder, f"{base}_{ts}{ext}")
    out_name = f"{base}_{ts}_pose.mp4"
    out_path = os.path.join(out_folder, out_name)
    file.save(src_path)

    job_id = uuid.uuid4().hex
    with _video_jobs_lock:
        _video_jobs[job_id] = {"status": "running", "processed": 0, "total": 0,
                               "stats": None, "error": None}
    threading.Thread(
        target=_pose_worker,
        args=(job_id, lib, m.model_key or "", abs_path, src_path, out_path, out_name, conf),
        daemon=True,
    ).start()
    return jsonify(code=0, message="任务已启动", data={"jobId": job_id})


def _track_worker(job_id, abs_path, src_path, out_path, out_name, conf, imgsz, line,
                  alert_rules_payload=None):
    """后台线程：逐帧追踪，按帧上报进度，完成写结果。"""
    def cb(processed, total):
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j["processed"] = processed
                j["total"] = total
    try:
        from inference import track_video
        stats = track_video(
            abs_path, src_path, out_path, conf=conf, imgsz=imgsz,
            line=line, progress_cb=cb,
            alert_rules=alert_rules_payload, alert_source_key=job_id,
        )
        stats["output"] = out_name
        with _video_jobs_lock:
            _video_jobs[job_id].update(status="done", stats=stats,
                                       processed=stats["frames"], total=stats["frames"])
    except Exception as e:  # noqa: BLE001
        with _video_jobs_lock:
            _video_jobs[job_id].update(status="error", error=str(e))
    finally:
        if os.path.isfile(src_path):
            try:
                os.remove(src_path)
            except OSError:
                pass


@ai_model_bp.post("/<int:mid>/track-video")
@permission_required("ai:model:query")
def track_video_route(mid):
    """目标追踪：启动异步逐帧 ByteTrack 任务，返回 jobId（进度复用 video-progress）。"""
    m = AiModel.query.get_or_404(mid)
    if (m.library or "ultralytics") != "ultralytics" or (m.task or "") != "object-detection":
        return jsonify(code=400, message="目标追踪仅支持 YOLO（ultralytics）目标检测模型"), 400
    abs_path = _abs_weight(m)
    if abs_path is None:
        return jsonify(code=400, message="该模型暂无本地权重，请先上传或拉取权重"), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到视频"), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的视频格式"), 400

    try:
        conf = float(request.form.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25
    try:
        imgsz = int(request.form.get("imgsz", 640))
    except (TypeError, ValueError):
        imgsz = 640

    line = None
    raw_line = request.form.get("line")
    if raw_line:
        try:
            import json
            parsed = json.loads(raw_line)
            if isinstance(parsed, list) and len(parsed) == 4:
                line = [float(v) for v in parsed]
        except (ValueError, TypeError):
            line = None

    alert_enabled = str(request.form.get("alertEnabled", "0")).strip().lower() in (
        "1", "true", "on", "yes"
    )
    rules_payload = None
    if alert_enabled:
        from services.alert_rules_query import (
            load_enabled_alert_rules,
            parse_rule_keys,
            serialize_alert_rules_payload,
        )
        raw_keys = request.form.get("alertRuleKeys")
        if raw_keys is None or str(raw_keys).strip() == "":
            rule_keys = None
        else:
            rule_keys = parse_rule_keys(raw_keys)
        enabled_rules = load_enabled_alert_rules(rule_keys)
        if not enabled_rules:
            return jsonify(
                code=400,
                message="当前没有启用中的告警规则；请到「检测告警」页启用至少一条规则",
            ), 400
        rules_payload = serialize_alert_rules_payload(enabled_rules)

    video_folder = current_app.config["VIDEO_FOLDER"]
    out_folder = current_app.config["OUTPUT_FOLDER"]
    _ensure_dir(video_folder)
    _ensure_dir(out_folder)

    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "video"
    src_path = os.path.join(video_folder, f"{base}_{ts}{ext}")
    out_name = f"{base}_{ts}_track.mp4"
    out_path = os.path.join(out_folder, out_name)
    file.save(src_path)

    job_id = uuid.uuid4().hex
    with _video_jobs_lock:
        _video_jobs[job_id] = {"status": "running", "processed": 0, "total": 0,
                               "stats": None, "error": None}
    threading.Thread(
        target=_track_worker,
        args=(job_id, abs_path, src_path, out_path, out_name, conf, imgsz, line, rules_payload),
        daemon=True,
    ).start()
    return jsonify(code=0, message="任务已启动", data={"jobId": job_id})


@ai_model_bp.post("/<int:mid>/track-frame")
@permission_required("ai:model:query")
def track_frame_route(mid):
    """摄像头实时追踪：单帧 -> 检测框 + 轨迹ID（前端叠画）。"""
    m = AiModel.query.get_or_404(mid)
    if (m.library or "ultralytics") != "ultralytics" or (m.task or "") != "object-detection":
        return jsonify(code=400, message="目标追踪仅支持 YOLO（ultralytics）目标检测模型"), 400
    abs_path = _abs_weight(m)
    if abs_path is None:
        return jsonify(code=400, message="该模型暂无本地权重，请先上传或拉取权重"), 400
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400
    try:
        conf = float(request.form.get("conf", 0.25))
    except (TypeError, ValueError):
        conf = 0.25
    reset = request.form.get("reset", "0") == "1"
    try:
        from inference import track_frame
        result = track_frame(abs_path, file.read(), conf=conf, reset=reset)
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"追踪失败：{e}"), 500
    return jsonify(code=0, message="ok", data=result)


@ai_model_bp.get("/output/<path:name>")
@permission_required("ai:model:query")
def get_output(name):
    """返回带框输出视频（防目录穿越）。"""
    out_folder = current_app.config["OUTPUT_FOLDER"]
    abs_path = os.path.abspath(os.path.join(out_folder, name))
    if not abs_path.startswith(os.path.abspath(out_folder) + os.sep):
        return jsonify(code=400, message="非法路径"), 400
    if not os.path.isfile(abs_path):
        return jsonify(code=404, message="输出文件不存在"), 404
    return send_file(abs_path, mimetype="video/mp4")


# ------------------------------------------------------------ Linly-Talker 数字人合成
_IMAGE_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# 数字人异步任务进度表：jobId -> {status, processed, total, output, error}
_talker_jobs = {}
_talker_jobs_lock = threading.Lock()


def _talker_worker(job_id, model_dir, image_path, audio_path, out_path, out_name):
    """后台线程：调 SadTalker 合成说话视频，上报进度，完成写结果。"""
    def cb(processed, total):
        with _talker_jobs_lock:
            j = _talker_jobs.get(job_id)
            if j:
                j["processed"] = processed
                j["total"] = total
    try:
        from inference import synthesize_talking_head
        synthesize_talking_head(model_dir, image_path, audio_path, out_path, progress_cb=cb)
        with _talker_jobs_lock:
            _talker_jobs[job_id].update(status="done", output=out_name)
    except Exception as e:  # noqa: BLE001
        with _talker_jobs_lock:
            _talker_jobs[job_id].update(status="error", error=str(e))
    finally:
        for p in (image_path, audio_path):
            if p and os.path.isfile(p):
                try:
                    os.remove(p)  # 处理完删除上传源
                except OSError:
                    pass


@ai_model_bp.post("/<int:mid>/talking-head")
@permission_required("ai:model:query")
def talking_head_route(mid):
    """数字人合成：上传人像图 + 驱动音频，启动异步任务，返回 jobId。"""
    m = AiModel.query.get_or_404(mid)
    path = _abs_model_path(m)
    if path is None:
        return jsonify(code=400, message="该模型暂无本地权重，请先拉取"), 400

    image = request.files.get("image")
    audio = request.files.get("audio")
    if image is None or not image.filename:
        return jsonify(code=400, message="未接收到人像图片"), 400
    if audio is None or not audio.filename:
        return jsonify(code=400, message="未接收到驱动音频"), 400
    img_ext = os.path.splitext(image.filename)[1].lower()
    aud_ext = os.path.splitext(audio.filename)[1].lower()
    if img_ext not in _IMAGE_ALLOWED_EXT:
        return jsonify(code=400, message="不支持的图片格式"), 400
    if aud_ext not in current_app.config["AUDIO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的音频格式"), 400

    video_folder = current_app.config["VIDEO_FOLDER"]
    audio_folder = current_app.config["AUDIO_FOLDER"]
    out_folder = current_app.config["OUTPUT_FOLDER"]
    for d in (video_folder, audio_folder, out_folder):
        _ensure_dir(d)

    ts = int(time.time())
    image_path = os.path.join(video_folder, f"talker_{ts}{img_ext}")
    audio_path = os.path.join(audio_folder, f"talker_{ts}{aud_ext}")
    out_name = f"talker_{ts}.mp4"
    out_path = os.path.join(out_folder, out_name)
    image.save(image_path)
    audio.save(audio_path)

    job_id = uuid.uuid4().hex
    with _talker_jobs_lock:
        _talker_jobs[job_id] = {"status": "running", "processed": 0, "total": 0,
                                "output": None, "error": None}
    threading.Thread(
        target=_talker_worker,
        args=(job_id, path, image_path, audio_path, out_path, out_name),
        daemon=True,
    ).start()
    return jsonify(code=0, message="任务已启动", data={"jobId": job_id})


@ai_model_bp.get("/<int:mid>/talking-progress/<job_id>")
@permission_required("ai:model:query")
def talking_progress(mid, job_id):
    """查询数字人合成任务进度。"""
    with _talker_jobs_lock:
        j = _talker_jobs.get(job_id)
        if j is None:
            return jsonify(code=404, message="任务不存在或已过期"), 404
        data = dict(j)
    if data["status"] == "error":
        return jsonify(code=500, message=f"数字人合成失败：{data['error']}"), 500
    return jsonify(code=0, data=data)
