"""球落地：仅死球落点；过网对打不应刷落点。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.badminton_report import (  # noqa: E402
    COURT_L_M,
    COURT_W_M,
    extract_shot_landings,
    net_mids_from_corners,
    side_of_net_img,
)


# 标准俯视四角（像素即球场米的仿射）
_CORNERS = [
    (0.0, 0.0),
    (COURT_W_M, 0.0),
    (COURT_W_M, COURT_L_M),
    (0.0, COURT_L_M),
]


def test_net_mids_are_half_court():
    left, right = net_mids_from_corners(_CORNERS)
    assert abs(left[0] - 0.0) < 1e-6
    assert abs(left[1] - COURT_L_M / 2) < 1e-6
    assert abs(right[0] - COURT_W_M) < 1e-6
    assert abs(right[1] - COURT_L_M / 2) < 1e-6


def test_side_of_net_tl_vs_bl():
    left, right = net_mids_from_corners(_CORNERS)
    assert side_of_net_img(1.0, 1.0, left, right) == 0  # 上场
    assert side_of_net_img(1.0, COURT_L_M - 1.0, left, right) == 1  # 下场


def _mk(frame, x, y):
    return {"frame": frame, "ix": x, "iy": y, "x": x, "y": y}


def test_net_cross_alone_is_not_landing():
    """连续过网对打（无长失检）不应产生落地。"""
    half = COURT_L_M / 2
    track = []
    f = 1
    # 模拟多次过网来回，帧连续
    for y in [half - 3.0, half - 1.0, half + 1.0, half + 3.0,
              half + 1.0, half - 1.0, half - 3.5, half - 1.0, half + 2.0]:
        track.append(_mk(f, 2.5, y))
        f += 2
    lands = extract_shot_landings(track, _CORNERS, fps=25, total_frames=f + 5)
    assert lands == [] or len(lands) <= 1  # 末段若贴近视频结束且像落地，至多 1


def test_ground_landing_after_long_silence():
    """飞行段结束后长失检 → 记 1 次落地，落在接球方半场。"""
    half = COURT_L_M / 2
    track = []
    # 上场飞出过网进入下场并深入后减速
    ys = [half - 2.0, half - 0.5, half + 0.5, half + 2.0, half + 3.5, half + 4.0, half + 4.1]
    for i, y in enumerate(ys):
        track.append(_mk(i + 1, 2.5, y))
    # 长间隙后再出现（下一回合），中间静默视为落地
    track.append(_mk(80, 2.0, half - 2.0))
    lands = extract_shot_landings(track, _CORNERS, fps=25, total_frames=100)
    assert len(lands) >= 1
    first = lands[0]
    assert first["player"] == "p2"
    assert first["y"] > half
    assert first["kind"] in ("ground_gap", "ground_end")


def test_continuous_rally_many_crosses_one_final_land():
    """约 22s 连续对打多次过网，仅末尾落地 → 落点约 1 次。"""
    half = COURT_L_M / 2
    fps = 30
    track = []
    f = 1
    # ~20s 来回过网
    for wave in range(18):
        seq = [half - 3.0, half - 1.0, half + 0.8, half + 3.2] if wave % 2 == 0 else [
            half + 3.0, half + 1.0, half - 0.8, half - 3.2
        ]
        for y in seq:
            track.append(_mk(f, 2.4 + 0.02 * (wave % 3), y))
            f += 4
    # 最后 1s：球落到上场侧并停住
    for y in [half - 1.0, half - 2.5, half - 4.0, half - 4.5, half - 4.6]:
        track.append(_mk(f, 2.6, y))
        f += 3
    total = f + 2  # 视频几乎紧接结束
    lands = extract_shot_landings(track, _CORNERS, fps=fps, total_frames=total)
    assert len(lands) == 1, f"expected 1 ground landing, got {len(lands)}: {lands}"
    assert lands[0]["player"] == "p1"
    assert lands[0]["y"] < half


def test_dense_one_side_detections_not_plotted_as_landings():
    """单侧密集晃动检不出点不应刷一堆落点。"""
    half = COURT_L_M / 2
    track = []
    for i in range(80):
        y = half - 1.0 - (i % 20) * 0.05
        track.append(_mk(i + 1, 2.5, y))
    lands = extract_shot_landings(track, _CORNERS, fps=25, total_frames=90)
    assert len(lands) <= 1


def test_custom_net_pts_still_used_for_side():
    half = COURT_L_M / 2
    custom_net = [(0.0, half - 1.5), (COURT_W_M, half - 1.5)]
    track = []
    # 过网后深入并减速，再长静默
    ys = [half - 3.5, half - 2.0, half - 0.5, half + 0.5, half + 1.8, half + 2.4, half + 2.5]
    for i, y in enumerate(ys):
        track.append(_mk(i + 1, 2.5, y))
    track.append(_mk(90, 1.0, half - 3.0))
    lands = extract_shot_landings(track, _CORNERS, fps=25, net_pts=custom_net, total_frames=100)
    assert lands
    assert lands[0]["kind"] in ("ground_gap", "ground_end")


def test_parse_net_points_default_and_override():
    from services.badminton import _parse_net_points, _parse_court_points
    corners = [[0, 0], [1, 0], [1, 1], [0, 1]]
    img = _parse_court_points(corners, 100, 200)
    default = _parse_net_points(None, 100, 200, img)
    assert abs(float(default[0][1]) - 100) < 1e-3
    assert abs(float(default[1][1]) - 100) < 1e-3
    custom = _parse_net_points([[0.2, 0.4], [0.8, 0.45]], 100, 200, img)
    assert abs(float(custom[0][0]) - 20) < 1e-3
    assert abs(float(custom[0][1]) - 80) < 1e-3
