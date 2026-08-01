"""车辆追踪模块：区域人/车进出计数集成单测。"""
import numpy as np

from services.vehicle_track import VehicleSession, enrich_vehicle_frame, draw_vehicle_hud


SQUARE = np.array([[100, 100], [300, 100], [300, 300], [100, 300]], dtype=np.int32)


def _det(tid, cx, cy, *, class_id=2, class_name="car", w=60, h=40):
    return {
        "trackId": tid,
        "classId": class_id,
        "className": class_name,
        "confidence": 0.9,
        "bbox": [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
    }


def test_enrich_zone_counts_vehicle_enter():
    session = VehicleSession()
    frame = np.zeros((400, 400, 3), dtype=np.uint8)
    # 区外稳态
    for pos in ((50, 200), (60, 200)):
        enrich_vehicle_frame(frame, [_det(1, *pos)], session, region_px=SQUARE, enable_ocr=False, enable_speed=False)
    # 区内确认
    out = None
    for pos in ((150, 200), (160, 200)):
        out = enrich_vehicle_frame(frame, [_det(1, *pos)], session, region_px=SQUARE, enable_ocr=False, enable_speed=False)
    assert out["regionEnabled"] is True
    assert out["crossing"]["vehicle"]["in"] >= 1
    assert out["zoneOccupancy"]["vehicle"] >= 1


def test_enrich_zone_counts_person():
    session = VehicleSession()
    frame = np.zeros((400, 400, 3), dtype=np.uint8)
    person = lambda x, y: _det(7, x, y, class_id=0, class_name="person", w=30, h=60)
    for pos in ((40, 200), (50, 200)):
        enrich_vehicle_frame(frame, [person(*pos)], session, region_px=SQUARE, enable_ocr=False, enable_speed=False)
    out = None
    for pos in ((180, 200), (190, 200)):
        out = enrich_vehicle_frame(frame, [person(*pos)], session, region_px=SQUARE, enable_ocr=False, enable_speed=False)
    assert out["crossing"]["person"]["in"] >= 1
    assert out["zoneOccupancy"]["person"] >= 1


def test_draw_vehicle_hud_with_region():
    frame = np.zeros((400, 400, 3), dtype=np.uint8)
    result = {
        "detections": [],
        "zoneOccupancy": {"vehicle": 2, "person": 0},
        "congestion": {"label": "畅通", "vehicleCount": 0},
        "alarms": [],
    }
    out = draw_vehicle_hud(
        frame, result,
        region_px=SQUARE,
        zone_style={"borderColor": "#ff0000", "fillColor": "rgba(255,0,0,0.2)"},
    )
    assert out.shape == frame.shape
    assert int(out.sum()) > 0


def test_enrich_attaches_trail_by_track_id():
    """连续帧后同一 Track ID 应带有运动轨迹点。"""
    session = VehicleSession()
    frame = np.zeros((400, 400, 3), dtype=np.uint8)
    out = None
    for i, x in enumerate((120, 140, 160, 180, 200)):
        out = enrich_vehicle_frame(
            frame, [_det(3, x, 200)], session,
            enable_ocr=False, enable_speed=False, enable_trail=True,
        )
    trail = out["detections"][0].get("trail") or []
    assert out.get("trailEnabled") is True
    assert len(trail) >= 5
    assert trail[0][0] == 120.0
    assert trail[-1][0] == 200.0
    # HUD 绘制轨迹后画面非全黑
    vis = draw_vehicle_hud(frame, out, draw_trails=True)
    assert int(vis.sum()) > 0


def test_enrich_trail_can_disable():
    session = VehicleSession()
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    out = enrich_vehicle_frame(
        frame, [_det(1, 80, 80)], session,
        enable_ocr=False, enable_speed=False, enable_trail=False,
    )
    assert out["detections"][0].get("trail") == []
    assert out.get("trailEnabled") is False
