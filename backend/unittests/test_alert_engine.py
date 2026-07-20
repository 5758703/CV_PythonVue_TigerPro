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
