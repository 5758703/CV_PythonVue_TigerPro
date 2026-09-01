import numpy as np

from services.vehicle_track import SPEED_HISTORY_LEN, VehicleSession, enrich_vehicle_frame


def _det(track_id, bbox):
    return {
        "trackId": track_id,
        "classId": 2,
        "className": "car",
        "confidence": 0.9,
        "bbox": bbox,
    }


def test_scale_speed_uses_explicit_timestamp_and_bottom_center():
    """Speed must use supplied media time and the road-contact point."""
    session = VehicleSession()
    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    enrich_vehicle_frame(
        frame, [_det(7, [10, 20, 30, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, sample_ts=10.0,
    )
    second = enrich_vehicle_frame(
        frame, [_det(7, [20, 20, 40, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, sample_ts=11.0,
    )
    assert session.speed_history[7][-1][:2] == (30.0, 60.0)
    assert second["detections"][0]["speedKmh"] == 3.6


def test_speed_history_length_does_not_follow_trail_setting():
    """Changing the display trail must not change scale-speed samples."""
    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    enabled_session = VehicleSession()
    disabled_session = VehicleSession()
    enabled = disabled = None
    for timestamp in range(20):
        detection = [_det(7, [10, 20, 30, 60])]
        enabled = enrich_vehicle_frame(
            frame, detection, enabled_session, enable_ocr=False, enable_trail=True,
            meters_per_pixel=0.1, sample_ts=float(timestamp),
        )
        disabled = enrich_vehicle_frame(
            frame, detection, disabled_session, enable_ocr=False, enable_trail=False,
            meters_per_pixel=0.1, sample_ts=float(timestamp),
        )
    assert len(enabled_session.speed_history[7]) == SPEED_HISTORY_LEN
    assert len(disabled_session.speed_history[7]) == SPEED_HISTORY_LEN
    assert enabled["detections"][0]["speedKmh"] == disabled["detections"][0]["speedKmh"] == 0.0


def test_non_monotonic_timestamp_resets_speed_history():
    """A reversed media timestamp must discard the prior speed window."""
    session = VehicleSession()
    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    enrich_vehicle_frame(
        frame, [_det(7, [10, 20, 30, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, sample_ts=2.0,
    )
    result = enrich_vehicle_frame(
        frame, [_det(7, [20, 20, 40, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, sample_ts=1.0,
    )
    speed = result["detections"][0]
    assert speed["speedKmh"] is None
    assert speed["speedQuality"] == "warming-up"
    assert session.speed_history[7] == [(30.0, 60.0, 1.0)]


def test_gap_over_two_seconds_resets_speed_history():
    """A tracking interruption longer than two seconds starts a new window."""
    session = VehicleSession()
    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    enrich_vehicle_frame(
        frame, [_det(7, [10, 20, 30, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, sample_ts=0.0,
    )
    result = enrich_vehicle_frame(
        frame, [_det(7, [20, 20, 40, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, sample_ts=2.1,
    )
    speed = result["detections"][0]
    assert speed["speedKmh"] is None
    assert speed["speedQuality"] == "warming-up"
    assert session.speed_history[7] == [(30.0, 60.0, 2.1)]


def test_impossible_speed_is_rejected():
    """An interval above the configured physical limit is not reported as speed."""
    session = VehicleSession()
    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    enrich_vehicle_frame(
        frame, [_det(7, [10, 20, 30, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, sample_ts=0.0,
    )
    result = enrich_vehicle_frame(
        frame, [_det(7, [1010, 20, 1030, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, sample_ts=1.0,
    )
    speed = result["detections"][0]
    assert speed["speedKmh"] is None
    assert speed["speedSource"] is None
    assert speed["speedQuality"] == "invalid"


def test_interval_median_filters_single_plausible_outlier():
    """One fast but in-range interval cannot displace a stable median speed."""
    session = VehicleSession()
    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    result = None
    for timestamp, x in enumerate((0, 10, 20, 30, 40, 50, 250)):
        result = enrich_vehicle_frame(
            frame, [_det(7, [x, 20, x + 20, 60])], session,
            enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, sample_ts=float(timestamp),
        )
    speed = result["detections"][0]
    assert speed["speedKmh"] == 3.6
    assert speed["speedSource"] == "scale"
    assert speed["speedQuality"] == "estimated"
