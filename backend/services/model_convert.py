"""模型权重格式转换服务。

基于 Ultralytics export（YOLO .pt/.pth）与 OpenVINO（.onnx → IR），
提供常见部署格式互转：onnx / torchscript / openvino / ncnn / engine 等。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

# 源扩展名 → 可导出目标（Ultralytics YOLO）
_PT_SOURCES = (".pt", ".pth")
_ONNX_SOURCES = (".onnx",)

# 目标格式目录：value 与 ultralytics export format 对齐（openvino-from-onnx 为自定义）
FORMAT_CATALOG: list[dict[str, Any]] = [
    {
        "value": "onnx",
        "label": "ONNX",
        "ext": ".onnx",
        "sources": list(_PT_SOURCES),
        "engine": "ultralytics",
        "recommended": True,
        "note": "跨平台推理，ORT / OpenCV DNN 通用；推荐首选",
    },
    {
        "value": "torchscript",
        "label": "TorchScript",
        "ext": ".torchscript",
        "sources": list(_PT_SOURCES),
        "engine": "ultralytics",
        "note": "PyTorch 原生序列化，便于 C++ libtorch 部署",
    },
    {
        "value": "openvino",
        "label": "OpenVINO",
        "ext": "_openvino_model",
        "isDir": True,
        "sources": list(_PT_SOURCES),
        "engine": "ultralytics",
        "note": "Intel OpenVINO IR（xml+bin），CPU 推理加速",
    },
    {
        "value": "openvino",
        "label": "OpenVINO（自 ONNX）",
        "ext": "_openvino_model",
        "isDir": True,
        "sources": list(_ONNX_SOURCES),
        "engine": "openvino",
        "alias": "openvino-from-onnx",
        "note": "将已有 ONNX 转为 OpenVINO IR，无需原始 .pt",
    },
    {
        "value": "ncnn",
        "label": "NCNN",
        "ext": "_ncnn_model",
        "isDir": True,
        "sources": list(_PT_SOURCES),
        "engine": "ultralytics",
        "note": "移动端 / 嵌入式轻量推理",
    },
    {
        "value": "engine",
        "label": "TensorRT",
        "ext": ".engine",
        "sources": list(_PT_SOURCES),
        "engine": "ultralytics",
        "requiresGpu": True,
        "note": "需 NVIDIA GPU + TensorRT；失败时请改用 onnx / openvino",
    },
]


def list_formats(source_ext: str | None = None) -> list[dict[str, Any]]:
    """返回可选目标格式；可按源扩展名过滤。"""
    ext = (source_ext or "").lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in FORMAT_CATALOG:
        key = item.get("alias") or f"{item['value']}:{','.join(item['sources'])}"
        if key in seen:
            continue
        if ext and ext not in item["sources"]:
            continue
        seen.add(key)
        out.append({
            "value": item.get("alias") or item["value"],
            "format": item["value"],
            "label": item["label"],
            "ext": item["ext"],
            "isDir": bool(item.get("isDir")),
            "sources": item["sources"],
            "engine": item["engine"],
            "recommended": bool(item.get("recommended")),
            "requiresGpu": bool(item.get("requiresGpu")),
            "note": item.get("note") or "",
        })
    return out


def detect_source_ext(path: str | Path) -> str:
    return Path(path).suffix.lower()


def resolve_out_dir(
    src_path: str | Path,
    *,
    mode: str = "sibling",
    custom_subdir: str = "",
    models_root: str | Path | None = None,
) -> Path:
    """解析输出目录。

    mode:
      - sibling: 与源文件同目录（默认）
      - converted: models/_converted/<stem>/
      - custom: models/<custom_subdir>/（相对 models_root，禁止 ..）
    """
    src = Path(src_path).resolve()
    mode = (mode or "sibling").strip().lower()
    if mode == "sibling":
        return src.parent

    if models_root is None:
        raise ValueError("自定义输出需要 models_root")
    root = Path(models_root).resolve()

    if mode == "converted":
        dest = root / "_converted" / src.stem
    elif mode == "custom":
        sub = (custom_subdir or "").strip().replace("\\", "/").lstrip("/")
        if not sub or ".." in sub.split("/"):
            raise ValueError("自定义输出子目录非法（禁止空路径与 ..）")
        dest = (root / sub).resolve()
        if not str(dest).startswith(str(root)):
            raise ValueError("输出路径必须位于模型目录内")
    else:
        raise ValueError(f"不支持的输出模式: {mode}")

    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _move_export_result(exported: Path, out_dir: Path) -> Path:
    """将 ultralytics 导出产物移动/复制到目标目录。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    if exported.resolve().parent == out_dir.resolve():
        return exported
    dest = out_dir / exported.name
    if exported.is_dir():
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(exported, dest)
        # 清理原始导出目录（若仍在源旁）
        try:
            if exported.exists() and exported.resolve() != dest.resolve():
                shutil.rmtree(exported, ignore_errors=True)
        except OSError:
            pass
        return dest
    if dest.exists():
        dest.unlink()
    shutil.move(str(exported), str(dest))
    return dest


def _export_ultralytics(src: Path, fmt: str, opts: dict) -> Path:
    try:
        from inference import _disable_ultralytics_autoinstall
        _disable_ultralytics_autoinstall()
    except Exception:  # noqa: BLE001
        pass
    from ultralytics import YOLO

    model = YOLO(str(src))
    dynamic = bool(opts.get("dynamic"))
    half = bool(opts.get("half")) and not dynamic
    export_kw: dict[str, Any] = {
        "format": fmt,
        "imgsz": int(opts.get("imgsz") or 640),
        "half": half,
        "dynamic": dynamic,
        "simplify": bool(opts.get("simplify", True)),
        "device": opts.get("device") or "cpu",
        "verbose": False,
    }
    if fmt == "onnx":
        export_kw["opset"] = int(opts.get("opset") or 12)
    if fmt == "openvino":
        export_kw.setdefault("half", True)
        export_kw["dynamic"] = False
    if fmt == "engine":
        export_kw["device"] = opts.get("device") or 0

    out = model.export(**export_kw)
    out_path = Path(str(out))
    if not out_path.exists():
        raise RuntimeError(f"导出未生成文件: {fmt}")
    return out_path


def _onnx_to_openvino(src: Path, out_dir: Path) -> Path:
    import openvino as ov

    out_dir.mkdir(parents=True, exist_ok=True)
    dest_dir = out_dir / f"{src.stem}_openvino_model"
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)
    xml_path = dest_dir / f"{src.stem}.xml"
    ov_model = ov.convert_model(str(src))
    ov.save_model(ov_model, str(xml_path))
    if not xml_path.is_file():
        raise RuntimeError("OpenVINO 转换未生成 xml")
    return dest_dir


def convert_file(
    src_path: str | Path,
    target: str,
    *,
    out_dir: str | Path | None = None,
    opts: dict | None = None,
) -> dict[str, Any]:
    """执行单次转换，返回产物信息。

    target: onnx / torchscript / openvino / ncnn / engine / openvino-from-onnx
    """
    src = Path(src_path)
    if not src.is_file():
        raise FileNotFoundError(f"源文件不存在: {src}")

    opts = dict(opts or {})
    target = (target or "").strip().lower()
    src_ext = src.suffix.lower()
    dest_dir = Path(out_dir) if out_dir else src.parent

    # 反向转换明确拒绝
    if target in ("pt", "pth") or target.endswith(".pt"):
        raise ValueError(
            "无法将 ONNX/部署格式还原为可训练的 .pt："
            "ONNX 等为冻结推理图，请保留原始 PyTorch 权重"
        )

    if target == "openvino-from-onnx" or (target == "openvino" and src_ext == ".onnx"):
        result = _onnx_to_openvino(src, dest_dir)
    elif src_ext in _PT_SOURCES:
        # 标准 ultralytics 目标
        fmt = "openvino" if target == "openvino" else target
        allowed = {f["value"] for f in FORMAT_CATALOG if src_ext in f["sources"] and f["engine"] == "ultralytics"}
        if fmt not in allowed:
            raise ValueError(f"不支持的目标格式: {target}（源 {src_ext}）")
        exported = _export_ultralytics(src, fmt, opts)
        result = _move_export_result(exported, dest_dir)
        if fmt == "onnx":
            try:
                from onnx_compat import ensure_compatible_onnx
                result = Path(ensure_compatible_onnx(str(result)))
            except Exception:  # noqa: BLE001
                pass
    else:
        raise ValueError(
            f"源格式 {src_ext} 暂不支持转为 {target}。"
            f"当前支持：.pt/.pth → onnx/torchscript/openvino/ncnn/engine；.onnx → openvino"
        )

    size = 0
    if result.is_file():
        size = result.stat().st_size
    elif result.is_dir():
        for root, _dirs, files in os.walk(result):
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass

    return {
        "output": str(result),
        "outputName": result.name,
        "outputSize": size,
        "isDir": result.is_dir(),
        "target": target,
    }
