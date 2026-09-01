import csv
import importlib.util
import io
import pathlib
import sys
import types

import numpy as np
import pytest
from flask import Flask

from services import vehicle_track
from services.vehicle_track import SPEED_HISTORY_LEN, VehicleSession, enrich_vehicle_frame


def _load_vehicle_route(monkeypatch):
    """Load the route in isolation from unrelated JWT-protected blueprints."""
    models_module = types.ModuleType("models")
    models_module.AiModel = object
    security_module = types.ModuleType("security")
    security_module.permission_required = lambda _permission: lambda fn: fn
    monkeypatch.setitem(sys.modules, "models", models_module)
    monkeypatch.setitem(sys.modules, "security", security_module)
    route_path = pathlib.Path(__file__).parents[1] / "routes" / "vehicle.py"
    spec = importlib.util.spec_from_file_location("vehicle_route_test", route_path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _det(track_id, bbox):
    return {
        "trackId": track_id,
        "classId": 2,
        "className": "car",
        "confidence": 0.9,
        "bbox": bbox,
    }


def _double_line_sample(session, track_id, x, timestamp, **overrides):
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    options = {
        "enable_ocr": False,
        "enable_trail": False,
        "speed_mode": "double-line",
        "speed_line_a_px": [20, 0, 20, 100],
        "speed_line_b_px": [120, 0, 120, 100],
        "speed_distance_m": 10.0,
        "sample_ts": timestamp,
    }
    options.update(overrides)
    result = enrich_vehicle_frame(
        frame,
        [_det(track_id, [x - 5, 10, x + 5, 50])],
        session,
        **options,
    )
    return result["detections"][0]


def _double_line_point_sample(session, point, timestamp, *, line_a, line_b):
    x, y = point
    frame = np.zeros((120, 80, 3), dtype=np.uint8)
    result = enrich_vehicle_frame(
        frame,
        [_det(7, [x - 2, y - 10, x + 2, y])],
        session,
        enable_ocr=False,
        enable_trail=False,
        speed_mode="double-line",
        speed_line_a_px=line_a,
        speed_line_b_px=line_b,
        speed_distance_m=10.0,
        sample_ts=timestamp,
    )
    return result["detections"][0]


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


@pytest.mark.parametrize("meters_per_pixel", [None, 0.0, float("nan")])
def test_uncalibrated_scale_does_not_report_speed(meters_per_pixel):
    """Missing, zero, and non-finite calibration cannot produce vehicle speed."""
    session = VehicleSession()
    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    enrich_vehicle_frame(
        frame, [_det(7, [10, 20, 30, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=meters_per_pixel, sample_ts=0.0,
    )
    result = enrich_vehicle_frame(
        frame, [_det(7, [20, 20, 40, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=meters_per_pixel, sample_ts=1.0,
    )
    speed = result["detections"][0]
    assert speed["speedKmh"] is None
    assert speed["speedSource"] is None


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
        enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, speed_max_kmh=3.5, sample_ts=0.0,
    )
    result = enrich_vehicle_frame(
        frame, [_det(7, [1010, 20, 1030, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, speed_max_kmh=3.5, sample_ts=1.0,
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


def test_scale_speed_ema_uses_configured_weights_after_median_changes():
    """A new 7.2-km/h median is blended with the 3.6-km/h prior EMA at 0.35/0.65."""
    session = VehicleSession()
    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    result = None
    for timestamp, x in enumerate((0, 10, 20, 30, 40, 50, 70, 90, 110)):
        result = enrich_vehicle_frame(
            frame, [_det(7, [x, 20, x + 20, 60])], session,
            enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, sample_ts=float(timestamp),
        )
    assert result["detections"][0]["speedKmh"] == 4.9
    assert session.speed_ema[7] == pytest.approx(4.86)

    result = enrich_vehicle_frame(
        frame, [_det(7, [130, 20, 150, 60])], session,
        enable_ocr=False, enable_trail=False, meters_per_pixel=0.1, sample_ts=9.0,
    )
    assert result["detections"][0]["speedKmh"] == 5.7
    assert session.speed_ema[7] == pytest.approx(5.679)


@pytest.mark.parametrize(
    "samples",
    [
        [(0.0, 10), (1.0, 30), (1.5, 110), (2.0, 130)],
        [(0.0, 130), (1.0, 110), (1.5, 30), (2.0, 10)],
    ],
)
def test_double_line_speed_in_both_directions(samples):
    """Either gate order must measure 10 metres crossed in one second as 36 km/h."""
    session = VehicleSession()
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    result = None
    for timestamp, x in samples:
        result = enrich_vehicle_frame(
            frame,
            [_det(7, [x - 5, 10, x + 5, 50])],
            session,
            enable_ocr=False,
            enable_trail=False,
            speed_mode="double-line",
            speed_line_a_px=[20, 0, 20, 100],
            speed_line_b_px=[120, 0, 120, 100],
            speed_distance_m=10.0,
            sample_ts=timestamp,
        )

    speed = result["detections"][0]
    assert speed["speedKmh"] == 36.0
    assert speed["speedSource"] == "double-line"
    assert speed["speedQuality"] == "measured"


def test_double_line_ignores_repeated_crossing_jitter():
    """Repeated A-line crossings must not replace the first valid gate timestamp."""
    session = VehicleSession()
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    result = None
    for timestamp, x in [(0.0, 10), (0.2, 30), (0.4, 10), (0.6, 30), (0.8, 110), (1.2, 130)]:
        result = enrich_vehicle_frame(
            frame,
            [_det(7, [x - 5, 10, x + 5, 50])],
            session,
            enable_ocr=False,
            enable_trail=False,
            speed_mode="double-line",
            speed_line_a_px=[20, 0, 20, 100],
            speed_line_b_px=[120, 0, 120, 100],
            speed_distance_m=10.0,
            sample_ts=timestamp,
        )

    speed = result["detections"][0]
    assert speed["speedKmh"] == 36.0
    assert speed["speedSource"] == "double-line"
    assert speed["speedQuality"] == "measured"


def test_incomplete_double_line_config_falls_back_to_scale():
    """Missing gate distance must preserve calibrated scale-speed behavior."""
    session = VehicleSession()
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    enrich_vehicle_frame(
        frame,
        [_det(7, [5, 10, 15, 50])],
        session,
        enable_ocr=False,
        enable_trail=False,
        speed_mode="double-line",
        speed_line_a_px=[20, 0, 20, 100],
        speed_line_b_px=[120, 0, 120, 100],
        meters_per_pixel=0.1,
        sample_ts=0.0,
    )
    result = enrich_vehicle_frame(
        frame,
        [_det(7, [15, 10, 25, 50])],
        session,
        enable_ocr=False,
        enable_trail=False,
        speed_mode="double-line",
        speed_line_a_px=[20, 0, 20, 100],
        speed_line_b_px=[120, 0, 120, 100],
        meters_per_pixel=0.1,
        sample_ts=1.0,
    )

    speed = result["detections"][0]
    assert speed["speedKmh"] == 3.6
    assert speed["speedSource"] == "scale"
    assert speed["speedQuality"] == "estimated"


def test_double_line_rejects_speed_above_limit():
    """A physically impossible gate interval must not produce a numeric speed."""
    session = VehicleSession()
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    result = None
    for timestamp, x in [(0.0, 10), (1.0, 30), (1.05, 110), (1.1, 130)]:
        result = enrich_vehicle_frame(
            frame,
            [_det(7, [x - 5, 10, x + 5, 50])],
            session,
            enable_ocr=False,
            enable_trail=False,
            speed_mode="double-line",
            speed_line_a_px=[20, 0, 20, 100],
            speed_line_b_px=[120, 0, 120, 100],
            speed_distance_m=10.0,
            speed_max_kmh=100.0,
            sample_ts=timestamp,
        )

    speed = result["detections"][0]
    assert speed["speedKmh"] is None
    assert speed["speedQuality"] == "invalid"


@pytest.mark.parametrize(
    ("line_a", "line_b"),
    [
        ([20, 100, 20, 0], [120, 0, 120, 100]),
        ([20, 0, 20, 100], [120, 100, 120, 0]),
    ],
)
def test_double_line_turnaround_starts_at_first_inward_gate_crossing(line_a, line_b):
    """An outward crossing from between the gates cannot become a measurement start."""
    session = VehicleSession()
    speed = None
    for timestamp, x in [(0.0, 50), (1.0, 10), (1.5, 50), (1.8, 110), (2.0, 130)]:
        speed = _double_line_sample(
            session,
            7,
            x,
            timestamp,
            speed_line_a_px=line_a,
            speed_line_b_px=line_b,
        )

    assert speed["speedKmh"] == 72.0
    assert speed["speedSource"] == "double-line"
    assert speed["speedQuality"] == "measured"
    assert session.speed_gates[7]["first_ts"] == 1.5
    assert session.speed_gates[7]["completed_at"] == 2.0


@pytest.mark.parametrize(
    ("line_a", "line_b"),
    [
        ([20, 0, 20, 100], [30, 0, 30, 10]),
        ([20, 100, 20, 0], [30, 0, 30, 10]),
        ([20, 0, 20, 100], [30, 10, 30, 0]),
    ],
    ids=["original", "a-reversed", "b-reversed"],
)
@pytest.mark.parametrize(
    ("points", "first_line", "direction"),
    [
        ([(10, -7), (25, 5), (35, 13)], "a", 1),
        ([(35, 13), (25, 5), (10, -7)], "b", -1),
    ],
    ids=["forward", "reverse"],
)
def test_double_line_offset_unequal_gates_use_local_crossing_direction(
    line_a,
    line_b,
    points,
    first_line,
    direction,
):
    """Actual crossing geometry must support offset unequal gates in either travel direction."""
    session = VehicleSession()
    _double_line_point_sample(session, points[0], 0.0, line_a=line_a, line_b=line_b)
    waiting = _double_line_point_sample(session, points[1], 1.0, line_a=line_a, line_b=line_b)

    assert waiting["speedKmh"] is None
    assert waiting["speedSource"] is None
    assert waiting["speedQuality"] == "warming-up"
    assert session.speed_gates[7]["first_line"] == first_line
    assert session.speed_gates[7]["first_ts"] == 1.0
    assert session.speed_gates[7]["direction"] == direction

    measured = _double_line_point_sample(session, points[2], 2.0, line_a=line_a, line_b=line_b)
    assert measured["speedKmh"] == 36.0
    assert measured["speedSource"] == "double-line"
    assert measured["speedQuality"] == "measured"


def test_double_line_gate_state_is_isolated_by_track_id():
    """Interleaved vehicles must retain independent first gates and timestamps."""
    session = VehicleSession()
    _double_line_sample(session, 7, 10, 0.0)
    _double_line_sample(session, 8, 130, 0.0)
    _double_line_sample(session, 7, 30, 1.0)
    _double_line_sample(session, 8, 110, 1.0)

    assert session.speed_gates[7]["first_line"] == "a"
    assert session.speed_gates[7]["first_ts"] == 1.0
    assert session.speed_gates[8]["first_line"] == "b"
    assert session.speed_gates[8]["first_ts"] == 1.0

    forward = _double_line_sample(session, 7, 130, 2.0)
    reverse = _double_line_sample(session, 8, 10, 2.0)
    assert (forward["speedKmh"], forward["speedSource"], forward["speedQuality"]) == (
        36.0,
        "double-line",
        "measured",
    )
    assert (reverse["speedKmh"], reverse["speedSource"], reverse["speedQuality"]) == (
        36.0,
        "double-line",
        "measured",
    )


@pytest.mark.parametrize(
    ("changed_options", "final_x"),
    [
        ({"speed_distance_m": 20.0}, 130),
        ({"speed_max_kmh": 100.0}, 130),
        ({"speed_line_b_px": [130, 0, 130, 100]}, 140),
    ],
    ids=["distance", "speed-limit", "line"],
)
def test_double_line_configuration_change_resets_pending_gate(changed_options, final_x):
    """A pending first gate cannot be completed under a different calibration."""
    session = VehicleSession()
    _double_line_sample(session, 7, 10, 0.0)
    _double_line_sample(session, 7, 30, 1.0)

    speed = _double_line_sample(session, 7, final_x, 2.0, **changed_options)

    assert speed["speedKmh"] is None
    assert speed["speedSource"] is None
    assert speed["speedQuality"] == "warming-up"
    assert "completed_at" not in session.speed_gates[7]


@pytest.mark.parametrize("timestamp", [1.0, 0.5, 3.1], ids=["zero-dt", "non-monotonic", "gap"])
def test_double_line_invalid_timeline_resets_only_that_gate(timestamp):
    """Equal, reversed, and interrupted media time cannot complete a gate interval."""
    session = VehicleSession()
    _double_line_sample(session, 7, 10, 0.0)
    _double_line_sample(session, 7, 30, 1.0)
    speed = _double_line_sample(session, 7, 130, timestamp)

    assert speed["speedKmh"] is None
    assert speed["speedSource"] is None
    assert speed["speedQuality"] == "warming-up"
    assert session.speed_gates[7] == {"last_point": (130.0, 50.0), "last_ts": timestamp}


def test_double_line_completed_gate_ignores_second_line_jitter():
    """Second-line oscillation inside cooldown must not create or retime another measurement."""
    session = VehicleSession()
    speed = None
    for timestamp, x in [(0.0, 10), (1.0, 30), (1.5, 119), (2.0, 121), (2.5, 119)]:
        speed = _double_line_sample(session, 7, x, timestamp)

    assert speed["speedKmh"] == 36.0
    assert speed["speedSource"] == "double-line"
    assert speed["speedQuality"] == "measured"
    assert session.speed_gates[7]["first_ts"] == 1.0
    assert session.speed_gates[7]["completed_at"] == 2.0


def test_double_line_completed_gate_resets_after_two_second_cooldown():
    """A completed gate held near line B must reset when its two-second cooldown expires."""
    session = VehicleSession()
    for timestamp, x in [(0.0, 10), (1.0, 30), (1.5, 119), (2.0, 121), (2.5, 119)]:
        _double_line_sample(session, 7, x, timestamp)
    speed = _double_line_sample(session, 7, 121, 4.1)

    assert speed["speedKmh"] is None
    assert speed["speedSource"] is None
    assert speed["speedQuality"] == "warming-up"
    assert session.speed_gates[7] == {"last_point": (121.0, 50.0), "last_ts": 4.1}


@pytest.mark.parametrize(
    "overrides",
    [
        {"speed_line_a_px": None},
        {"speed_line_b_px": None},
        {"speed_line_a_px": [float("nan"), 0, 20, 100]},
        {"speed_distance_m": 0.0},
        {"speed_distance_m": float("nan")},
        {"speed_mode": "warp-drive"},
    ],
    ids=["missing-a", "missing-b", "nan-line", "zero-distance", "nan-distance", "invalid-mode"],
)
def test_invalid_double_line_configuration_safely_falls_back_to_scale(overrides):
    """Malformed double-line inputs must leave no gate state and use calibrated scale speed."""
    session = VehicleSession()
    _double_line_sample(session, 7, 10, 0.0, meters_per_pixel=0.1, **overrides)
    speed = _double_line_sample(session, 7, 20, 1.0, meters_per_pixel=0.1, **overrides)

    assert speed["speedKmh"] == 3.6
    assert speed["speedSource"] == "scale"
    assert speed["speedQuality"] == "estimated"
    assert 7 not in session.speed_gates


def test_records_are_created_without_ocr_and_refresh_when_speed_completes():
    """One Track ID owns one record even without OCR, including later speed state changes."""
    session = VehicleSession()
    samples = [(0.0, 10), (1.0, 30), (1.5, 110), (2.0, 130)]

    first = _double_line_sample(session, 7, samples[0][1], samples[0][0])
    assert first["speedQuality"] == "warming-up"
    assert len(session.records) == 1
    assert session.records[0]["plate"] is None
    assert session.records[0]["speedKmh"] is None
    assert session.records[0]["speedSource"] is None
    assert session.records[0]["speedQuality"] == "warming-up"

    for timestamp, x in samples[1:]:
        _double_line_sample(session, 7, x, timestamp)

    assert len(session.records) == 1
    assert session.records[0]["speedKmh"] == 36.0
    assert session.records[0]["speedSource"] == "double-line"
    assert session.records[0]["speedQuality"] == "measured"

    _double_line_sample(session, 7, 150, 2.5)
    assert session.records[0]["speedKmh"] == 36.0
    assert session.records[0]["speedSource"] == "double-line"
    assert session.records[0]["speedQuality"] == "measured"


def test_stale_track_cleanup_removes_all_speed_state_and_record_index():
    """Evicting stale trail state must evict the same Track IDs from speed ownership."""
    session = VehicleSession()
    session.record_indices = {}
    for track_id in range(70):
        session.track_history[track_id] = [(0.0, 0.0, 0.0)]
        session.speed_history[track_id] = [(0.0, 0.0, 0.0)]
        session.speed_ema[track_id] = 1.0
        session.speed_gates[track_id] = {"last_point": (0.0, 0.0), "last_ts": 0.0}
        session.record_indices[track_id] = track_id
        session.records.append({"trackId": track_id})

    enrich_vehicle_frame(
        np.zeros((100, 200, 3), dtype=np.uint8),
        [_det(999, [10, 20, 30, 60])],
        session,
        enable_ocr=False,
        enable_speed=False,
        enable_trail=False,
        sample_ts=1.0,
    )

    for state in (
        session.track_history,
        session.speed_history,
        session.speed_ema,
        session.speed_gates,
        session.record_indices,
    ):
        assert 0 not in state


@pytest.mark.parametrize(
    "detection",
    [
        {"speedKmh": 0.0, "speedSource": "scale", "speedQuality": "estimated"},
        {"speedKmh": None, "speedSource": None, "speedQuality": "warming-up"},
    ],
    ids=["legal-zero", "warming-up"],
)
def test_video_hud_renders_speed_quality_and_source(monkeypatch, detection):
    """Video HUD must render legal zero and the same Chinese quality/source vocabulary as the UI."""
    labels = []

    def capture_label(image, text, *_args, **_kwargs):
        labels.append(text)
        return image

    monkeypatch.setattr(vehicle_track, "_draw_label_bgr", capture_label)
    vehicle_track.draw_vehicle_hud(
        np.zeros((100, 200, 3), dtype=np.uint8),
        {
            "detections": [{
                **_det(7, [10, 20, 30, 60]),
                **detection,
                "plate": None,
                "alarm": None,
            }],
        },
        draw_trails=False,
    )

    expected = "0.0km/h 比例估算" if detection["speedKmh"] == 0.0 else "测速准备中"
    assert any(expected in label for label in labels)


@pytest.mark.parametrize(
    ("line_a", "line_b"),
    [
        ([20, 0, 20, 0], [120, 0, 120, 100]),
        ([20, 0, 20, 100], [20, 0, 20, 100]),
        ([20, 0, 20, 100], [22, 0, 22, 100]),
        ([0, 0, 100, 0], [10, 0, 110, 0]),
    ],
    ids=["zero-length", "overlapping", "near-overlapping", "partially-overlapping"],
)
def test_degenerate_double_line_gates_fall_back_to_scale(line_a, line_b):
    """Zero-length and overlapping gate geometry cannot create measurement state."""
    session = VehicleSession()
    options = {
        "meters_per_pixel": 0.1,
        "speed_line_a_px": line_a,
        "speed_line_b_px": line_b,
    }
    _double_line_sample(session, 7, 10, 0.0, **options)
    speed = _double_line_sample(session, 7, 20, 1.0, **options)

    assert speed["speedKmh"] == 3.6
    assert speed["speedSource"] == "scale"
    assert speed["speedQuality"] == "estimated"
    assert 7 not in session.speed_gates


def test_track_frame_double_line_parameters_are_scaled_and_clamped(monkeypatch):
    """The frame API must convert normalized gates to pixels and clamp the speed limit."""
    import cv2
    import inference

    vehicle_route = _load_vehicle_route(monkeypatch)
    app = Flask(__name__)
    app.register_blueprint(vehicle_route.vehicle_bp)
    captured = {}
    monkeypatch.setattr(
        vehicle_route,
        "_resolve_models",
        lambda: ({"detect_path": "fake.pt", "plate_path": None, "ocr_fn": None}, None),
    )
    monkeypatch.setattr(vehicle_route, "_resolve_track_classes", lambda **_kwargs: ([2], None))
    monkeypatch.setattr(inference, "track_frame", lambda *_args, **_kwargs: {"detections": []})

    def capture_enrich(_image, _detections, _session, **kwargs):
        captured.update(kwargs)
        return {"detections": []}

    monkeypatch.setattr(vehicle_track, "enrich_vehicle_frame", capture_enrich)
    ok, encoded = cv2.imencode(".jpg", np.zeros((100, 200, 3), dtype=np.uint8))
    assert ok
    response = app.test_client().post(
        "/api/ai/vehicle/track-frame",
        data={
            "file": (io.BytesIO(encoded.tobytes()), "frame.jpg"),
            "speedMode": "double-line",
            "speedLineA": "[0.1, 0, 0.1, 1]",
            "speedLineB": "[0.6, 0, 0.6, 1]",
            "speedDistanceM": "10",
            "speedMaxKmh": "5",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert captured["speed_mode"] == "double-line"
    assert captured["speed_line_a_px"] == [20.0, 0.0, 20.0, 100.0]
    assert captured["speed_line_b_px"] == [120.0, 0.0, 120.0, 100.0]
    assert captured["speed_distance_m"] == 10.0
    assert captured["speed_max_kmh"] == 30.0


@pytest.mark.parametrize(
    "invalid_line",
    [
        "[-0.1, 0, 0.1, 1]",
        "[0.1, 0, 1.1, 1]",
    ],
    ids=["below-zero", "above-one"],
)
def test_track_frame_rejects_out_of_range_normalized_speed_lines(monkeypatch, invalid_line):
    """Normalized gate coordinates outside 0..1 must not reach pixel geometry."""
    import cv2
    import inference

    vehicle_route = _load_vehicle_route(monkeypatch)
    app = Flask(__name__)
    app.register_blueprint(vehicle_route.vehicle_bp)
    captured = {}
    monkeypatch.setattr(
        vehicle_route,
        "_resolve_models",
        lambda: ({"detect_path": "fake.pt", "plate_path": None, "ocr_fn": None}, None),
    )
    monkeypatch.setattr(vehicle_route, "_resolve_track_classes", lambda **_kwargs: ([2], None))
    monkeypatch.setattr(inference, "track_frame", lambda *_args, **_kwargs: {"detections": []})

    def capture_enrich(_image, _detections, _session, **kwargs):
        captured.update(kwargs)
        return {"detections": []}

    monkeypatch.setattr(vehicle_track, "enrich_vehicle_frame", capture_enrich)
    ok, encoded = cv2.imencode(".jpg", np.zeros((100, 200, 3), dtype=np.uint8))
    assert ok
    response = app.test_client().post(
        "/api/ai/vehicle/track-frame",
        data={
            "file": (io.BytesIO(encoded.tobytes()), "frame.jpg"),
            "speedMode": "double-line",
            "speedLineA": invalid_line,
            "speedLineB": "[0.6, 0, 0.6, 1]",
            "speedDistanceM": "10",
            "metersPerPixel": "0.1",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert captured["speed_line_a_px"] is None
    assert captured["speed_line_b_px"] == [120.0, 0.0, 120.0, 100.0]


def test_legacy_meters_per_pixel_request_remains_supported(monkeypatch):
    """A pre-calibration client must still obtain scale speed from metersPerPixel."""
    import cv2
    import inference

    vehicle_route = _load_vehicle_route(monkeypatch)
    app = Flask(__name__)
    app.register_blueprint(vehicle_route.vehicle_bp)
    detections = iter([
        {"detections": [_det(7, [10, 20, 30, 60])]},
        {"detections": [_det(7, [30, 20, 50, 60])]},
    ])
    monkeypatch.setattr(
        vehicle_route,
        "_resolve_models",
        lambda: ({"detect_path": "fake.pt", "plate_path": None, "ocr_fn": None}, None),
    )
    monkeypatch.setattr(vehicle_route, "_resolve_track_classes", lambda **_kwargs: ([2], None))
    monkeypatch.setattr(inference, "track_frame", lambda *_args, **_kwargs: next(detections))
    timestamps = iter([0.0, 1.0])
    monkeypatch.setattr(vehicle_track.time, "monotonic", lambda: next(timestamps))
    ok, encoded = cv2.imencode(".jpg", np.zeros((100, 200, 3), dtype=np.uint8))
    assert ok
    client = app.test_client()

    for reset in ("1", "0"):
        response = client.post(
            "/api/ai/vehicle/track-frame",
            data={
                "file": (io.BytesIO(encoded.tobytes()), "frame.jpg"),
                "sessionId": "legacy-scale",
                "reset": reset,
                "enableOcr": "0",
                "enableTrail": "0",
                "enableSpeed": "1",
                "metersPerPixel": "0.05",
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 200

    assert response.json["data"]["detections"][0]["speedSource"] == "scale"


def test_export_records_csv_includes_speed_source_and_quality(monkeypatch):
    """The live export endpoint must preserve the record's speed provenance end to end."""
    vehicle_route = _load_vehicle_route(monkeypatch)
    app = Flask(__name__)
    app.register_blueprint(vehicle_route.vehicle_bp)
    session_id = "speed-export"
    session = vehicle_track.get_session(session_id, reset=True)
    try:
        for timestamp, x in [(0.0, 10), (1.0, 30), (1.5, 110), (2.0, 130)]:
            _double_line_sample(session, 7, x, timestamp)

        response = app.test_client().post(
            "/api/ai/vehicle/export-records",
            json={"sessionId": session_id},
        )

        assert response.status_code == 200
        rows = list(csv.reader(io.StringIO(response.json["data"]["csv"])))
        assert rows[0] == [
            "time", "trackId", "className", "plate", "plateScore",
            "speedKmh", "speedSource", "speedQuality", "confidence",
        ]
        assert rows[1][5:8] == ["36.0", "double-line", "measured"]
        assert response.json["data"]["count"] == 1
    finally:
        vehicle_track.clear_session(session_id)


def test_track_video_double_line_parameters_reach_worker_config(monkeypatch, tmp_path):
    """The video API must preserve normalized gate config for dimension-aware worker conversion."""
    vehicle_route = _load_vehicle_route(monkeypatch)
    app = Flask(__name__)
    app.config.update(
        VIDEO_ALLOWED_EXT={".mp4"},
        VIDEO_FOLDER=str(tmp_path / "videos"),
        OUTPUT_FOLDER=str(tmp_path / "outputs"),
    )
    app.register_blueprint(vehicle_route.vehicle_bp)
    launched = {}
    monkeypatch.setattr(
        vehicle_route,
        "_resolve_models",
        lambda: ({"detect_path": "fake.pt", "plate_path": None, "ocr_fn": None}, None),
    )
    monkeypatch.setattr(vehicle_route, "_resolve_track_classes", lambda **_kwargs: ([2], None))

    class _CapturedThread:
        def __init__(self, *, target, args, daemon):
            launched.update(target=target, args=args, daemon=daemon)

        def start(self):
            pass

    monkeypatch.setattr(vehicle_route.threading, "Thread", _CapturedThread)
    response = app.test_client().post(
        "/api/ai/vehicle/track-video",
        data={
            "file": (io.BytesIO(b"not-a-real-video"), "traffic.mp4"),
            "speedMode": "double-line",
            "speedLineA": "[0.1, 0, 0.1, 1]",
            "speedLineB": "[0.6, 0, 0.6, 1]",
            "speedDistanceM": "10",
            "speedMaxKmh": "999",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    config = launched["args"][1]
    assert config["speed_mode"] == "double-line"
    assert config["speed_line_a"] == [0.1, 0.0, 0.1, 1.0]
    assert config["speed_line_b"] == [0.6, 0.0, 0.6, 1.0]
    assert config["speed_distance_m"] == 10.0
    assert config["speed_max_kmh"] == 400.0


class _FakeCapture:
    def __init__(self, frames, fps):
        self._frames = frames
        self._fps = fps
        self._index = 0

    def isOpened(self):
        return True

    def get(self, prop):
        import cv2

        if prop == cv2.CAP_PROP_FPS:
            return self._fps
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return len(self._frames)
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return self._frames[0].shape[1]
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return self._frames[0].shape[0]
        return 0

    def read(self):
        if self._index >= len(self._frames):
            return False, None
        frame = self._frames[self._index]
        self._index += 1
        return True, frame

    def release(self):
        pass


class _FakeTensor:
    def __init__(self, values):
        self._values = values

    def int(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self._values


class _FakeVehicleModel:
    def __init__(self):
        self._frame_index = 0

    def track(self, _frame, **_kwargs):
        x = self._frame_index * 10
        self._frame_index += 1
        boxes = type("Boxes", (), {
            "id": _FakeTensor([7]),
            "cls": _FakeTensor([2]),
            "conf": _FakeTensor([0.9]),
            "xyxy": _FakeTensor([[x, 20, x + 20, 60]]),
        })()
        return [type("Result", (), {"names": {2: "car"}, "boxes": boxes})()]


class _FakeWriter:
    def close(self):
        pass


def _run_fake_vehicle_worker(vehicle_route, monkeypatch, tmp_path, monotonic_values):
    """Run three known frames and return observable worker speed output."""
    import cv2
    import inference

    frames = [np.zeros((100, 200, 3), dtype=np.uint8) for _ in range(3)]
    speeds = []
    monotonic = iter(monotonic_values)
    job_id = f"media-time-{len(monotonic_values)}-{monotonic_values[0]}"

    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: _FakeCapture(frames, fps=2.0))
    monkeypatch.setattr(inference, "_get_model", lambda _path: _FakeVehicleModel())
    monkeypatch.setattr(inference, "_open_h264", lambda _dst, _fps, w, h: (_FakeWriter(), w, h))
    monkeypatch.setattr(inference, "_write_bgr", lambda *_args: None)
    monkeypatch.setattr(inference, "_video_alert_ctx", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(inference, "_video_alert_stats", lambda _ctx: {})
    monkeypatch.setattr(vehicle_track.time, "monotonic", lambda: next(monotonic))

    def capture_enriched(frame, enriched, **_kwargs):
        speeds.append(enriched["detections"][0]["speedKmh"])
        return frame

    monkeypatch.setattr(vehicle_track, "draw_vehicle_hud", capture_enriched)
    monkeypatch.setitem(
        vehicle_route._video_jobs,
        job_id,
        {"status": "running", "processed": 0, "total": 0, "stats": None, "error": None},
    )
    vehicle_route._vehicle_worker(job_id, {
        "detect_path": "fake.pt",
        "src_path": str(tmp_path / "input.mp4"),
        "dst_path": str(tmp_path / "output.mp4"),
        "out_name": "output.mp4",
        "conf": 0.25,
        "imgsz": 640,
        "line": None,
        "session_id": f"{job_id}-session",
        "enable_ocr": False,
        "enable_speed": True,
        "enable_trail": False,
        "meters_per_pixel": 0.1,
    })
    assert vehicle_route._video_jobs[job_id]["status"] == "done"
    return [speed for speed in speeds if speed is not None]


def test_vehicle_video_speed_uses_media_timeline(monkeypatch, tmp_path):
    """Offline video speed is invariant to processing-time delays."""
    vehicle_route = _load_vehicle_route(monkeypatch)
    first = _run_fake_vehicle_worker(vehicle_route, monkeypatch, tmp_path, monotonic_values=[1, 100, 900])
    second = _run_fake_vehicle_worker(vehicle_route, monkeypatch, tmp_path, monotonic_values=[5, 6, 7])
    assert first == second == [7.2, 7.2]


@pytest.mark.parametrize(
    "invalid_fps",
    [0.0, -1.0, float("nan"), float("inf"), 241.0],
    ids=["zero", "negative", "nan", "infinite", "over-240"],
)
def test_vehicle_video_invalid_fps_uses_25_for_writer_and_media_timestamps(
    monkeypatch, tmp_path, invalid_fps,
):
    """Invalid source FPS must not leak into output timing or writer configuration."""
    import cv2
    import inference

    vehicle_route = _load_vehicle_route(monkeypatch)
    frames = [np.zeros((100, 200, 3), dtype=np.uint8) for _ in range(3)]
    writer_fps = []
    sample_timestamps = []
    real_enrich = vehicle_track.enrich_vehicle_frame
    job_id = f"invalid-fps-{invalid_fps!r}"

    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: _FakeCapture(frames, fps=invalid_fps))
    monkeypatch.setattr(inference, "_get_model", lambda _path: _FakeVehicleModel())

    def open_writer(_dst, fps, width, height):
        writer_fps.append(fps)
        return _FakeWriter(), width, height

    def capture_enrich(*args, **kwargs):
        sample_timestamps.append(kwargs["sample_ts"])
        return real_enrich(*args, **kwargs)

    monkeypatch.setattr(inference, "_open_h264", open_writer)
    monkeypatch.setattr(inference, "_write_bgr", lambda *_args: None)
    monkeypatch.setattr(inference, "_video_alert_ctx", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(inference, "_video_alert_stats", lambda _ctx: {})
    monkeypatch.setattr(vehicle_track, "enrich_vehicle_frame", capture_enrich)
    monkeypatch.setattr(vehicle_track, "draw_vehicle_hud", lambda frame, _enriched, **_kwargs: frame)
    monkeypatch.setitem(
        vehicle_route._video_jobs,
        job_id,
        {"status": "running", "processed": 0, "total": 0, "stats": None, "error": None},
    )

    vehicle_route._vehicle_worker(job_id, {
        "detect_path": "fake.pt",
        "src_path": str(tmp_path / "input.mp4"),
        "dst_path": str(tmp_path / "output.mp4"),
        "out_name": "output.mp4",
        "conf": 0.25,
        "imgsz": 640,
        "line": None,
        "session_id": f"{job_id}-session",
        "enable_ocr": False,
        "enable_speed": True,
        "enable_trail": False,
        "meters_per_pixel": 0.1,
    })

    assert vehicle_route._video_jobs[job_id]["status"] == "done"
    assert writer_fps == [25.0]
    assert sample_timestamps == pytest.approx([0.0, 0.04, 0.08])


def test_double_line_video_worker_converts_normalized_lines(monkeypatch, tmp_path):
    """The video worker must scale normalized gates with the decoded video dimensions."""
    import cv2
    import inference

    vehicle_route = _load_vehicle_route(monkeypatch)
    frames = [np.zeros((100, 200, 3), dtype=np.uint8)]
    captured = {}
    real_enrich = vehicle_track.enrich_vehicle_frame
    job_id = "double-line-worker"

    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: _FakeCapture(frames, fps=25.0))
    monkeypatch.setattr(inference, "_get_model", lambda _path: _FakeVehicleModel())
    monkeypatch.setattr(inference, "_open_h264", lambda _dst, _fps, w, h: (_FakeWriter(), w, h))
    monkeypatch.setattr(inference, "_write_bgr", lambda *_args: None)
    monkeypatch.setattr(inference, "_video_alert_ctx", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(inference, "_video_alert_stats", lambda _ctx: {})

    def capture_enrich(*args, **kwargs):
        captured.update(kwargs)
        return real_enrich(*args, **kwargs)

    monkeypatch.setattr(vehicle_track, "enrich_vehicle_frame", capture_enrich)
    monkeypatch.setattr(vehicle_track, "draw_vehicle_hud", lambda frame, _enriched, **_kwargs: frame)
    monkeypatch.setitem(
        vehicle_route._video_jobs,
        job_id,
        {"status": "running", "processed": 0, "total": 0, "stats": None, "error": None},
    )
    vehicle_route._vehicle_worker(job_id, {
        "detect_path": "fake.pt",
        "src_path": str(tmp_path / "input.mp4"),
        "dst_path": str(tmp_path / "output.mp4"),
        "out_name": "output.mp4",
        "conf": 0.25,
        "imgsz": 640,
        "line": None,
        "region": None,
        "session_id": "double-line-worker-session",
        "enable_ocr": False,
        "enable_speed": True,
        "enable_trail": False,
        "meters_per_pixel": None,
        "speed_mode": "double-line",
        "speed_line_a": [0.1, 0.0, 0.1, 1.0],
        "speed_line_b": [0.6, 0.0, 0.6, 1.0],
        "speed_distance_m": 10.0,
        "speed_max_kmh": 240.0,
    })

    assert vehicle_route._video_jobs[job_id]["status"] == "done"
    assert captured["speed_mode"] == "double-line"
    assert captured["speed_line_a_px"] == [20.0, 0.0, 20.0, 100.0]
    assert captured["speed_line_b_px"] == [120.0, 0.0, 120.0, 100.0]
    assert captured["speed_distance_m"] == 10.0
    assert captured["speed_max_kmh"] == 240.0
