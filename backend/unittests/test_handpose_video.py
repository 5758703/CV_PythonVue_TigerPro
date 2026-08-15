"""手势视频处理轻量单测（不跑整段推理）。"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.handpose_video import _overlay_banner  # noqa: E402


def test_overlay_banner_keeps_shape():
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    out = _overlay_banner(img, "2 1 | A")
    assert out.shape == img.shape
    assert out is not img


def test_overlay_banner_empty_text_noop():
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    out = _overlay_banner(img, None)
    assert out is img
