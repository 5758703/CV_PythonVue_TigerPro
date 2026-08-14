"""回归测试：运行环境未安装 openvino 时，`_get_model` 不应返回一个「加载成功但
predict 时才炸」的半成品 OpenVINO 模型。

根因回顾：Ultralytics 的 OpenVINO 后端是惰性导入（真正 `import openvino` 发生在
首次 predict，而非 YOLO(...) 构造期），因此旧代码里 `use_ov` 分支的 try/except
只能兜住加载期异常，兜不住 predict 期异常，导致 `auto` 模式的自动回退形同虚设。

测试策略：直接 monkeypatch `inference._openvino_available` 让其返回 False，
测的是「_get_model 是否遵守『不可用就跳过 OpenVINO 分支』这个契约」，不依赖
`builtins.__import__` 拦截的细节（后者容易因为拦太宽——把 ultralytics 内部
`from .openvino import OpenVINOBackend` 这种 level>0 的相对导入也拦掉——而测出
假阳性）。额外用 `importlib.util.find_spec` 的真实行为验证探测机制本身可靠。
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import inference  # noqa: E402

WEIGHT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "uploads", "models",
        "yolo26n-pose-ONNX", "yolo26n-pose.pt",
    )
)

pytestmark = pytest.mark.skipif(
    not os.path.isfile(WEIGHT_PATH),
    reason=f"测试权重不存在（uploads 目录缺失）：{WEIGHT_PATH}",
)


@pytest.fixture(autouse=True)
def _isolate_model_cache_and_openvino_probe(monkeypatch):
    """`_get_model` 内部按 (path, backend, precision, imgsz, mtime, prefer_onnx)
    缓存模型对象；同时 `_openvino_available()` 的探测结果也做了模块级缓存。
    两者都可能被其它测试污染，这里在每个用例前后清空，保证互不干扰。
    """
    inference._cache.clear()
    monkeypatch.setattr(inference, "_openvino_available_cache", None, raising=False)
    yield
    inference._cache.clear()
    monkeypatch.setattr(inference, "_openvino_available_cache", None, raising=False)


def test_find_spec_probe_mechanism_sanity():
    """验证探测机制本身：find_spec 对确定不存在的包返回 None，对标准库包返回非 None。

    这不是测 `_openvino_available()`（它硬编码探测 "openvino"，探测结果取决于
    当前解释器是否真的装了 openvino，本机 .venv 装了 2026.2.1，测不出 bug），
    而是确认我们选用的探测机制（`importlib.util.find_spec`）符合预期，为
    `_openvino_available()` 的实现提供独立佐证。
    """
    import importlib.util

    assert importlib.util.find_spec("os") is not None
    assert importlib.util.find_spec("a_pkg_that_definitely_does_not_exist_xyz123") is None


def test_get_model_falls_back_to_pytorch_when_openvino_unavailable(monkeypatch):
    """RED（改前）：旧代码里 use_ov 分支的回退只覆盖加载期，返回的模型对象在这个
    monkeypatch 场景下依然是 OpenVINO 后端，本用例的 predict 断言会因
    ModuleNotFoundError('openvino') 而失败。
    GREEN（改后）：`_openvino_available()` 提前探测，backend='auto' 时直接跳过
    OpenVINO 分支走 PyTorch，加载和 predict 都应成功。
    """
    monkeypatch.setattr(inference, "_openvino_available", lambda: False)
    monkeypatch.delenv("YOLO_INFER_BACKEND", raising=False)  # 走默认 auto

    model = inference._get_model(WEIGHT_PATH)

    # 必须是 PyTorch 路径加载的模型，不是 OpenVINO 导出目录
    ckpt_path = str(getattr(model, "ckpt_path", "") or "")
    assert ckpt_path.lower().endswith((".pt", ".pth")), (
        f"期望模型来自 .pt 文件，实际 ckpt_path={ckpt_path!r}（疑似仍走了 OpenVINO 分支）"
    )
    assert "openvino" not in ckpt_path.lower()

    # 关键断言：真正跑一次 predict。原 bug 恰恰是「加载成功、predict 才炸」，
    # 只检查 ckpt_path 而不 predict 无法复现该 bug。
    dummy_img = np.zeros((64, 64, 3), dtype=np.uint8)
    result = model.predict(dummy_img, conf=0.25, verbose=False, device="cpu")
    assert result is not None
    assert len(result) == 1


def test_get_model_raises_readable_error_when_backend_forced_openvino_unavailable(monkeypatch):
    """用例 2：用户显式指定 YOLO_INFER_BACKEND=openvino，环境却不可用时，
    不能静默回退 PyTorch（否则用户会误以为在用 OpenVINO 加速），
    应抛出可读的中文错误，并提示 pip install openvino / 改用 auto。
    """
    monkeypatch.setattr(inference, "_openvino_available", lambda: False)
    monkeypatch.setenv("YOLO_INFER_BACKEND", "openvino")

    with pytest.raises(RuntimeError) as exc_info:
        inference._get_model(WEIGHT_PATH)

    msg = str(exc_info.value)
    assert "openvino" in msg.lower()
    assert "pip install openvino" in msg
    assert "auto" in msg.lower()
