"""handpose 单测：anchors 生成、数手指几何逻辑（不依赖模型权重）。"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.handpose import _gen_palm_anchors, count_fingers  # noqa: E402


def test_palm_anchors_grid():
    a = _gen_palm_anchors()
    assert a.shape == (2016, 2)
    # stride8 段首：(0.5/24, 0.5/24) ×2
    assert np.allclose(a[0], [0.5 / 24, 0.5 / 24])
    assert np.allclose(a[1], a[0])
    # stride16 段首（index 24*24*2 = 1152）：(0.5/12, 0.5/12)
    assert np.allclose(a[1152], [0.5 / 12, 0.5 / 12])
    # 末尾：(11.5/12, 11.5/12)
    assert np.allclose(a[-1], [11.5 / 12, 11.5 / 12])
    assert (a > 0).all() and (a < 1).all()


def _open_hand():
    """竖直张开手掌（腕在下，指尖朝上），单位像素。"""
    lm = np.zeros((21, 3))
    lm[0] = [100, 200, 0]                       # wrist
    lm[1], lm[2], lm[3], lm[4] = [80, 185, 0], [62, 168, 0], [48, 152, 0], [35, 138, 0]  # 拇指外张
    for i, x in [(5, 85), (9, 100), (13, 115), (17, 130)]:  # 四指 MCP
        lm[i] = [x, 140, 0]
        lm[i + 1] = [x, 110, 0]   # PIP
        lm[i + 2] = [x, 85, 0]    # DIP
        lm[i + 3] = [x, 60, 0]    # TIP
    return lm


def test_count_open_hand_is_five():
    r = count_fingers(_open_hand())
    assert r["count"] == 5
    assert all(r["fingers"].values())


def test_count_fist_is_zero():
    lm = _open_hand()
    # 四指折叠：TIP/DIP 收回到 MCP 下方（朝手腕），PIP 弯曲角大
    for mcp in (5, 9, 13, 17):
        x = lm[mcp][0]
        lm[mcp + 1] = [x, 120, 0]
        lm[mcp + 2] = [x, 145, 0]
        lm[mcp + 3] = [x, 165, 0]
    # 拇指收拢贴掌
    lm[2], lm[3], lm[4] = [88, 165, 0], [92, 150, 0], [98, 140, 0]
    r = count_fingers(lm)
    assert r["count"] == 0, r


def test_count_two_fingers():
    lm = _open_hand()
    # 折叠无名指与小指、收拢拇指 → 食指+中指 = 2
    for mcp in (13, 17):
        x = lm[mcp][0]
        lm[mcp + 1] = [x, 120, 0]
        lm[mcp + 2] = [x, 145, 0]
        lm[mcp + 3] = [x, 165, 0]
    lm[2], lm[3], lm[4] = [88, 165, 0], [92, 150, 0], [98, 140, 0]
    r = count_fingers(lm)
    assert r["count"] == 2
    assert r["fingers"]["index"] and r["fingers"]["middle"]
    assert not r["fingers"]["ring"] and not r["fingers"]["pinky"] and not r["fingers"]["thumb"]
