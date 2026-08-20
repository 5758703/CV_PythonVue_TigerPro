"""ByteTrack vs IoU LocalTracker 概念验证脚本。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.mtmc_local_track import (
    LocalTracker,
    ByteTrackLocalTracker,
    bytetrack_available,
    create_local_tracker,
)


def _det(bbox, conf=0.9, cls="person"):
    return {"bbox": bbox, "confidence": conf, "className": cls}


def _first_track(tr, det):
    """首帧可能为空（ByteTrack 未确认），向后找第一个有效轨迹。"""
    out = tr.update(det)
    if out:
        return out[0]
    out = tr.update(det)
    return out[0] if out else None


def scenario_id_continuity(tracker_cls, name: str) -> dict:
    tr = tracker_cls(iou_thresh=0.3, max_age=5)
    first = _det([10, 10, 50, 80])
    t0 = _first_track(tr, [first])
    if t0 is None:
        return {"name": name, "scenario": "id_continuity", "pass": False, "ids": []}
    tid = t0.track_id
    ids = [tid]
    for dx in (2, 4, 6, 8):
        b = tr.update([_det([10 + dx, 10 + dx, 50 + dx, 80 + dx])])
        ids.append(b[0].track_id if b else None)
    ok = len(set(x for x in ids if x is not None)) == 1
    return {"name": name, "scenario": "id_continuity", "pass": ok, "ids": ids}


def scenario_low_conf_recovery(tracker_cls, name: str) -> dict:
    """ByteTrack 优势场景：中间帧低置信度检测仍保持 ID。"""
    tr = tracker_cls(iou_thresh=0.3, max_age=5)
    t0 = _first_track(tr, [_det([100, 100, 160, 200], conf=0.85)])
    if t0 is None:
        return {"name": name, "scenario": "low_conf_recovery", "pass": False, "start_id": None}
    tid = t0.track_id
    b = tr.update([_det([102, 102, 162, 202], conf=0.15)])
    c = tr.update([_det([104, 104, 164, 204], conf=0.88)])
    id_b = b[0].track_id if b else None
    id_c = c[0].track_id if c else None
    ok = id_c == tid
    return {
        "name": name,
        "scenario": "low_conf_recovery",
        "pass": ok,
        "start_id": tid,
        "low_conf_id": id_b,
        "recover_id": id_c,
    }


def scenario_occlusion_gap(tracker_cls, name: str) -> dict:
    tr = tracker_cls(iou_thresh=0.3, max_age=2)
    t0 = _first_track(tr, [_det([10, 10, 50, 80])])
    if t0 is None:
        return {"name": name, "scenario": "occlusion_gap", "pass": False}
    tid = t0.track_id
    tr.update([])
    tr.update([])
    tr.update([])
    b = tr.update([_det([10, 10, 50, 80])])
    new_id = b[0].track_id if b else None
    return {
        "name": name,
        "scenario": "occlusion_gap",
        "pass": new_id != tid,
        "start_id": tid,
        "after_gap_id": new_id,
    }


def scenario_multi_object(tracker_cls, name: str) -> dict:
    tr = tracker_cls(iou_thresh=0.3, max_age=5)
    dets = [_det([10, 10, 50, 80]), _det([200, 200, 260, 280])]
    a = tr.update(dets)
    if len(a) < 2:
        a = tr.update(dets)
    ids_a = sorted(t.track_id for t in a)
    b = tr.update([
        _det([12, 12, 52, 82]),
        _det([202, 202, 262, 282]),
    ])
    ids_b = sorted(t.track_id for t in b)
    ok = len(ids_a) == 2 and ids_a == ids_b
    return {"name": name, "scenario": "multi_object", "pass": ok, "ids_a": ids_a, "ids_b": ids_b}


def main():
    results = []
    scenarios = [
        scenario_id_continuity,
        scenario_low_conf_recovery,
        scenario_occlusion_gap,
        scenario_multi_object,
    ]
    for fn in scenarios:
        results.append(fn(LocalTracker, "IoU LocalTracker"))
        if bytetrack_available():
            results.append(fn(ByteTrackLocalTracker, "ByteTrack"))

    print("=== ByteTrack PoC Results ===")
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"[{status}] {r['name']} :: {r['scenario']} :: {r}")

    iou_pass = sum(1 for r in results if r["name"] == "IoU LocalTracker" and r["pass"])
    bt_pass = sum(1 for r in results if r["name"] == "ByteTrack" and r["pass"])
    iou_total = sum(1 for r in results if r["name"] == "IoU LocalTracker")
    bt_total = sum(1 for r in results if r["name"] == "ByteTrack")
    print(f"\nIoU: {iou_pass}/{iou_total}  ByteTrack: {bt_pass}/{bt_total}")
    print(f"bytetrack_available={bytetrack_available()}")
    print(f"factory_bytetrack={type(create_local_tracker('bytetrack')).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
