"""跌倒检测视频模式：判定链路契约单测 + 一条真正驱动 fall_video 本体的集成测试。

覆盖 fall_video 逐帧循环依赖的三条核心契约（不跑 inference.fall_video 本体，
直接调 services.alert_engine，见文件下半部分标注"1/2/3"的三个测试）：
1. 质心速度指标必须走视频时间轴（frames/fps），不能用墙钟；
2. 同一帧内三次引擎调用（evaluate_rules / fall_detections / active_overlay_style）
   共用同一 frame_token 时命中 memo，不重复推进质心历史；
3. source_type="video" 与 "camera" 一样受冷启动门控约束，不像 "image" 那样豁免。

以及最后一条 test_fall_video_end_to_end_emits_fall_events_within_factory_cooldown：
monkeypatch cv2.VideoCapture / inference._open_h264 / inference._write_bgr /
inference._get_model，真正调用 inference.fall_video() 本体（上面三条只测引擎，
不触碰 fall_video 内部构造 now_ts/frame_token 的那段代码，对 fall_video 自身
的实现缺陷零鉴别力——这条集成测试专门补这个洞，尤其是 C-1：now_ts 起点缺失
导致出厂 cooldown_sec=60 时视频前 60 秒内的触发被冷却静默吞掉）。

姿态关键点几何沿用 unittests/test_alert_engine.py 中 _standing_det / _lying_det
的构造方式（躯干角、身高比、头部高度三指标同时命中，总分恒 >= min_score），
避免每个测试都要重新验算跌倒判定的四个指标——那些算术验算已在
test_alert_engine.py 里覆盖，本文件只关心视频模式新增的时间轴/memo/门控契约。
"""
import types

import cv2
import numpy as np

import inference
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

    重要澄清（复审 I-2 指出的边界）：本测试手工构造 now_ts 序列并直接传给
    evaluate_rules，验证的是"给定正确的 now_ts 序列时，引擎按 fps 比例算出
    dt/speed"这条引擎算术契约本身——它不驱动 inference.fall_video()，因此
    **不能**拦住 fall_video 内部构造 now_ts 时的实现缺陷（例如 now_ts 忘记
    叠加起始墙钟、或误用 time.time() 而非 frames/fps）。这类"now_ts 是怎么
    从 fall_video 内部产出的"回归由
    test_fall_video_end_to_end_emits_fall_events_within_factory_cooldown
    （monkeypatch 驱动 fall_video 本体）负责拦截，见该测试文档串。
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


# ---------------------------------------------- 4. 真正驱动 fall_video 本体（C-1 反证）
def _fake_person_kp(kp):
    """裸 [x,y,c]×17 关键点 -> ultralytics r.keypoints.data.cpu().tolist() 单人条目。"""
    return kp


def _standing_kp(hip_y=260.0, nose_y=60.0, conf=0.9):
    kp = [[320.0, 100.0, conf] for _ in range(17)]
    kp[0] = [320.0, nose_y, conf]
    kp[5] = [300.0, hip_y - 140.0, conf]
    kp[6] = [340.0, hip_y - 140.0, conf]
    kp[11] = [305.0, hip_y, conf]
    kp[12] = [335.0, hip_y, conf]
    kp[15] = [305.0, hip_y + 180.0, conf]
    kp[16] = [335.0, hip_y + 180.0, conf]
    return _fake_person_kp(kp)


def _lying_kp(y=430.0, conf=0.9):
    kp = [[300.0, y, conf] for _ in range(17)]
    kp[0] = [200.0, y - 5.0, conf]
    kp[5] = [240.0, y - 10.0, conf]
    kp[6] = [240.0, y + 10.0, conf]
    kp[11] = [360.0, y - 10.0, conf]
    kp[12] = [360.0, y + 10.0, conf]
    kp[15] = [460.0, y - 40.0, conf]
    kp[16] = [460.0, y - 30.0, conf]
    return _fake_person_kp(kp)


def _interp_kp(kp_a, kp_b, t):
    """逐点线性插值，模拟渐进的跌倒动作（而非站立<->卧地的单帧瞬间跳变）。

    真实的 assign_track_ids 是按 IoU + 质心距离做帧间匹配的（不像本文件其它
    测试那样手工固定 trackId），站立 bbox（瘦高）到卧地 bbox（矮宽）之间若
    只用一帧完成跳变，IoU 会跌破 0.2 阈值，被判定为"新目标"而不是同一人
    继续运动，导致该 trackId 的冷启动状态（okFrames/since）被重置——这会
    掩盖本测试真正要验证的 C-1 冷却 bug（新 trackId 会被冷启动门控拦住，
    看起来像是"没触发"，但原因跟 C-1 无关）。用多帧小步插值保证帧间 bbox
    连续重叠，trackId 全程不变，只留下 C-1 这一个变量。
    """
    return [
        [kp_a[i][0] + (kp_b[i][0] - kp_a[i][0]) * t,
         kp_a[i][1] + (kp_b[i][1] - kp_a[i][1]) * t,
         min(kp_a[i][2], kp_b[i][2])]
        for i in range(len(kp_a))
    ]


class _FakeTensor:
    """伪造 r.keypoints.data：支持 .cpu().tolist() 链式调用。"""

    def __init__(self, data):
        self._data = data

    def cpu(self):
        return self

    def tolist(self):
        return self._data


class _FakeResult:
    """伪造 ultralytics predict() 结果：r.keypoints.data / r.plot()。"""

    def __init__(self, persons_kp, shape):
        self.keypoints = types.SimpleNamespace(data=_FakeTensor(persons_kp))
        self._shape = shape

    def plot(self):
        return np.zeros(self._shape, dtype=np.uint8)


class _FakeModel:
    """按调用次序回放预先构造好的逐帧关键点序列（模拟 ultralytics 姿态模型）。"""

    def __init__(self, frames_kp):
        self.frames_kp = frames_kp
        self.calls = 0

    def predict(self, frame, **kwargs):
        idx = min(self.calls, len(self.frames_kp) - 1)
        self.calls += 1
        return [_FakeResult(self.frames_kp[idx], frame.shape)]


class _FakeCap:
    """伪造 cv2.VideoCapture：固定 fps/total，按顺序吐出预置帧。"""

    def __init__(self, frames, fps, total):
        self._frames = frames
        self._fps = fps
        self._total = total
        self._idx = 0

    def isOpened(self):
        return True

    def get(self, prop):
        if prop == cv2.CAP_PROP_FPS:
            return self._fps
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return self._total
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return self._frames[0].shape[1]
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return self._frames[0].shape[0]
        return 0

    def read(self):
        if self._idx >= len(self._frames):
            return False, None
        f = self._frames[self._idx]
        self._idx += 1
        return True, f

    def release(self):
        pass


class _FakeWriter:
    def close(self):
        pass


def test_fall_video_end_to_end_emits_fall_events_within_factory_cooldown(monkeypatch):
    """C-1 反证 + I-1 反证：这是本文件里唯一真正驱动 inference.fall_video() 本体
    的测试（上面三个测试只调 services.alert_engine，从不 import/调用
    inference.fall_video，对 fall_video 内部实现的缺陷零鉴别力）。

    C-1：出厂 cooldown_sec=60、视频总长 2 秒（远短于 60 秒）时，fall_video
    必须仍能产出非空 fallEvents。monkeypatch cv2.VideoCapture /
    inference._open_h264 / inference._write_bgr / inference._get_model，喂
    60 帧合成关键点（fps=30：前 5 帧站立建立 okFrames 基线，随后 21 帧用
    _interp_kp 从站立渐进插值到卧地——保证 assign_track_ids 真实按 IoU/
    质心距离匹配时 trackId 全程不变，其余帧维持卧地），断言返回的
    fallEvents 非空。

    在 C-1 修复前（now_ts = frames / fps，起点为 0）本测试必须 FAIL：cooldown
    判断是 now - last_fire_ts(初值 0.0) < cooldown_sec(60)，now 本身从 0 起算、
    视频只有 2 秒，恒小于 60，触发被静默吞掉。修复后（now_ts = 处理起始墙钟 +
    frames / fps）必须 PASS。

    I-1：额外启用一条 count_threshold（人员聚集）规则，cooldown_sec=0、
    consecutive_frames=1，几乎每帧都会命中，断言 fallEvents 里的条目全部
    trackId/score/indicators 非 None——验证它没有混入聚集规则产出的空字段行。
    """
    reset_runtime("fall-video-e2e")

    fps = 30.0
    total = 60
    standing_kp = _standing_kp(hip_y=260.0)
    lying_kp = _lying_kp(y=430.0)
    transition_steps = 20
    frames_kp = [[standing_kp] for _ in range(5)]
    frames_kp += [
        [_interp_kp(standing_kp, lying_kp, i / transition_steps)]
        for i in range(transition_steps + 1)
    ]
    frames_kp += [[lying_kp] for _ in range(total - len(frames_kp))]
    frame_shape = (480, 640, 3)
    frames = [np.zeros(frame_shape, dtype=np.uint8) for _ in range(total)]

    fake_model = _FakeModel(frames_kp)
    monkeypatch.setattr(inference, "_get_model", lambda path: fake_model)
    monkeypatch.setattr(
        inference.cv2, "VideoCapture", lambda path: _FakeCap(frames, fps, total)
    )
    monkeypatch.setattr(
        inference, "_open_h264", lambda dst, fps_, w, h: (_FakeWriter(), w, h)
    )
    monkeypatch.setattr(inference, "_write_bgr", lambda writer, bgr, ew, eh: None)

    fall_rule = _fall_rule({"consecutive_frames": 2, "cooldown_sec": 60}, rid=970)
    crowd_rule = types.SimpleNamespace(
        id=971, rule_key="crowd-gathering", name="crowd-gathering",
        rule_type="count_threshold", severity="medium", status="0",
        config=lambda: {
            "class_name": "person", "min_count": 1, "min_confidence": 0.0,
            "consecutive_frames": 1, "cooldown_sec": 0,
        },
    )

    stats = inference.fall_video(
        "ultralytics", "yolo-pose", "dummy.pt", "dummy_src.mp4", "dummy_dst.mp4",
        rules=[fall_rule, crowd_rule], source_key="fall-video-e2e",
        conf=0.25, progress_cb=None,
    )

    assert stats["frames"] == total
    assert stats["fps"] == fps
    assert stats["width"] == 640
    assert stats["height"] == 480
    assert len(stats["fallEvents"]) >= 1  # C-1：出厂 cooldown 下仍应有非空触发
    for ev in stats["fallEvents"]:
        # I-1：不应混入 crowd-gathering 触发产出的空字段行
        assert ev["trackId"] is not None
        assert ev["score"] is not None
        assert ev["indicators"] is not None
        assert ev["title"] and "跌倒" in ev["title"]
        # sec 走视频内部时间轴（frames/fps），必须是小量级的秒数，不能是
        # 叠加了墙钟起点后的巨大数字
        assert 0 <= ev["sec"] < total / fps + 0.01

    reset_runtime("fall-video-e2e")
