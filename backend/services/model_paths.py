"""模型权重路径解析（MTMC / 推理共用）。"""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

_PREFERRED_WEIGHT_NAMES = (
    "best.pt",
    "best.onnx",
    "yolo26n.pt",
    "yolo26n.onnx",
    "yolo11n.pt",
    "yolov8n.pt",
)


def resolve_managed_model_path(upload_folder: str, file_path: str | None) -> Path | None:
    """Resolve a stored model path without escaping its managed upload tree."""
    if not file_path or not isinstance(file_path, str) or "\\" in file_path:
        return None
    relative = Path(file_path)
    if relative.is_absolute() or PureWindowsPath(file_path).is_absolute():
        return None
    parts = relative.parts
    if not parts or parts[0] not in ("models", "insightface") or ".." in parts:
        return None
    root = Path(upload_folder).resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root / parts[0])
    except ValueError:
        return None
    if target == root or target == root / "models":
        return None
    return target


def resolve_model_weight_path(upload_folder: str, file_path: str | None) -> str | None:
    """将 AiModel.file_path 解析为可加载的权重文件路径。"""
    if not file_path:
        return None
    resolved = resolve_managed_model_path(upload_folder, file_path)
    if resolved is None:
        return None
    root = str(resolved)
    if os.path.isfile(root):
        return root
    if not os.path.isdir(root):
        return None
    for name in _PREFERRED_WEIGHT_NAMES:
        p = os.path.join(root, name)
        if os.path.isfile(p):
            return p
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.lower().endswith((".pt", ".onnx", ".engine")):
                return os.path.join(dirpath, f)
    return None
