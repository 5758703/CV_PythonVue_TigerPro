"""人员离岗检测：ByteTrack 检人 + InsightFace/FAISS 识人 + 连续时间状态机。"""
from __future__ import annotations

import csv
import io
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import cv2
import numpy as np

from services.duty_faiss import search as faiss_search

_sessions_lock = threading.Lock()
_sessions: dict[str, "DutySession"] = {}

DEFAULT_ABSENCE_THRESHOLD_SEC = 30.0
DEFAULT_FACE_COOLDOWN_SEC = 0.8
DEFAULT_FACE_STICKY_SEC = 2.5
DEFAULT_FACE_THRESHOLD = 0.4

# API 内部仍用英文状态码；展示层用中文
DUTY_STATUS_ZH = {
    "on_duty": "在岗",
    "away": "暂离",
    "absent": "离岗",
    "stream_down": "信号中断",
}
DUTY_EVENT_ZH = {
    "absent": "离岗告警",
    "return": "回岗",
}


def duty_status_zh(status: str | None) -> str:
    if not status:
        return "-"
    return DUTY_STATUS_ZH.get(str(status), str(status))


def duty_event_zh(event: str | None) -> str:
    if not event:
        return "-"
    return DUTY_EVENT_ZH.get(str(event), str(event))


def format_duty_hud_label(status: str | None, away_seconds: float = 0.0, staff_names: list[str] | None = None) -> str:
    """视频叠加 / HUD 中文文案。"""
    st = str(status or "")
    away = float(away_seconds or 0)
    if st == "on_duty":
        label = "状态：在岗"
    elif st == "away":
        label = f"状态：暂离　已离岗 {away:.1f} 秒"
    elif st == "absent":
        label = f"状态：离岗告警　已离岗 {away:.1f} 秒"
    elif st == "stream_down":
        label = f"状态：信号中断　计时暂停 {away:.1f} 秒"
    else:
        label = f"状态：{duty_status_zh(st)}"
    names = [n for n in (staff_names or []) if n]
    if names:
        label += "　|　" + "、".join(names[:3])
    return label


def events_to_csv(events: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["时间", "事件", "状态", "离岗秒数", "工位ID", "工位名称", "人员ID", "人员姓名", "说明"])
    for e in events or []:
        w.writerow([
            e.get("time"),
            duty_event_zh(e.get("event")),
            duty_status_zh(e.get("dutyStatus")),
            e.get("awaySeconds"),
            e.get("zoneId") or "",
            e.get("zoneName") or "",
            e.get("staffId"),
            e.get("staffName"),
            e.get("detail") or "",
        ])
    return buf.getvalue()


@dataclass
class DutyZoneState:
    """单个工位的离岗计时状态。"""

    zone_id: str = ""
    zone_name: str = ""
    away_since: float | None = None
    last_staff_id: int | None = None
    last_staff_name: str | None = None
    alert_active: bool = False
    absence_threshold_sec: float = DEFAULT_ABSENCE_THRESHOLD_SEC
    _stream_pause_at: float | None = None


@dataclass
class DutySession:
    """单路视频/摄像头离岗会话（可含多工位状态）。"""

    away_since: float | None = None
    last_staff_id: int | None = None
    last_staff_name: str | None = None
    alert_active: bool = False
    last_match_by_track: dict[int, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    absence_threshold_sec: float = DEFAULT_ABSENCE_THRESHOLD_SEC
    face_cooldown_sec: float = DEFAULT_FACE_COOLDOWN_SEC
    face_sticky_sec: float = DEFAULT_FACE_STICKY_SEC
    # 断流起始墙钟；恢复时把 away_since 顺延，断流时段不计入离岗
    _stream_pause_at: float | None = None
    zone_states: dict[str, DutyZoneState] = field(default_factory=dict)

    def ensure_zone(
        self,
        zone_id: str,
        zone_name: str = "",
        absence_threshold_sec: float | None = None,
    ) -> DutyZoneState:
        zid = str(zone_id or "default")
        z = self.zone_states.get(zid)
        thr = float(
            absence_threshold_sec
            if absence_threshold_sec is not None
            else self.absence_threshold_sec
        )
        if z is None:
            z = DutyZoneState(
                zone_id=zid,
                zone_name=zone_name or zid,
                absence_threshold_sec=thr,
            )
            self.zone_states[zid] = z
        else:
            if zone_name:
                z.zone_name = zone_name
            z.absence_threshold_sec = thr
        return z


STATUS_PRIORITY = {"absent": 0, "away": 1, "stream_down": 2, "on_duty": 3}


def aggregate_zone_duties(zone_results: list[dict[str, Any]]) -> dict[str, Any]:
    """多工位汇总：取最差状态；离岗秒取暂离/离岗中的最大值。"""
    if not zone_results:
        return {
            "dutyStatus": "away",
            "awaySeconds": 0.0,
            "onDuty": False,
            "alertActive": False,
            "matchedStaff": [],
            "alarms": [],
        }
    worst = min(
        zone_results,
        key=lambda r: STATUS_PRIORITY.get(str(r.get("dutyStatus")), 9),
    )
    away_vals = [
        float(r.get("awaySeconds") or 0)
        for r in zone_results
        if r.get("dutyStatus") in ("away", "absent", "stream_down")
    ]
    matched: list[dict] = []
    seen: set[int] = set()
    alarms: list[dict] = []
    for r in zone_results:
        for m in r.get("matchedStaff") or []:
            pid = m.get("personId")
            if pid is None or int(pid) in seen:
                continue
            seen.add(int(pid))
            matched.append(m)
        for a in r.get("alarms") or []:
            alarms.append(a)
    return {
        "dutyStatus": worst.get("dutyStatus"),
        "awaySeconds": round(max(away_vals) if away_vals else 0.0, 2),
        "onDuty": any(bool(r.get("onDuty")) for r in zone_results),
        "alertActive": any(bool(r.get("alertActive")) for r in zone_results),
        "matchedStaff": matched,
        "alarms": alarms,
        "lastStaffId": worst.get("lastStaffId"),
        "lastStaffName": worst.get("lastStaffName"),
    }


def parse_zones_payload(
    zones_raw,
    *,
    region=None,
    staff_ids: list[int] | None = None,
    absence_threshold_sec: float = DEFAULT_ABSENCE_THRESHOLD_SEC,
) -> list[dict[str, Any]]:
    """解析多工位配置；兼容单 region。region 为已 parse 的归一化多边形。"""
    from services.track_zone import parse_region

    staff_ids = staff_ids or []
    out: list[dict[str, Any]] = []
    if isinstance(zones_raw, str) and zones_raw.strip():
        try:
            import json
            zones_raw = json.loads(zones_raw)
        except (TypeError, ValueError):
            zones_raw = None
    if isinstance(zones_raw, list) and zones_raw:
        for i, z in enumerate(zones_raw):
            if not isinstance(z, dict):
                continue
            reg = parse_region(z.get("region") or z.get("points") or z.get("polygon"))
            if not reg:
                continue
            zid = str(z.get("id") or f"z{i + 1}")
            name = str(z.get("name") or z.get("label") or f"工位{i + 1}")
            z_staff = z.get("staffIds") if z.get("staffIds") is not None else z.get("staff_ids")
            if z_staff is None:
                z_staff = list(staff_ids)
            try:
                z_staff = [int(x) for x in (z_staff or [])]
            except (TypeError, ValueError):
                z_staff = list(staff_ids)
            thr = z.get("absenceThresholdSec", z.get("absence_threshold_sec"))
            try:
                thr_f = float(thr) if thr is not None else float(absence_threshold_sec)
            except (TypeError, ValueError):
                thr_f = float(absence_threshold_sec)
            try:
                ref_sec = float(z.get("refSec", z.get("ref_sec")) or 0.0)
            except (TypeError, ValueError):
                ref_sec = 0.0
            out.append({
                "id": zid,
                "name": name,
                "region": reg,
                "staffIds": z_staff,
                "absenceThresholdSec": thr_f,
                "borderColor": z.get("borderColor") or z.get("border_color"),
                "fillColor": z.get("fillColor") or z.get("fill_color"),
                # 该工位绘制时的视频时间（镜头运动补偿的参考帧）
                "refSec": ref_sec,
                # 镜头摇出画面：该帧此工位不可见，离岗计时按断流规则暂停
                "outOfView": bool(z.get("outOfView") or z.get("out_of_view")),
            })
        return out
    if region is not None and len(region) >= 3:
        return [{
            "id": "default",
            "name": "工位区",
            "region": region,
            "staffIds": list(staff_ids),
            "absenceThresholdSec": float(absence_threshold_sec),
            "borderColor": None,
            "fillColor": None,
        }]
    # 无区域：全画面视为一个虚拟工位
    return [{
        "id": "frame",
        "name": "全画面",
        "region": None,
        "staffIds": list(staff_ids),
        "absenceThresholdSec": float(absence_threshold_sec),
        "borderColor": None,
        "fillColor": None,
    }]


def get_session(session_id: str, *, reset: bool = False) -> DutySession:
    with _sessions_lock:
        if reset or session_id not in _sessions:
            _sessions[session_id] = DutySession()
        return _sessions[session_id]


def clear_session(session_id: str) -> None:
    with _sessions_lock:
        _sessions.pop(session_id, None)


def export_events_csv(session: DutySession) -> str:
    return events_to_csv(session.events)

def step_duty_session(
    session: DutySession | DutyZoneState,
    *,
    now: float,
    on_duty: bool,
    matched_staff: list[dict[str, Any]] | None = None,
    stream_ok: bool = True,
    absence_threshold_sec: float | None = None,
    events_out: list[dict[str, Any]] | None = None,
    zone_id: str | None = None,
    zone_name: str | None = None,
) -> dict[str, Any]:
    """推进离岗状态机（可单测，不依赖模型）。

    - stream_ok=False：不计离岗时长，状态 stream_down
    - on_duty=True：清零 away，必要时写 return 事件
    - on_duty=False：累计 away；达阈值 → absent + absent 事件
    - session 可为 DutySession（单区）或 DutyZoneState（多工位）
    - events_out：事件写入目标列表；默认写入 DutySession.events
    """
    thr = float(
        absence_threshold_sec
        if absence_threshold_sec is not None
        else getattr(session, "absence_threshold_sec", DEFAULT_ABSENCE_THRESHOLD_SEC)
    )
    session.absence_threshold_sec = thr
    matched_staff = matched_staff or []
    alarms: list[dict[str, Any]] = []
    zid = zone_id if zone_id is not None else getattr(session, "zone_id", None) or None
    zname = zone_name if zone_name is not None else getattr(session, "zone_name", None) or None
    if events_out is None and isinstance(session, DutySession):
        events_out = session.events

    def _push(event: str, status: str, away_sec: float, detail: str = ""):
        staff = matched_staff[0] if matched_staff else None
        row = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "event": event,
            "dutyStatus": status,
            "awaySeconds": round(away_sec, 2),
            "staffId": (staff or {}).get("personId") or session.last_staff_id,
            "staffName": (staff or {}).get("name") or session.last_staff_name,
            "detail": detail,
            "zoneId": zid or "",
            "zoneName": zname or "",
        }
        if events_out is not None:
            events_out.append(row)
        return row

    if not stream_ok:
        if session._stream_pause_at is None:
            session._stream_pause_at = now
        frozen = 0.0
        if session.away_since is not None:
            frozen = max(0.0, float(session._stream_pause_at) - session.away_since)
        return {
            "dutyStatus": "stream_down",
            "awaySeconds": round(frozen, 2),
            "onDuty": False,
            "alertActive": session.alert_active,
            "matchedStaff": matched_staff,
            "alarms": alarms,
            "lastStaffId": session.last_staff_id,
            "lastStaffName": session.last_staff_name,
            "zoneId": zid or "",
            "zoneName": zname or "",
        }

    # 流恢复：断流时长从 away_since 中扣除（顺延起点）
    if session._stream_pause_at is not None:
        pause_dur = max(0.0, now - float(session._stream_pause_at))
        if session.away_since is not None:
            session.away_since += pause_dur
        session._stream_pause_at = None

    if on_duty:
        top = matched_staff[0] if matched_staff else None
        if top:
            session.last_staff_id = top.get("personId")
            session.last_staff_name = top.get("name")
        was_absent = session.alert_active or (
            session.away_since is not None and (now - session.away_since) >= thr
        )
        session.away_since = None
        if was_absent or session.alert_active:
            detail = "已登记人员回到岗位"
            if zname:
                detail = f"「{zname}」{detail}"
            _push("return", "on_duty", 0.0, detail)
            session.alert_active = False
        return {
            "dutyStatus": "on_duty",
            "awaySeconds": 0.0,
            "onDuty": True,
            "alertActive": False,
            "matchedStaff": matched_staff,
            "alarms": alarms,
            "lastStaffId": session.last_staff_id,
            "lastStaffName": session.last_staff_name,
            "zoneId": zid or "",
            "zoneName": zname or "",
        }

    # 非在岗
    if session.away_since is None:
        session.away_since = now
    away_sec = max(0.0, now - session.away_since)
    if away_sec >= thr:
        status = "absent"
        if not session.alert_active:
            session.alert_active = True
            detail = f"连续离岗 ≥ {thr:.0f}s"
            if zname:
                detail = f"「{zname}」{detail}"
            ev = _push("absent", "absent", away_sec, detail)
            alarms.append({
                "event": "ABSENT",
                "message": ev["detail"],
                "awaySeconds": round(away_sec, 2),
                "zoneId": zid or "",
                "zoneName": zname or "",
            })
    else:
        status = "away"

    return {
        "dutyStatus": status,
        "awaySeconds": round(away_sec, 2),
        "onDuty": False,
        "alertActive": session.alert_active,
        "matchedStaff": matched_staff,
        "alarms": alarms,
        "lastStaffId": session.last_staff_id,
        "lastStaffName": session.last_staff_name,
        "zoneId": zid or "",
        "zoneName": zname or "",
    }


def _upper_body_crop(img: np.ndarray, bbox: list[float]) -> np.ndarray | None:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox]
    bw, bh = x2 - x1, y2 - y1
    if bw < 8 or bh < 8:
        return None
    # 上半身偏脸部区域
    cy2 = y1 + bh * 0.55
    nx1 = max(0, int(x1 - bw * 0.05))
    ny1 = max(0, int(y1 - bh * 0.05))
    nx2 = min(w, int(x2 + bw * 0.05))
    ny2 = min(h, int(cy2))
    if nx2 - nx1 < 8 or ny2 - ny1 < 8:
        return None
    return img[ny1:ny2, nx1:nx2]


def _encode_jpeg(bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr)
    if not ok:
        raise ValueError("无法编码人脸裁剪图")
    return buf.tobytes()


def match_persons_on_frame(
    img: np.ndarray,
    detections: list[dict],
    session: DutySession,
    *,
    face_root: str,
    face_pack: str,
    face_model_key: str,
    staff_ids: list[int],
    face_threshold: float = DEFAULT_FACE_THRESHOLD,
    det_thresh: float = 0.5,
    now: float | None = None,
    require_in_zone: bool = False,
    search_fn: Callable[..., dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """对 person 检测做人脸识别，写回 det 字段，返回 (detections, matched_staff)。"""
    from inference import extract_face_embeddings

    now = time.time() if now is None else float(now)
    search_fn = search_fn or faiss_search
    staff_set = {int(x) for x in staff_ids}
    matched_staff: list[dict] = []
    out_dets: list[dict] = []

    for det in detections:
        item = dict(det)
        cname = (item.get("className") or "").lower()
        cid = item.get("classId")
        is_person = cname == "person" or cid == 0
        if not is_person:
            out_dets.append(item)
            continue
        if require_in_zone and item.get("inZone") is False:
            out_dets.append(item)
            continue

        tid = item.get("trackId")
        tid_i = int(tid) if tid is not None else None
        reused = None
        if tid_i is not None:
            prev = session.last_match_by_track.get(tid_i)
            if prev and (now - float(prev.get("at", 0))) < session.face_cooldown_sec:
                reused = prev

        match = None
        if reused:
            match = {
                "personId": reused.get("personId"),
                "name": reused.get("name"),
                "score": reused.get("score"),
                "matched": bool(reused.get("matched")),
            }
        else:
            crop = _upper_body_crop(img, item.get("bbox") or [0, 0, 0, 0])
            if crop is not None:
                try:
                    faces, _ = extract_face_embeddings(
                        face_root, face_pack, _encode_jpeg(crop), det_thresh=det_thresh,
                    )
                    if faces:
                        faces = sorted(faces, key=lambda f: float(f.get("detScore") or 0), reverse=True)
                        emb = faces[0]["embedding"]
                        match = search_fn(
                            emb,
                            face_model_key,
                            threshold=face_threshold,
                            staff_ids=list(staff_set) if staff_set else None,
                        )
                except Exception:  # noqa: BLE001
                    match = None
            # 人脸偶发失败时，短时沿用同 track 上次结果，避免框颜色/标签闪烁
            if match is None and tid_i is not None:
                prev = session.last_match_by_track.get(tid_i)
                sticky = float(getattr(session, "face_sticky_sec", DEFAULT_FACE_STICKY_SEC) or DEFAULT_FACE_STICKY_SEC)
                if prev and (now - float(prev.get("at", 0))) < sticky:
                    match = {
                        "personId": prev.get("personId"),
                        "name": prev.get("name"),
                        "score": prev.get("score"),
                        "matched": bool(prev.get("matched")),
                    }
            elif match and tid_i is not None:
                session.last_match_by_track[tid_i] = {
                    **match,
                    "at": now,
                }

        if match:
            item["personId"] = match.get("personId")
            item["personName"] = match.get("name")
            item["faceScore"] = match.get("score")
            item["faceMatched"] = bool(match.get("matched"))
            if match.get("matched") and match.get("personId") is not None:
                pid = int(match["personId"])
                # staff_ids 为空：任意已登记命中即在岗；非空：须在名单内
                if not staff_set or pid in staff_set:
                    matched_staff.append({
                        "personId": pid,
                        "name": match.get("name"),
                        "score": match.get("score"),
                        "trackId": tid_i,
                    })
        out_dets.append(item)

    # 去重 matched_staff by personId
    seen: set[int] = set()
    uniq: list[dict] = []
    for m in matched_staff:
        pid = int(m["personId"])
        if pid in seen:
            continue
        seen.add(pid)
        uniq.append(m)
    return out_dets, uniq


def enrich_duty_frame(
    frame_bgr: np.ndarray,
    track_result: dict,
    session: DutySession,
    *,
    face_root: str,
    face_pack: str,
    face_model_key: str,
    staff_ids: list[int],
    absence_threshold_sec: float = DEFAULT_ABSENCE_THRESHOLD_SEC,
    face_threshold: float = DEFAULT_FACE_THRESHOLD,
    stream_ok: bool = True,
    now: float | None = None,
    search_fn: Callable[..., dict] | None = None,
    zones: list[dict[str, Any]] | None = None,
    region=None,
) -> dict[str, Any]:
    """在 ByteTrack 结果上叠加人脸识别与离岗状态（支持多工位）。"""
    from services.track_zone import is_effectively_inside, region_to_pixels

    now = time.time() if now is None else float(now)
    h, w = frame_bgr.shape[:2]
    dets = list(track_result.get("detections") or [])

    zone_cfgs = parse_zones_payload(
        zones,
        region=region,
        staff_ids=staff_ids,
        absence_threshold_sec=absence_threshold_sec,
    )
    union_staff: list[int] = []
    seen_s: set[int] = set()
    for z in zone_cfgs:
        for sid in z.get("staffIds") or []:
            si = int(sid)
            if si not in seen_s:
                seen_s.add(si)
                union_staff.append(si)
    if not union_staff:
        union_staff = list(staff_ids or [])

    # 显式传 zones 时在 enrich 内按多边形判定，不依赖 YOLO 单 region 的 inZone
    require_zone = bool(track_result.get("regionEnabled")) and not zones

    dets2, _ = match_persons_on_frame(
        frame_bgr,
        dets,
        session,
        face_root=face_root,
        face_pack=face_pack,
        face_model_key=face_model_key,
        staff_ids=union_staff,
        face_threshold=face_threshold,
        now=now,
        require_in_zone=require_zone,
        search_fn=search_fn,
    )

    zone_results: list[dict[str, Any]] = []
    all_alarms: list[dict] = []
    for z in zone_cfgs:
        zid = z["id"]
        zname = z["name"]
        z_staff = {int(x) for x in (z.get("staffIds") or [])}
        thr = float(z.get("absenceThresholdSec") or absence_threshold_sec)
        px = region_to_pixels(z["region"], w, h) if z.get("region") is not None else None

        matched: list[dict] = []
        for d in dets2:
            if not d.get("faceMatched") or d.get("personId") is None:
                continue
            pid = int(d["personId"])
            if z_staff and pid not in z_staff:
                continue
            if px is not None:
                bbox = d.get("bbox") or []
                if len(bbox) < 4:
                    continue
                cx = (float(bbox[0]) + float(bbox[2])) / 2
                cy = (float(bbox[1]) + float(bbox[3])) / 2
                if not is_effectively_inside(
                    bbox, px, center=(cx, cy), class_name=d.get("className") or "person",
                ):
                    continue
            matched.append({
                "personId": pid,
                "name": d.get("personName"),
                "score": d.get("faceScore"),
                "trackId": d.get("trackId"),
                "zoneId": zid,
                "zoneName": zname,
            })
            zids = d.setdefault("zoneIds", [])
            if zid not in zids:
                zids.append(zid)
            d["zoneId"] = zid
            d["zoneName"] = zname

        seen_p: set[int] = set()
        uniq_m: list[dict] = []
        for m in matched:
            pid = int(m["personId"])
            if pid in seen_p:
                continue
            seen_p.add(pid)
            uniq_m.append(m)

        # 镜头摇出画面时该工位不可见：按断流规则暂停计时，避免「没拍到」被算成「离岗」
        z_stream_ok = stream_ok and not bool(z.get("outOfView"))
        if zid == "frame" and not z.get("region"):
            duty = step_duty_session(
                session,
                now=now,
                on_duty=len(uniq_m) > 0,
                matched_staff=uniq_m,
                stream_ok=z_stream_ok,
                absence_threshold_sec=thr,
                zone_id=zid,
                zone_name=zname,
            )
        else:
            zstate = session.ensure_zone(zid, zname, thr)
            duty = step_duty_session(
                zstate,
                now=now,
                on_duty=len(uniq_m) > 0,
                matched_staff=uniq_m,
                stream_ok=z_stream_ok,
                absence_threshold_sec=thr,
                events_out=session.events,
                zone_id=zid,
                zone_name=zname,
            )
        zone_results.append({
            **duty,
            "zoneId": zid,
            "zoneName": zname,
            "matchedStaff": uniq_m,
            "outOfView": bool(z.get("outOfView")),
        })
        all_alarms.extend(duty.get("alarms") or [])

    agg = aggregate_zone_duties(zone_results)
    out = dict(track_result)
    out["detections"] = dets2
    out.update(agg)
    out["zones"] = zone_results
    out["zoneCount"] = len(zone_results)
    out["events"] = session.events[-50:]
    out["eventCount"] = len(session.events)
    out["alarms"] = list(track_result.get("alarms") or []) + all_alarms
    out["zoneConfigs"] = [
        {
            "id": z["id"],
            "name": z["name"],
            "region": z.get("region"),
            "borderColor": z.get("borderColor"),
            "fillColor": z.get("fillColor"),
            "staffIds": z.get("staffIds") or [],
        }
        for z in zone_cfgs
        if z.get("region")
    ]
    return out


def draw_duty_hud(
    frame_bgr: np.ndarray,
    result: dict,
    *,
    region_px=None,
    zone_style=None,
    zones_px: list[dict[str, Any]] | None = None,
) -> np.ndarray:
    """视频结果叠加中文 HUD（支持多工位多边形）。"""
    from services.track_zone import draw_zone_overlay

    vis = frame_bgr.copy()
    style = zone_style or {}
    default_colors = [
        "#1E88E5", "#43A047", "#FB8C00", "#8E24AA", "#E53935", "#00897B", "#6D4C41",
    ]
    color_map = {
        "on_duty": (80, 200, 80),
        "away": (0, 180, 255),
        "absent": (40, 40, 240),
        "stream_down": (160, 160, 160),
    }

    drawn = False
    if zones_px:
        for i, z in enumerate(zones_px):
            # 不可对 ndarray 使用 `or` / 真值判断，会触发 ambiguous truth value
            poly = z.get("region_px")
            if poly is None:
                poly = z.get("polygon")
            if poly is None:
                continue
            try:
                n_pts = len(poly)
            except TypeError:
                continue
            if n_pts < 3:
                continue
            border = z.get("borderColor") or style.get("borderColor") or default_colors[i % len(default_colors)]
            fill = z.get("fillColor") or style.get("fillColor") or border
            vis = draw_zone_overlay(
                vis,
                np.asarray(poly, dtype=np.float32),
                border_color=border,
                fill_color=fill,
                fill_alpha=style.get("fillAlpha", 0.14),
                border_width=style.get("borderWidth", style.get("border_width", 3)),
            )
            try:
                pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
                cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())
            except Exception:  # noqa: BLE001
                cx, cy = 20, 40 + i * 28
            st = z.get("dutyStatus") or ""
            label = f"{z.get('zoneName') or z.get('name') or z.get('zoneId') or ''}·{duty_status_zh(st)}"
            away_z = z.get("awaySeconds")
            if st in ("away", "absent") and away_z is not None:
                label += f" {float(away_z):.0f}s"
            vis = _draw_cn_label(
                vis, label, (max(8, cx - 40), max(8, cy - 10)),
                bg_bgr=color_map.get(st, (30, 136, 229)), font_size=16,
            )
            drawn = True

    if not drawn and region_px is not None and len(region_px) >= 3:
        vis = draw_zone_overlay(
            vis,
            np.asarray(region_px, dtype=np.float32),
            border_color=style.get("borderColor") or style.get("border_color"),
            fill_color=style.get("fillColor") or style.get("fill_color"),
            fill_alpha=style.get("fillAlpha", style.get("fill_alpha")),
            border_width=style.get("borderWidth", style.get("border_width", style.get("lineWidth"))),
        )

    status = result.get("dutyStatus") or "-"
    away = float(result.get("awaySeconds") or 0)
    color = color_map.get(status, (200, 200, 200))
    staff = result.get("matchedStaff") or []
    names = [str(s.get("name") or s.get("personId") or "") for s in staff[:3]]
    zone_n = int(result.get("zoneCount") or 0)
    if zone_n > 1:
        absent_n = sum(1 for z in (result.get("zones") or []) if z.get("dutyStatus") == "absent")
        away_n = sum(1 for z in (result.get("zones") or []) if z.get("dutyStatus") == "away")
        on_n = sum(1 for z in (result.get("zones") or []) if z.get("dutyStatus") == "on_duty")
        label = f"汇总：在岗{on_n} 暂离{away_n} 离岗{absent_n}　最差={duty_status_zh(status)}"
        if away > 0 and status in ("away", "absent"):
            label += f"　{away:.1f}秒"
    else:
        label = format_duty_hud_label(status, away, names)
    vis = _draw_cn_label(vis, label, (10, 10), bg_bgr=color, font_size=20)

    for d in result.get("detections") or []:
        bbox = d.get("bbox") or []
        if len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox]
        matched = bool(d.get("faceMatched"))
        c = (50, 255, 50) if matched else (255, 0, 255)
        cv2.rectangle(vis, (x1, y1), (x2, y2), c, 3)
        name = d.get("personName") or d.get("className") or "人员"
        if str(name).lower() == "person":
            name = "人员"
        tid = d.get("trackId")
        zlabel = d.get("zoneName") or ""
        parts = []
        if tid is not None:
            parts.append(f"ID{tid}")
        parts.append(str(name))
        if zlabel:
            parts.append(str(zlabel))
        txt = " ".join(parts)
        ty = max(8, y1 - 28)
        vis = _draw_cn_label(vis, txt, (x1, ty), bg_bgr=c, font_size=18)
    return vis


def _draw_cn_label(img_bgr: np.ndarray, text: str, origin, *, bg_bgr=(80, 200, 80), font_size: int = 18) -> np.ndarray:
    """PIL 绘制中文标签（OpenCV putText 不支持中文）。"""
    if not text:
        return img_bgr
    from PIL import Image, ImageDraw
    from services.track_zone import _zone_font

    font = _zone_font(font_size, bold=True)
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    x, y = int(origin[0]), int(origin[1])
    bbox = draw.textbbox((x, y), text, font=font)
    pad = 4
    # BGR -> RGB fill
    fill = (int(bg_bgr[2]), int(bg_bgr[1]), int(bg_bgr[0]))
    draw.rectangle(
        [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
        fill=fill,
    )
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)