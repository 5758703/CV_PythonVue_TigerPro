"""四套独立标注工具工作区：web / xanylabeling / cvat / roboflow。

- web：沿用 raw/images + raw/labels（内置 Canvas）
- 其余：tools/<tool>/labels 独立落盘，可 apply 回灌 raw/labels
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def _mask_secrets(text: str) -> str:
    """避免 API Key 等出现在前端错误提示中。"""
    s = str(text or "")
    s = re.sub(r"(api_key=)[^&\s\"']+", r"\1***", s, flags=re.I)
    s = re.sub(r"(Authorization:\s*(?:Bearer|Token)\s+)\S+", r"\1***", s, flags=re.I)
    return s


def _ascii_slug(text: str, *, fallback: str = "dataset", max_len: int = 40) -> str:
    """Roboflow 等要求 name 仅含字母/数字/短横线/下划线/空格。"""
    raw = (text or "").strip()
    parts: list[str] = []
    for ch in raw:
        if ch.isascii() and (ch.isalnum() or ch in "-_ "):
            parts.append(ch.lower() if ch.isalnum() else ch)
        else:
            parts.append("-")
    slug = re.sub(r"[-_\s]+", "-", "".join(parts)).strip("-")
    if not slug:
        digest = hashlib.md5(raw.encode("utf-8") or b"x").hexdigest()[:8]
        slug = f"{fallback}-{digest}"
    return slug[:max_len].strip("-") or fallback


def _roboflow_project_name(dataset_name: str, dataset_id: int | None = None) -> str:
    """生成 Roboflow 合法项目名（纯 ASCII）。"""
    base = _ascii_slug(dataset_name, fallback="ds", max_len=28)
    if dataset_id is not None:
        return f"tiger-ds{int(dataset_id)}-{base}"[:64].strip("-")
    return f"tiger-{base}"[:64].strip("-")


def _roboflow_annotation_group(class_names: list[str] | None) -> str:
    first = (class_names or ["object"])[0] if class_names else "object"
    slug = _ascii_slug(str(first), fallback="object", max_len=64)
    return slug or "object"

from services.dataset_annotation import (
    annotation_stats,
    ensure_annotation_dirs,
    list_annotation_samples,
)
from services.training import IMG_EXTENSIONS

TOOL_WEB = "web"
TOOL_XANY = "xanylabeling"
TOOL_CVAT = "cvat"
TOOL_ROBOFLOW = "roboflow"
ALL_TOOLS = (TOOL_WEB, TOOL_XANY, TOOL_CVAT, TOOL_ROBOFLOW)

TOOL_META = {
    TOOL_WEB: {
        "id": TOOL_WEB,
        "name": "内置 Web 画框",
        "kind": "builtin",
        "description": "浏览器 Canvas 矩形框，标签直接写入 raw/labels。",
    },
    TOOL_XANY: {
        "id": TOOL_XANY,
        "name": "X-AnyLabeling",
        "kind": "desktop",
        "description": "导出图片包到桌面 X-AnyLabeling 标注后回传 YOLO 标签（独立工作区）。",
    },
    TOOL_CVAT: {
        "id": TOOL_CVAT,
        "name": "CVAT",
        "kind": "server",
        "description": "通过 CVAT REST API 推送图片并拉取 YOLO 标注（独立工作区）。",
    },
    TOOL_ROBOFLOW: {
        "id": TOOL_ROBOFLOW,
        "name": "Roboflow Annotate",
        "kind": "cloud",
        "description": "通过 Roboflow API 上传图片并下载 YOLO 数据集（独立工作区）。",
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tools_root(dataset_dir: Path) -> Path:
    p = dataset_dir / "tools"
    p.mkdir(parents=True, exist_ok=True)
    return p


def tool_dir(dataset_dir: Path, tool: str) -> Path:
    if tool not in ALL_TOOLS:
        raise ValueError(f"未知标注工具：{tool}")
    p = tools_root(dataset_dir) / tool
    p.mkdir(parents=True, exist_ok=True)
    (p / "labels").mkdir(exist_ok=True)
    (p / "packs").mkdir(exist_ok=True)
    return p


def session_path(dataset_dir: Path, tool: str) -> Path:
    return tool_dir(dataset_dir, tool) / "session.json"


def load_session(dataset_dir: Path, tool: str) -> dict[str, Any]:
    path = session_path(dataset_dir, tool)
    if not path.is_file():
        return {"tool": tool, "updatedAt": None, "state": "idle"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"tool": tool, "updatedAt": None, "state": "idle"}


def save_session(dataset_dir: Path, tool: str, data: dict[str, Any]) -> dict[str, Any]:
    data = dict(data)
    data["tool"] = tool
    data["updatedAt"] = _utc_now()
    path = session_path(dataset_dir, tool)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def tool_label_dir(dataset_dir: Path, tool: str) -> Path:
    if tool == TOOL_WEB:
        _, lbl = ensure_annotation_dirs(dataset_dir / "raw")
        return lbl
    return tool_dir(dataset_dir, tool) / "labels"


def tool_stats(dataset_dir: Path, tool: str) -> dict[str, Any]:
    raw_dir = dataset_dir / "raw"
    ensure_annotation_dirs(raw_dir)
    samples = list_annotation_samples(raw_dir)
    total = len(samples)
    lbl_dir = tool_label_dir(dataset_dir, tool)
    annotated = 0
    boxes = 0
    for s in samples:
        lp = lbl_dir / f"{s['stem']}.txt"
        if not lp.is_file():
            continue
        try:
            lines = [ln for ln in lp.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except OSError:
            lines = []
        if lines:
            annotated += 1
            boxes += len(lines)
    return {
        "total": total,
        "annotated": annotated,
        "unannotated": max(0, total - annotated),
        "totalBoxes": boxes,
        "labelDir": str(lbl_dir.relative_to(dataset_dir)).replace("\\", "/") if lbl_dir.exists() else "",
    }


def config_status() -> dict[str, Any]:
    cvat_url = (os.getenv("CVAT_URL") or "").rstrip("/")
    cvat_user = os.getenv("CVAT_USERNAME") or ""
    cvat_pass = os.getenv("CVAT_PASSWORD") or ""
    cvat_token = os.getenv("CVAT_TOKEN") or ""
    rf_key = os.getenv("ROBOFLOW_API_KEY") or ""
    rf_ws = os.getenv("ROBOFLOW_WORKSPACE") or ""
    xany_cmd = os.getenv("XANYLABELING_CMD") or ""
    return {
        TOOL_WEB: {"ready": True, "message": "内置可用"},
        TOOL_XANY: {
            "ready": True,
            "message": "导出/导入可用；可选配置 XANYLABELING_CMD 启动本地程序",
            "cmdConfigured": bool(xany_cmd),
            "cmd": xany_cmd,
        },
        TOOL_CVAT: {
            "ready": bool(cvat_url and (cvat_token or (cvat_user and cvat_pass))),
            "message": "需配置 CVAT_URL + (CVAT_TOKEN 或 CVAT_USERNAME/PASSWORD)",
            "url": cvat_url,
        },
        TOOL_ROBOFLOW: {
            "ready": bool(rf_key),
            "message": "需配置 ROBOFLOW_API_KEY；可选 ROBOFLOW_WORKSPACE",
            "workspace": rf_ws,
        },
    }


def list_tools(dataset_dir: Path) -> list[dict[str, Any]]:
    cfg = config_status()
    out = []
    raw_exists = (dataset_dir / "raw").exists()
    for tid in ALL_TOOLS:
        meta = dict(TOOL_META[tid])
        meta["config"] = cfg.get(tid, {})
        meta["stats"] = tool_stats(dataset_dir, tid) if raw_exists else {
            "total": 0, "annotated": 0, "unannotated": 0, "totalBoxes": 0, "labelDir": "",
        }
        meta["session"] = load_session(dataset_dir, tid)
        out.append(meta)
    return out


def _copy_yolo_labels(src_dir: Path, dst_dir: Path, *, clear_dst: bool = False) -> int:
    dst_dir.mkdir(parents=True, exist_ok=True)
    if clear_dst:
        for p in dst_dir.glob("*.txt"):
            try:
                p.unlink()
            except OSError:
                pass
    count = 0
    if not src_dir.is_dir():
        return 0
    for src in src_dir.glob("*.txt"):
        shutil.copy2(src, dst_dir / src.name)
        count += 1
    return count


def apply_tool_labels(dataset_dir: Path, tool: str, *, mode: str = "merge") -> dict[str, Any]:
    """将工具工作区标签写回 raw/labels。mode=merge|replace。"""
    if tool == TOOL_WEB:
        stats = annotation_stats(dataset_dir / "raw")
        return {"applied": stats.get("annotated", 0), "message": "Web 工具已直接写入 raw/labels，无需回灌"}
    src = tool_label_dir(dataset_dir, tool)
    _, dst = ensure_annotation_dirs(dataset_dir / "raw")
    n = _copy_yolo_labels(src, dst, clear_dst=(mode == "replace"))
    sess = load_session(dataset_dir, tool)
    sess["lastApply"] = {"mode": mode, "files": n, "at": _utc_now()}
    save_session(dataset_dir, tool, sess)
    return {"applied": n, "mode": mode, "rawStats": annotation_stats(dataset_dir / "raw")}


def export_xanylabeling_pack(dataset_dir: Path, class_names: list[str]) -> Path:
    """导出供 X-AnyLabeling 使用的 zip：images/ + classes.txt + README。"""
    raw_dir = dataset_dir / "raw"
    img_dir, _ = ensure_annotation_dirs(raw_dir)
    images = [p for p in sorted(img_dir.iterdir()) if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS]
    if not images:
        raise ValueError("数据集暂无图片，请先抽帧或上传")

    tdir = tool_dir(dataset_dir, TOOL_XANY)
    pack_name = f"xany_pack_{int(time.time())}.zip"
    pack_path = tdir / "packs" / pack_name

    readme = (
        "X-AnyLabeling 独立标注包\n"
        "1. 解压后用 X-AnyLabeling 打开 images 目录\n"
        "2. 按 classes.txt 配置类别\n"
        "3. 标注完成后导出 YOLO 标签，在平台「导入标签」回传\n"
        "4. 本工具工作区与 Web/CVAT/Roboflow 互不影响，回灌前请确认\n"
    )
    with zipfile.ZipFile(pack_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("classes.txt", "\n".join(class_names) + ("\n" if class_names else ""))
        zf.writestr("README.txt", readme)
        for img in images:
            zf.write(img, arcname=f"images/{img.name}")
            lbl = tool_label_dir(dataset_dir, TOOL_XANY) / f"{img.stem}.txt"
            if lbl.is_file():
                zf.write(lbl, arcname=f"labels/{lbl.name}")

    sess = load_session(dataset_dir, TOOL_XANY)
    sess.update({
        "state": "exported",
        "lastExport": {"file": pack_name, "images": len(images), "at": _utc_now()},
    })
    save_session(dataset_dir, TOOL_XANY, sess)
    return pack_path


def import_yolo_labels_zip(dataset_dir: Path, tool: str, zip_bytes: bytes) -> dict[str, Any]:
    """从 zip 导入 YOLO .txt 到指定工具工作区（不自动覆盖 raw）。"""
    if tool == TOOL_WEB:
        raise ValueError("Web 工具请直接在画布保存，勿通过此接口导入")
    lbl_dir = tool_label_dir(dataset_dir, tool)
    imported = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name.lower().endswith(".txt"):
                continue
            if name.startswith("."):
                continue
            (lbl_dir / name).write_bytes(zf.read(info))
            imported += 1
    if imported == 0:
        raise ValueError("压缩包内未找到 YOLO .txt 标签文件")
    sess = load_session(dataset_dir, tool)
    sess.update({
        "state": "imported",
        "lastImport": {"files": imported, "at": _utc_now()},
    })
    save_session(dataset_dir, tool, sess)
    return {"imported": imported, "stats": tool_stats(dataset_dir, tool)}


def import_yolo_label_files(dataset_dir: Path, tool: str, files: list[tuple[str, bytes]]) -> dict[str, Any]:
    if tool == TOOL_WEB:
        raise ValueError("Web 工具请直接在画布保存")
    lbl_dir = tool_label_dir(dataset_dir, tool)
    imported = 0
    for filename, data in files:
        name = Path(filename).name
        if not name.lower().endswith(".txt"):
            continue
        (lbl_dir / name).write_bytes(data)
        imported += 1
    if imported == 0:
        raise ValueError("未收到有效的 .txt 标签文件")
    sess = load_session(dataset_dir, tool)
    sess.update({"state": "imported", "lastImport": {"files": imported, "at": _utc_now()}})
    save_session(dataset_dir, tool, sess)
    return {"imported": imported, "stats": tool_stats(dataset_dir, tool)}


def _cvat_auth_headers() -> tuple[str, dict[str, str], tuple | None]:
    """CVAT 鉴权。

    - Personal Access Token（推荐，形如 ``xxxx.yyyy``）：``Authorization: Bearer …``
    - 旧版登录 Token：``Authorization: Token …``
    - 或 Basic：``CVAT_USERNAME`` / ``CVAT_PASSWORD``
    """
    base = (os.getenv("CVAT_URL") or "").rstrip("/")
    if not base:
        raise ValueError("未配置 CVAT_URL")
    token = (os.getenv("CVAT_TOKEN") or "").strip()
    user = os.getenv("CVAT_USERNAME") or ""
    password = os.getenv("CVAT_PASSWORD") or ""
    scheme_override = (os.getenv("CVAT_AUTH_SCHEME") or "").strip().lower()
    headers = {"Content-Type": "application/json"}
    auth = None
    if token:
        low = token.lower()
        if low.startswith("bearer "):
            headers["Authorization"] = f"Bearer {token[7:].strip()}"
        elif low.startswith("token "):
            headers["Authorization"] = f"Token {token[6:].strip()}"
        elif scheme_override in ("bearer", "token"):
            headers["Authorization"] = f"{scheme_override.capitalize()} {token}"
        elif "." in token:
            # PAT：key_id.secret —— app.cvat.ai 必须用 Bearer
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers["Authorization"] = f"Token {token}"
    elif user and password:
        auth = (user, password)
    else:
        raise ValueError("请配置 CVAT_TOKEN 或 CVAT_USERNAME/CVAT_PASSWORD")
    return base, headers, auth


def _http_raise(resp: requests.Response, *, what: str) -> None:
    if resp.ok:
        return
    detail = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            detail = body.get("detail") or body.get("error") or body.get("message") or ""
            if not detail:
                detail = json.dumps(body, ensure_ascii=False)[:300]
        else:
            detail = str(body)[:300]
    except Exception:  # noqa: BLE001
        detail = (resp.text or "")[:300]
    msg = f"{what}失败 HTTP {resp.status_code}"
    if detail:
        msg = f"{msg}：{_mask_secrets(detail)}"
    raise ValueError(msg)


def cvat_push(
    dataset_dir: Path,
    dataset_name: str,
    class_names: list[str],
    *,
    dataset_id: int | None = None,
) -> dict[str, Any]:
    """创建/复用 CVAT 项目与任务，上传 raw/images。"""
    base, headers, auth = _cvat_auth_headers()
    img_dir, _ = ensure_annotation_dirs(dataset_dir / "raw")
    images = [p for p in sorted(img_dir.iterdir()) if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS]
    if not images:
        raise ValueError("数据集暂无图片")

    labels_payload = [{"name": n, "attributes": []} for n in (class_names or ["object"])]
    # CVAT 项目名可用中文；附带 id 保证唯一、便于检索
    if dataset_id is not None:
        proj_name = f"tiger-ds{int(dataset_id)}-{dataset_name}"[:120]
    else:
        proj_name = f"tiger-{dataset_name}"[:120]

    r = requests.get(f"{base}/api/projects", params={"search": proj_name}, headers=headers, auth=auth, timeout=60)
    _http_raise(r, what="CVAT 查询项目")
    results = (r.json() or {}).get("results") or []
    project_id = None
    for item in results:
        if item.get("name") == proj_name:
            project_id = item.get("id")
            break
    if project_id is None:
        r = requests.post(
            f"{base}/api/projects",
            headers=headers,
            auth=auth,
            json={"name": proj_name, "labels": labels_payload},
            timeout=60,
        )
        _http_raise(r, what="CVAT 创建项目")
        project_id = r.json().get("id")

    task_name = f"{proj_name}-task-{int(time.time())}"[:128]
    # 归属项目时不要再传 labels，否则 CVAT 返回 400
    r = requests.post(
        f"{base}/api/tasks",
        headers=headers,
        auth=auth,
        json={"name": task_name, "project_id": project_id},
        timeout=60,
    )
    _http_raise(r, what="CVAT 创建任务")
    task_id = r.json().get("id")

    files = []
    handles = []
    try:
        for i, img in enumerate(images):
            fh = open(img, "rb")
            handles.append(fh)
            files.append((f"client_files[{i}]", (img.name, fh, "application/octet-stream")))
        up_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        r = requests.post(
            f"{base}/api/tasks/{task_id}/data",
            headers=up_headers,
            auth=auth,
            data={"image_quality": 95},
            files=files,
            timeout=600,
        )
        _http_raise(r, what="CVAT 上传图片")
    finally:
        for fh in handles:
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass

    ui = f"{base}/tasks/{task_id}"
    sess = load_session(dataset_dir, TOOL_CVAT)
    sess.update({
        "state": "pushed",
        "projectId": project_id,
        "projectName": proj_name,
        "taskId": task_id,
        "taskUrl": ui,
        "imageCount": len(images),
        "lastPushAt": _utc_now(),
    })
    save_session(dataset_dir, TOOL_CVAT, sess)
    return {"projectId": project_id, "taskId": task_id, "taskUrl": ui, "images": len(images)}


def cvat_pull(dataset_dir: Path) -> dict[str, Any]:
    """从 CVAT 任务导出 YOLO 1.1 并写入 tools/cvat/labels。"""
    base, headers, auth = _cvat_auth_headers()
    sess = load_session(dataset_dir, TOOL_CVAT)
    task_id = sess.get("taskId")
    if not task_id:
        raise ValueError("尚未推送到 CVAT，请先执行推送")

    fmt = "YOLO 1.1"
    r = requests.post(
        f"{base}/api/tasks/{task_id}/dataset/export",
        headers=headers,
        auth=auth,
        params={"format": fmt, "save_images": False},
        timeout=120,
    )
    if r.status_code >= 400:
        r = requests.get(
            f"{base}/api/tasks/{task_id}/dataset",
            headers={k: v for k, v in headers.items() if k.lower() != "content-type"},
            auth=auth,
            params={"format": fmt, "action": "download"},
            timeout=300,
        )
        r.raise_for_status()
        zip_bytes = r.content
    else:
        payload = r.json() if r.content else {}
        rq_id = payload.get("rq_id") or payload.get("id")
        zip_bytes = None
        if rq_id:
            for _ in range(60):
                time.sleep(2)
                cr = requests.get(f"{base}/api/requests/{rq_id}", headers=headers, auth=auth, timeout=60)
                if cr.status_code >= 400:
                    continue
                body = cr.json() or {}
                status = (body.get("status") or body.get("state") or "").lower()
                if status in ("finished", "completed"):
                    result_url = (
                        body.get("result_url")
                        or body.get("url")
                        or f"{base}/api/tasks/{task_id}/dataset?format={fmt}&action=download"
                    )
                    dr = requests.get(
                        result_url,
                        headers={k: v for k, v in headers.items() if k.lower() != "content-type"},
                        auth=auth,
                        timeout=300,
                    )
                    dr.raise_for_status()
                    zip_bytes = dr.content
                    break
                if status in ("failed", "error"):
                    raise ValueError(f"CVAT 导出失败：{body}")
        if zip_bytes is None:
            dr = requests.get(
                f"{base}/api/tasks/{task_id}/dataset",
                headers={k: v for k, v in headers.items() if k.lower() != "content-type"},
                auth=auth,
                params={"format": fmt, "action": "download"},
                timeout=300,
            )
            dr.raise_for_status()
            zip_bytes = dr.content

    lbl_dir = tool_label_dir(dataset_dir, TOOL_CVAT)
    for old in lbl_dir.glob("*.txt"):
        try:
            old.unlink()
        except OSError:
            pass
    imported = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name.lower().endswith(".txt"):
                continue
            if name.lower() in ("classes.txt", "obj.names", "notes.json"):
                continue
            (lbl_dir / name).write_bytes(zf.read(info))
            imported += 1

    sess.update({"state": "pulled", "lastPull": {"files": imported, "at": _utc_now()}})
    save_session(dataset_dir, TOOL_CVAT, sess)
    return {"imported": imported, "stats": tool_stats(dataset_dir, TOOL_CVAT), "taskId": task_id}


def roboflow_push(
    dataset_dir: Path,
    dataset_name: str,
    class_names: list[str],
    *,
    dataset_id: int | None = None,
) -> dict[str, Any]:
    api_key = os.getenv("ROBOFLOW_API_KEY") or ""
    if not api_key:
        raise ValueError("未配置 ROBOFLOW_API_KEY")
    workspace_slug = os.getenv("ROBOFLOW_WORKSPACE") or ""

    from roboflow import Roboflow

    rf = Roboflow(api_key=api_key)
    workspace = rf.workspace(workspace_slug) if workspace_slug else rf.workspace()

    # Roboflow name 禁止非 ASCII（中文会 422）；用 ds{id}+ascii 片段保证合法且稳定
    proj_id = _roboflow_project_name(dataset_name, dataset_id)
    annotation = _roboflow_annotation_group(class_names)
    try:
        project = workspace.project(proj_id)
    except Exception:  # noqa: BLE001
        try:
            project = workspace.create_project(
                project_name=proj_id,
                project_license="MIT",
                project_type="object-detection",
                annotation=annotation,
            )
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Roboflow 创建项目失败：{_mask_secrets(e)}") from e

    # SDK 返回的实际 slug 可能与 name 略有差异
    actual_id = getattr(project, "id", None) or getattr(project, "name", None) or proj_id
    if isinstance(actual_id, str) and "/" in actual_id:
        actual_id = actual_id.split("/")[-1]
    proj_id = str(actual_id)

    img_dir, _ = ensure_annotation_dirs(dataset_dir / "raw")
    images = [p for p in sorted(img_dir.iterdir()) if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS]
    if not images:
        raise ValueError("数据集暂无图片")

    uploaded = 0
    errors = []
    for img in images:
        try:
            project.upload(str(img), num_retry_uploads=2)
            uploaded += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"{img.name}: {_mask_secrets(e)}")

    ws_name = getattr(workspace, "url", None) or getattr(workspace, "name", None) or workspace_slug or "workspace"
    annotate_url = f"https://app.roboflow.com/{ws_name}/{proj_id}/annotate"
    sess = load_session(dataset_dir, TOOL_ROBOFLOW)
    sess.update({
        "state": "pushed",
        "projectId": proj_id,
        "workspace": ws_name,
        "annotateUrl": annotate_url,
        "uploaded": uploaded,
        "errors": errors[:20],
        "lastPushAt": _utc_now(),
    })
    save_session(dataset_dir, TOOL_ROBOFLOW, sess)
    return {
        "projectId": proj_id,
        "uploaded": uploaded,
        "failed": len(errors),
        "annotateUrl": annotate_url,
        "errors": errors[:10],
    }


def roboflow_pull(dataset_dir: Path, *, version: int | None = None) -> dict[str, Any]:
    api_key = os.getenv("ROBOFLOW_API_KEY") or ""
    if not api_key:
        raise ValueError("未配置 ROBOFLOW_API_KEY")
    sess = load_session(dataset_dir, TOOL_ROBOFLOW)
    proj_id = sess.get("projectId")
    workspace_slug = sess.get("workspace") or os.getenv("ROBOFLOW_WORKSPACE") or ""
    if not proj_id:
        raise ValueError("尚未推送到 Roboflow，请先执行推送")

    from roboflow import Roboflow

    rf = Roboflow(api_key=api_key)
    workspace = rf.workspace(workspace_slug) if workspace_slug else rf.workspace()
    project = workspace.project(proj_id)

    ver = version
    if ver is None:
        try:
            vers = project.versions()
            ver = max([int(getattr(v, "version", 1)) for v in vers], default=1) if vers else 1
        except Exception:  # noqa: BLE001
            ver = int(os.getenv("ROBOFLOW_DATASET_VERSION") or 1)

    tdir = tool_dir(dataset_dir, TOOL_ROBOFLOW)
    out_dir = tdir / "packs" / f"rf_v{ver}"
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    v = project.version(ver)
    try:
        v.download("yolov8", location=str(out_dir))
    except Exception:  # noqa: BLE001
        v.download("yolov5", location=str(out_dir))

    lbl_dir = tool_label_dir(dataset_dir, TOOL_ROBOFLOW)
    for old in lbl_dir.glob("*.txt"):
        try:
            old.unlink()
        except OSError:
            pass
    imported = 0
    for p in out_dir.rglob("*.txt"):
        if p.name.lower() in ("classes.txt",):
            continue
        shutil.copy2(p, lbl_dir / p.name)
        imported += 1

    sess.update({
        "state": "pulled",
        "version": ver,
        "lastPull": {"files": imported, "at": _utc_now()},
    })
    save_session(dataset_dir, TOOL_ROBOFLOW, sess)
    return {"imported": imported, "version": ver, "stats": tool_stats(dataset_dir, TOOL_ROBOFLOW)}
