"""正式比赛回合判定：容忍对打中丢检，不因短失检切成多回合。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.badminton import _RallyTracker  # noqa: E402


def test_continuous_play_with_detection_gaps_is_one_rally():
    """22s 级连续对打，中间多次 1~2s 丢检，应仍为 1 回合。"""
    fps = 30
    rt = _RallyTracker(fps)
    total = int(22 * fps)
    # 每 2s 丢检约 1.5s（旧逻辑会切回合；新逻辑 3.5s 才切）
    for f in range(total):
        phase = f % int(fps * 3.5)
        if phase < int(fps * 2.0):
            rt.on_ball()
        else:
            rt.on_miss()
    rt.finalize()
    assert rt.rally_count == 1, f"got {rt.rally_count} rallies, lengths={rt.lengths}"
    assert len(rt.lengths) == 1


def test_two_points_separated_by_dead_ball():
    """两分之间有足够长死球间隔 → 2 回合。"""
    fps = 25
    rt = _RallyTracker(fps)
    for _ in range(int(fps * 3)):
        rt.on_ball()
    for _ in range(int(fps * 4)):  # > 3.5s dead
        rt.on_miss()
    for _ in range(int(fps * 3)):
        rt.on_ball()
    rt.finalize()
    assert rt.rally_count == 2
    assert len(rt.lengths) == 2


def test_short_blip_not_counted():
    """不足最短时长的闪检不计入回合。"""
    fps = 30
    rt = _RallyTracker(fps)
    for _ in range(5):  # << 0.8s
        rt.on_ball()
    for _ in range(int(fps * 4)):
        rt.on_miss()
    rt.finalize()
    assert rt.rally_count == 0
    assert rt.lengths == []


def test_old_1_5s_gap_does_not_split():
    """旧阈值 1.5s 失检在新逻辑下不应结束回合。"""
    fps = 30
    rt = _RallyTracker(fps)
    for _ in range(int(fps * 2)):
        rt.on_ball()
    ended_any = False
    cleared_any = False
    for _ in range(int(fps * 1.5)):
        clear, ended = rt.on_miss()
        ended_any = ended_any or ended
        cleared_any = cleared_any or clear
    assert not ended_any
    assert cleared_any  # 尾迹可清，回合仍在
    for _ in range(int(fps * 2)):
        rt.on_ball()
    rt.finalize()
    assert rt.rally_count == 1
