"""手势识别多模型合并逻辑单测。"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.handpose_multi import merge_estimate_results  # noqa: E402


def test_merge_both_engines():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    mp = {
        "displayText": "2 1",
        "leftDigit": 1,
        "rightDigit": 2,
        "hands": [{"digit": 1}],
        "primaryDigit": 2,
        "totalCount": 2,
        "extendedTotal": 3,
    }
    csl = {
        "displayText": "A",
        "labelZh": "A（啊）",
        "primaryLabel": "A",
        "confidence": 0.9,
        "detections": [{"className": "A", "bbox": [1, 2, 3, 4], "confidence": 0.9}],
        "classes": ["A"],
        "count": 1,
    }
    data = merge_estimate_results(img, ["mediapipe", "csl-yolo11s"], mp, csl, draw=False)
    assert data["recognizers"] == ["mediapipe", "csl-yolo11s"]
    assert data["digitText"] == "2 1"
    assert data["signText"] == "A"
    assert data["displayText"] == "2 1 | A"
    assert data["hands"] and data["detections"]


def test_merge_single_mediapipe():
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    mp = {"displayText": "5", "hands": [], "primaryDigit": 5, "totalCount": 5, "extendedTotal": 5}
    data = merge_estimate_results(img, ["mediapipe"], mp, None, draw=False)
    assert data["recognizer"] == "mediapipe"
    assert data["displayText"] == "5"
    assert data["signText"] is None


def test_merge_single_csl():
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    csl = {
        "displayText": "B",
        "labelZh": "B（波）",
        "detections": [],
        "primaryLabel": "B",
        "confidence": 0.8,
        "count": 0,
    }
    data = merge_estimate_results(img, ["csl-yolo11s"], None, csl, draw=False)
    assert data["recognizer"] == "csl-yolo11s"
    assert data["displayText"] == "B"
    assert data["digitText"] is None
