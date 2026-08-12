"""ONNX 与 ONNX Runtime 兼容性辅助。

安防包等 YOLO 导出常带 ai.onnx opset=20；部分环境 ORT 仅官方支持到 19，
加载时报 ValidateOpsetForDomain。此处将过高 opset 降到安全版本。
"""
from __future__ import annotations

import os
import threading

_lock = threading.Lock()
# 经验值：覆盖常见 CPU ORT（含 1.16.x～1.21.x 混用环境）
DEFAULT_MAX_OPSET = 19


def onnx_ai_opset(path: str) -> int | None:
    """读取模型主域 ai.onnx 的 opset；失败返回 None。"""
    try:
        import onnx
        model = onnx.load(path)
        for o in model.opset_import:
            if not o.domain or o.domain == "ai.onnx":
                return int(o.version)
    except Exception:  # noqa: BLE001
        return None
    return None


def ensure_compatible_onnx(
    path: str,
    max_opset: int = DEFAULT_MAX_OPSET,
    *,
    inplace: bool = True,
) -> str:
    """若 ONNX 主 opset > max_opset，则转换为 max_opset 并写回（默认原地）。

    返回实际可用于推理的路径。转换失败时返回原 path（由调用方决定是否再失败）。
    """
    if not path or not str(path).lower().endswith(".onnx"):
        return path
    if not os.path.isfile(path):
        return path

    cur = onnx_ai_opset(path)
    if cur is None or cur <= int(max_opset):
        return path

    with _lock:
        # 双检：可能已被其他线程降级
        cur = onnx_ai_opset(path)
        if cur is None or cur <= int(max_opset):
            return path
        try:
            import onnx
            from onnx import version_converter

            model = onnx.load(path)
            converted = version_converter.convert_version(model, int(max_opset))
            dest = path if inplace else f"{os.path.splitext(path)[0]}_opset{max_opset}.onnx"
            # 先写临时文件再替换，避免半截损坏
            tmp = dest + ".tmp"
            onnx.save(converted, tmp)
            os.replace(tmp, dest)
            return dest
        except Exception:  # noqa: BLE001
            try:
                tmp = path + ".tmp"
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return path


def is_opset_compat_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "opset" in msg
        and (
            "validateopsetfordomain" in msg.replace(" ", "")
            or "under development" in msg
            or "official support" in msg
            or "opset 20" in msg
        )
    )
