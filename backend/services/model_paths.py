"""模型权重路径解析（MTMC / 推理共用）。"""
from __future__ import annotations

import os

_PREFERRED_WEIGHT_NAMES = (
    "best.pt",
    "best.onnx",
    "yolo26n.pt",
    "yolo26n.onnx",
    "yolo11n.pt",
    "yolov8n.pt",
)


def resolve_model_weight_path(upload_folder: str, file_path: str | None) -> str | None:
    """将 AiModel.file_path 解析为可加载的权重文件路径。"""
    if not file_path:
        return None
    root = os.path.join(upload_folder, file_path)
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
