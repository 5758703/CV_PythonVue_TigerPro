"""告警规则引擎单测。"""
import json
import math
import types

from services.alert_engine import (
    active_overlay_kind,
    active_overlay_style,
    evaluate_rules,
    reset_runtime,
    resolve_overlay_style,
)
from services.fall_detect import reset_tracker


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


def _eval(rule, dets, src, ts, token, source_type=None):
    return evaluate_rules([rule], dets, src, now_ts=ts,
                          frame_width=640, frame_height=480, frame_token=token,
                          source_type=source_type)


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


def _bending_det(track_id=1, hip_y=260.0, theta_deg=65.0, conf=0.9):
    """缓慢弯腰：仅躯干角越阈，髋部不下坠（速度=0）、鼻部仍在画面上部、
    肩→踝纵向跨度相对站立基线未显著缩短（身高比未低于阈值）。

    躯干长度固定为 140（与 _standing_det 的肩髋距一致），围绕髋部旋转 theta_deg，
    鼻子沿同一方向延伸到距髋 200（= 躯干140 + 站立时鼻肩差60）处，双脚不动。
    """
    theta = math.radians(theta_deg)
    hip_x = 320.0
    trunk_len = 140.0
    dx = trunk_len * math.sin(theta)
    dy = -trunk_len * math.cos(theta)
    shoulder_x = hip_x + dx
    shoulder_y = hip_y + dy
    nose_dist = trunk_len + 60.0
    nose_x = hip_x + nose_dist * math.sin(theta)
    nose_y = hip_y - nose_dist * math.cos(theta)
    kp = [[hip_x, hip_y, conf] for _ in range(17)]
    kp[0] = [nose_x, nose_y, conf]
    kp[5] = [shoulder_x - 15.0, shoulder_y, conf]
    kp[6] = [shoulder_x + 15.0, shoulder_y, conf]
    kp[11] = [hip_x - 15.0, hip_y, conf]
    kp[12] = [hip_x + 15.0, hip_y, conf]
    kp[15] = [hip_x - 15.0, hip_y + 180.0, conf]
    kp[16] = [hip_x + 15.0, hip_y + 180.0, conf]
    return {"className": "person", "confidence": conf, "trackId": track_id,
            "bbox": [200.0, hip_y - 220.0, 440.0, hip_y + 210.0], "keypoints": kp}


def test_fall_slow_bend_only_trunk_indicator_does_not_trigger():
    """四指标全开、min_score=2 时，仅躯干角越阈的缓慢弯腰不得触发——这是对抗
    「老人主动弯腰/躺下」误报的核心防线，必须验证是「只有一个指标命中」而不是
    「凑分不够」才不触发。四指标算术验算（hip_y=260, theta=65°, frame 640x480）：
      trunk：dx=140*sin65°≈126.9，dy=-140*cos65°≈-59.16，
             trunkAngle=atan2(126.9,59.16)=65° > 60° 阈值 → 命中(+1)
      speed：髋部三帧站立后本帧仍在 hip_y=260，位移为 0 → v=0 < 0.5 阈值 → 不命中
      height：肩y=260-59.16=200.84，踝y=260+180=440，bodyHeight=|200.84-440|=239.16；
             基线（3 帧站立）body_height=320；ratio=239.16/320≈0.747，
             未低于 0.5 阈值 → 不命中
      head：鼻y=260-200*cos65°≈175.48，head_ratio=175.48/480≈0.366，
            未高于 0.75 阈值 → 不命中
      总分=1（仅 trunk）< min_score(2) → 不触发
    """
    reset_runtime("fall2b")
    rule = _fall_rule({"consecutive_frames": 1})
    # 前三帧站立：建立身高比基线（body_height=320）
    for i in range(3):
        assert _eval(rule, [_standing_det()], "fall2b", 100.0 + i * 0.1, f"bend{i}") == []
    out = _eval(rule, [_bending_det()], "fall2b", 100.3, "bend3")
    assert out == []
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


from services.alert_engine import fall_detections


def test_fall_detections_returns_synthetic_box():
    reset_runtime("fall5")
    rule = _fall_rule({"consecutive_frames": 1}, rid=95)
    for i in range(3):
        _eval(rule, [_standing_det()], "fall5", 100.0 + i * 0.1, f"b{i}")
    dets = [_lying_det()]
    _eval(rule, dets, "fall5", 100.4, "b9")
    boxes = fall_detections([rule], dets, source_key="fall5", frame_width=640,
                            frame_height=480, frame_token="b9", now_ts=100.4)
    assert len(boxes) == 1
    box = boxes[0]
    assert box["className"] == "fall"
    assert box["synthetic"] is True
    assert len(box["bbox"]) == 4
    assert box["trackId"] == 1
    assert box["ruleKey"] == "fall-detection"
    assert set(box["indicators"]) >= {"trunk", "height", "head"}
    reset_runtime()


def test_fall_frame_token_is_idempotent():
    reset_runtime("fall6")
    rule = _fall_rule({"consecutive_frames": 1}, rid=96)
    for i in range(3):
        _eval(rule, [_standing_det()], "fall6", 100.0 + i * 0.1, f"c{i}")
    dets = [_lying_det()]
    _eval(rule, dets, "fall6", 100.4, "c9")
    first = fall_detections([rule], dets, source_key="fall6", frame_width=640,
                            frame_height=480, frame_token="c9", now_ts=100.4)
    active_overlay_style([rule], dets, frame_width=640, frame_height=480,
                         source_key="fall6", frame_token="c9")
    second = fall_detections([rule], dets, source_key="fall6", frame_width=640,
                             frame_height=480, frame_token="c9", now_ts=100.4)
    assert first[0]["indicators"]["speed"] == second[0]["indicators"]["speed"]
    reset_runtime()


def test_fall_detections_empty_when_no_fall():
    reset_runtime("fall7")
    rule = _fall_rule({"consecutive_frames": 1}, rid=97)
    dets = [_standing_det()]
    _eval(rule, dets, "fall7", 100.0, "d1")
    assert fall_detections([rule], dets, source_key="fall7", frame_width=640,
                           frame_height=480, frame_token="d1", now_ts=100.0) == []
    reset_runtime()


def test_fall_overlay_theme_and_priority():
    reset_runtime()
    fall = _fall_rule({"consecutive_frames": 1}, rid=98)
    crowd = _rule(
        "crowd-gathering",
        "count_threshold",
        {"class_name": "person", "min_count": 1, "min_confidence": 0.2,
         "consecutive_frames": 1, "cooldown_sec": 0},
        rid=99,
    )
    for i in range(3):
        _eval(fall, [_standing_det()], "fall8", 100.0 + i * 0.1, f"e{i}")
    dets = [_lying_det()]
    _eval(fall, dets, "fall8", 100.4, "e9")
    style = active_overlay_style([fall, crowd], dets, frame_width=640,
                                 frame_height=480, source_key="fall8", frame_token="e9")
    assert style["ruleKey"] == "fall-detection"
    assert style["fillColor"] == "#CF1322"
    assert style["titleLines"] == ["FALL DETECTED"]
    reset_runtime()


def test_fall_title_message():
    reset_runtime("fall9")
    rule = _fall_rule({"consecutive_frames": 1}, rid=100)
    for i in range(3):
        _eval(rule, [_standing_det()], "fall9", 100.0 + i * 0.1, f"g{i}")
    out = _eval(rule, [_lying_det()], "fall9", 100.4, "g9")
    assert len(out) == 1
    assert "跌倒" in out[0]["title"]
    assert "1 人" in out[0]["title"]
    assert "急救" in out[0]["message"]
    reset_runtime()


def test_fall_cold_start_without_fall_evidence_never_triggers():
    """基线未建立（站立基线帧数 < 3，从未有过「非跌倒」帧）且从无下坠证据（质心
    速度指标从未越阈）时，即便躯干角+头部两指标凑够 min_score，也不得判定跌倒。

    覆盖场景：取流开始时目标就已处于当前姿态（如坐在低矮沙发上），躯干角刚好
    过 60° 且鼻部偏下，若不加此门控，会被误判为跌倒 → 该 track 因为「一直被判定
    为跌倒」永远拿不到非跌倒帧 → 站立基线永远建不起来 → 每次 cooldown_sec 后
    复触，形成误报自锁。此处每帧姿态、时间戳都保持完全不变（无下坠动作），
    验证该场景下永不触发。
    """
    reset_runtime("fall_cold1")
    rule = _fall_rule({"consecutive_frames": 1})
    for i in range(6):
        out = _eval(rule, [_lying_det()], "fall_cold1", 100.0 + i * 0.1, f"cold{i}")
        assert out == []
    reset_runtime()


def test_fall_cold_start_with_fast_drop_still_triggers():
    """基线未建立，但存在真实下坠（质心速度越阈）时应正常触发，且一旦跌倒事件
    已经开始（tr["since"] 已置位），后续卧地不动（无下坠）的帧不应被冷启动门控
    重新拦截——否则真实跌倒也会被该门控误伤，无法凑满 consecutive_frames。

    序列：仅 1 帧站立（standHist 远未达到 3 帧基线门槛）→ 快速下坠一帧（髋部
    从 260 猛降到 430，dt=0.1s，v=170/0.1/480≈3.54 远超 0.5 阈值，是「下坠证据」）
    → 两帧卧地不动（v≈0，但事件已开始，不应被二次拦截）。consecutive_frames=3。
    """
    reset_runtime("fall_cold2")
    rule = _fall_rule({"consecutive_frames": 3})
    assert _eval(rule, [_standing_det()], "fall_cold2", 100.0, "drop0") == []
    assert _eval(rule, [_lying_det()], "fall_cold2", 100.1, "drop1") == []  # streak 1/3，下坠证据触发首帧判定
    assert _eval(rule, [_lying_det()], "fall_cold2", 100.2, "drop2") == []  # streak 2/3，无下坠但事件已开始
    out = _eval(rule, [_lying_det()], "fall_cold2", 100.3, "drop3")  # streak 3/3 → 触发
    assert len(out) == 1
    reset_runtime()


def test_fall_cold_start_gate_exempts_image_source_type():
    """图片模式（source_type="image"）豁免冷启动门控：每次检测都是独立单帧、
    无上一帧、无基线，若仍套用门控会导致图片模式恒判定不触发（回归修复）。

    用与 test_fall_cold_start_without_fall_evidence_never_triggers 完全相同的
    「取流即已倒地、无下坠」序列，camera 不触发、image 触发——两条断言对比
    才能证明豁免只影响 source_type，而不是把门控整个拆掉。
    """
    reset_runtime("fall_cold_cam")
    rule_cam = _fall_rule({"consecutive_frames": 1}, rid=104)
    out_cam = _eval(rule_cam, [_lying_det()], "fall_cold_cam", 100.0, "camsrc0",
                     source_type="camera")
    assert out_cam == []  # 摄像头模式：门控行为必须与之前一字不变
    reset_runtime()

    reset_runtime("fall_cold_img")
    rule_img = _fall_rule({"consecutive_frames": 1}, rid=105)
    out_img = _eval(rule_img, [_lying_det()], "fall_cold_img", 100.0, "imgsrc0",
                     source_type="image")
    assert len(out_img) == 1  # 图片模式：豁免门控，score>=min_score 当帧即触发
    reset_runtime()


def test_fall_cold_start_gate_exempts_speed_weight_disabled():
    """weights.speed=0 时管理员已主动关闭速度指标，speed_hit 永远无法为 True，
    再拿它当冷启动准入条件会让该 track 永久无法首次触发——门控需豁免这种配置。
    """
    reset_runtime("fall_cold_nospeed")
    rule = _fall_rule({
        "weights": {"trunk": 1, "speed": 0, "height": 1, "head": 1},
        "consecutive_frames": 1,
    }, rid=106)
    out = _eval(rule, [_lying_det()], "fall_cold_nospeed", 100.0, "nospeed0")
    assert len(out) == 1
    reset_runtime()


def test_fall_config_clamps_min_score_track_age_and_weights():
    """PUT /api/ai/alert/rules/:id 可直传 config，绕过前端 el-input-number 的 :min
    校验；min_score=0 会让站立当帧即判跌倒，track_max_age=0 会让跟踪永远建立不起来，
    负权重会反向减分——三者都需要服务端下限兜底（M-2）。"""
    from services.alert_engine import fall_config

    out = fall_config({
        "min_score": 0,
        "track_max_age": 0,
        "weights": {"trunk": -1, "speed": 1, "height": 1, "head": 1},
    })
    assert out["min_score"] >= 0.5
    assert out["track_max_age"] >= 1
    assert out["weights"]["trunk"] >= 0.0


def test_fall_config_clamps_kp_min_conf():
    """kp_min_conf<=0 会让 I-1 的哨兵置信度 bug 原样复现（_track_anchor 的
    `c >= min_conf` 判据在 min_conf<=0 时对 conf=0 的哨兵值恒真），也会让
    build_person_detections 把哨兵点纳入 bbox 计算。config 解析入口需要下限
    兜底（回归修复 Must-fix 3）。"""
    from services.alert_engine import fall_config

    assert fall_config({"kp_min_conf": 0})["kp_min_conf"] > 0
    assert fall_config({"kp_min_conf": -0.5})["kp_min_conf"] > 0


def test_fall_default_consecutive_frames_is_eight_when_config_missing_key():
    """引擎兜底的 default_consec 分支：config 缺 consecutive_frames 时，fall_detection
    应回落到 8（与 seed 默认值、前端一致），而不是与其它规则共用的 2（M-5）。

    先跑 3 帧站立建立基线，绕开冷启动门控（本测试目标是 default_consec 兜底值，
    不是冷启动门控），再跑 8 帧卧地：前 7 帧只累计 streak，第 8 帧才触发。
    """
    reset_runtime("fall_m5")
    cfg = {
        "trunk_angle_deg": 60, "centroid_speed": 0.5, "height_ratio": 0.5,
        "head_y_ratio": 0.75, "weights": {"trunk": 1, "speed": 1, "height": 1, "head": 1},
        "min_score": 2, "kp_min_conf": 0.3, "stand_baseline_window": 90,
        "track_max_age": 15, "cooldown_sec": 0,
    }  # 故意不含 consecutive_frames，走引擎兜底默认值分支
    rule = _rule("fall-detection", "fall_detection", cfg, rid=103)
    for i in range(3):
        assert _eval(rule, [_standing_det()], "fall_m5", 100.0 + i * 0.1, f"base{i}") == []
    for i in range(7):
        assert _eval(rule, [_lying_det()], "fall_m5", 100.3 + i * 0.1, f"def{i}") == []
    out = _eval(rule, [_lying_det()], "fall_m5", 101.0, "def7")
    assert len(out) == 1
    reset_runtime()


def test_reset_runtime_clears_fall_tracker():
    reset_tracker()
    reset_runtime("fall10")
    rule = _fall_rule({"consecutive_frames": 1}, rid=101)
    # 前三帧站立：建立站立高度基线（长度 >= 3）
    for i in range(3):
        _eval(rule, [_standing_det()], "fall10", 100.0 + i * 0.1, f"h{i}")
    # 前置断言：卧地帧因基线已建立，身高比指标应参与计分（有 "height" 键）
    out_before = _eval(rule, [_lying_det()], "fall10", 100.3, "h_before")
    assert len(out_before) == 1
    assert "height" in out_before[0]["detail"]["fallen"][0]["indicators"]
    # 复位跟踪器与基线
    reset_runtime("fall10")
    # 复位后基线清空且是本次跌倒状态的首次判定：先给一帧站立（seed 髋部位置，
    # 不足以建立基线，standHist 长度仍 < 3），再给一帧快速下坠（真实速度证据，
    # 满足冷启动门控），验证身高比指标因基线未建立而不参与计分（无 "height" 键）
    _eval(rule, [_standing_det()], "fall10", 100.35, "h_seed")
    out = _eval(rule, [_lying_det()], "fall10", 100.4, "h_after")
    assert len(out) == 1
    assert "height" not in out[0]["detail"]["fallen"][0]["indicators"]
    reset_runtime()
