from inference import _crosses


LINE = [0.0, 5.0, 10.0, 5.0]  # 水平线 y=5, x∈[0,10]


def test_cross_forward_is_in():
    # 从下(y=2)到上(y=8)，prev 在负侧 -> 进
    assert _crosses((5.0, 2.0), (5.0, 8.0), LINE) == 1


def test_cross_backward_is_out():
    assert _crosses((5.0, 8.0), (5.0, 2.0), LINE) == -1


def test_same_side_no_cross():
    assert _crosses((5.0, 2.0), (5.0, 3.0), LINE) == 0


def test_movement_outside_line_segment_no_cross():
    # 线段只覆盖 x∈[0,10]，在 x=20 处竖直穿越不应计数
    short = [0.0, 5.0, 10.0, 5.0]
    assert _crosses((20.0, 2.0), (20.0, 8.0), short) == 0
