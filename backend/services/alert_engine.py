"""检测告警规则引擎：烟火 / 聚集 / PPE 未戴帽 / 越线入侵等。

规则阈值与中央叠加样式均存于 AlertRule.config_json，管理员可改。
越线复用跟踪页几何判定（与 inference._crosses 一致）。
"""
from __future__ import annotations

import threading
import time
from typing import Any

# (rule_id, source_key) -> { streak, last_fire_ts, centroids, crossed,
#                            fall_tracks, fall_frame_token, fall_frame_detail }
_runtime: dict[tuple[int, str], dict[str, Any]] = {}
_lock = threading.Lock()

_SUGGESTIONS = {
    "fire-smoke": "立即核实火情、就近取用灭火器并启动应急预案；确认消防通道畅通。",
    "crowd-gathering": "评估区域承载上限、做人流疏导与分流；增派现场管理人员。",
    "ppe-no-hardhat": "立即提醒未戴安全帽人员补戴或撤离危险区域；入口增设佩戴检查。",
    "line-intrusion": "核查越线人员身份与事由；必要时广播劝离并联动门禁/安保。",
    "zone-intrusion": "核查区域越界人员/车辆身份与事由；必要时广播劝离并联动门禁/安保。",
    "stranger-face": "核查现场人员身份；必要时登记访客或联动门禁/安保。",
}

_PERSON_ALIASES = ("person", "people", "human", "pedestrian", "行人", "人", "人体", "Person")
_UNKNOWN_FACE_ALIASES = ("unknown", "未知", "stranger", "陌生人")

# 默认叠加样式（可被规则 config.overlay 覆盖）
_DEFAULT_OVERLAY: dict[str, dict[str, Any]] = {
    "fire-smoke": {
        "fillColor": "#FF1A1A",
        "borderColor": "#CC0000",
        "textColor": "#FFFFFF",
        "titleLines": ["FIRE", "DANGEROUS", "ALERT"],
        "subtitleLines": [],
        "panelWidthRatio": 0.72,
        "panelHeightRatio": 0.36,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#FFFFFF",
        "triangleMark": "#B00000",
    },
    "crowd-gathering": {
        "fillColor": "#FFD400",
        "borderColor": "#E6B800",
        "textColor": "#1A1A1A",
        "titleLines": ["CROWD ALERT"],
        "subtitleLines": ["注意安全", "防止拥挤踩踏"],
        "panelWidthRatio": 0.72,
        "panelHeightRatio": 0.36,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#1A1A1A",
        "triangleMark": "#FFFFFF",
    },
    "ppe-no-hardhat": {
        "fillColor": "#FF7A00",
        "borderColor": "#CC6200",
        "textColor": "#FFFFFF",
        "titleLines": ["NO HARDHAT"],
        "subtitleLines": ["未佩戴安全帽", "立即纠正"],
        "panelWidthRatio": 0.72,
        "panelHeightRatio": 0.36,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#FFFFFF",
        "triangleMark": "#CC6200",
    },
    "line-intrusion": {
        "fillColor": "#9254DE",
        "borderColor": "#722ED1",
        "textColor": "#FFFFFF",
        "titleLines": ["INTRUSION"],
        "subtitleLines": ["越线告警", "请勿闯入"],
        "panelWidthRatio": 0.72,
        "panelHeightRatio": 0.36,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#FFFFFF",
        "triangleMark": "#722ED1",
    },
    "zone-intrusion": {
        "fillColor": "#CF1322",
        "borderColor": "#A8071A",
        "textColor": "#FFFFFF",
        "titleLines": ["ZONE ALARM"],
        "subtitleLines": ["区域越界", "请勿闯入/离开"],
        "panelWidthRatio": 0.72,
        "panelHeightRatio": 0.36,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#FFFFFF",
        "triangleMark": "#A8071A",
    },
    "stranger-face": {
        "fillColor": "#409EFF",
        "borderColor": "#1D6FBF",
        "textColor": "#FFFFFF",
        "titleLines": ["STRANGER"],
        "subtitleLines": ["陌生人脸", "请核验身份"],
        "panelWidthRatio": 0.68,
        "panelHeightRatio": 0.32,
        "opacity": 0.45,
        "showTriangle": True,
        "triangleFill": "#FFFFFF",
        "triangleMark": "#1D6FBF",
    },
}

_GENERIC_OVERLAY = {
    "fillColor": "#409EFF",
    "borderColor": "#337ECC",
    "textColor": "#FFFFFF",
    "titleLines": ["ALERT"],
    "subtitleLines": ["请现场核实"],
    "panelWidthRatio": 0.72,
    "panelHeightRatio": 0.32,
    "opacity": 0.45,
    "showTriangle": True,
    "triangleFill": "#FFFFFF",
    "triangleMark": "#337ECC",
}


def _norm(s: str) -> str:
    return (s or "").strip().lower().replace("_", "-").replace(" ", "-")


def _match_class(name: str, targets: list[str]) -> bool:
    n = _norm(name)
    for t in targets:
        t = _norm(t)
        if n == t or t in n or n in t:
            return True
    return False


def _filter_dets(detections: list[dict], min_conf: float) -> list[dict]:
    out = []
    for d in detections or []:
        try:
            c = float(d.get("confidence", 0))
        except (TypeError, ValueError):
            c = 0.0
        if c >= min_conf:
            out.append(d)
    return out


def _crowd_class_targets(cfg: dict) -> list[str]:
    raw = cfg.get("class_names") or cfg.get("class_name") or cfg.get("className") or "person"
    if isinstance(raw, str):
        raw = [raw]
    return list(dict.fromkeys([*(raw or []), *_PERSON_ALIASES]))


def count_persons(detections: list[dict], min_conf: float = 0.25) -> int:
    dets = _filter_dets(detections, min_conf)
    return sum(1 for d in dets if _match_class(d.get("className", ""), list(_PERSON_ALIASES)))


def _eval_class_presence(rule, cfg: dict, detections: list[dict]) -> dict | None:
    classes = cfg.get("classes") or []
    min_conf = float(cfg.get("min_confidence", 0.35))
    dets = _filter_dets(detections, min_conf)
    hits = [d for d in dets if _match_class(d.get("className", ""), classes)]
    if not hits:
        return None
    names = sorted({d.get("className", "") for d in hits})
    return {
        "matched": True,
        "hitCount": len(hits),
        "classes": names,
        "maxConfidence": round(max(float(d.get("confidence", 0)) for d in hits), 4),
        "detections": [
            {
                "className": d.get("className"),
                "confidence": d.get("confidence"),
                "bbox": d.get("bbox"),
            }
            for d in hits[:10]
        ],
    }


def _eval_count_threshold(rule, cfg: dict, detections: list[dict]) -> dict | None:
    min_count = int(cfg.get("min_count", cfg.get("minCount", 4)))
    min_conf = float(cfg.get("min_confidence", 0.25))
    dets = _filter_dets(detections, min_conf)
    targets = _crowd_class_targets(cfg)
    hits = [d for d in dets if _match_class(d.get("className", ""), targets)]
    count = len(hits)
    if count < min_count:
        return None
    return {
        "matched": True,
        "count": count,
        "minCount": min_count,
        "className": targets[0] if targets else "person",
        "maxConfidence": round(max((float(d.get("confidence", 0)) for d in hits), default=0), 4),
        "detections": [
            {
                "className": d.get("className"),
                "confidence": d.get("confidence"),
                "bbox": d.get("bbox"),
            }
            for d in hits[:10]
        ],
    }


def _orient(ax, ay, bx, by, cx, cy):
    """点 C 相对有向线段 A->B 的叉积（与 inference._orient 一致）。"""
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _crosses(prev, curr, line):
    """prev->curr 是否穿过 line；+1 进 / -1 出 / 0 未穿。"""
    ax, ay = prev
    bx, by = curr
    x1, y1, x2, y2 = line
    d1 = _orient(x1, y1, x2, y2, ax, ay)
    d2 = _orient(x1, y1, x2, y2, bx, by)
    d3 = _orient(ax, ay, bx, by, x1, y1)
    d4 = _orient(ax, ay, bx, by, x2, y2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 1 if d1 < 0 else -1
    return 0


def _parse_line(raw) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
        try:
            raw = [float(p) for p in parts]
        except (TypeError, ValueError):
            return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        line = [float(x) for x in raw]
    except (TypeError, ValueError):
        return None
    return line


def _centroid_norm(det: dict, frame_w: float | None, frame_h: float | None):
    bbox = det.get("bbox") or det.get("box")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    except (TypeError, ValueError):
        return None
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    # 像素坐标 → 归一化；若已是 0–1 量级则直接使用
    if frame_w and frame_h and max(abs(x1), abs(y1), abs(x2), abs(y2)) > 1.5:
        return (cx / float(frame_w), cy / float(frame_h))
    return (cx, cy)


def _line_class_targets(cfg: dict) -> list[str]:
    raw = cfg.get("classes") or cfg.get("class_names") or cfg.get("class_name") or list(_PERSON_ALIASES[:1])
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.replace("，", ",").split(",") if x.strip()]
    return list(dict.fromkeys(raw or ["person"]))


def _eval_line_crossing(rule, cfg: dict, detections: list[dict], ctx: dict | None) -> dict | None:
    """基于 trackId 轨迹中心点与警戒线几何相交判定入侵。"""
    ctx = ctx or {}
    line = _parse_line(ctx.get("line")) or _parse_line(cfg.get("line"))
    if not line:
        return None
    min_conf = float(cfg.get("min_confidence", 0.25))
    direction = (cfg.get("direction") or "both").strip().lower()
    targets = _line_class_targets(cfg)
    fw = ctx.get("frame_width") or ctx.get("frameWidth")
    fh = ctx.get("frame_height") or ctx.get("frameHeight")
    try:
        fw = float(fw) if fw is not None else None
        fh = float(fh) if fh is not None else None
    except (TypeError, ValueError):
        fw, fh = None, None

    rid = rule.id if hasattr(rule, "id") else rule.get("id")
    src = (ctx.get("source_key") or "default")
    key = (rid, src)
    frame_token = ctx.get("frame_token")

    dets = _filter_dets(detections, min_conf)
    with _lock:
        st = _runtime.setdefault(
            key, {"streak": 0, "last_fire_ts": 0.0, "centroids": {}, "crossed": set()}
        )
        # 同一帧 evaluate + overlay 各调用一次时复用结果，避免质心被提前推进
        if frame_token is not None and st.get("frame_token") == frame_token:
            return st.get("frame_detail")

        centroids: dict = st.setdefault("centroids", {})
        crossed: set = st.setdefault("crossed", set())
        hits = []

        for d in dets:
            if not _match_class(d.get("className", ""), targets):
                continue
            tid = d.get("trackId", d.get("track_id"))
            if tid is None:
                continue
            try:
                tid = int(tid)
            except (TypeError, ValueError):
                continue
            curr = _centroid_norm(d, fw, fh)
            if curr is None:
                continue
            prev = centroids.get(tid)
            centroids[tid] = curr
            if prev is None:
                continue
            cross_dir = _crosses(prev, curr, line)
            if cross_dir == 0:
                continue
            if direction == "in" and cross_dir <= 0:
                continue
            if direction == "out" and cross_dir >= 0:
                continue
            mark = (tid, cross_dir)
            if mark in crossed:
                continue
            crossed.add(mark)
            hits.append({
                "trackId": tid,
                "direction": "in" if cross_dir > 0 else "out",
                "className": d.get("className"),
                "confidence": d.get("confidence"),
                "bbox": d.get("bbox"),
            })

        detail = None
        if hits:
            detail = {
                "matched": True,
                "crossCount": len(hits),
                "direction": direction,
                "line": line,
                "classes": sorted({h["className"] for h in hits if h.get("className")}),
                "maxConfidence": round(
                    max((float(h.get("confidence") or 0) for h in hits), default=0), 4
                ),
                "crossings": hits[:10],
            }
        if frame_token is not None:
            st["frame_token"] = frame_token
            st["frame_detail"] = detail
        return detail


def _parse_region(raw) -> list[list[float]] | None:
    """解析归一化多边形 [[x,y],...]。"""
    from services.track_zone import parse_region
    return parse_region(raw)


def _eval_zone_crossing(rule, cfg: dict, detections: list[dict], ctx: dict | None) -> dict | None:
    """基于 trackId 检测框与多边形重叠面积（≥30%）判定有效进出。"""
    from services.track_zone import (
        DEFAULT_AREA_RATIO,
        is_effectively_inside,
        region_to_pixels,
        zone_cross_by_area,
    )

    ctx = ctx or {}
    region = _parse_region(ctx.get("region")) or _parse_region(cfg.get("region"))
    if not region:
        return None
    min_conf = float(cfg.get("min_confidence", 0.25))
    direction = (cfg.get("direction") or "both").strip().lower()
    targets = _line_class_targets(cfg)
    try:
        area_ratio = float(cfg.get("area_ratio", cfg.get("areaRatio", DEFAULT_AREA_RATIO)))
    except (TypeError, ValueError):
        area_ratio = DEFAULT_AREA_RATIO
    fw = ctx.get("frame_width") or ctx.get("frameWidth")
    fh = ctx.get("frame_height") or ctx.get("frameHeight")
    try:
        fw = float(fw) if fw is not None else None
        fh = float(fh) if fh is not None else None
    except (TypeError, ValueError):
        fw, fh = None, None
    if not fw or not fh or fw <= 0 or fh <= 0:
        return None

    rid = rule.id if hasattr(rule, "id") else rule.get("id")
    src = (ctx.get("source_key") or "default")
    key = (rid, src)
    frame_token = ctx.get("frame_token")

    poly = region_to_pixels(region, int(fw), int(fh))
    dets = _filter_dets(detections, min_conf)
    with _lock:
        st = _runtime.setdefault(
            key, {"streak": 0, "last_fire_ts": 0.0, "centroids": {}, "crossed": set(), "inside": {}}
        )
        if frame_token is not None and st.get("frame_token") == frame_token:
            return st.get("frame_detail")

        inside_map: dict = st.setdefault("inside", {})
        crossed = st.setdefault("crossed", set())
        if not isinstance(crossed, set):
            crossed = set()
            st["crossed"] = crossed
        hits = []

        for d in dets:
            if not _match_class(d.get("className", ""), targets):
                continue
            tid = d.get("trackId", d.get("track_id"))
            if tid is None:
                continue
            try:
                tid = int(tid)
            except (TypeError, ValueError):
                continue
            bbox = d.get("bbox") or d.get("box")
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            try:
                x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
            except (TypeError, ValueError):
                continue
            # bbox 可能是归一化或像素
            if max(x1, y1, x2, y2) <= 1.5:
                px_bbox = [x1 * fw, y1 * fh, x2 * fw, y2 * fh]
            else:
                px_bbox = [x1, y1, x2, y2]
            curr_in = is_effectively_inside(
                px_bbox, poly,
                area_ratio=area_ratio,
                class_id=d.get("classId"),
                class_name=d.get("className"),
            )
            prev_in = inside_map.get(tid)
            inside_map[tid] = curr_in
            if prev_in is None:
                continue
            cross_dir = zone_cross_by_area(bool(prev_in), bool(curr_in))
            if cross_dir == 0:
                continue
            if direction == "in" and cross_dir <= 0:
                continue
            if direction == "out" and cross_dir >= 0:
                continue
            mark = (tid, cross_dir)
            if mark in crossed:
                continue
            crossed.add(mark)
            hits.append({
                "trackId": tid,
                "direction": "in" if cross_dir > 0 else "out",
                "className": d.get("className"),
                "confidence": d.get("confidence"),
                "bbox": d.get("bbox"),
            })

        detail = None
        if hits:
            detail = {
                "matched": True,
                "crossCount": len(hits),
                "direction": direction,
                "region": region,
                "areaRatio": area_ratio,
                "classes": sorted({h["className"] for h in hits if h.get("className")}),
                "maxConfidence": round(
                    max((float(h.get("confidence") or 0) for h in hits), default=0), 4
                ),
                "crossings": hits[:10],
            }
        if frame_token is not None:
            st["frame_token"] = frame_token
            st["frame_detail"] = detail
        return detail


def _is_unmatched_face(d: dict) -> bool:
    """人脸识别结果是否为未匹配（陌生人）。"""
    if d.get("matched") is False:
        return True
    if d.get("matched") is True:
        return False
    name = str(d.get("name") or d.get("className") or "").strip().lower()
    return name in _UNKNOWN_FACE_ALIASES


def _eval_unmatched_face(rule, cfg: dict, detections: list[dict]) -> dict | None:
    """未匹配人脸：matched=false 或 name/className 为 unknown。"""
    min_score = float(cfg.get("min_confidence", cfg.get("minConfidence", 0.0)))
    hits = []
    for d in detections or []:
        if not _is_unmatched_face(d):
            continue
        score = d.get("score")
        if score is None:
            score = d.get("confidence", 0)
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        # 陌生人：相似度通常低于阈值；min_confidence 用作「检测框置信度」下限（可选）
        det_conf = d.get("detConfidence", d.get("det_confidence"))
        if det_conf is not None:
            try:
                if float(det_conf) < min_score:
                    continue
            except (TypeError, ValueError):
                pass
        hits.append({
            "name": d.get("name") or d.get("className") or "unknown",
            "score": round(score, 4),
            "bbox": d.get("bbox"),
            "personId": d.get("personId"),
        })
    if not hits:
        return None
    return {
        "matched": True,
        "count": len(hits),
        "classes": ["unknown"],
        "maxConfidence": round(max((h["score"] for h in hits), default=0), 4),
        "faces": hits[:10],
    }


# ---------------------------------------------------------------- 跌倒检测
_FALL_THRESHOLD_DEFAULTS = {
    "trunk_angle_deg": 60.0,
    "centroid_speed": 0.5,
    "height_ratio": 0.5,
    "head_y_ratio": 0.75,
    "min_score": 2.0,
    "kp_min_conf": 0.3,
}
_FALL_INT_DEFAULTS = {
    "stand_baseline_window": 90,
    "track_max_age": 15,
}
_FALL_WEIGHT_KEYS = ("trunk", "speed", "height", "head")


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(w.capitalize() for w in rest)


def _cfg_num(cfg: dict, key: str, default, cast=float):
    raw = cfg.get(key, cfg.get(_camel(key), default))
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return cast(default)


def fall_config(cfg: dict) -> dict:
    """从规则 config 解析跌倒阈值与权重，缺省回落到默认值（兼容驼峰键）。"""
    cfg = cfg or {}
    out = {k: _cfg_num(cfg, k, v) for k, v in _FALL_THRESHOLD_DEFAULTS.items()}
    out.update({k: _cfg_num(cfg, k, v, int) for k, v in _FALL_INT_DEFAULTS.items()})
    raw_w = cfg.get("weights") or {}
    weights = {}
    for k in _FALL_WEIGHT_KEYS:
        try:
            weights[k] = float(raw_w.get(k, 1))
        except (TypeError, ValueError):
            weights[k] = 1.0
    out["weights"] = weights
    out["stand_baseline_window"] = max(3, out["stand_baseline_window"])
    return out


def _eval_fall_detection(rule, cfg: dict, detections: list[dict], ctx: dict | None) -> dict | None:
    """姿态关键点四指标跌倒判定：躯干角 / 质心速度 / 身高比 / 头部高度。

    阈值与权重全部来自 rule.config()。跨帧状态按 trackId 存于 _runtime；
    同一 frame_token 重复调用直接复用缓存，避免质心被提前推进。
    """
    from services.fall_detect import keypoint_metrics

    ctx = ctx or {}
    fh = ctx.get("frame_height") or ctx.get("frameHeight")
    try:
        fh = float(fh) if fh is not None else None
    except (TypeError, ValueError):
        fh = None

    rid = rule.id if hasattr(rule, "id") else rule.get("id")
    src = ctx.get("source_key") or "default"
    key = (rid, src)
    frame_token = ctx.get("frame_token")
    try:
        now = float(ctx.get("now_ts")) if ctx.get("now_ts") is not None else time.time()
    except (TypeError, ValueError):
        now = time.time()

    conf = fall_config(cfg)
    weights = conf["weights"]
    total_weight = sum(weights.values()) or 1.0
    window = conf["stand_baseline_window"]

    with _lock:
        st = _runtime.setdefault(
            key, {"streak": 0, "last_fire_ts": 0.0, "centroids": {}, "crossed": set()}
        )
        if frame_token is not None and st.get("fall_frame_token") == frame_token:
            return st.get("fall_frame_detail")

        tracks: dict = st.setdefault("fall_tracks", {})
        fallen = []
        live = set()

        for d in detections or []:
            tid = d.get("trackId", d.get("track_id"))
            kp = d.get("keypoints")
            if tid is None or not kp:
                continue
            try:
                tid = int(tid)
            except (TypeError, ValueError):
                continue
            live.add(tid)
            m = keypoint_metrics(kp, None, fh, conf["kp_min_conf"])
            tr = tracks.setdefault(tid, {"hip": None, "standHist": [], "since": None, "miss": 0})
            tr["miss"] = 0

            score = 0.0
            indicators = {}

            # 指标 1：躯干角（肩中点->髋中点 与垂直方向夹角）
            if weights["trunk"] and m["valid"]["trunk"]:
                indicators["trunk"] = round(m["trunkAngle"], 2)
                if m["trunkAngle"] > conf["trunk_angle_deg"]:
                    score += weights["trunk"]

            # 指标 2：质心（髋部）下降速度，单位「画面高/秒」
            if m["valid"]["hip"]:
                prev = tr.get("hip")
                if weights["speed"] and prev and fh and now - prev[0] > 0:
                    v = (m["hipY"] - prev[1]) / (now - prev[0]) / fh
                    indicators["speed"] = round(v, 4)
                    if v > conf["centroid_speed"]:
                        score += weights["speed"]
                tr["hip"] = (now, m["hipY"])

            # 指标 3：身高比（当前躯干高度 / 站立基线）
            # 本块只算比值/计分，不直接写基线——基线是否可信取决于本帧
            # 综合判定结果（见下方 not-fallen 分支），而非本指标单独的态度。
            pending_stand_h = None
            if weights["height"]:
                body_h = m["bodyHeight"]  # 关键点置信度不足时为 None，直接跳过，不用 bbox 顶替
                if body_h:
                    hist = tr["standHist"]
                    base = max(hist) if len(hist) >= 3 else None
                    if base:
                        ratio = body_h / base
                        indicators["height"] = round(ratio, 4)
                        if ratio < conf["height_ratio"]:
                            score += weights["height"]
                        else:
                            pending_stand_h = body_h  # 疑似站立，待整体判定确认后再计入基线
                    else:
                        pending_stand_h = body_h  # 基线冷启动：先暂存，同样待整体判定确认

            # 指标 4：头部离地高度
            if weights["head"] and m["valid"]["nose"] and fh:
                head_ratio = m["noseY"] / fh
                indicators["head"] = round(head_ratio, 4)
                if head_ratio > conf["head_y_ratio"]:
                    score += weights["head"]

            if score >= conf["min_score"]:
                if tr["since"] is None:
                    tr["since"] = now
                fallen.append({
                    "trackId": tid,
                    "bbox": d.get("bbox"),
                    "fallScore": round(score, 4),
                    "confidence": round(score / total_weight, 4),
                    "sustainSec": round(now - tr["since"], 2),
                    "indicators": indicators,
                })
            else:
                tr["since"] = None
                # 仅整体判定为「非跌倒」时才把本帧身高计入站立基线，避免倒地污染
                if pending_stand_h is not None:
                    hist = tr["standHist"]
                    hist.append(pending_stand_h)
                    if len(hist) > window:
                        del hist[:-window]

        for tid in list(tracks):
            if tid in live:
                continue
            tracks[tid]["miss"] = tracks[tid].get("miss", 0) + 1
            if tracks[tid]["miss"] > conf["track_max_age"]:
                del tracks[tid]

        detail = None
        if fallen:
            detail = {
                "matched": True,
                "fallenCount": len(fallen),
                "maxScore": max(f["fallScore"] for f in fallen),
                "sustainSec": max(f["sustainSec"] for f in fallen),
                "fallen": fallen[:10],
            }
        if frame_token is not None:
            st["fall_frame_token"] = frame_token
            st["fall_frame_detail"] = detail
        return detail


def _condition_met(rule, detections: list[dict], ctx: dict | None = None) -> dict | None:
    cfg = rule.config() if hasattr(rule, "config") else (rule.get("config") or {})
    rtype = rule.rule_type if hasattr(rule, "rule_type") else rule.get("ruleType")
    if rtype == "class_presence":
        return _eval_class_presence(rule, cfg, detections)
    if rtype == "count_threshold":
        return _eval_count_threshold(rule, cfg, detections)
    if rtype == "line_crossing":
        return _eval_line_crossing(rule, cfg, detections, ctx)
    if rtype == "zone_crossing":
        return _eval_zone_crossing(rule, cfg, detections, ctx)
    if rtype == "unmatched_face":
        return _eval_unmatched_face(rule, cfg, detections)
    if rtype == "fall_detection":
        return _eval_fall_detection(rule, cfg, detections, ctx)
    return None


def _title_message(rule, detail: dict) -> tuple[str, str]:
    key = rule.rule_key if hasattr(rule, "rule_key") else rule.get("ruleKey", "")
    name = rule.name if hasattr(rule, "name") else rule.get("name", "告警")
    cfg = rule.config() if hasattr(rule, "config") else (rule.get("config") or {})

    # 管理员自定义文案模板（可选）
    title_tpl = (cfg.get("title_template") or cfg.get("titleTemplate") or "").strip()
    msg_tpl = (cfg.get("message_template") or cfg.get("messageTemplate") or "").strip()
    if title_tpl or msg_tpl:
        ctx = {
            "name": name,
            "count": detail.get("count", 0),
            "minCount": detail.get("minCount", 0),
            "classes": "、".join(detail.get("classes") or []),
            "maxConfidence": detail.get("maxConfidence", 0),
            "crossCount": detail.get("crossCount", 0),
            "direction": detail.get("direction", ""),
        }
        try:
            title = title_tpl.format(**ctx) if title_tpl else name
        except (KeyError, ValueError):
            title = title_tpl or name
        try:
            msg = msg_tpl.format(**ctx) if msg_tpl else (detail.get("message") or "请现场核实")
        except (KeyError, ValueError):
            msg = msg_tpl or "请现场核实"
        return title, msg

    if key == "fire-smoke":
        cls = "、".join(detail.get("classes") or [])
        title = f"疑似烟火：检测到 {cls or 'fire/smoke'}"
        msg = _SUGGESTIONS["fire-smoke"]
        if detail.get("maxConfidence"):
            msg = f"最高置信度 {detail['maxConfidence']:.0%}。{msg}"
        return title, msg
    if key == "crowd-gathering":
        title = f"人员聚集：当前 {detail.get('count', 0)} 人（阈值 {detail.get('minCount', 0)}）"
        msg = _SUGGESTIONS["crowd-gathering"]
        return title, msg
    if key == "ppe-no-hardhat":
        cls = "、".join(detail.get("classes") or [])
        title = f"未戴安全帽：检测到 {cls or 'NO-Hardhat'}"
        msg = _SUGGESTIONS["ppe-no-hardhat"]
        if detail.get("maxConfidence"):
            msg = f"最高置信度 {detail['maxConfidence']:.0%}。{msg}"
        return title, msg
    if key == "line-intrusion" or (
        (rule.rule_type if hasattr(rule, "rule_type") else rule.get("ruleType")) == "line_crossing"
    ):
        n = detail.get("crossCount", 0)
        dirs = "、".join(sorted({c.get("direction", "") for c in (detail.get("crossings") or []) if c.get("direction")}))
        title = f"越线入侵：{n} 次穿越" + (f"（{dirs}）" if dirs else "")
        msg = _SUGGESTIONS.get(key) or _SUGGESTIONS["line-intrusion"]
        return title, msg
    if key == "zone-intrusion" or (
        (rule.rule_type if hasattr(rule, "rule_type") else rule.get("ruleType")) == "zone_crossing"
    ):
        n = detail.get("crossCount", 0)
        dirs = "、".join(sorted({c.get("direction", "") for c in (detail.get("crossings") or []) if c.get("direction")}))
        title = f"区域越界：{n} 次穿越" + (f"（{dirs}）" if dirs else "")
        msg = _SUGGESTIONS.get(key) or _SUGGESTIONS["zone-intrusion"]
        return title, msg
    if key == "stranger-face" or (
        (rule.rule_type if hasattr(rule, "rule_type") else rule.get("ruleType")) == "unmatched_face"
    ):
        n = detail.get("count", 0)
        title = f"陌生人脸：检测到 {n} 张未匹配人脸"
        msg = _SUGGESTIONS.get(key) or _SUGGESTIONS["stranger-face"]
        return title, msg
    return name, detail.get("message") or "检测规则触发，请现场核实。"


def resolve_overlay_style(rule) -> dict[str, Any]:
    """合并规则自带 overlay 与默认主题，返回可序列化样式。"""
    key = rule.rule_key if hasattr(rule, "rule_key") else rule.get("ruleKey", "")
    name = rule.name if hasattr(rule, "name") else rule.get("name", "告警")
    cfg = rule.config() if hasattr(rule, "config") else (rule.get("config") or {})
    base = dict(_DEFAULT_OVERLAY.get(key) or _GENERIC_OVERLAY)
    custom = cfg.get("overlay") or {}
    if isinstance(custom, dict):
        base.update({k: v for k, v in custom.items() if v is not None and v != ""})
    # 规范化线条字段
    for field in ("titleLines", "subtitleLines"):
        val = base.get(field)
        if isinstance(val, str):
            base[field] = [ln.strip() for ln in val.replace("\r", "").split("\n") if ln.strip()]
        elif not isinstance(val, list):
            base[field] = []
        else:
            base[field] = [str(x).strip() for x in val if str(x).strip()]
    base["ruleKey"] = key
    base["ruleName"] = name
    return base


def _video_overlay_cfg(cfg: dict) -> dict:
    """视频中央图标用更宽松阈值（video_min_count）。"""
    c = dict(cfg or {})
    if c.get("video_min_count") is not None:
        c["min_count"] = int(c["video_min_count"])
    elif c.get("videoMinCount") is not None:
        c["min_count"] = int(c["videoMinCount"])
    else:
        c["min_count"] = min(int(c.get("min_count", c.get("minCount", 4))), 4)
    return c


def active_overlay_style(
    rules,
    detections,
    *,
    video: bool = False,
    frame_width: float | None = None,
    frame_height: float | None = None,
    line: list | None = None,
    region: list | None = None,
    source_key: str = "default",
    frame_token: str | None = None,
) -> dict | None:
    """当前帧应显示的叠加样式（无防抖）。优先级：config.priority 升序。"""
    eval_ctx = {
        "source_key": source_key,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "line": line,
        "region": region,
        "frame_token": frame_token,
    }
    matched: list[tuple[int, int, Any, dict]] = []
    for rule in rules or []:
        status = rule.status if hasattr(rule, "status") else rule.get("status", "0")
        if status != "0":
            continue
        cfg = rule.config() if hasattr(rule, "config") else (rule.get("config") or {})
        overlay_cfg = cfg.get("overlay") or {}
        if overlay_cfg.get("enabled") is False:
            continue
        rtype = rule.rule_type if hasattr(rule, "rule_type") else rule.get("ruleType")
        if video and rtype == "count_threshold":
            detail = _eval_count_threshold(rule, _video_overlay_cfg(cfg), detections)
        else:
            detail = _condition_met(rule, detections, eval_ctx)
        if not detail:
            continue
        key = rule.rule_key if hasattr(rule, "rule_key") else rule.get("ruleKey", "")
        default_pri = {
            "fire-smoke": 0,
            "ppe-no-hardhat": 5,
            "crowd-gathering": 10,
            "zone-intrusion": 12,
            "line-intrusion": 15,
            "stranger-face": 8,
        }.get(key, 20)
        try:
            pri = int(overlay_cfg.get("priority", cfg.get("priority", default_pri)))
        except (TypeError, ValueError):
            pri = default_pri
        rid = rule.id if hasattr(rule, "id") else rule.get("id") or 0
        matched.append((pri, int(rid), rule, detail))

    if not matched:
        return None
    matched.sort(key=lambda x: (x[0], x[1]))
    rule = matched[0][2]
    style = resolve_overlay_style(rule)
    return style


def active_overlay_kind(
    rules,
    detections,
    *,
    video: bool = False,
    frame_width: float | None = None,
    frame_height: float | None = None,
    line: list | None = None,
    source_key: str = "default",
    frame_token: str | None = None,
) -> str | None:
    """兼容旧接口：返回 fire / crowd / ppe / intrusion / generic。"""
    style = active_overlay_style(
        rules,
        detections,
        video=video,
        frame_width=frame_width,
        frame_height=frame_height,
        line=line,
        source_key=source_key,
        frame_token=frame_token,
    )
    if not style:
        return None
    key = style.get("ruleKey") or ""
    if key == "fire-smoke":
        return "fire"
    if key == "crowd-gathering":
        return "crowd"
    if key == "ppe-no-hardhat":
        return "ppe"
    if key == "line-intrusion":
        return "intrusion"
    if key == "zone-intrusion":
        return "zone"
    return "generic"


def evaluate_rules(
    rules: list,
    detections: list[dict],
    source_key: str,
    *,
    persist_event=None,
    now_ts: float | None = None,
    frame_width: float | None = None,
    frame_height: float | None = None,
    line: list | None = None,
    region: list | None = None,
    frame_token: str | None = None,
) -> list[dict]:
    """评估规则列表；满足连续帧 + 冷却则触发并可选持久化。"""
    now = float(now_ts) if now_ts is not None else time.time()
    triggered = []
    src = source_key or "default"
    eval_ctx = {
        "source_key": src,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "line": line,
        "region": region,
        "frame_token": frame_token,
        "now_ts": now,
    }

    for rule in rules:
        status = rule.status if hasattr(rule, "status") else rule.get("status", "0")
        if status != "0":
            continue
        rid = rule.id if hasattr(rule, "id") else rule.get("id")
        cfg = rule.config() if hasattr(rule, "config") else (rule.get("config") or {})
        rtype = rule.rule_type if hasattr(rule, "rule_type") else rule.get("ruleType")
        # 越线/区域越界/陌生人：瞬时或低频事件，默认连续 1～2 帧
        if rtype in ("line_crossing", "zone_crossing"):
            default_consec = 1
        elif rtype == "unmatched_face":
            default_consec = 2
        else:
            default_consec = 2
        consecutive = int(cfg.get("consecutive_frames", cfg.get("consecutiveFrames", default_consec)))
        cooldown = float(cfg.get("cooldown_sec", cfg.get("cooldownSec", 30)))

        detail = _condition_met(rule, detections, eval_ctx)
        key = (rid, src)

        with _lock:
            st = _runtime.setdefault(
                key, {"streak": 0, "last_fire_ts": 0.0, "centroids": {}, "crossed": set()}
            )
            if detail:
                st["streak"] += 1
            else:
                st["streak"] = 0
                continue

            if st["streak"] < consecutive:
                continue
            if now - st["last_fire_ts"] < cooldown:
                continue
            st["last_fire_ts"] = now
            st["streak"] = 0

        title, message = _title_message(rule, detail)
        item = {
            "ruleId": rid,
            "ruleKey": rule.rule_key if hasattr(rule, "rule_key") else rule.get("ruleKey"),
            "ruleName": rule.name if hasattr(rule, "name") else rule.get("name"),
            "severity": rule.severity if hasattr(rule, "severity") else rule.get("severity", "medium"),
            "title": title,
            "message": message,
            "detail": detail,
            "overlay": resolve_overlay_style(rule),
            "notify": True,
        }
        if persist_event:
            ev = persist_event(rule, title, message, detail)
            if ev:
                item["eventId"] = ev.get("id")
                item.update({k: ev[k] for k in ("createTime",) if k in ev})
        triggered.append(item)

    return triggered


def reset_runtime(source_key: str | None = None):
    """测试或停止检测时清状态。"""
    with _lock:
        if source_key is None:
            _runtime.clear()
            return
        keys = [k for k in _runtime if k[1] == source_key]
        for k in keys:
            del _runtime[k]
