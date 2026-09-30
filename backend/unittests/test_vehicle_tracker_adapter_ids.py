"""A local tracker adapter must preserve confirmed native vehicle identities."""
from types import SimpleNamespace

import numpy as np
import pytest

from services.mtmc_local_track import _SvTrackerAdapter


class Tracked:
    def __init__(self, ids, boxes):
        self.tracker_id = np.asarray(ids)
        self.xyxy = np.asarray(boxes, dtype=np.float32)
        self.confidence = np.full(len(ids), 0.9)

    def __len__(self):
        return len(self.tracker_id)


def test_confirmed_vehicle_ids_do_not_swap_when_boxes_cross(monkeypatch):
    left, right = [0, 0, 40, 40], [100, 0, 140, 40]
    frames = iter([
        Tracked([-1], [left]), Tracked([0], [left]),
        Tracked([-1], [right]), Tracked([1], [right]),
        Tracked([0, 1], [right, left]),
    ])
    adapter = _SvTrackerAdapter(SimpleNamespace(update=lambda _d: next(frames)))
    monkeypatch.setattr(adapter, "_to_sv_detections", lambda d: d)
    detections = [{"bbox": b, "className": "car"} for b in (left, right)]
    first = adapter.update(detections)[0].track_id
    assert adapter.update(detections)[0].track_id == first
    second = adapter.update(detections)[0].track_id
    assert adapter.update(detections)[0].track_id == second
    assert first != second
    crossed = adapter.update(detections)
    assert [t.track_id for t in crossed] == [first, second]


def test_new_native_vehicle_cannot_reuse_old_confirmed_tentative_id(monkeypatch):
    box = [0, 0, 40, 40]
    frames = iter([Tracked([-1], [box]), Tracked([0], [box]), Tracked([1], [box])])
    adapter = _SvTrackerAdapter(SimpleNamespace(update=lambda _d: next(frames)))
    monkeypatch.setattr(adapter, "_to_sv_detections", lambda d: d)
    detections = [{"bbox": box, "className": "car"}]
    first = adapter.update(detections)[0].track_id
    assert adapter.update(detections)[0].track_id == first
    assert adapter.update(detections)[0].track_id != first


def test_overlapping_tentative_vehicles_have_unique_ids_in_one_frame(monkeypatch):
    boxes = [[0, 0, 40, 40], [10, 0, 50, 40]]
    adapter = _SvTrackerAdapter(SimpleNamespace(update=lambda _d: Tracked([-1, -1], boxes)))
    monkeypatch.setattr(adapter, "_to_sv_detections", lambda d: d)
    result = adapter.update([{"bbox": b, "className": "car"} for b in boxes])
    assert len({t.track_id for t in result}) == 2


def test_unconfirmed_vehicle_placeholder_cannot_bridge_a_detection_gap(monkeypatch):
    box = [0, 0, 40, 40]
    frames = iter([Tracked([-1], [box]), Tracked([], []), Tracked([-1], [box])])
    adapter = _SvTrackerAdapter(SimpleNamespace(update=lambda _d: next(frames)))
    monkeypatch.setattr(adapter, "_to_sv_detections", lambda d: d)
    detections = [{"bbox": box, "className": "car"}]
    first = adapter.update(detections)[0].track_id
    adapter.update([])
    assert adapter.update(detections)[0].track_id != first


def test_new_confirmed_vehicle_cannot_promote_a_missing_placeholder(monkeypatch):
    box = [0, 0, 40, 40]
    frames = iter([Tracked([-1], [box]), Tracked([], []), Tracked([0], [box])])
    adapter = _SvTrackerAdapter(SimpleNamespace(update=lambda _d: next(frames)))
    monkeypatch.setattr(adapter, "_to_sv_detections", lambda d: d)
    detections = [{"bbox": box, "className": "car"}]
    first = adapter.update(detections)[0].track_id
    adapter.update([])
    assert adapter.update(detections)[0].track_id != first


@pytest.mark.parametrize("backend", ["bytetrack", "botsort"])
def test_tracker_activates_accepted_vehicle_below_library_default_split(backend):
    pytest.importorskip("trackers")
    pytest.importorskip("supervision")
    from services.mtmc_local_track import create_local_tracker

    tracker = create_local_tracker(backend, track_activation_threshold=0.25, frame_rate=2)
    detections = [{"bbox": [0, 0, 100, 100], "className": "car", "confidence": 0.45}]
    tracker.update(detections)
    result = tracker.update(detections)
    assert len(result) == 1
    assert not result[0].attrs["tentative"]
