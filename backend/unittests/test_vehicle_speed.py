import importlib.util
import pathlib
import sys
import types

import numpy as np
import pytest

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
