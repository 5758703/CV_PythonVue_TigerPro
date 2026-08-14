"""跌倒检测关键点指标与轻量跟踪器单测。"""
from services.fall_detect import build_person_detections, keypoint_metrics


def _kp(overrides=None, conf=0.9):
    """构造 COCO-17 关键点，默认站立姿态（画面 640x480）。"""
    pts = [[320.0, 100.0, conf] for _ in range(17)]
    pts[0] = [320.0, 60.0, conf]    # 鼻
    pts[5] = [300.0, 120.0, conf]   # 左肩
    pts[6] = [340.0, 120.0, conf]   # 右肩
    pts[11] = [305.0, 260.0, conf]  # 左髋
    pts[12] = [335.0, 260.0, conf]  # 右髋
    pts[15] = [305.0, 440.0, conf]  # 左踝
    pts[16] = [335.0, 440.0, conf]  # 右踝
    for idx, val in (overrides or {}).items():
        pts[idx] = val
    return pts


def test_metrics_standing_trunk_angle_near_zero():
    m = keypoint_metrics(_kp(), 640, 480)
    assert m["valid"]["trunk"] is True
    assert m["trunkAngle"] < 5.0
    assert m["hipY"] == 260.0
    assert m["bodyHeight"] == 320.0


def test_metrics_lying_trunk_angle_near_ninety():
    # 侧躺：肩在髋左侧、两者等高
    kp = _kp({5: [180.0, 300.0, 0.9], 6: [180.0, 320.0, 0.9],
              11: [320.0, 300.0, 0.9], 12: [320.0, 320.0, 0.9]})
    m = keypoint_metrics(kp, 640, 480)
    assert 85.0 < m["trunkAngle"] < 95.0


def test_metrics_low_confidence_marks_invalid():
    m = keypoint_metrics(_kp(conf=0.1), 640, 480)
    assert m["valid"] == {"trunk": False, "hip": False, "ankle": False, "nose": False}
    assert m["trunkAngle"] is None
    assert m["bodyHeight"] is None


def test_build_person_detections_bbox_within_frame():
    dets = build_person_detections([{"keypoints": _kp()}], 640, 480)
    assert len(dets) == 1
    x1, y1, x2, y2 = dets[0]["bbox"]
    assert 0.0 <= x1 < x2 <= 640.0
    assert 0.0 <= y1 < y2 <= 480.0
    assert dets[0]["className"] == "person"
    assert dets[0]["keypoints"] is not None


def test_build_person_detections_skips_all_low_conf():
    assert build_person_detections([{"keypoints": _kp(conf=0.05)}], 640, 480) == []


from services.fall_detect import assign_track_ids, reset_tracker


def _det(cx, cy, w=60.0, h=160.0):
    """构造带 bbox 与髋关键点的检测框（所有关键点置于框中心）。"""
    kp = [[cx, cy, 0.9] for _ in range(17)]
    return {
        "className": "person",
        "confidence": 0.9,
        "bbox": [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
        "keypoints": kp,
    }


def test_tracker_keeps_id_for_small_motion():
    reset_tracker("t1")
    first = assign_track_ids([_det(300.0, 240.0)], "t1")
    tid = first[0]["trackId"]
    second = assign_track_ids([_det(306.0, 246.0)], "t1")
    assert second[0]["trackId"] == tid
    reset_tracker("t1")


def test_tracker_assigns_new_id_after_max_age():
    reset_tracker("t2")
    first = assign_track_ids([_det(300.0, 240.0)], "t2", max_age=2)
    tid = first[0]["trackId"]
    for _ in range(3):
        assign_track_ids([], "t2", max_age=2)
    again = assign_track_ids([_det(300.0, 240.0)], "t2", max_age=2)
    assert again[0]["trackId"] != tid
    reset_tracker("t2")


def test_tracker_separates_two_people():
    reset_tracker("t3")
    out = assign_track_ids([_det(150.0, 240.0), _det(500.0, 240.0)], "t3")
    assert out[0]["trackId"] != out[1]["trackId"]
    out2 = assign_track_ids([_det(155.0, 242.0), _det(505.0, 238.0)], "t3")
    assert out2[0]["trackId"] == out[0]["trackId"]
    assert out2[1]["trackId"] == out[1]["trackId"]
    reset_tracker("t3")


def test_reset_tracker_all_clears_ids():
    reset_tracker()
    a = assign_track_ids([_det(300.0, 240.0)], "t4")[0]["trackId"]
    reset_tracker()
    b = assign_track_ids([_det(300.0, 240.0)], "t4")[0]["trackId"]
    assert a == b == 1
    reset_tracker()
