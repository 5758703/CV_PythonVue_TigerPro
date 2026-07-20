"""羽毛球检测辅助逻辑单元测试（不依赖真实推理）。"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.badminton import _expand_court_poly, _in_court_polygon  # noqa: E402


def test_expand_court_poly_grows_outward():
    poly = np.array(
        [[[100.0, 100.0]], [[300.0, 100.0]], [[300.0, 300.0]], [[100.0, 300.0]]],
        dtype=np.float32,
    )
    expanded = _expand_court_poly(poly, 0.08)
    pts = expanded.reshape(-1, 2)
    # 中心仍约在 (200,200)，角点应更远离中心
    c = pts.mean(axis=0)
    assert abs(c[0] - 200) < 1 and abs(c[1] - 200) < 1
    orig = poly.reshape(-1, 2)
    d0 = math.hypot(*(orig[0] - orig.mean(axis=0)))
    d1 = math.hypot(*(pts[0] - c))
    assert d1 > d0


def test_in_court_after_expand_includes_near_edge():
    poly = np.array(
        [[[100.0, 100.0]], [[300.0, 100.0]], [[300.0, 300.0]], [[100.0, 300.0]]],
        dtype=np.float32,
    )
    # 刚好在原边框外一点
    assert not _in_court_polygon(95, 200, poly)
    expanded = _expand_court_poly(poly, 0.08)
    assert _in_court_polygon(95, 200, expanded)


def test_yolo11s_ball_weight_on_disk():
    root = os.path.join(os.path.dirname(__file__), "..", "uploads", "models", "yolo11s-ball")
    pt = os.path.join(root, "yolo11s-ball.pt")
    assert os.path.isfile(pt), f"missing weight: {pt}"
    assert os.path.getsize(pt) > 1_000_000
