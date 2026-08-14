"""跌倒检测视频模式：判定链路契约单测（不跑真实模型/视频编解码，见 e2e 验证）。

覆盖 fall_video 逐帧循环依赖的三条核心契约：
1. 质心速度指标必须走视频时间轴（frames/fps），不能用墙钟；
2. 同一帧内三次引擎调用（evaluate_rules / fall_detections / active_overlay_style）
   共用同一 frame_token 时命中 memo，不重复推进质心历史；
3. source_type="video" 与 "camera" 一样受冷启动门控约束，不像 "image" 那样豁免。

姿态关键点几何沿用 unittests/test_alert_engine.py 中 _standing_det / _lying_det
的构造方式（躯干角、身高比、头部高度三指标同时命中，总分恒 >= min_score），
避免每个测试都要重新验算跌倒判定的四个指标——那些算术验算已在
test_alert_engine.py 里覆盖，本文件只关心视频模式新增的时间轴/memo/门控契约。
"""
import types

from services.alert_engine import (
    active_overlay_style,
    evaluate_rules,
    fall_detections,
    reset_runtime,
)


def _rule(cfg, rid):
    return types.SimpleNamespace(
        id=rid,
        rule_key="fall-detection",
        name="fall-detection",
        rule_type="fall_detection",
        severity="medium",
        status="0",
        config=lambda c=cfg: c,
    )


def _fall_rule(cfg=None, rid=900):
    base = {
        "trunk_angle_deg": 60,
        "centroid_speed": 0.5,
        "body_torso_ratio": 1.5,
        "head_y_ratio": 0.75,
        "weights": {"trunk": 1, "speed": 1, "height": 1, "head": 1},
        "min_score": 2,
        "kp_min_conf": 0.3,
        "track_max_age": 15,
        "consecutive_frames": 1,
        "cooldown_sec": 0,
    }
    base.update(cfg or {})
    return _rule(base, rid)


def _standing_det(track_id=1, hip_y=260.0, nose_y=60.0, conf=0.9):
    """站立：躯干竖直、鼻在画面上部、肩踝相距 320px（不触发任何指标）。"""
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
    """卧地：肩髋左右分布且等高（髋中点纵坐标恰为 y，便于精确控制位移）、
    鼻贴近画面底部、躯干高度骤降——躯干角/身高比/头部高度三指标同时命中，
    总分恒 >= min_score=2，不依赖速度指标是否越阈。"""
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


# ------------------------------------------------------------------ 1. fps 时间轴
def test_fall_speed_indicator_uses_video_timeline_not_wallclock():
    """质心速度指标必须按视频时间轴 (now_ts = start_ts + frames/fps) 算 dt，
    而不是墙钟 time.time()。

    构造：3 帧站立把该 track 的 okFrames 推过冷启动门控门槛（3），随后 1 帧
    髋部纵坐标从 260 猛跳到 430（Δy=170px，画面高 480）触发判定。同一组像素
    位移分别用 fps=30 与 fps=10 跑一遍——dt 在两次跑法里分别精确等于 1/30 与
    1/10（now_ts 直接由 frames/fps 算出，不掺入真实耗时），所以 speed 应严格
    按 fps 成正比：speed = Δy / dt / fh = Δy * fps / fh。

    这是最容易出错也最难靠肉眼发现的地方：如果实现不慎用了 time.time()
    （墙钟）而不是 frames/fps 算出的 now_ts，两次跑法在同一进程里几毫秒内
    完成，dt 会几乎相等而非相差 3 倍，speed 也会几乎相等——本测试通过断言
    严格的 3 倍比例关系来捕捉这类回归。
    """
    def run(fps):
        source_key = f"fall-video-fps-{int(fps)}"
        reset_runtime(source_key)
        rule = _fall_rule(rid=900 + int(fps))
        start_ts = 100.0
        for i in range(3):
            now_ts = start_ts + i / fps
            out = evaluate_rules(
                [rule], [_standing_det(hip_y=260.0)], source_key,
                now_ts=now_ts, frame_width=640, frame_height=480,
                frame_token=f"{source_key}-{i}", source_type="video",
            )
            assert out == []
        now_ts = start_ts + 3 / fps
        dets = [_lying_det(y=430.0)]
        out = evaluate_rules(
            [rule], dets, source_key,
            now_ts=now_ts, frame_width=640, frame_height=480,
            frame_token=f"{source_key}-3", source_type="video",
        )
        assert len(out) == 1
        speed = out[0]["detail"]["fallen"][0]["indicators"]["speed"]
        reset_runtime(source_key)
        return speed

    speed_30 = run(30.0)
    speed_10 = run(10.0)

    # 解析计算核对（170px / (1/fps) / 480fh = 170*fps/480）
    assert abs(speed_30 - 170.0 * 30.0 / 480.0) < 0.01
    assert abs(speed_10 - 170.0 * 10.0 / 480.0) < 0.01
    assert speed_30 != speed_10
    assert abs(speed_30 / speed_10 - 3.0) < 0.01


# --------------------------------------------------------- 2. 同帧三次调用共用 token
def test_engine_calls_sharing_frame_token_do_not_double_advance_state():
    """fall_video 每帧要依次调用 evaluate_rules -> fall_detections ->
    active_overlay_style，三者必须共用同一 frame_token，命中 _eval_fall_detection
    内的单帧 memo，不重复推进质心历史（否则 dt 会塌成 0，速度指标发散/失真）。

    验证方式：先用 evaluate_rules 触发一次判定并记下 speed；再用同一 frame_token
    分别调用两次 fall_detections 与一次 active_overlay_style，断言读到的 speed
    与 evaluate_rules 首次算出的值完全一致——如果 token 未生效，后续调用会把
    tr["hip"] 更新为 (now, hipY)，dt 变成 0，speed 会截然不同。
    """
    source_key = "fall-video-token"
    reset_runtime(source_key)
    rule = _fall_rule(rid=950)
    fps = 30.0
    start_ts = 100.0
    for i in range(3):
        now_ts = start_ts + i / fps
        evaluate_rules(
            [rule], [_standing_det(hip_y=260.0)], source_key,
            now_ts=now_ts, frame_width=640, frame_height=480,
            frame_token=f"tok-{i}", source_type="video",
        )

    dets = [_lying_det(y=430.0)]
    token = "tok-3"
    now_ts = start_ts + 3 / fps
    triggered = evaluate_rules(
        [rule], dets, source_key,
        now_ts=now_ts, frame_width=640, frame_height=480,
        frame_token=token, source_type="video",
    )
    assert len(triggered) == 1
    speed_from_evaluate = triggered[0]["detail"]["fallen"][0]["indicators"]["speed"]

    boxes_1 = fall_detections(
        [rule], dets, source_key=source_key, frame_width=640, frame_height=480,
        frame_token=token, now_ts=now_ts, source_type="video",
    )
    boxes_2 = fall_detections(
        [rule], dets, source_key=source_key, frame_width=640, frame_height=480,
        frame_token=token, now_ts=now_ts, source_type="video",
    )
    style = active_overlay_style(
        [rule], dets, frame_width=640, frame_height=480,
        source_key=source_key, frame_token=token, source_type="video",
    )

    assert len(boxes_1) == 1 and len(boxes_2) == 1
    assert boxes_1[0]["indicators"]["speed"] == speed_from_evaluate
    assert boxes_2[0]["indicators"]["speed"] == speed_from_evaluate
    assert style is not None
    assert style["ruleKey"] == "fall-detection"
    reset_runtime(source_key)


# ------------------------------------------------------ 3. source_type="video" 不豁免门控
def test_fall_video_source_type_shares_cold_start_gate_with_camera():
    """source_type="video" 必须与 "camera" 一样受冷启动误报自锁门控约束，不能
    像 "image" 那样被豁免——图片模式豁免的前提是「每次检测都是独立单帧、
    routes/fall.py 每次 /detect 前都会 reset-runtime」，这对视频模式不成立：
    视频是真实连续流，正是四指标唯一全可用、也正是冷启动误报自锁风险最真实
    存在的模式。

    三段对照：
      a) video + 无历史 + 无下坠证据 -> 不触发（与 camera 行为一致）
      b) image + 完全相同的单帧序列 -> 当帧即触发（豁免门控，对照组）
      c) video + 先建立站立基线 + 真实下坠证据 -> 正常触发（证明门控没有被
         过度收紧，四指标齐全的视频模式仍然可以判出真实跌倒）
    """
    # a) video 冷启动、无下坠证据：不触发
    reset_runtime("fall-video-cold")
    rule_video = _fall_rule(rid=960)
    out_video = evaluate_rules(
        [rule_video], [_lying_det(y=430.0)], "fall-video-cold",
        now_ts=100.0, frame_width=640, frame_height=480,
        frame_token="vcold0", source_type="video",
    )
    assert out_video == []
    reset_runtime("fall-video-cold")

    # b) 对照：image 模式相同序列豁免门控，当帧触发
    reset_runtime("fall-image-cold")
    rule_image = _fall_rule(rid=961)
    out_image = evaluate_rules(
        [rule_image], [_lying_det(y=430.0)], "fall-image-cold",
        now_ts=100.0, frame_width=640, frame_height=480,
        frame_token="icold0", source_type="image",
    )
    assert len(out_image) == 1
    reset_runtime("fall-image-cold")

    # c) video + 真实下坠证据：正常触发（门控不会拦住真实跌倒）
    reset_runtime("fall-video-drop")
    rule_drop = _fall_rule(rid=962)
    assert evaluate_rules(
        [rule_drop], [_standing_det(hip_y=260.0)], "fall-video-drop",
        now_ts=100.0, frame_width=640, frame_height=480,
        frame_token="vdrop0", source_type="video",
    ) == []
    out_drop = evaluate_rules(
        [rule_drop], [_lying_det(y=430.0)], "fall-video-drop",
        now_ts=100.1, frame_width=640, frame_height=480,
        frame_token="vdrop1", source_type="video",
    )
    assert len(out_drop) == 1
    reset_runtime("fall-video-drop")
