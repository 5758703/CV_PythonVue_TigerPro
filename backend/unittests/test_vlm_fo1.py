"""VLM-FO1 解析与 prompt 组装单测（不加载 3B 权重）。"""
from __future__ import annotations


def test_parse_fo1_prediction_to_label_boxes():
    from services.vlm_fo1 import parse_fo1_prediction_to_label_boxes

    bbox_list = [
        [10, 10, 50, 50],
        [60, 60, 100, 100],
        [120, 20, 180, 80],
    ]
    raw = (
        "<ground>cat</ground><objects><region0><region2></objects>"
        "<ground>remote</ground><objects><region1></objects>"
    )
    out = parse_fo1_prediction_to_label_boxes(raw, bbox_list)
    assert "cat" in out
    assert len(out["cat"]) == 2
    assert out["cat"][0] == [10, 10, 50, 50]
    assert out["remote"][0] == [60, 60, 100, 100]


def test_build_target_phrase():
    from services.vlm_fo1 import build_target_phrase

    assert build_target_phrase("左边的猫", None) == "左边的猫"
    assert build_target_phrase("", "cat, dog") == "cat, dog"
    assert build_target_phrase(None, ["helmet", "vest"]) == "helmet, vest"
    assert build_target_phrase("", None) == "object"


def test_label_boxes_to_detections():
    from services.vlm_fo1 import label_boxes_to_detections

    dets = label_boxes_to_detections({"cat": [[1, 2, 3, 4]]}, default_conf=0.7)
    assert dets[0]["className"] == "cat"
    assert dets[0]["confidence"] == 0.7
    assert dets[0]["bbox"] == [1.0, 2.0, 3.0, 4.0]


def test_detect_image_vlm_fo1_mocked(monkeypatch):
    import numpy as np
    import cv2
    import inference

    def fake_ground(model_dir, image_bgr, **kwargs):
        return {
            "detections": [{
                "className": "cat", "classId": 0, "confidence": 0.8,
                "bbox": [5.0, 5.0, 40.0, 40.0],
            }],
            "count": 1,
            "prompt": "cat",
            "proposalCount": 3,
            "rawText": "<ground>cat</ground><objects><region0></objects>",
            "engine": "vlm-fo1",
            "promptClasses": ["cat"],
        }

    monkeypatch.setattr("services.vlm_fo1.ground_image", fake_ground)
    img = np.zeros((48, 48, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    out = inference.detect_image_vlm_fo1("dummy", buf.tobytes(), conf=0.5, draw=False, prompt="cat")
    assert out["engine"] == "vlm-fo1"
    assert out["count"] == 1
    assert out["detections"][0]["className"] == "cat"
