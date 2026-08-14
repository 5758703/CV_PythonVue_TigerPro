"""handpose 单测：anchors、数手指、Zoo 0-9 手势（不依赖模型权重）。"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.handpose import (  # noqa: E402
    _gen_palm_anchors,
    classify_gesture,
    count_fingers,
    format_display_digits,
    primary_digit,
    resolve_handedness,
)


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


def _fold_fingers(lm, *mcps):
    lm = lm.copy()
    for mcp in mcps:
        x = lm[mcp][0]
        lm[mcp + 1] = [x, 120, 0]
        lm[mcp + 2] = [x, 145, 0]
        lm[mcp + 3] = [x, 165, 0]
    return lm


def _fold_thumb(lm):
    lm = lm.copy()
    lm[2], lm[3], lm[4] = [88, 165, 0], [92, 150, 0], [98, 140, 0]
    return lm


def test_count_open_hand_is_five():
    r = count_fingers(_open_hand())
    assert r["count"] == 5
    assert all(r["fingers"].values())


def test_count_fist_is_zero():
    lm = _fold_thumb(_fold_fingers(_open_hand(), 5, 9, 13, 17))
    r = count_fingers(lm)
    assert r["count"] == 0, r


def test_count_two_fingers():
    lm = _fold_thumb(_fold_fingers(_open_hand(), 13, 17))
    r = count_fingers(lm)
    assert r["count"] == 2
    assert r["fingers"]["index"] and r["fingers"]["middle"]
    assert not r["fingers"]["ring"] and not r["fingers"]["pinky"] and not r["fingers"]["thumb"]


def test_gesture_0_to_5():
    cases = [
        (0, "Zero", _fold_thumb(_fold_fingers(_open_hand(), 5, 9, 13, 17))),
        (1, "One", _fold_thumb(_fold_fingers(_open_hand(), 9, 13, 17))),
        (2, "Two", _fold_thumb(_fold_fingers(_open_hand(), 13, 17))),
        (3, "Three", _fold_thumb(_fold_fingers(_open_hand(), 17))),
        (4, "Four", _fold_thumb(_open_hand())),
        (5, "Five", _open_hand()),
    ]
    for digit, name, lm in cases:
        g = classify_gesture(lm)
        assert g["gesture"] == name, (digit, g)
        assert g["digit"] == digit


def test_gesture_chinese_6_to_9():
    """中式单手：6 拇+小、7 拇+食、8 拇+食+中、9 拇+食+中+无。"""
    cases = [
        (6, "Six", _fold_fingers(_open_hand(), 5, 9, 13)),
        (7, "Seven", _fold_fingers(_open_hand(), 9, 13, 17)),
        (8, "Eight", _fold_fingers(_open_hand(), 13, 17)),
        (9, "Nine", _fold_fingers(_open_hand(), 17)),
    ]
    for digit, name, lm in cases:
        g = classify_gesture(lm)
        assert g["gesture"] == name, (digit, g)
        assert g["digit"] == digit
        # 伸直指数 ≠ 手势数字（旧逻辑会把 6/7 误判为 2）
        assert count_fingers(lm)["count"] != digit


def test_primary_digit_picks_highest_conf():
    hands = [
        {"confidence": 0.7, "digit": 2},
        {"confidence": 0.95, "digit": 6},
    ]
    assert primary_digit(hands) == 6
    assert primary_digit([]) is None


def test_format_display_single_hand():
    assert format_display_digits([
        {"handedness": "Right", "confidence": 0.9, "digit": 2},
    ]) == {"displayText": "2", "leftDigit": None, "rightDigit": 2}
    assert format_display_digits([
        {"handedness": "Left", "confidence": 0.9, "digit": 1},
    ]) == {"displayText": "1", "leftDigit": 1, "rightDigit": None}
    assert format_display_digits([]) == {"displayText": None, "leftDigit": None, "rightDigit": None}


def test_format_display_dual_hands():
    hands = [
        {"handedness": "Left", "confidence": 0.88, "digit": 1},
        {"handedness": "Right", "confidence": 0.92, "digit": 2},
    ]
    assert format_display_digits(hands) == {"displayText": "1.2", "leftDigit": 1, "rightDigit": 2}


def test_format_display_picks_best_per_side():
    hands = [
        {"handedness": "Left", "confidence": 0.6, "digit": 3},
        {"handedness": "Left", "confidence": 0.95, "digit": 1},
        {"handedness": "Right", "confidence": 0.9, "digit": 2},
    ]
    assert format_display_digits(hands)["displayText"] == "1.2"


def test_format_display_same_side_falls_back_to_position():
    """双手被标成同一侧时，按画面位置回退为 左.右（未镜像自拍：右画面=左手）。"""
    hands = [
        # 画面左侧（使用者右手）数字 2
        {"handedness": "Right", "confidence": 0.9, "digit": 2, "bbox": [10, 20, 80, 160]},
        # 画面右侧（使用者左手）数字 1
        {"handedness": "Right", "confidence": 0.88, "digit": 1, "bbox": [200, 20, 280, 160]},
    ]
    r = format_display_digits(hands)
    assert r["displayText"] == "1.2"
    assert r["leftDigit"] == 1
    assert r["rightDigit"] == 2


def test_resolve_handedness_swaps_and_splits_same_side():
    hands = [
        {"handedness": "Right", "confidence": 0.9, "digit": 2, "bbox": [10, 0, 50, 50]},
        {"handedness": "Right", "confidence": 0.85, "digit": 1, "bbox": [200, 0, 250, 50]},
    ]
    out = resolve_handedness(hands, swap_labels=True)
    by_x = sorted(out, key=lambda h: (h["bbox"][0] + h["bbox"][2]) / 2)
    assert by_x[0]["handedness"] == "Right"
    assert by_x[1]["handedness"] == "Left"
    assert format_display_digits(out)["displayText"] == "1.2"


def test_resolve_handedness_swap_distinct_sides():
    hands = [
        {"handedness": "Left", "confidence": 0.9, "digit": 1, "bbox": [10, 0, 50, 50]},
        {"handedness": "Right", "confidence": 0.9, "digit": 2, "bbox": [200, 0, 250, 50]},
    ]
    out = resolve_handedness(hands, swap_labels=True)
    assert {h["handedness"] for h in out} == {"Left", "Right"}
    # 已区分左右时交换：原 Left→Right(1)、原 Right→Left(2) → 显示 2.1
    assert format_display_digits(out)["displayText"] == "2.1"
