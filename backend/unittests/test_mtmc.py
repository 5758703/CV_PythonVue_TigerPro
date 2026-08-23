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


def test_associator_records_evidence():
    from services.mtmc_associator import AssocEvidence, AssocMode

    assoc = MtmcAssociator(appear_thresh=0.4, time_window_sec=60)
    emb = _l2(np.random.randn(32).astype(np.float32))
    g = assoc.associate(object_type="person", camera_id=1, embedding=emb, local_track_id=1, now=1.0)
    assert isinstance(assoc.last_evidence, AssocEvidence)
    assert assoc.last_evidence.target_global_id == g.global_id
    assert assoc.last_mode == AssocMode.NEW


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
    if bytetrack_available():
        bt = create_local_tracker("bytetrack")
        assert isinstance(bt, ByteTrackLocalTracker)
    else:
        bt = create_local_tracker("iou")
        assert isinstance(bt, LocalTracker)


def test_make_local_tracker_default_bytetrack():
    """引擎工厂：默认 bytetrack，缺依赖时回退 iou。"""
    from services.mtmc_engine import MtmcConfig, _make_local_tracker

    cfg = MtmcConfig(camera_ids=[1], local_track_backend="bytetrack")
    tr = _make_local_tracker(cfg)
    if bytetrack_available():
        assert isinstance(tr, ByteTrackLocalTracker)
        assert cfg.local_track_backend == "bytetrack"
    else:
        assert isinstance(tr, LocalTracker)
        assert cfg.local_track_backend == "iou"


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


def test_associator_same_frame_unique_gids():
    """同帧两辆相似车不得共用 Global ID。"""
    assoc = MtmcAssociator(
        appear_thresh=0.4,
        time_window_sec=60,
        same_cam_min_gap=0.4,
        same_cam_appear_thresh=0.7,
    )
    # 高度相似的外观（模拟同色车）
    base = _l2(np.random.randn(64).astype(np.float32))
    emb_a = _l2(base + 0.02 * np.random.randn(64).astype(np.float32))
    emb_b = _l2(base + 0.02 * np.random.randn(64).astype(np.float32))
    claimed = set()
    g1 = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=emb_a,
        local_track_id=1, exclude_gids=claimed, now=10.0,
    )
    claimed.add(g1.global_id)
    g2 = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=emb_b,
        local_track_id=2, exclude_gids=claimed, now=10.0,
    )
    claimed.add(g2.global_id)
    assert g1.global_id != g2.global_id


def test_associator_local_track_sticky():
    """同一 local_track_id 跨帧续接同一 Global ID。"""
    assoc = MtmcAssociator(appear_thresh=0.9, time_window_sec=60, local_sticky_sec=20)
    emb1 = _l2(np.random.randn(48).astype(np.float32))
    emb2 = _l2(np.random.randn(48).astype(np.float32))  # 外观变化很大
    g1 = assoc.associate(
        object_type="person", camera_id=1, embedding=emb1,
        local_track_id=7, now=1.0,
    )
    g2 = assoc.associate(
        object_type="person", camera_id=1, embedding=emb2,
        local_track_id=7, now=1.5,
    )
    assert g1.global_id == g2.global_id


def test_associator_unknown_identity_not_merge():
    """无效 identity_key 不得把多车合并。"""
    assoc = MtmcAssociator(appear_thresh=0.99, time_window_sec=60, same_cam_min_gap=0.4)
    claimed = set()
    g1 = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=None,
        identity_key="UNKNOWN|U", local_track_id=1, exclude_gids=claimed, now=1.0,
    )
    claimed.add(g1.global_id)
    g2 = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=None,
        identity_key="UNKNOWN|U", local_track_id=2, exclude_gids=claimed, now=1.0,
    )
    assert g1.global_id != g2.global_id


def test_fuse_no_shared_unknown_key():
    r = fuse_plate_visual(plate=None, plate_score=0, emb_a=None, emb_b=None)
    assert r["identityKey"] is None


def test_mcbyte_sticky_skips_appearance_rematch():
    """短时粘性：外观巨变仍保持同一 Global（不开放外观重匹配）。"""
    from services.mtmc_associator import AssocMode

    assoc = MtmcAssociator(appear_thresh=0.99, mcbyte_decouple=True, local_sticky_sec=30)
    emb1 = _l2(np.random.randn(64).astype(np.float32))
    emb2 = _l2(np.random.randn(64).astype(np.float32))
    g1 = assoc.associate(
        object_type="person", camera_id=1, embedding=emb1, local_track_id=3, now=1.0,
    )
    g2 = assoc.associate(
        object_type="person", camera_id=1, embedding=emb2, local_track_id=3, now=1.2,
    )
    assert g1.global_id == g2.global_id
    assert assoc.last_mode == AssocMode.STICKY


def test_mcbyte_new_track_revives_lost_global():
    """新生 local 在丢失一段时间后，可用外观复活旧 Global。"""
    from services.mtmc_associator import AssocMode

    assoc = MtmcAssociator(
        appear_thresh=0.4,
        lost_revive_sec=1.0,
        same_cam_min_gap=0.4,
        mcbyte_decouple=True,
        local_sticky_sec=20,
    )
    emb = _l2(np.ones(32, dtype=np.float32))
    g1 = assoc.associate(
        object_type="person", camera_id=1, embedding=emb, local_track_id=1, now=0.0,
    )
    # 局部消失 → 标记 lost
    assoc.prune_inactive_locals("person", 1, active_local_ids=[])
    # 新生 local_track_id=9，间隔足够，外观复活
    g2 = assoc.associate(
        object_type="person", camera_id=1, embedding=emb, local_track_id=9, now=2.5,
    )
    assert g2.global_id == g1.global_id
    assert assoc.last_mode == AssocMode.LONG_TERM


def test_mcbyte_active_same_cam_not_stolen_by_new_track():
    """同镜仍活跃的 Global 不可被另一新生 track 用外观抢走。"""
    assoc = MtmcAssociator(
        appear_thresh=0.3,
        lost_revive_sec=2.0,
        same_cam_min_gap=0.5,
        mcbyte_decouple=True,
    )
    emb = _l2(np.random.randn(48).astype(np.float32))
    claimed = set()
    g1 = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=emb,
        local_track_id=1, exclude_gids=claimed, now=10.0,
    )
    claimed.add(g1.global_id)
    g2 = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=emb,
        local_track_id=2, exclude_gids=claimed, now=10.05,
    )
    assert g1.global_id != g2.global_id


def test_peek_sticky_allows_skip_reid():
    assoc = MtmcAssociator(local_sticky_sec=20)
    emb = _l2(np.random.randn(16).astype(np.float32))
    g = assoc.associate(
        object_type="person", camera_id=2, embedding=emb, local_track_id=5, now=1.0,
    )
    assert assoc.peek_sticky(object_type="person", camera_id=2, local_track_id=5, now=1.1) == g.global_id
    assert assoc.peek_sticky(object_type="person", camera_id=2, local_track_id=99, now=1.1) is None


def test_three_tier_candidate_not_merge():
    """三档决策：中间分数新建 Global 并记录候选，不合并。"""
    from services.mtmc_associator import AssocMode

    assoc = MtmcAssociator(
        appear_thresh=0.5,
        confirm_thresh=0.92,
        candidate_thresh=0.45,
        mcbyte_decouple=True,
    )
    emb_a = _l2(np.ones(32, dtype=np.float32))
    emb_b = _l2(np.concatenate([np.ones(24, dtype=np.float32), np.zeros(8, dtype=np.float32)]))
    g1 = assoc.associate(object_type="person", camera_id=1, embedding=emb_a, local_track_id=1, now=1.0)
    assoc.prune_inactive_locals("person", 1, active_local_ids=[])
    g2 = assoc.associate(
        object_type="person", camera_id=2, embedding=emb_b, local_track_id=2, now=5.0,
    )
    assert g2.global_id != g1.global_id
    assert assoc.last_mode == AssocMode.CANDIDATE
    assert assoc.last_evidence.candidate_global_id == g1.global_id
    assert len(assoc.list_candidates()) >= 1


def test_three_tier_confirm_merge():
    """三档决策：高分确认合并。"""
    from services.mtmc_associator import AssocMode

    assoc = MtmcAssociator(
        appear_thresh=0.4,
        confirm_thresh=0.55,
        candidate_thresh=0.35,
    )
    emb = _l2(np.ones(48, dtype=np.float32))
    g1 = assoc.associate(object_type="person", camera_id=1, embedding=emb, now=1.0)
    g2 = assoc.associate(object_type="person", camera_id=2, embedding=emb, now=6.0)
    assert g1.global_id == g2.global_id
    assert assoc.last_mode == AssocMode.LONG_TERM


def test_hard_conflict_plate_reject():
    """硬冲突：不同车牌不得合并，即使外观相似。"""
    assoc = MtmcAssociator(appear_thresh=0.3, confirm_thresh=0.3, candidate_thresh=0.2)
    emb = _l2(np.random.randn(32).astype(np.float32))
    claimed = set()
    g1 = assoc.associate(
        object_type="vehicle", camera_id=1, embedding=emb,
        plate="粤B11111", identity_key="粤B11111|VK1",
        local_track_id=1, exclude_gids=claimed, now=1.0,
    )
    claimed.add(g1.global_id)
    assoc.prune_inactive_locals("vehicle", 1, active_local_ids=[])
    g2 = assoc.associate(
        object_type="vehicle", camera_id=2, embedding=emb,
        plate="粤B22222", identity_key="粤B22222|VK2",
        local_track_id=2, exclude_gids=claimed, now=5.0,
    )
    assert g2.global_id != g1.global_id


def test_active_gallery_faiss_search():
    from services.mtmc_active_gallery import MtmcActiveGallery

    gal = MtmcActiveGallery()
    emb = _l2(np.random.randn(64).astype(np.float32))
    gal.upsert("person", "P000001", emb)
    if not gal.faiss_available():
        return
    hits = gal.search("person", emb, topk=3)
    assert hits and hits[0][0] == "P000001" and hits[0][1] > 0.99
