"""MTMC 局部跟踪 / 关联器 / 车辆融合 单测。"""
from __future__ import annotations

import numpy as np

from services.mtmc_associator import MtmcAssociator
from services.mtmc_local_track import LocalTracker, ByteTrackLocalTracker, bytetrack_available, create_local_tracker
from services.vehicle_reid_feat import fuse_plate_visual, visual_key_from_embedding, _color_hist_embedding
from services.strong_reid import cosine, _pad_or_trim, _l2


def test_local_tracker_keeps_id():
    tr = LocalTracker(iou_thresh=0.3, max_age=5)
    a = tr.update([{"bbox": [10, 10, 50, 80], "confidence": 0.9, "className": "person"}])
    tid = a[0].track_id
    b = tr.update([{"bbox": [12, 12, 52, 82], "confidence": 0.9, "className": "person"}])
    assert b[0].track_id == tid
    assert len(b[0].trail) >= 2


def test_local_tracker_new_id_after_max_age():
    tr = LocalTracker(iou_thresh=0.3, max_age=2)
    a = tr.update([{"bbox": [10, 10, 50, 80], "confidence": 0.9, "className": "person"}])
    tid = a[0].track_id
    tr.update([])
    tr.update([])
    tr.update([])
    b = tr.update([{"bbox": [10, 10, 50, 80], "confidence": 0.9, "className": "person"}])
    assert b[0].track_id != tid


def test_associator_same_person_across_cameras():
    assoc = MtmcAssociator(appear_thresh=0.4, time_window_sec=60)
    emb = _l2(np.random.randn(64).astype(np.float32))
    g1 = assoc.associate(object_type="person", camera_id=1, embedding=emb, now=100.0)
    g2 = assoc.associate(object_type="person", camera_id=2, embedding=emb + 0.01, now=105.0)
    assert g1.global_id == g2.global_id


def test_associator_topology_rejects_too_fast():
    assoc = MtmcAssociator(appear_thresh=0.3, time_window_sec=120)
    assoc.set_topology([{
        "fromCameraId": 1, "toCameraId": 2,
        "minTransitSec": 10, "maxTransitSec": 60,
    }])
    emb = _l2(np.ones(32, dtype=np.float32))
    g1 = assoc.associate(object_type="person", camera_id=1, embedding=emb, now=0.0)
    # 2 秒过短，应新建 ID
    g2 = assoc.associate(object_type="person", camera_id=2, embedding=emb, now=2.0)
    assert g1.global_id != g2.global_id
    # 合法时间窗内应关联
    g3 = assoc.associate(object_type="person", camera_id=2, embedding=emb, now=20.0)
    assert g3.global_id == g1.global_id


def test_associator_maps_known_reid_person():
    assoc = MtmcAssociator(appear_thresh=0.9, time_window_sec=60)
    emb_a = _l2(np.random.randn(48).astype(np.float32))
    emb_b = _l2(np.random.randn(48).astype(np.float32))
    g1 = assoc.associate(
        object_type="person", camera_id=1, embedding=emb_a,
        reid_person_id=7, display_name="张三", now=1.0,
    )
    g2 = assoc.associate(
        object_type="person", camera_id=2, embedding=emb_b,
        reid_person_id=7, display_name="张三", now=5.0,
    )
    assert g1.global_id == g2.global_id
    assert g2.display_name == "张三"


def test_vehicle_fuse_plate_identity():
    emb = _l2(np.random.randn(64).astype(np.float32))
    r = fuse_plate_visual(plate="粤B12345", plate_score=0.9, emb_a=emb, emb_b=emb)
    assert r["plateOk"]
    assert r["identityKey"].startswith("粤B12345|")
    assert r["fuseScore"] > 0.5


def test_vehicle_fuse_noplate_visual():
    emb = _color_hist_embedding(np.zeros((80, 120, 3), dtype=np.uint8) + 40)
    r = fuse_plate_visual(plate=None, plate_score=0, emb_a=emb, emb_b=emb)
    assert r["identityKey"].startswith("NOPLATE|")
    assert r["visualKey"]


def test_visual_key_stable():
    emb = _l2(np.arange(32, dtype=np.float32))
    assert visual_key_from_embedding(emb) == visual_key_from_embedding(emb)


def test_pad_or_trim_and_cosine():
    a = _l2(np.ones(10, dtype=np.float32))
    b = _pad_or_trim(a, 16)
    assert b.size == 16
    assert cosine(a, a) > 0.99


def test_create_local_tracker_factory():
    iou = create_local_tracker("iou")
    assert isinstance(iou, LocalTracker)


def test_bytetrack_local_tracker_keeps_id():
    if not bytetrack_available():
        return
    tr = ByteTrackLocalTracker(iou_thresh=0.3, max_age=5)
    d = {"bbox": [10, 10, 50, 80], "confidence": 0.9, "className": "person"}
    a = tr.update([d])
    if not a:
        a = tr.update([d])
    tid = a[0].track_id
    b = tr.update([{"bbox": [12, 12, 52, 82], "confidence": 0.9, "className": "person"}])
    assert b and b[0].track_id == tid
