"""TrackZone 区域进出几何单测（含 30% 面积阈值）。"""
import numpy as np

from services.track_zone import (
    ZoneFlowCounter,
    anchor_point,
    bbox_zone_overlap_ratio,
    class_group,
    is_effectively_inside,
    parse_region,
    point_in_polygon,
    region_to_pixels,
    resolve_classes,
    zone_cross_direction,
)


SQUARE = np.array([[100, 100], [300, 100], [300, 300], [100, 300]], dtype=np.int32)


def _bbox_at(ax: float, ay: float, *, vehicle: bool = True, w: float = 40, h: float = 40):
    """构造锚点落在 (ax,ay) 的框：车辆底边中心=锚点，人用几何中心。"""
    if vehicle:
        return [ax - w / 2, ay - h, ax + w / 2, ay]
    return [ax - w / 2, ay - h / 2, ax + w / 2, ay + h / 2]


def _walk_enter(c: ZoneFlowCounter, tid: int, *, class_id=2, class_name="car"):
    """稳态区外 2 帧 → 区内 2 帧，触发一次 ENTER（框大部分在区内）。"""
    vehicle = class_group(class_id, class_name) == "vehicle"
    for x, y in ((50, 200), (60, 200), (150, 200), (160, 200)):
        alarm = c.update(
            tid, (x, y), SQUARE,
            class_id=class_id, class_name=class_name,
            bbox=_bbox_at(x, y, vehicle=vehicle),
        )
        c.end_frame({tid})
    return alarm


def test_point_in_polygon_inside_outside():
    assert point_in_polygon((200, 200), SQUARE) is True
    assert point_in_polygon((50, 50), SQUARE) is False
    assert point_in_polygon((100, 200), SQUARE) is True  # 边界


def test_bbox_overlap_ratio_full_and_edge():
    # 完全在区内
    full = [150, 150, 250, 250]
    assert bbox_zone_overlap_ratio(full, SQUARE) >= 0.99
    # 完全在区外
    outside = [10, 10, 50, 50]
    assert bbox_zone_overlap_ratio(outside, SQUARE) < 0.01
    # 擦边：仅一小角伸入
    graze = [80, 180, 110, 220]  # 宽 30，伸入约 10 → ~33%? 调小伸入
    graze = [70, 180, 105, 220]  # 伸入 x∈[100,105] → 5/35 ≈ 14%
    r = bbox_zone_overlap_ratio(graze, SQUARE)
    assert r < 0.30
    assert is_effectively_inside(graze, SQUARE) is False
    # 超过 30%
    deep = [80, 150, 160, 250]  # 伸入 x∈[100,160]=60 / 宽80=75%
    assert bbox_zone_overlap_ratio(deep, SQUARE) >= 0.30
    assert is_effectively_inside(deep, SQUARE) is True


def test_graze_not_counted_as_enter():
    """擦边（重叠 <30%）不应触发进出。"""
    c = ZoneFlowCounter(stable_frames=2, confirm_frames=2, dedupe_dist=1, miss_exit_frames=999)
    # 框大部分在区外，仅擦边
    graze_boxes = [
        [70, 180, 105, 220],
        [72, 180, 106, 220],
        [74, 180, 108, 220],
        [76, 180, 110, 220],
    ]
    for box in graze_boxes:
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
        c.update(1, (cx, cy), SQUARE, class_id=2, class_name="car", bbox=box)
        c.end_frame({1})
    assert c.snapshot()["in"] == 0


def test_zone_enter_exit_direction():
    assert zone_cross_direction((50, 200), (150, 200), SQUARE) == 1
    assert zone_cross_direction((150, 200), (50, 200), SQUARE) == -1
    assert zone_cross_direction((150, 200), (180, 200), SQUARE) == 0
    assert zone_cross_direction((50, 200), (40, 200), SQUARE) == 0


def test_anchor_point_vehicle_uses_bottom():
    pt = anchor_point((150, 200), [100, 100, 200, 300], class_id=2, class_name="car")
    assert pt == (150.0, 300.0)


def test_zone_flow_counter_by_class():
    c = ZoneFlowCounter(stable_frames=2, confirm_frames=2, dedupe_dist=1, miss_exit_frames=999)
    alarm = _walk_enter(c, 1, class_id=0, class_name="person")
    assert alarm is not None
    assert alarm["event"] == "ENTER"
    assert alarm["group"] == "person"

    # car：区内稳态后离开
    for x, y in ((150, 200), (160, 200), (50, 200), (40, 200)):
        alarm2 = c.update(
            2, (x, y), SQUARE, class_id=2, class_name="car",
            bbox=_bbox_at(x, y, vehicle=True),
        )
        c.end_frame({1, 2})
    assert alarm2 is not None
    assert alarm2["event"] == "EXIT"
    assert alarm2["group"] == "vehicle"

    snap = c.snapshot()
    assert snap["in"] == 1
    assert snap["out"] == 1
    assert snap["person"]["in"] == 1
    assert snap["vehicle"]["out"] == 1


def test_single_frame_jitter_not_counted():
    """边界单帧抖动不应计数。"""
    c = ZoneFlowCounter(stable_frames=2, confirm_frames=2, dedupe_dist=1, miss_exit_frames=999)
    for x, y in ((50, 200), (150, 200), (160, 200)):
        c.update(1, (x, y), SQUARE, class_id=2, class_name="car", bbox=_bbox_at(x, y))
        c.end_frame({1})
    assert c.snapshot()["in"] == 0


def test_id_switch_spatial_dedupe():
    """换 ID 后在相近位置再次 ENTER 应被空间去重。"""
    c = ZoneFlowCounter(stable_frames=2, confirm_frames=2, dedupe_dist=80, dedupe_frames=60, miss_exit_frames=999)
    a1 = _walk_enter(c, 10, class_id=2, class_name="car")
    assert a1 is not None
    assert c.snapshot()["in"] == 1

    a2 = _walk_enter(c, 99, class_id=2, class_name="car")
    assert a2 is None
    assert c.snapshot()["in"] == 1


def test_miss_exit_when_lost_inside():
    """区内目标丢检一段时间后补记 EXIT。"""
    c = ZoneFlowCounter(stable_frames=2, confirm_frames=2, dedupe_dist=1, miss_exit_frames=3)
    assert _walk_enter(c, 5, class_id=2, class_name="car") is not None
    assert c.snapshot()["in"] == 1
    for _ in range(3):
        alarms = c.end_frame(set())
    assert c.snapshot()["out"] == 1
    assert any(a["event"] == "EXIT" for a in alarms)


def test_parse_region_and_pixels():
    raw = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
    norm = parse_region(raw)
    assert norm is not None and len(norm) == 4
    px = region_to_pixels(norm, 1000, 800)
    assert px.shape[1] == 2
    assert len(px) >= 3


def test_resolve_classes_presets():
    assert resolve_classes("person") == [0]
    assert 2 in resolve_classes("vehicle")
    assert 0 in resolve_classes("person_vehicle")
    assert 2 in resolve_classes("person_vehicle")
    assert resolve_classes("all") is None
    assert resolve_classes(None, [0, 2]) == [0, 2]


def test_class_group():
    assert class_group(0, "person") == "person"
    assert class_group(2, "car") == "vehicle"
    assert class_group(56, "chair") == "other"


def test_format_zone_occupancy_lines_hides_zeros():
    from services.track_zone import format_zone_occupancy_lines, occupancy_from_counter
    assert format_zone_occupancy_lines({"person": 0, "vehicle": 0}) == []
    assert format_zone_occupancy_lines({"person": 2, "vehicle": 0}) == ["人：2"]
    assert format_zone_occupancy_lines({"person": 0, "vehicle": 3}) == ["车：3"]
    assert format_zone_occupancy_lines({"person": 1, "vehicle": 2}) == ["车：2", "人：1"]


def test_polygon_area_square():
    from services.track_zone import _polygon_area
    # 200x200 正方形
    assert abs(_polygon_area(SQUARE) - 40000.0) < 1e-3


def test_draw_zone_occupancy_label_scales_with_polygon():
    """大区域标签字号应明显大于小区域。"""
    from services.track_zone import _draw_zone_occupancy_label, _fit_zone_label_font_size
    from PIL import Image, ImageDraw

    small = np.array([[10, 10], [80, 10], [80, 80], [10, 80]], dtype=np.int32)
    large = np.array([[10, 10], [410, 10], [410, 410], [10, 410]], dtype=np.int32)
    frame = np.zeros((500, 500, 3), dtype=np.uint8)
    pil = Image.fromarray(frame)
    draw = ImageDraw.Draw(pil)
    lines = ["车：3"]
    s = _fit_zone_label_font_size(draw, lines, small, area_ratio=0.06)
    l = _fit_zone_label_font_size(draw, lines, large, area_ratio=0.06)
    assert l > s
    assert l >= 18  # 大区域仍大于小区域，但整体字号更小
    # 默认比例下大框字号应明显小于旧版 1/4 面积策略
    old = _fit_zone_label_font_size(draw, lines, large, area_ratio=0.25)
    assert l < old
    out = _draw_zone_occupancy_label(frame.copy(), large, {"vehicle": 3, "person": 0})
    assert out.shape == frame.shape
    assert int(out.sum()) > 0
    # 相对基准放大 2.5 倍（5 倍再缩小 2 倍）
    from services.track_zone import _ZONE_LABEL_SCALE
    assert _ZONE_LABEL_SCALE == 2.5
    scaled = min(int(l * 2.5), max(18, int(400 * 0.95)))
    assert scaled >= int(l * 2)


def test_occupancy_from_counter():
    from services.track_zone import occupancy_from_counter
    c = ZoneFlowCounter(stable_frames=1, confirm_frames=1, dedupe_dist=1, miss_exit_frames=999)
    c.by_group["person"]["in"] = 1
    c.by_group["vehicle"]["in"] = 4
    c.enter_count = 5
    assert occupancy_from_counter(c) == {"person": 1, "vehicle": 4}


def test_parse_css_color():
    from services.track_zone import parse_css_color
    bgr, a = parse_css_color("#2196f3")
    assert bgr == (0xf3, 0x96, 0x21) and a == 1.0
    bgr, a = parse_css_color("rgba(33, 150, 243, 0.12)")
    assert bgr == (243, 150, 33) and abs(a - 0.12) < 1e-6
    bgr, a = parse_css_color("#ff000080")
    assert bgr == (0, 0, 255) and abs(a - 128 / 255) < 1e-6


def test_draw_zone_overlay_custom_colors():
    from services.track_zone import draw_zone_overlay
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    poly = np.array([[20, 20], [180, 20], [180, 180], [20, 180]], dtype=np.int32)
    out = draw_zone_overlay(
        frame.copy(), poly,
        border_color="#00ff00",
        fill_color="rgba(255, 0, 0, 0.5)",
    )
    # 内部应有红色分量（BGR 的 R=channel2）
    center = out[100, 100]
    assert int(center[2]) > 80
    # 与空帧不同
    assert int(out.sum()) > 0
    # 换绿色填充应改变中心色
    out2 = draw_zone_overlay(
        frame.copy(), poly,
        border_color="#ffffff",
        fill_color="rgba(0, 255, 0, 0.8)",
    )
    assert int(out2[100, 100][1]) > int(out[100, 100][1])


def test_draw_zone_overlay_border_width():
    from services.track_zone import draw_zone_overlay
    frame = np.zeros((120, 120, 3), dtype=np.uint8)
    poly = np.array([[10, 10], [110, 10], [110, 110], [10, 110]], dtype=np.int32)
    thin = draw_zone_overlay(frame.copy(), poly, border_color="#ffffff", border_width=1, fill_alpha=0)
    thick = draw_zone_overlay(frame.copy(), poly, border_color="#ffffff", border_width=8, fill_alpha=0)
    assert int(thick.sum()) > int(thin.sum())
