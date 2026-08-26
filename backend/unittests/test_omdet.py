"""OmDet-Turbo 开放词汇检测单测（不加载真实权重）。"""
from __future__ import annotations

import types

import numpy as np


def test_is_omdet_model_by_dirname(tmp_path):
    from inference import _is_omdet_model

    p = tmp_path / "omdet-turbo-swin-tiny"
    p.mkdir()
    assert _is_omdet_model(str(p)) is True


def test_is_omdet_model_by_config(tmp_path):
    from inference import _is_omdet_model

    p = tmp_path / "custom"
    p.mkdir()
    (p / "config.json").write_text('{"model_type": "omdet-turbo"}', encoding="utf-8")
    assert _is_omdet_model(str(p)) is True


def test_detect_image_omdet_formats_detections(monkeypatch):
    import inference

    class FakeProc:
        def __call__(self, pil, text=None, return_tensors=None):
            return {"pixel_values": types.SimpleNamespace(to=lambda d: "pv")}

        def post_process_grounded_object_detection(self, outputs, classes, target_sizes, score_threshold, nms_threshold):
            return [{
                "scores": [0.91, 0.55],
                "classes": ["cat", "remote"],
                "boxes": [
                    types.SimpleNamespace(tolist=lambda: [10.0, 20.0, 100.0, 200.0]),
                    types.SimpleNamespace(tolist=lambda: [30.0, 40.0, 80.0, 90.0]),
                ],
            }]

    class FakeModel:
        def eval(self):
            return self

        def to(self, device):
            return self

        def parameters(self):
            yield types.SimpleNamespace(device="cpu")

        def __call__(self, **kwargs):
            return object()

    monkeypatch.setattr(inference, "_get_omdet", lambda _d: (FakeProc(), FakeModel()))

    # 1x1 PNG
    import cv2
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok

    out = inference.detect_image_omdet("dummy", buf.tobytes(), conf=0.3, draw=False, classes="cat,remote")
    assert out["count"] == 2
    assert out["engine"] == "omdet-turbo"
    assert out["promptClasses"] == ["cat", "remote"]
    assert out["detections"][0]["className"] == "cat"
    assert out["detections"][0]["bbox"] == [10.0, 20.0, 100.0, 200.0]
