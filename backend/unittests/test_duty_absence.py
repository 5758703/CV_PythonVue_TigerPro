"""人员离岗：状态机与 FAISS 单测（不加载真实权重）。"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.duty_absence import DutySession, step_duty_session
from services.duty_faiss import build_index_from_vectors, search


def test_start_empty_becomes_absent():
    s = DutySession(absence_threshold_sec=5.0)
    t0 = 1000.0
    r1 = step_duty_session(s, now=t0, on_duty=False, stream_ok=True)
    assert r1["dutyStatus"] == "away"
    assert r1["alertActive"] is False
    r2 = step_duty_session(s, now=t0 + 5.0, on_duty=False, stream_ok=True)
    assert r2["dutyStatus"] == "absent"
    assert r2["alertActive"] is True
    assert any(e["event"] == "absent" for e in s.events)


def test_start_with_staff_on_duty():
    s = DutySession(absence_threshold_sec=5.0)
    staff = [{"personId": 1, "name": "张三", "score": 0.9}]
    r = step_duty_session(s, now=1000.0, on_duty=True, matched_staff=staff, stream_ok=True)
    assert r["dutyStatus"] == "on_duty"
    assert r["awaySeconds"] == 0
    assert r["alertActive"] is False
    assert not s.events


def test_brief_occlusion_no_absent():
    s = DutySession(absence_threshold_sec=10.0)
    t0 = 2000.0
    step_duty_session(s, now=t0, on_duty=True, matched_staff=[{"personId": 1, "name": "A"}], stream_ok=True)
    # 遮挡 3 秒
    r_away = step_duty_session(s, now=t0 + 3.0, on_duty=False, stream_ok=True)
    assert r_away["dutyStatus"] == "away"
    assert r_away["alertActive"] is False
    # 恢复
    r_back = step_duty_session(s, now=t0 + 4.0, on_duty=True, matched_staff=[{"personId": 1, "name": "A"}], stream_ok=True)
    assert r_back["dutyStatus"] == "on_duty"
    assert not any(e["event"] == "absent" for e in s.events)


def test_multi_staff_alternating_stays_on_duty():
    s = DutySession(absence_threshold_sec=5.0)
    t0 = 3000.0
    step_duty_session(s, now=t0, on_duty=True, matched_staff=[{"personId": 1, "name": "A"}], stream_ok=True)
    # A 离开瞬间无匹配 1s，未达阈值
    step_duty_session(s, now=t0 + 1.0, on_duty=False, stream_ok=True)
    # B 接岗
    r = step_duty_session(s, now=t0 + 1.5, on_duty=True, matched_staff=[{"personId": 2, "name": "B"}], stream_ok=True)
    assert r["dutyStatus"] == "on_duty"
    assert not any(e["event"] == "absent" for e in s.events)


def test_stranger_only_becomes_absent():
    """仅陌生人：on_duty=False，应计时离岗。"""
    s = DutySession(absence_threshold_sec=2.0)
    t0 = 4000.0
    step_duty_session(s, now=t0, on_duty=False, stream_ok=True)
    r = step_duty_session(s, now=t0 + 2.0, on_duty=False, stream_ok=True)
    assert r["dutyStatus"] == "absent"


def test_stream_down_pauses_absence_timer():
    s = DutySession(absence_threshold_sec=5.0)
    t0 = 5000.0
    step_duty_session(s, now=t0, on_duty=False, stream_ok=True)
    # 已 away 2s
    step_duty_session(s, now=t0 + 2.0, on_duty=False, stream_ok=True)
    # 断流检测到（接近最后一帧），之后墙钟过去 20s 再恢复
    r_down = step_duty_session(s, now=t0 + 2.1, on_duty=False, stream_ok=False)
    assert r_down["dutyStatus"] == "stream_down"
    assert r_down["alertActive"] is False
    assert r_down["awaySeconds"] == pytest.approx(2.1, abs=0.05)
    # 恢复后仍无人：断流 20s 不计入，再过约 3s 才 absent
    r1 = step_duty_session(s, now=t0 + 22.1, on_duty=False, stream_ok=True)
    assert r1["dutyStatus"] == "away"
    assert r1["awaySeconds"] == pytest.approx(2.1, abs=0.1)
    r2 = step_duty_session(s, now=t0 + 25.1, on_duty=False, stream_ok=True)
    assert r2["dutyStatus"] == "absent"


def test_return_event_after_absent():
    s = DutySession(absence_threshold_sec=1.0)
    t0 = 6000.0
    step_duty_session(s, now=t0, on_duty=False, stream_ok=True)
    step_duty_session(s, now=t0 + 1.0, on_duty=False, stream_ok=True)
    assert s.alert_active
    r = step_duty_session(
        s, now=t0 + 2.0, on_duty=True,
        matched_staff=[{"personId": 9, "name": "李四"}], stream_ok=True,
    )
    assert r["dutyStatus"] == "on_duty"
    assert any(e["event"] == "return" for e in s.events)


def test_faiss_search_hit_and_staff_filter():
    faiss = pytest.importorskip("faiss")
    _ = faiss
    rng = np.random.default_rng(0)
    v1 = rng.normal(size=512).astype(np.float32)
    v2 = rng.normal(size=512).astype(np.float32)
    pack = build_index_from_vectors([1, 2], ["Alice", "Bob"], [v1, v2])
    hit = search(v1, "demo", threshold=0.5, staff_ids=[1, 2], index_pack=pack)
    assert hit["matched"] is True
    assert hit["personId"] == 1
    # 不在名单
    miss = search(v1, "demo", threshold=0.5, staff_ids=[2], index_pack=pack)
    assert miss["matched"] is False


def test_parse_zones_and_aggregate():
    from services.duty_absence import aggregate_zone_duties, parse_zones_payload

    zones = parse_zones_payload(
        [
            {"id": "z1", "name": "工位1", "region": [[0, 0], [1, 0], [1, 1], [0, 1]], "staffIds": [1]},
            {"id": "z2", "name": "工位2", "region": [[0, 0], [0.4, 0], [0.4, 0.4], [0, 0.4]], "staffIds": [2], "absenceThresholdSec": 10},
        ],
        staff_ids=[9],
        absence_threshold_sec=30,
    )
    assert len(zones) == 2
    assert zones[0]["staffIds"] == [1]
    assert zones[1]["absenceThresholdSec"] == 10.0

    agg = aggregate_zone_duties([
        {"dutyStatus": "on_duty", "awaySeconds": 0, "onDuty": True, "alertActive": False, "matchedStaff": [{"personId": 1}]},
        {"dutyStatus": "absent", "awaySeconds": 12, "onDuty": False, "alertActive": True, "matchedStaff": [], "alarms": [{"event": "ABSENT"}]},
    ])
    assert agg["dutyStatus"] == "absent"
    assert agg["awaySeconds"] == 12
    assert agg["alertActive"] is True
    assert agg["onDuty"] is True  # 另一工位仍在岗


def test_multi_zone_independent_absence():
    """两工位独立计时：A 在岗不影响 B 离岗告警。"""
    from services.duty_absence import DutySession, DutyZoneState, step_duty_session

    s = DutySession(absence_threshold_sec=5.0)
    t0 = 7000.0
    za = s.ensure_zone("zA", "工位A", 5.0)
    zb = s.ensure_zone("zB", "工位B", 5.0)

    step_duty_session(
        za, now=t0, on_duty=True, matched_staff=[{"personId": 1, "name": "A"}],
        stream_ok=True, events_out=s.events, zone_id="zA", zone_name="工位A",
    )
    step_duty_session(
        zb, now=t0, on_duty=False, stream_ok=True,
        events_out=s.events, zone_id="zB", zone_name="工位B",
    )
    # B 达阈值离岗；A 仍在岗
    r_b = step_duty_session(
        zb, now=t0 + 5.0, on_duty=False, stream_ok=True,
        events_out=s.events, zone_id="zB", zone_name="工位B",
    )
    r_a = step_duty_session(
        za, now=t0 + 5.0, on_duty=True, matched_staff=[{"personId": 1, "name": "A"}],
        stream_ok=True, events_out=s.events, zone_id="zA", zone_name="工位A",
    )
    assert r_a["dutyStatus"] == "on_duty"
    assert r_b["dutyStatus"] == "absent"
    assert any(e.get("zoneId") == "zB" and e.get("event") == "absent" for e in s.events)
    assert not any(e.get("zoneId") == "zA" and e.get("event") == "absent" for e in s.events)
    assert isinstance(za, DutyZoneState)


def test_draw_duty_hud_accepts_ndarray_region_px():
    """region_px 为 ndarray 时不得触发 ambiguous truth value。"""
    from services.duty_absence import draw_duty_hud
    from services.track_zone import region_to_pixels

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    poly = region_to_pixels([[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]], 320, 240)
    assert isinstance(poly, np.ndarray)
    vis = draw_duty_hud(
        frame,
        {"dutyStatus": "on_duty", "awaySeconds": 0, "matchedStaff": [], "zoneCount": 1, "zones": []},
        zones_px=[{
            "zoneId": "z1",
            "zoneName": "工位1",
            "region_px": poly,
            "borderColor": "#1E88E5",
            "fillColor": "rgba(30,136,229,0.2)",
            "dutyStatus": "on_duty",
            "awaySeconds": 0,
        }],
    )
    assert vis.shape == frame.shape
