"""MTMC 局部跟踪 / 关联器 / 车辆融合 单测。"""
from __future__ import annotations

import numpy as np

from services.mtmc_associator import MtmcAssociator, AssocMode
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


def test_bytetrack_emits_tentative_detections():
    """低置信/未激活轨迹仍应输出（MTMC 2FPS 采样下 UI 需可见）。"""
    if not bytetrack_available():
        return
    tr = ByteTrackLocalTracker(iou_thresh=0.3, max_age=5, track_activation_threshold=0.25)
    dets = [
        {"bbox": [100, 100, 180, 220], "confidence": 0.36, "className": "car"},
        {"bbox": [300, 120, 380, 240], "confidence": 0.49, "className": "car"},
    ]
    out = tr.update(dets)
    assert len(out) >= 1
    assert any(getattr(t, "attrs", {}).get("tentative") for t in out) or len(out) == len(dets)


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


def test_vehicle_cross_cam_noplate_visual_merge():
    """无牌时 NOPLATE|* 视觉键跨视角不同，但 embedding 相似应跨镜合并。"""
    assoc = MtmcAssociator(appear_thresh=0.48, vehicle_appear_thresh=0.48, confirm_thresh=0.48)
    emb = _l2(np.random.randn(64).astype(np.float32))
    noise = _l2(emb + np.random.randn(64).astype(np.float32) * 0.05)
    fuse_a = fuse_plate_visual(plate=None, plate_score=0, emb_a=emb, emb_b=emb)
    fuse_b = fuse_plate_visual(plate=None, plate_score=0, emb_a=noise, emb_b=noise)
    assert fuse_a["identityKey"] != fuse_b["identityKey"]
    g1 = assoc.associate(
        object_type="vehicle", camera_id=71, embedding=emb,
        identity_key=fuse_a["identityKey"], local_track_id=1, exclude_gids=set(), now=100.0,
    )
    g2 = assoc.associate(
        object_type="vehicle", camera_id=81, embedding=noise,
        identity_key=fuse_b["identityKey"], local_track_id=3, exclude_gids=set(), now=100.01,
    )
    assert g1.global_id == g2.global_id
    assert assoc.last_mode == AssocMode.LONG_TERM


def test_garbage_plate_no_hard_conflict_merge():
    """OCR 噪声车牌不得阻断高相似视觉跨镜合并。"""
    assoc = MtmcAssociator(appear_thresh=0.48, vehicle_appear_thresh=0.48, confirm_thresh=0.48)
    emb = _l2(np.random.randn(64).astype(np.float32))
    noise = _l2(emb + np.random.randn(64).astype(np.float32) * 0.04)
    fuse_a = fuse_plate_visual(plate="UNEC", plate_score=0.88, emb_a=emb, emb_b=emb)
    fuse_b = fuse_plate_visual(plate="LMM", plate_score=0.88, emb_a=noise, emb_b=noise)
    assert not fuse_a["plateOk"]
    assert not fuse_b["plateOk"]
    g1 = assoc.associate(
        object_type="vehicle", camera_id=71, embedding=emb,
        identity_key=fuse_a["identityKey"], plate=fuse_a["plate"],
        local_track_id=1, exclude_gids=set(), now=100.0,
    )
    g2 = assoc.associate(
        object_type="vehicle", camera_id=81, embedding=noise,
        identity_key=fuse_b["identityKey"], plate=fuse_b["plate"],
        local_track_id=3, exclude_gids=set(), now=101.0,
    )
    assert g1.global_id == g2.global_id


def test_vehicle_cross_cam_takeover_same_cam_sibling():
    """同镜误占 Global 时，新 local 应能通过跨镜原型接管正确 Global。"""
    assoc = MtmcAssociator(
        appear_thresh=0.48, vehicle_appear_thresh=0.48, confirm_thresh=0.48,
        vehicle_sticky_warmup_sec=0.0,
    )
    emb_cam81 = _l2(np.random.randn(64).astype(np.float32))
    emb_wrong71 = _l2(emb_cam81 + np.random.randn(64).astype(np.float32) * 0.05)
    emb_right71 = _l2(emb_cam81 + np.random.randn(64).astype(np.float32) * 0.02)

    g81 = assoc.associate(
        object_type="vehicle", camera_id=81, embedding=emb_cam81,
        local_track_id=4, exclude_gids=set(), now=200.0,
    )
    assoc.associate(
        object_type="vehicle", camera_id=71, embedding=emb_wrong71,
        local_track_id=3, exclude_gids=set(), now=200.5,
    )
    assert assoc._local_bind.get(("vehicle", 71, 3)) == g81.global_id

    g_new = assoc.associate(
        object_type="vehicle", camera_id=71, embedding=emb_right71,
        local_track_id=5, exclude_gids=set(), now=201.0,
    )
    assert g_new.global_id == g81.global_id
    assert assoc._local_bind.get(("vehicle", 71, 5)) == g81.global_id
    assert ("vehicle", 71, 3) not in assoc._local_bind


def test_overlay_unique_gids_after_same_cam_takeover():
    """takeover 后受害者 builder 仍缓存旧 GID 时，同帧绘制不得与接管者共用。"""
    from types import SimpleNamespace

    from services.mtmc_engine import _resolve_overlay_global
    from services.mtmc_tracklet import TrackletBuilder

    assoc = MtmcAssociator(
        appear_thresh=0.48, vehicle_appear_thresh=0.48, confirm_thresh=0.48,
        vehicle_sticky_warmup_sec=0.0,
    )
    emb_cam81 = _l2(np.random.randn(64).astype(np.float32))
    emb_wrong71 = _l2(emb_cam81 + np.random.randn(64).astype(np.float32) * 0.05)
    emb_right71 = _l2(emb_cam81 + np.random.randn(64).astype(np.float32) * 0.02)

    g81 = assoc.associate(
        object_type="vehicle", camera_id=81, embedding=emb_cam81,
        local_track_id=4, exclude_gids=set(), now=200.0,
    )
    assoc.associate(
        object_type="vehicle", camera_id=71, embedding=emb_wrong71,
        local_track_id=3, exclude_gids=set(), now=200.5,
    )
    assoc.associate(
        object_type="vehicle", camera_id=71, embedding=emb_right71,
        local_track_id=5, exclude_gids=set(), now=201.0,
    )
    assert ("vehicle", 71, 3) not in assoc._local_bind

    session = SimpleNamespace(
        associator=assoc,
        cfg=SimpleNamespace(persist_events=False),
        session_id="s",
        app=None,
    )
    victim = TrackletBuilder.create(
        session_id="s", camera_id=71, object_type="vehicle", local_track_id=3, now=201.0,
    )
    victim.assigned_global_id = g81.global_id  # 过期缓存（真实 bug 路径）
    victim.add_observation(
        bbox=[10, 10, 120, 80], conf=0.9, frame_h=720, frame_w=1280,
        embedding=emb_wrong71, now=201.0,
    )
    winner = TrackletBuilder.create(
        session_id="s", camera_id=71, object_type="vehicle", local_track_id=5, now=201.0,
    )
    winner.assigned_global_id = g81.global_id
    winner.add_observation(
        bbox=[200, 10, 320, 90], conf=0.9, frame_h=720, frame_w=1280,
        embedding=emb_right71, now=201.0,
    )

    claimed: set[str] = set()
    sticky_w = assoc.peek_sticky(
        object_type="vehicle", camera_id=71, local_track_id=5, now=201.0,
    )
    g_w = _resolve_overlay_global(
        session, winner, sticky_gid=sticky_w, claimed=claimed, now=201.0,
        associate_kwargs={"embedding": emb_right71},
    )
    assert g_w is not None
    claimed.add(g_w.global_id)

    sticky_v = assoc.peek_sticky(
        object_type="vehicle", camera_id=71, local_track_id=3, now=201.0,
    )
    assert sticky_v is None
    g_v = _resolve_overlay_global(
        session, victim, sticky_gid=sticky_v, claimed=claimed, now=201.0,
        associate_kwargs={"embedding": emb_wrong71},
    )
    assert g_v is not None
    assert g_v.global_id != g_w.global_id
    assert g_w.global_id == g81.global_id


def test_supplement_orphan_vehicle_dets():
    from services.mtmc_engine import supplement_orphan_vehicle_dets
    from services.mtmc_local_track import Tracklet

    car = Tracklet(track_id=1, bbox=[100, 100, 150, 140], class_name="car", conf=0.7)
    raw = [
        {"bbox": [102, 102, 148, 138], "confidence": 0.68, "className": "car"},
        {"bbox": [10, 10, 400, 300], "confidence": 0.65, "className": "truck"},
    ]
    out = supplement_orphan_vehicle_dets([car], raw, frame_w=640, frame_h=360)
    assert len(out) == 2
    assert any(getattr(t, "attrs", {}).get("orphanDet") for t in out)
    assert any(getattr(t, "class_name", None) == "truck" for t in out)
    out2 = supplement_orphan_vehicle_dets([car], [{"bbox": [10, 10, 400, 300], "confidence": 0.65, "className": "car"}], frame_w=640, frame_h=360)
    assert len(out2) == 1


def test_infer_vehicle_class_large_bbox():
    from services.vehicle_reid_feat import infer_vehicle_class
    bbox = [10, 10, 450, 350]
    assert infer_vehicle_class("car", bbox, frame_h=360, frame_w=640) == "truck"


def test_vehicle_class_mismatch_blocks_cross_cam_merge():
    """货车与轿车类别互斥时，即使视觉相似也不应跨镜合并。"""
    assoc = MtmcAssociator(appear_thresh=0.48, vehicle_appear_thresh=0.48, confirm_thresh=0.48)
    emb_truck = _l2(np.random.randn(64).astype(np.float32))
    emb_car_like = _l2(emb_truck + np.random.randn(64).astype(np.float32) * 0.03)
    g_truck = assoc.associate(
        object_type="vehicle", camera_id=71, embedding=emb_truck,
        vehicle_class="truck", local_track_id=1, exclude_gids=set(), now=100.0,
    )
    g_car = assoc.associate(
        object_type="vehicle", camera_id=81, embedding=emb_car_like,
        vehicle_class="car", local_track_id=2, exclude_gids=set(), now=101.0,
    )
    assert g_truck.global_id != g_car.global_id


def test_cross_cam_tie_band_prefers_established_global():
    """分数接近时优先已有对侧原型的 Global（白色 SUV 多车干扰）。"""
    assoc = MtmcAssociator(
        appear_thresh=0.48, vehicle_appear_thresh=0.48, confirm_thresh=0.48,
        cross_cam_tie_band=0.03,
    )
    emb71 = _l2(np.random.randn(64).astype(np.float32))
    emb81_a = _l2(emb71 + np.random.randn(64).astype(np.float32) * 0.04)
    emb81_b = _l2(emb71 + np.random.randn(64).astype(np.float32) * 0.035)

    g71 = assoc.associate(
        object_type="vehicle", camera_id=71, embedding=emb71,
        vehicle_class="car", local_track_id=1, exclude_gids=set(), now=100.0,
    )
    g_other = assoc.associate(
        object_type="vehicle", camera_id=71, embedding=_l2(np.random.randn(64).astype(np.float32)),
        vehicle_class="car", local_track_id=2, exclude_gids=set(), now=100.5,
    )
    assert g_other.global_id != g71.global_id

    g81 = assoc.associate(
        object_type="vehicle", camera_id=81, embedding=emb81_a,
        vehicle_class="car", local_track_id=5, exclude_gids=set(), now=101.0,
    )
    assert g81.global_id == g71.global_id


def test_person_cross_cam_uses_peer_prototype():
    """行人跨镜应合并到对侧已有 Global（cross_proto）。"""
    assoc = MtmcAssociator(appear_thresh=0.48, confirm_thresh=0.48, cross_cam_tie_band=0.02)
    emb = _l2(np.random.randn(64).astype(np.float32))
    noise = _l2(emb + np.random.randn(64).astype(np.float32) * 0.05)
    g1 = assoc.associate(
        object_type="person", camera_id=71, embedding=emb,
        local_track_id=1, exclude_gids=set(), now=200.0,
    )
    g2 = assoc.associate(
        object_type="person", camera_id=81, embedding=noise,
        local_track_id=2, exclude_gids=set(), now=201.0,
    )
    assert g1.global_id == g2.global_id


def test_motor_vs_car_no_hard_conflict():
    """摩托↔轿车不硬冲突（YOLO 常误标），高相似应跨镜合并。"""
    from services.vehicle_reid_feat import vehicle_class_conflict
    assert not vehicle_class_conflict("motorcycle", "car")
    assert vehicle_class_conflict("truck", "car")
    assoc = MtmcAssociator(appear_thresh=0.48, vehicle_appear_thresh=0.48, confirm_thresh=0.48)
    emb = _l2(np.random.randn(64).astype(np.float32))
    noise = _l2(emb + np.random.randn(64).astype(np.float32) * 0.04)
    g1 = assoc.associate(
        object_type="vehicle", camera_id=71, embedding=emb,
        vehicle_class="motorcycle", local_track_id=1, exclude_gids=set(), now=50.0,
    )
    g2 = assoc.associate(
        object_type="vehicle", camera_id=81, embedding=noise,
        vehicle_class="car", local_track_id=2, exclude_gids=set(), now=50.0,
    )
    assert g1.global_id == g2.global_id


def test_simultaneous_cross_cam_dt_zero_merges():
    """重叠视野同时刻（dt=0）应允许跨镜合并。"""
    assoc = MtmcAssociator(
        appear_thresh=0.48, vehicle_appear_thresh=0.48, confirm_thresh=0.48,
        topology={(71, 81): (0.0, 30.0), (81, 71): (0.0, 30.0)},
    )
    emb = _l2(np.random.randn(64).astype(np.float32))
    noise = _l2(emb + np.random.randn(64).astype(np.float32) * 0.03)
    g1 = assoc.associate(
        object_type="vehicle", camera_id=71, embedding=emb,
        vehicle_class="car", local_track_id=1, exclude_gids=set(), now=200.0,
    )
    g2 = assoc.associate(
        object_type="vehicle", camera_id=81, embedding=noise,
        vehicle_class="car", local_track_id=5, exclude_gids=set(), now=200.0,
    )
    assert g1.global_id == g2.global_id


def test_person_color_sig_helps_low_visual():
    """弱外观 + 强颜色签名应跨镜合并行人。"""
    from services.strong_reid import color_signature
    assoc = MtmcAssociator(
        appear_thresh=0.48, confirm_thresh=0.48,
        topology={(71, 81): (0.0, 30.0), (81, 71): (0.0, 30.0)},
    )
    emb_a = _l2(np.random.randn(64).astype(np.float32))
    # 视觉相似度约 0.30（低于旧阈值）
    emb_b = _l2(emb_a + np.random.randn(64).astype(np.float32) * 0.55)
    # 合成红色上衣 ROI
    red = np.zeros((120, 60, 3), dtype=np.uint8)
    red[:, :] = (40, 40, 220)
    cs = color_signature(red)
    g1 = assoc.associate(
        object_type="person", camera_id=71, embedding=emb_a,
        color_sig=cs, local_track_id=1, exclude_gids=set(), now=10.0,
    )
    g2 = assoc.associate(
        object_type="person", camera_id=81, embedding=emb_b,
        color_sig=cs, local_track_id=2, exclude_gids=set(), now=10.5,
    )
    assert g1.global_id == g2.global_id


def test_active_gallery_faiss_search():
    from services.mtmc_active_gallery import MtmcActiveGallery

    gal = MtmcActiveGallery()
    emb = _l2(np.random.randn(64).astype(np.float32))
    gal.upsert("person", "P000001", emb)
    if not gal.faiss_available():
        return
    hits = gal.search("person", emb, topk=3)
    assert hits and hits[0][0] == "P000001" and hits[0][1] > 0.99


def test_public_live_det_omits_full_trail():
    from services.mtmc_engine import _public_live_det

    raw = {
        "objectType": "person",
        "globalId": "P000001-abc",
        "localTrackId": 3,
        "trackletId": "t1",
        "label": "P000001-abc|匿名",
        "bbox": [1, 2, 3, 4],
        "score": 0.55,
        "displayName": "匿名",
        "trail": [[10, 10], [12, 12], [14, 14]],
        "attrs": {"assocMode": "long_term", "cameraId": 71},
    }
    out = _public_live_det(raw)
    assert "trail" not in out
    assert out["trailTip"] == [14, 14]
    assert out["assocMode"] == "long_term"
    assert out["globalId"] == "P000001-abc"
    assert out["localTrackId"] == 3


def test_read_image_bgr_unicode_path(tmp_path):
    import cv2
    import numpy as np
    from services.mtmc_engine import _read_image_bgr

    img = np.zeros((48, 64, 3), dtype=np.uint8)
    img[:, :] = (0, 128, 255)
    p = tmp_path / "测试图片.png"
    cv2.imencode(".png", img)[1].tofile(str(p))
    out = _read_image_bgr(str(p))
    assert out is not None
    assert out.shape[:2] == (48, 64)


def test_static_image_worker_detects_vehicle(tmp_path):
    import threading
    import time
    import cv2
    import numpy as np
    from unittest.mock import patch
    from services.mtmc_engine import MtmcConfig, MtmcSession, CamState, _cam_worker_static_image
    from services.mtmc_associator import MtmcAssociator

    img = np.full((120, 200, 3), 180, dtype=np.uint8)
    cv2.rectangle(img, (30, 40), (170, 100), (20, 20, 200), -1)
    p = tmp_path / "car.png"
    cv2.imencode(".png", img)[1].tofile(str(p))

    cfg = MtmcConfig(
        camera_ids=[910001],
        enable_person=False,
        enable_vehicle=True,
        det_vehicle_path="fake.pt",
        sample_fps=8,
    )
    session = MtmcSession("img-test", cfg, MtmcAssociator(appear_thresh=0.48, time_window_sec=60))
    session.running = True
    cam_state = CamState(camera_id=910001)
    session.cams[910001] = cam_state
    fake_det = [{"bbox": [30.0, 40.0, 170.0, 100.0], "confidence": 0.9, "classId": 2, "className": "car"}]

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([], fake_det)):
        th = threading.Thread(
            target=_cam_worker_static_image,
            args=(session, cam_state, str(p)),
            daemon=True,
        )
        th.start()
        deadline = time.time() + 3.0
        while time.time() < deadline and session.stats["frames"] < 1:
            time.sleep(0.05)
        session._stop.set()
        th.join(timeout=2.0)

    assert session.stats["frames"] >= 1
    assert len(cam_state.last_dets) >= 1
    assert cam_state.overlay_jpeg


def test_local_file_worker_detects_vehicle(tmp_path):
    import threading
    import time
    import cv2
    import numpy as np
    from unittest.mock import patch
    from services.mtmc_engine import MtmcConfig, MtmcSession, CamState, _cam_worker_local_file
    from services.mtmc_associator import MtmcAssociator

    p = tmp_path / "clip.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    wr = cv2.VideoWriter(str(p), fourcc, 8, (200, 120))
    assert wr.isOpened()
    for _ in range(8):
        img = np.full((120, 200, 3), 180, dtype=np.uint8)
        cv2.rectangle(img, (30, 40), (170, 100), (20, 20, 200), -1)
        wr.write(img)
    wr.release()

    cfg = MtmcConfig(
        camera_ids=[910002],
        enable_person=False,
        enable_vehicle=True,
        det_vehicle_path="fake.pt",
        sample_fps=8,
    )
    session = MtmcSession("file-test", cfg, MtmcAssociator(appear_thresh=0.48, time_window_sec=60))
    session.running = True
    cam_state = CamState(camera_id=910002)
    session.cams[910002] = cam_state
    fake_det = [{"bbox": [30.0, 40.0, 170.0, 100.0], "confidence": 0.9, "classId": 2, "className": "car"}]

    with patch("services.mtmc_engine._detect_person_vehicle", return_value=([], fake_det)):
        th = threading.Thread(
            target=_cam_worker_local_file,
            args=(session, cam_state, str(p)),
            daemon=True,
        )
        th.start()
        deadline = time.time() + 3.0
        while time.time() < deadline and session.stats["frames"] < 1:
            time.sleep(0.05)
        session._stop.set()
        th.join(timeout=2.0)

    assert session.stats["frames"] >= 1
    assert len(cam_state.last_dets) >= 1
    assert cam_state.overlay_jpeg


def test_ffmpeg_scale_caps_long_side():
    from services.camera_stream import build_ffmpeg_cmd

    cmd = build_ffmpeg_cmd("ffmpeg", "file", "a.mp4", 960, 10)
    vf = cmd[cmd.index("-vf") + 1]
    assert "force_original_aspect_ratio=decrease" in vf
    assert "scale=960:-2" not in vf


def test_resize_max_side_caps_portrait():
    import numpy as np
    from services.mtmc_engine import _resize_max_side

    frame = np.zeros((1280, 584, 3), dtype=np.uint8)
    out = _resize_max_side(frame, 720)
    assert max(out.shape[:2]) == 720
    assert out.shape[0] > out.shape[1]


def test_engine_jpegs_yields_only_new_seq():
    from unittest.mock import patch
    from services.camera_stream import mjpeg_stream_mtmc_engine_jpegs
    from services.mtmc_engine import CamState, MtmcConfig, MtmcSession
    from services.mtmc_associator import MtmcAssociator

    cfg = MtmcConfig(camera_ids=[1], detect_only=True)
    session = MtmcSession("eng-jpeg", cfg, MtmcAssociator(appear_thresh=0.48, time_window_sec=60))
    session.running = True
    cam = CamState(camera_id=1, fast_preview=True)
    cam.overlay_jpeg = b"\xff\xd8fakejpg"
    cam.frame_seq = 3
    session.cams[1] = cam

    gen = mjpeg_stream_mtmc_engine_jpegs("eng-jpeg", 1, "overlay")
    with patch("services.mtmc_engine.get_session", return_value=session):
        with patch("services.camera_stream._request_disconnected", return_value=False):
            with patch("services.camera_stream.time.sleep", return_value=None):
                first = next(gen)
                session.running = False
                rest = list(gen)
    assert b"--frame" in first
    assert rest == []


def test_tracklet_embedding_rejects_single_foreign_crop():
    from services.mtmc_tracklet import TrackletBuilder

    rng = np.random.default_rng(20260830)
    identity = _l2(rng.normal(size=64).astype(np.float32))
    foreign = _l2(rng.normal(size=64).astype(np.float32))
    builder = TrackletBuilder.create(
        session_id="s", camera_id=1, object_type="vehicle", local_track_id=7, now=1.0,
    )
    for i in range(4):
        emb = foreign if i == 2 else _l2(identity + rng.normal(0, 0.015, 64))
        builder.add_observation(
            bbox=[10, 10, 210, 130], conf=0.9, frame_h=720, frame_w=1280,
            embedding=emb, now=1.0 + i,
        )
    aggregate = builder.aggregate_embedding()
    assert cosine(aggregate, identity) > 0.97
    assert cosine(aggregate, foreign) < 0.5


def test_camera_overlay_never_exposes_duplicate_global_id():
    from services.mtmc_engine import _enforce_unique_camera_global_ids

    items = [
        {"objectType": "vehicle", "globalId": "V1", "localTrackId": 1,
         "score": 0.42, "label": "V1"},
        {"objectType": "vehicle", "globalId": "V1", "localTrackId": 2,
         "score": 0.91, "label": "V1"},
        {"objectType": "person", "globalId": "P1", "localTrackId": 3,
         "score": 0.8, "label": "P1"},
    ]
    _enforce_unique_camera_global_ids(items)
    vehicle_gids = [x["globalId"] for x in items if x["objectType"] == "vehicle" and x["globalId"]]
    assert vehicle_gids == ["V1"]
    assert items[0]["globalId"] is None
    assert items[0]["attrs"]["duplicateGlobalIdSuppressed"] == "V1"


def test_active_gallery_keeps_distinct_camera_prototypes():
    from services.mtmc_active_gallery import MtmcActiveGallery

    gallery = MtmcActiveGallery()
    cam1 = np.asarray([1.0, 0.0, 0.0], dtype=np.float32)
    cam2 = np.asarray([0.0, 1.0, 0.0], dtype=np.float32)
    gallery.upsert("vehicle", "V1", cam1, camera_id=1)
    gallery.upsert("vehicle", "V1", cam2, camera_id=2)
    assert gallery.max_similarity("vehicle", "V1", cam1, exclude_camera_id=2) > 0.99
    assert gallery.max_similarity("vehicle", "V1", cam1, exclude_camera_id=1) < 0.1


def test_rider_proxy_supplements_missing_person_only_for_two_wheelers():
    from services.mtmc_engine import supplement_rider_person_dets

    vehicles = [
        {"classId": 3, "className": "motorcycle", "confidence": 0.8,
         "bbox": [100, 180, 180, 240]},
        {"classId": 2, "className": "car", "confidence": 0.9,
         "bbox": [250, 160, 420, 280]},
    ]
    out = supplement_rider_person_dets([], vehicles, frame_w=640, frame_h=360)
    assert len(out) == 1
    assert out[0]["className"] == "rider"
    assert out[0]["bbox"][1] < vehicles[0]["bbox"][1]


def test_rider_proxy_does_not_duplicate_real_person():
    from services.mtmc_engine import supplement_rider_person_dets

    person = {"classId": 0, "className": "person", "confidence": 0.7,
              "bbox": [105, 120, 175, 220]}
    motorcycle = {"classId": 3, "className": "motorcycle", "confidence": 0.8,
                  "bbox": [100, 180, 180, 240]}
    out = supplement_rider_person_dets([person], [motorcycle], frame_w=640, frame_h=360)
    assert out == [person]


def test_one_sided_rider_proxy_uses_stronger_color_fusion():
    assoc = MtmcAssociator(
        appear_thresh=0.48, confirm_thresh=0.48, candidate_thresh=0.30,
        topology={(71, 81): (0.0, 30.0), (81, 71): (0.0, 30.0)},
    )
    emb71 = np.asarray([1.0, 0.0, 0.0], dtype=np.float32)
    emb81 = np.asarray([0.0, 1.0, 0.0], dtype=np.float32)
    color71 = np.asarray([1.0, 0.0], dtype=np.float32)
    color81 = np.asarray([0.65, np.sqrt(1.0 - 0.65**2)], dtype=np.float32)
    first = assoc.associate(
        object_type="person", camera_id=71, embedding=emb71, color_sig=color71,
        visual_key="rider", local_track_id=1, now=10.0,
    )
    second = assoc.associate(
        object_type="person", camera_id=81, embedding=emb81, color_sig=color81,
        local_track_id=2, now=11.0,
    )
    assert second.global_id == first.global_id


def test_mtmc_preview_hub_caps_mjpeg_fps():
    from types import SimpleNamespace
    from services.mtmc_engine import _hub_stream_params

    session = SimpleNamespace(cfg=SimpleNamespace(width=960, fps=30))
    camera = SimpleNamespace(resolution=1280, fps=25)
    assert _hub_stream_params(session, camera) == (960, 12)


def test_mtmc_preview_hub_keeps_low_source_fps():
    from types import SimpleNamespace
    from services.mtmc_engine import _hub_stream_params

    session = SimpleNamespace(cfg=SimpleNamespace(width=640, fps=8))
    camera = SimpleNamespace(resolution=1280, fps=25)
    assert _hub_stream_params(session, camera) == (640, 8)


def test_ultralytics_config_uses_project_writable_dir():
    import os
    import inference

    configured = os.path.abspath(os.environ["YOLO_CONFIG_DIR"])
    backend_dir = os.path.dirname(os.path.abspath(inference.__file__))
    expected_root = os.path.join(backend_dir, "uploads")
    assert os.path.commonpath([configured, expected_root]) == expected_root
    assert os.path.isdir(configured)
