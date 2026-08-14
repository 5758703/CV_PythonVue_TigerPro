"""告警规则引擎单测。"""
import json
import types

from services.alert_engine import (
    active_overlay_kind,
    active_overlay_style,
    evaluate_rules,
    reset_runtime,
    resolve_overlay_style,
)


def _rule(key, rtype, cfg, rid=1):
    return types.SimpleNamespace(
        id=rid,
        rule_key=key,
        name=key,
        rule_type=rtype,
        severity="high" if key == "fire-smoke" else "medium",
        status="0",
        config=lambda c=cfg: c,
    )


def test_fire_smoke_triggers_after_consecutive_frames():
    reset_runtime("cam1")
    rule = _rule(
        "fire-smoke",
        "class_presence",
        {"classes": ["fire", "smoke"], "min_confidence": 0.3, "consecutive_frames": 2, "cooldown_sec": 0},
    )
    dets = [{"className": "fire", "confidence": 0.9, "bbox": [0, 0, 10, 10]}]
    assert evaluate_rules([rule], dets, "cam1") == []
    out = evaluate_rules([rule], dets, "cam1")
    assert len(out) == 1
    assert out[0]["ruleKey"] == "fire-smoke"
    reset_runtime()


def test_active_overlay_kind_prefers_fire_over_crowd():
    reset_runtime()
    fire = _rule(
        "fire-smoke",
        "class_presence",
        {"classes": ["fire"], "min_confidence": 0.3, "consecutive_frames": 1, "cooldown_sec": 0},
        rid=1,
    )
    crowd = _rule(
        "crowd-gathering",
        "count_threshold",
        {"class_name": "person", "min_count": 8, "video_min_count": 2,
         "min_confidence": 0.2, "consecutive_frames": 1, "cooldown_sec": 0},
        rid=2,
    )
    dets = [
        {"className": "fire", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
        {"className": "person", "confidence": 0.8, "bbox": [0, 0, 10, 10]},
        {"className": "person", "confidence": 0.7, "bbox": [20, 0, 30, 10]},
    ]
    assert active_overlay_kind([fire, crowd], dets) == "fire"
    assert active_overlay_kind([crowd], dets, video=True) == "crowd"
    assert active_overlay_kind([crowd], dets) is None  # 2 < min_count 8
    assert active_overlay_kind([crowd], dets[:1]) is None
    reset_runtime()


def test_crowd_count_threshold():
    reset_runtime("cam2")
    rule = _rule(
        "crowd-gathering",
        "count_threshold",
        {"class_name": "person", "min_count": 3, "min_confidence": 0.2, "consecutive_frames": 1, "cooldown_sec": 0},
        rid=2,
    )
    dets = [
        {"className": "person", "confidence": 0.8, "bbox": [0, 0, 10, 10]},
        {"className": "person", "confidence": 0.7, "bbox": [20, 0, 30, 10]},
    ]
    assert evaluate_rules([rule], dets, "cam2") == []
    dets.append({"className": "person", "confidence": 0.6, "bbox": [40, 0, 50, 10]})
    out = evaluate_rules([rule], dets, "cam2")
    assert len(out) == 1
    assert "3" in out[0]["title"]
    assert out[0].get("overlay")
    reset_runtime()


def test_custom_overlay_style_from_rule_config():
    rule = _rule(
        "crowd-gathering",
        "count_threshold",
        {
            "class_name": "person",
            "min_count": 2,
            "min_confidence": 0.2,
            "overlay": {
                "fillColor": "#00FF00",
                "titleLines": ["自定义聚集"],
                "subtitleLines": ["请勿拥挤"],
            },
        },
        rid=9,
    )
    style = resolve_overlay_style(rule)
    assert style["fillColor"] == "#00FF00"
    assert style["titleLines"] == ["自定义聚集"]
    dets = [{"className": "person", "confidence": 0.9, "bbox": [0, 0, 1, 1]}] * 2
    live = active_overlay_style([rule], dets, video=True)
    assert live is not None
    assert live["titleLines"] == ["自定义聚集"]


def test_ppe_no_hardhat_class_presence():
    reset_runtime("ppe1")
    rule = _rule(
        "ppe-no-hardhat",
        "class_presence",
        {
            "classes": ["NO-Hardhat", "no-hardhat"],
            "min_confidence": 0.3,
            "consecutive_frames": 2,
            "cooldown_sec": 0,
        },
        rid=3,
    )
    dets = [{"className": "NO-Hardhat", "confidence": 0.88, "bbox": [10, 10, 40, 40]}]
    assert evaluate_rules([rule], dets, "ppe1") == []
    out = evaluate_rules([rule], dets, "ppe1")
    assert len(out) == 1
    assert out[0]["ruleKey"] == "ppe-no-hardhat"
    assert "安全帽" in out[0]["title"] or "Hardhat" in out[0]["title"] or "NO" in out[0]["title"]
    reset_runtime()


def test_line_crossing_intrusion():
    reset_runtime("track1")
    rule = _rule(
        "line-intrusion",
        "line_crossing",
        {
            "classes": ["person"],
            "line": [0.0, 0.5, 1.0, 0.5],
            "direction": "both",
            "min_confidence": 0.2,
            "consecutive_frames": 1,
            "cooldown_sec": 0,
        },
        rid=4,
    )
    line = [0.0, 0.5, 1.0, 0.5]
    # 第一帧：建立质心（线下方）
    f1 = [{"className": "person", "confidence": 0.9, "bbox": [40, 70, 60, 90], "trackId": 7}]
    assert evaluate_rules(
        [rule], f1, "track1",
        frame_width=100, frame_height=100, line=line, frame_token="t1",
    ) == []
    # 第二帧：穿到线上方 → 越线
    f2 = [{"className": "person", "confidence": 0.9, "bbox": [40, 10, 60, 30], "trackId": 7}]
    out = evaluate_rules(
        [rule], f2, "track1",
        frame_width=100, frame_height=100, line=line, frame_token="t2",
    )
    assert len(out) == 1
    assert out[0]["ruleKey"] == "line-intrusion"
    assert out[0]["detail"]["crossCount"] >= 1
    # 同帧 overlay 应能读到缓存结果
    ov = active_overlay_style(
        [rule], f2,
        frame_width=100, frame_height=100, line=line,
        source_key="track1", frame_token="t2",
    )
    assert ov is not None
    assert ov["ruleKey"] == "line-intrusion"
    reset_runtime()


def test_stranger_face_unmatched():
    reset_runtime("face1")
    rule = _rule(
        "stranger-face",
        "unmatched_face",
        {
            "min_confidence": 0.0,
            "consecutive_frames": 2,
            "cooldown_sec": 0,
        },
        rid=5,
    )
    unknown = [{"className": "unknown", "name": "unknown", "matched": False, "score": 0.12, "bbox": [1, 2, 3, 4]}]
    assert evaluate_rules([rule], unknown, "face1") == []  # 第 1 帧仅累计
    out = evaluate_rules([rule], unknown, "face1")
    assert len(out) == 1
    assert out[0]["ruleKey"] == "stranger-face"
    assert out[0]["detail"]["count"] == 1
    # 已匹配人员不应触发
    reset_runtime("face2")
    known = [{"className": "张三", "name": "张三", "matched": True, "score": 0.8, "bbox": [1, 2, 3, 4]}]
    assert evaluate_rules([rule], known, "face2") == []
    assert evaluate_rules([rule], known, "face2") == []
    reset_runtime()


def _fall_rule(cfg=None, rid=90):
    base = {
        "trunk_angle_deg": 60,
        "centroid_speed": 0.5,
        "height_ratio": 0.5,
        "head_y_ratio": 0.75,
        "weights": {"trunk": 1, "speed": 1, "height": 1, "head": 1},
        "min_score": 2,
        "kp_min_conf": 0.3,
        "stand_baseline_window": 90,
        "track_max_age": 15,
        "consecutive_frames": 2,
        "cooldown_sec": 0,
    }
    base.update(cfg or {})
    return _rule("fall-detection", "fall_detection", base, rid=rid)


def _standing_det(track_id=1, hip_y=260.0, nose_y=60.0, conf=0.9):
    """站立：躯干竖直、鼻在画面上部、肩踝相距 320px。"""
    kp = [[320.0, 100.0, conf] for _ in range(17)]
    kp[0] = [320.0, nose_y, conf]
    kp[5] = [300.0, hip_y - 140.0, conf]
    kp[6] = [340.0, hip_y - 140.0, conf]
    kp[11] = [305.0, hip_y, conf]
    kp[12] = [335.0, hip_y, conf]
    kp[15] = [305.0, hip_y + 180.0, conf]
    kp[16] = [335.0, hip_y + 180.0, conf]
    return {"className": "person", "confidence": 0.9, "trackId": track_id,
            "bbox": [290.0, hip_y - 160.0, 350.0, hip_y + 190.0], "keypoints": kp}


def _lying_det(track_id=1, y=430.0, conf=0.9):
    """卧地：肩髋左右分布且等高、鼻贴近画面底部、躯干高度骤降。"""
    kp = [[300.0, y, conf] for _ in range(17)]
    kp[0] = [200.0, y - 5.0, conf]
    kp[5] = [240.0, y - 10.0, conf]
    kp[6] = [240.0, y + 10.0, conf]
    kp[11] = [360.0, y - 10.0, conf]
    kp[12] = [360.0, y + 10.0, conf]
    kp[15] = [460.0, y - 40.0, conf]
    kp[16] = [460.0, y - 30.0, conf]
    return {"className": "person", "confidence": 0.9, "trackId": track_id,
            "bbox": [190.0, y - 30.0, 470.0, y + 30.0], "keypoints": kp}


def _eval(rule, dets, src, ts, token):
    return evaluate_rules([rule], dets, src, now_ts=ts,
                          frame_width=640, frame_height=480, frame_token=token)


def test_fall_triggers_after_consecutive_frames():
    reset_runtime("fall1")
    rule = _fall_rule()
    # 前三帧站立：建立站立高度基线
    assert _eval(rule, [_standing_det()], "fall1", 100.0, "f1") == []
    assert _eval(rule, [_standing_det()], "fall1", 100.1, "f2") == []
    assert _eval(rule, [_standing_det()], "fall1", 100.2, "f3") == []
    # 下坠 + 卧地：连续两帧达标才触发
    assert _eval(rule, [_lying_det()], "fall1", 100.3, "f4") == []
    out = _eval(rule, [_lying_det()], "fall1", 100.4, "f5")
    assert len(out) == 1
    assert out[0]["ruleKey"] == "fall-detection"
    assert out[0]["detail"]["fallen"][0]["fallScore"] >= 2
    reset_runtime()


def test_fall_single_indicator_does_not_trigger():
    reset_runtime("fall2")
    # 只开躯干角权重，min_score=2 -> 单指标永远达不到
    rule = _fall_rule({"weights": {"trunk": 1, "speed": 0, "height": 0, "head": 0},
                       "consecutive_frames": 1})
    for i in range(4):
        assert _eval(rule, [_lying_det()], "fall2", 100.0 + i * 0.1, f"s{i}") == []
    reset_runtime()


def test_fall_low_confidence_keypoints_no_trigger():
    reset_runtime("fall3")
    rule = _fall_rule({"consecutive_frames": 1})
    for i in range(4):
        assert _eval(rule, [_lying_det(conf=0.05)], "fall3", 100.0 + i * 0.1, f"l{i}") == []
    reset_runtime()


def test_fall_isolates_two_tracks():
    reset_runtime("fall4")
    rule = _fall_rule({"consecutive_frames": 1})
    for i in range(3):
        _eval(rule, [_standing_det(1), _standing_det(2, hip_y=250.0)],
              "fall4", 100.0 + i * 0.1, f"a{i}")
    out = _eval(rule, [_lying_det(1), _standing_det(2, hip_y=250.0)],
                "fall4", 100.4, "a9")
    assert len(out) == 1
    # 只有 track 1 跌倒；track 2 的站立基线未被污染，仍判定为正常
    assert [f["trackId"] for f in out[0]["detail"]["fallen"]] == [1]
    assert out[0]["detail"]["fallenCount"] == 1
    reset_runtime()
