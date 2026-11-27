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


def test_live_bytetrack_recovers_low_frame_and_rejects_weak_new_track(monkeypatch):
    import cv2
    import numpy as np
    import torch
    from ultralytics import YOLO
    from ultralytics.models.yolo.detect.predict import DetectionPredictor
    import inference

    # Inject detector scores before real NMS, preserving tracking callbacks,
    # new-track activation, the second association and the public frame result.
    scores = iter([0.90, 0.15, 0.90, 0.15, 0.50])
    def predictions(self, img, *args, **kwargs):
        return torch.tensor([[[8., 8., 32., 32., next(scores), 0.]]])

    monkeypatch.setattr(DetectionPredictor, "inference", predictions)
    model = YOLO("yolo11n.yaml")
    monkeypatch.setattr(inference, "_get_model", lambda _: model)
    raw = cv2.imencode(".png", np.zeros((64, 64, 3), np.uint8))[1].tobytes()
    def frame(reset=False, conf=0.25):
        return inference.track_frame("test", raw, imgsz=64, conf=conf, reset=reset)["detections"]

    first = frame(reset=True)[0]["trackId"]
    assert first is not None
    low = frame()[0]
    assert low["trackId"] == first and low["confidence"] == 0.15
    assert frame()[0]["trackId"] == first
    assert frame(reset=True) == []
    assert frame(conf=0.8) == []
