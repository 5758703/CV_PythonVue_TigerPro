"""球场线检测：兼容 OpenCV 5 HoughLinesP 返回 (N,4) 的形状。"""
import unittest
from unittest.mock import patch

import numpy as np


class TestCourtDetectorHoughShape(unittest.TestCase):
    def test_detect_segments_accepts_2d_hough_output(self):
        from services.court_detector import _detect_court_line_segments

        image = np.zeros((720, 1080, 3), dtype=np.uint8)
        # 模拟 OpenCV 5：HoughLinesP 返回 (N, 4) 而非 (N, 1, 4)
        fake_lines = np.array(
            [
                [100, 200, 900, 210],
                [120, 500, 880, 520],
                [200, 180, 210, 600],
                [800, 190, 820, 610],
            ],
            dtype=np.int32,
        )
        with patch("services.court_detector._build_court_line_mask", return_value=np.zeros((720, 1080), np.uint8)), \
             patch("services.court_detector.cv2.HoughLinesP", return_value=fake_lines):
            horizontal, side, mask = _detect_court_line_segments(image)
        self.assertEqual(mask.shape, (720, 1080))
        self.assertGreaterEqual(len(horizontal) + len(side), 1)

    def test_detect_segments_accepts_3d_hough_output(self):
        from services.court_detector import _detect_court_line_segments

        image = np.zeros((720, 1080, 3), dtype=np.uint8)
        fake_lines = np.array(
            [[[100, 200, 900, 210]], [[120, 500, 880, 520]]],
            dtype=np.int32,
        )
        with patch("services.court_detector._build_court_line_mask", return_value=np.zeros((720, 1080), np.uint8)), \
             patch("services.court_detector.cv2.HoughLinesP", return_value=fake_lines):
            horizontal, side, _mask = _detect_court_line_segments(image)
        self.assertGreaterEqual(len(horizontal), 1)

    def test_detect_court_from_frame_no_crash_on_blank(self):
        from services.court_detector import detect_court_from_frame

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        out = detect_court_from_frame(frame, min_score=120.0)
        self.assertFalse(out["autoDetected"])
        self.assertEqual(out["courtPoints"], [])


if __name__ == "__main__":
    unittest.main()
