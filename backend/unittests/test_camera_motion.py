"""camera_motion 单测：合成平移估计、warp 往返、可见面积比、payload 透传。"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.camera_motion import (  # noqa: E402
    CameraMotionEstimator,
    profile_matrix_at,
    ref_to_cur_matrix,
    row_to_matrix,
    visible_ratio,
    warp_region_norm,
)


def _textured_frame(w=640, h=360, seed=7):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, size=(h // 8, w // 8), dtype=np.uint8)
    import cv2
    big = cv2.resize(base, (w, h), interpolation=cv2.INTER_NEAREST)
    return cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)


def test_estimator_recovers_translation():
    import cv2
    frame = _textured_frame()
    h, w = frame.shape[:2]
    dx, dy = 24.0, 10.0
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    shifted = cv2.warpAffine(frame, m, (w, h), borderMode=cv2.BORDER_REFLECT)

    est = CameraMotionEstimator()
    c0 = est.update(frame)
    assert np.allclose(c0, np.eye(3))
    c1 = est.update(shifted)
    # 归一化空间平移 ≈ dx/w, dy/h（允许 20% 相对误差）
    assert c1[0, 2] == pytest.approx(dx / w, rel=0.2)
    assert c1[1, 2] == pytest.approx(dy / h, rel=0.2)


def test_warp_region_roundtrip():
    c_ref = np.eye(3)
    c_cur = row_to_matrix([1, 0, 0.3, 0, 1, -0.1])
    reg = [[0.2, 0.2], [0.5, 0.2], [0.5, 0.6], [0.2, 0.6]]
    warped = warp_region_norm(reg, c_ref, c_cur)
    assert warped[0][0] == pytest.approx(0.5)
    assert warped[0][1] == pytest.approx(0.1)
    back = warp_region_norm(warped, c_cur, c_ref)
    for p0, p1 in zip(reg, back):
        assert p0[0] == pytest.approx(p1[0], abs=1e-9)
        assert p0[1] == pytest.approx(p1[1], abs=1e-9)


def test_ref_to_cur_matrix_identity_when_same():
    c = row_to_matrix([1.02, 0.01, 0.4, -0.01, 1.02, 0.05])
    m = ref_to_cur_matrix(c, c)
    assert np.allclose(m, np.eye(3), atol=1e-9)


def test_visible_ratio():
    inside = [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0.1, 0.4]]
    assert visible_ratio(inside) == pytest.approx(1.0)
    gone = [[1.5, 0.1], [1.9, 0.1], [1.9, 0.4], [1.5, 0.4]]
    assert visible_ratio(gone) == 0.0
    # 左半出画面：正好剩一半
    half = [[-0.2, 0.2], [0.2, 0.2], [0.2, 0.6], [-0.2, 0.6]]
    assert visible_ratio(half) == pytest.approx(0.5, abs=1e-6)
    assert visible_ratio(None) == 0.0
    assert visible_ratio([[0, 0], [1, 1]]) == 0.0


def test_profile_matrix_at_nearest():
    prof = {"fps": 10, "count": 3, "frames": [
        [1, 0, 0.0, 0, 1, 0.0],
        [1, 0, 0.1, 0, 1, 0.0],
        [1, 0, 0.2, 0, 1, 0.0],
    ]}
    assert profile_matrix_at(prof, 0.0)[0, 2] == pytest.approx(0.0)
    assert profile_matrix_at(prof, 0.1)[0, 2] == pytest.approx(0.1)
    # 超出末尾取最后一帧；缺 profile 返回单位阵
    assert profile_matrix_at(prof, 9.0)[0, 2] == pytest.approx(0.2)
    assert np.allclose(profile_matrix_at(None, 1.0), np.eye(3))


def test_parse_zones_payload_passthrough_ref_and_out_of_view():
    from services.duty_absence import parse_zones_payload

    zones = [{
        "id": "zA",
        "name": "工位A",
        "region": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]],
        "staffIds": [3],
        "refSec": 4.0,
        "outOfView": True,
    }]
    out = parse_zones_payload(zones, staff_ids=[3], absence_threshold_sec=30)
    assert len(out) == 1
    assert out[0]["refSec"] == pytest.approx(4.0)
    assert out[0]["outOfView"] is True
    # 缺省值
    out2 = parse_zones_payload([{"id": "zB", "region": [[0, 0], [1, 0], [1, 1]]}])
    assert out2[0]["refSec"] == 0.0
    assert out2[0]["outOfView"] is False
