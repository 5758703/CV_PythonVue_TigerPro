from __future__ import annotations

import math

import cv2
import numpy as np

from services.squat_counter import SquatConfig
from services.squat_video import annotate_squat_frame, process_squat_video


def _person(angle: float):
    radians = math.radians(angle)
    points = [[0.0, 0.0, 0.0] for _ in range(17)]
    for x, indices in ((20.0, (11, 13, 15)), (44.0, (12, 14, 16))):
        values = (
            (x, 12.0, 0.95),
            (x, 32.0, 0.95),
            (x + 20.0 * math.sin(radians), 32.0 - 20.0 * math.cos(radians), 0.95),
        )
        for index, value in zip(indices, values):
            points[index] = list(value)
    return {"bbox": [8, 5, 56, 60], "score": 0.95, "keypoints": points}


class SequenceEstimator:
    def __init__(self, angles):
        self.angles = iter(angles)

    def infer(self, _frame):
        return [_person(next(self.angles))]


def _write_video(path, frame_count=6, fps=10.0):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 64))
    assert writer.isOpened()
    try:
        for index in range(frame_count):
            writer.write(np.full((64, 64, 3), index * 20, dtype=np.uint8))
    finally:
        writer.release()


def test_annotate_squat_frame_does_not_mutate_input():
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    original = frame.copy()
    annotated = annotate_squat_frame(frame, {
        "count": 2,
        "stage": "bottom",
        "kneeAngle": 92.4,
        "trackingStatus": "tracking",
        "primaryPerson": _person(92),
    })
    assert np.array_equal(frame, original)
    assert not np.array_equal(annotated, original)


def test_process_video_counts_and_reports_progress(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    _write_video(source)
    progress = []

    stats = process_squat_video(
        SequenceEstimator([170, 170, 95, 95, 170, 170]),
        source,
        output,
        SquatConfig(confirm_frames=2, smoothing_window=1),
        progress_cb=lambda processed, total: progress.append((processed, total)),
    )

    assert output.is_file() and output.stat().st_size > 0
    assert stats["frames"] == 6
    assert stats["count"] == 1
    assert stats["repTimestamps"] == [0.5]
    assert stats["fps"] == 10.0
    assert stats["processedFps"] > 0
    assert progress[-1] == (6, 6)


def test_process_video_uses_browser_playable_h264(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    _write_video(source)

    process_squat_video(
        SequenceEstimator([170, 170, 95, 95, 170, 170]),
        source,
        output,
        SquatConfig(confirm_frames=2, smoothing_window=1),
    )

    capture = cv2.VideoCapture(str(output))
    assert capture.isOpened()
    try:
        fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
    finally:
        capture.release()
    codec = "".join(chr((fourcc >> (8 * index)) & 0xFF) for index in range(4)).lower()
    assert codec in {"avc1", "h264", "x264"}


def test_process_video_releases_output_when_estimator_fails(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    _write_video(source, frame_count=2)

    class BrokenEstimator:
        def infer(self, _frame):
            raise RuntimeError("pose failed")

    try:
        process_squat_video(BrokenEstimator(), source, output, SquatConfig())
    except RuntimeError as exc:
        assert str(exc) == "pose failed"
    else:
        raise AssertionError("expected estimator failure")

    if not output.exists():
        output.write_bytes(b"")
    assert output.rename(tmp_path / "released.mp4").exists()
