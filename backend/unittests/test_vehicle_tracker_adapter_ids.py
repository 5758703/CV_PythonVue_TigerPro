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


def test_mtmc_separate_vehicle_detector_feeds_only_matched_recovery_boxes(monkeypatch):
    pytest.importorskip("trackers")
    pytest.importorskip("supervision")
    from services import mtmc_engine as mt

    cfg = mt.MtmcConfig(camera_ids=[1], det_vehicle_path="vehicle.pt", enable_person=False)
    tracker = mt._make_local_tracker(cfg, object_type="vehicle")
    assert cfg.local_track_backend == "bytetrack"
    frame = np.zeros((100, 100, 3), np.uint8)
    scores = iter([0.90, 0.90, 0.15])

    def detect(path, frame, conf, classes):
        score = next(scores)
        boxes = [[4, 4, 30, 30]]
        if score < cfg.conf:
            boxes.append([60, 60, 90, 90])
        return [dict(className="car", classId=2, confidence=score, bbox=b) for b in boxes if score > conf]

    monkeypatch.setattr(mt, "_detect", detect)
    for _ in range(2):
        _, vehicles = mt._detect_person_vehicle(cfg, frame)
        previous = mt._tracks_or_raw(tracker, vehicles, frame)
    _, weak = mt._detect_person_vehicle(cfg, frame)
    assert len(weak) == 2 and all(d["associationOnly"] for d in weak)
    tracks = mt._tracks_or_raw(tracker, weak, frame)
    assert [t.track_id for t in tracks] == [previous[0].track_id]
    assert tracks[0].conf == pytest.approx(0.15)
    assert mt._tracks_or_raw(tracker, [weak[1]], frame) == []


def test_pipeline_reports_associated_scores_without_emitting_weak_orphans():
    pytest.importorskip("trackers")
    pytest.importorskip("supervision")
    from services.mtmc_local_track import create_local_tracker
    from services.pipeline_runtime import _apply_tracking

    session = SimpleNamespace(conf=0.35, stats={},
                              _tracker=create_local_tracker("bytetrack", track_activation_threshold=0.35))
    def det(x, score):
        return {"className": "car", "bbox": [x, 0, x + 20, 20], "confidence": score}

    _apply_tracking(session, [det(0, 0.8)])
    high = _apply_tracking(session, [det(0, 0.8)])[0]
    low = _apply_tracking(session, [det(0, 0.15), det(60, 0.15)])
    assert len(low) == 1 and low[0]["trackId"] == high["trackId"]
    assert low[0]["confidence"] == pytest.approx(0.15)
