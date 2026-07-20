"""羽毛球分析结果报告：球员对比、技战术指标、热区/落点、AI 洞察与训练建议。

指标由姿态球场坐标、移动距离/速度、回合与羽毛球检测等真实数据推导；
无击球分类模型时，「技术使用」以场地分区占用作为可解释代理。
"""
from __future__ import annotations

import math
from collections import defaultdict


COURT_W_M = 5.18
COURT_L_M = 13.4


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, int(round(v))))


def _zone_of(y_m: float) -> str:
    """沿球场长轴分区：前场 / 中场 / 后场（相对本半场）。"""
    # 0..L：半场中点 COURT_L_M/2 为网
    half = COURT_L_M / 2
    # 归一到「离网距离」在半场内的比例
    if y_m <= half:
        d = half - y_m  # 上场：网在 half，底线在 0
        ratio = d / half if half else 0
    else:
        d = y_m - half
        ratio = d / half if half else 0
    if ratio < 0.33:
        return "front"
    if ratio < 0.66:
        return "mid"
    return "back"


def _side_of(y_m: float) -> int:
    """0=上场(远端)，1=下场(近端)。"""
    return 0 if y_m < COURT_L_M / 2 else 1


def net_mids_from_corners(img_pts):
    """球场四角 TL,TR,BR,BL → 网线端点：左边中点 (TL+BL)/2，右边中点 (TR+BR)/2。"""
    pts = list(img_pts)
    if len(pts) < 4:
        return None, None
    tl, tr, br, bl = [tuple(map(float, p[:2])) for p in pts[:4]]
    left = ((tl[0] + bl[0]) * 0.5, (tl[1] + bl[1]) * 0.5)
    right = ((tr[0] + br[0]) * 0.5, (tr[1] + br[1]) * 0.5)
    return left, right


def side_of_net_img(ix, iy, left_mid, right_mid) -> int:
    """图像坐标相对网线的半场：0=上场(远端/TL 侧)，1=下场(近端/BL 侧)。

    网线从左边中点走向右边中点；叉积符号区分上下半场。
    """
    ax, ay = left_mid
    bx, by = right_mid
    cross = (bx - ax) * (float(iy) - ay) - (by - ay) * (float(ix) - ax)
    # A→B 近似向右时，cross>0 表示点在网线「下方」(图像 y 更大)=近端
    return 1 if cross >= 0 else 0


def _penetration_m(y_m: float, side: int) -> float:
    """进入接球方半场的深度（米，越大越靠近该侧底线）。"""
    half = COURT_L_M * 0.5
    if side == 0:
        return half - float(y_m)
    return float(y_m) - half


def _track_speed(track, i: int, fps: float) -> float:
    """球场坐标瞬时速度 m/s。"""
    if i <= 0 or i >= len(track) or fps <= 0:
        return 0.0
    a, b = track[i - 1], track[i]
    dt = (int(b.get("frame", i)) - int(a.get("frame", i - 1))) / fps
    if dt <= 1e-6:
        return 0.0
    return math.hypot(float(b["x"]) - float(a["x"]), float(b["y"]) - float(a["y"])) / dt


def extract_shot_landings(shuttle_track, img_pts, fps: float = 25.0, net_pts=None,
                          total_frames: int = None) -> list:
    """提取真正「球落地」点（死球落点），对齐正式比赛语义。

    注意：回合中的每次过网/击球落点 ≠ 球落地。旧逻辑把过网最深点都当成落点，
    会在单回合连续对打中产生大量虚假落点（且常偏一侧）。

    新规则：
      1) 将球轨迹按短间隙切成飞行段；
      2) 仅当段落后有足够长失检（≈ 落地后球静止/被捡走）才记一次落地；
      3) 取该段末尾附近的减速点或末点作为落点坐标，半场按网线归属；
      4) 视频结束时末段若呈减速深入半场，也可记一次；
      5) 两次落点至少间隔约 2s（一场连续对打不可能频密落地）。
    """
    if not shuttle_track or not img_pts:
        return []
    if net_pts is not None and len(net_pts) >= 2:
        left_mid = (float(net_pts[0][0]), float(net_pts[0][1]))
        right_mid = (float(net_pts[1][0]), float(net_pts[1][1]))
    else:
        left_mid, right_mid = net_mids_from_corners(img_pts)
    if left_mid is None:
        return []

    fps = float(fps or 25.0)
    # 短间隙：对打中丢检，仍属同一飞行过程
    gap_frames = max(3, int(fps * 0.35))
    # 长失检：更像落地/死球后球不再飞
    land_silence = max(int(fps * 1.8), gap_frames + 8)
    min_seg_pts = max(3, int(fps * 0.12))
    min_pen = 0.5
    min_land_gap_frames = max(int(fps * 2.0), 20)
    landings = []

    def _emit(pt, side: int, kind: str):
        pen = _penetration_m(pt["y"], side)
        if pen < min_pen:
            return False
        if landings:
            last = landings[-1]
            if int(pt.get("frame", 0)) - int(last.get("frame", 0)) < min_land_gap_frames:
                return False
            if math.hypot(last["x"] - float(pt["x"]), last["y"] - float(pt["y"])) < 0.55:
                return False
        landings.append({
            "x": round(float(pt["x"]), 3),
            "y": round(float(pt["y"]), 3),
            "player": "p1" if side == 0 else "p2",
            "frame": int(pt.get("frame", 0)),
            "kind": kind,
            "penetration": round(pen, 3),
        })
        return True

    # 规范化轨迹点
    pts = []
    for raw in shuttle_track:
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            x, y = float(raw[0]), float(raw[1])
            half = COURT_L_M * 0.5
            pts.append({
                "frame": len(pts) + 1,
                "x": x, "y": y,
                "ix": x, "iy": y,
                "_side": 0 if y < half else 1,
            })
            continue
        ix = raw.get("ix", raw.get("image_x"))
        iy = raw.get("iy", raw.get("image_y"))
        x = float(raw.get("x", raw.get("court_x", 0)))
        y = float(raw.get("y", raw.get("court_y", 0)))
        if ix is None or iy is None:
            side = _side_of(y)
        else:
            side = side_of_net_img(ix, iy, left_mid, right_mid)
        pts.append({
            "frame": int(raw.get("frame", len(pts) + 1)),
            "x": x, "y": y,
            "ix": float(ix) if ix is not None else x,
            "iy": float(iy) if iy is not None else y,
            "_side": side,
        })

    if len(pts) < 2:
        return landings

    # 分段：帧间隙过大则切断
    segments = []
    cur = [pts[0]]
    for p in pts[1:]:
        if int(p["frame"]) - int(cur[-1]["frame"]) > gap_frames:
            segments.append(cur)
            cur = [p]
        else:
            cur.append(p)
    segments.append(cur)

    end_frame = int(total_frames) if total_frames else int(pts[-1]["frame"])

    def _pick_landing_point(seg):
        """段末优先取减速点，否则取末点。"""
        if len(seg) < 2:
            return seg[-1]
        # 从后往前找减速
        for k in range(len(seg) - 1, 1, -1):
            v_prev = _track_speed(seg, k - 1, fps)
            v_now = _track_speed(seg, k, fps)
            if v_prev >= 2.5 and v_now <= max(1.0, v_prev * 0.45):
                return seg[k]
        # 末尾窗口内取穿深最大（更接近半场深处落地）
        tail = seg[-min(len(seg), max(3, int(fps * 0.25))):]
        return max(tail, key=lambda p: _penetration_m(p["y"], p["_side"]))

    def _seg_looks_landed(seg):
        if len(seg) < min_seg_pts:
            return False
        tip = _pick_landing_point(seg)
        if _penetration_m(tip["y"], tip["_side"]) < min_pen:
            return False
        # 末段速度不应仍是高速穿场
        v_end = _track_speed(seg, len(seg) - 1, fps)
        return v_end <= 8.0

    for i, seg in enumerate(segments):
        if len(seg) < min_seg_pts:
            continue
        seg_end_f = int(seg[-1]["frame"])
        if i + 1 < len(segments):
            silence = int(segments[i + 1][0]["frame"]) - seg_end_f
            is_terminal = silence >= land_silence
            kind = "ground_gap"
        else:
            # 末段：视频结束后仍有静默，或末段本身像落地
            silence = max(0, end_frame - seg_end_f)
            is_terminal = silence >= land_silence or (
                silence <= max(2, int(fps * 0.4)) and _seg_looks_landed(seg)
            )
            kind = "ground_end"

        if not is_terminal:
            continue
        if not _seg_looks_landed(seg):
            continue
        tip = _pick_landing_point(seg)
        _emit(tip, tip["_side"], kind)

    return landings


def _pct(part, total):
    if not total:
        return 0
    return round(100.0 * part / total, 1)


def _fmt_duration(seconds: float) -> str:
    s = max(0, int(seconds))
    m, sec = divmod(s, 60)
    return f"{m}:{sec:02d}"


def _player_metrics(tid, dist, max_speed, positions, active_frames, fps):
    zones = {"front": 0, "mid": 0, "back": 0}
    left = right = 0
    for x, y in positions:
        zones[_zone_of(y)] += 1
        if x < COURT_W_M / 2:
            left += 1
        else:
            right += 1
    n = len(positions) or 1
    front_r = zones["front"] / n
    mid_r = zones["mid"] / n
    back_r = zones["back"] / n
    # 综合评分：移动覆盖 + 峰值速度 + 前场参与
    score = (
        min(40.0, (dist or 0) * 1.1)
        + min(35.0, (max_speed or 0) * 8.0)
        + front_r * 25.0
    )
    avg_speed = (dist / (active_frames / fps)) if active_frames and fps > 0 else 0.0
    return {
        "tid": tid,
        "score": _clamp(score),
        "distance": round(float(dist or 0), 2),
        "maxSpeed": round(float(max_speed or 0), 2),
        "maxSpeedKmh": round(float(max_speed or 0) * 3.6, 2),
        "avgSpeed": round(avg_speed, 2),
        "activeFrames": int(active_frames or 0),
        "zoneRatio": {
            "front": round(front_r * 100, 1),
            "mid": round(mid_r * 100, 1),
            "back": round(back_r * 100, 1),
        },
        "lateral": {
            "left": _pct(left, n),
            "right": _pct(right, n),
        },
        "positions": [{"x": round(x, 3), "y": round(y, 3)} for x, y in positions[:: max(1, len(positions) // 80)]],
    }


def _dimension_scores(p: dict) -> dict:
    zr = p["zoneRatio"]
    # 0–100 代理维度
    attack = _clamp(zr["front"] * 0.55 + min(45, p["maxSpeed"] * 10))
    defense = _clamp(zr["mid"] * 0.7 + min(30, p["distance"] * 0.8))
    net = _clamp(zr["front"] * 0.95)
    rear = _clamp(zr["back"] * 0.9 + min(20, p["distance"] * 0.4))
    return {
        "进攻压迫": attack,
        "防守稳定": defense,
        "网前控制": net,
        "后场调动": rear,
    }


def _build_insights(p1, p2, dims1, dims2, rally_count, avg_rally_shots, shuttle_n):
    insights = []
    if dims1["网前控制"] >= dims2["网前控制"] + 8:
        insights.append({
            "tone": "primary",
            "title": f"P1 网前优势显著",
            "text": (
                f"前场活动占比 {p1['zoneRatio']['front']}%，"
                f"网前控制评分 {dims1['网前控制']}（P2 为 {dims2['网前控制']}）。"
                "建议继续抢高点、限制对手起球。"
            ),
        })
    elif dims2["网前控制"] >= dims1["网前控制"] + 8:
        insights.append({
            "tone": "orange",
            "title": "P2 网前更主动",
            "text": (
                f"P2 前场占比 {p2['zoneRatio']['front']}%，"
                f"网前评分 {dims2['网前控制']}。P1 可加强网前封网与搓放练习。"
            ),
        })

    weak = None
    if p1["lateral"]["right"] < 35 and p1["zoneRatio"]["back"] > 30:
        weak = ("P1", "右后场")
    elif p2["lateral"]["right"] < 35 and p2["zoneRatio"]["back"] > 30:
        weak = ("P2", "右后场")
    elif p1["lateral"]["left"] < 35 and p1["zoneRatio"]["back"] > 30:
        weak = ("P1", "左后场")
    elif p2["lateral"]["left"] < 35 and p2["zoneRatio"]["back"] > 30:
        weak = ("P2", "左后场")
    if weak:
        insights.append({
            "tone": "orange",
            "title": f"{weak[0]} {weak[1]}覆盖偏弱",
            "text": (
                f"该侧活动占比偏低，后场占比 {p1['zoneRatio']['back'] if weak[0]=='P1' else p2['zoneRatio']['back']}%。"
                "被调动后回中心与二次启动值得专项强化。"
            ),
        })

    if avg_rally_shots >= 6:
        insights.append({
            "tone": "green",
            "title": "多拍相持能力较好",
            "text": (
                f"平均约 {avg_rally_shots:.1f} 拍/回合（估算），共 {rally_count} 个回合；"
                f"羽毛球有效检出 {shuttle_n} 帧。可针对性练 9 拍后的进攻转换。"
            ),
        })
    elif rally_count > 0:
        insights.append({
            "tone": "green",
            "title": "回合偏短，节奏切换快",
            "text": (
                f"共 {rally_count} 个回合，平均约 {avg_rally_shots:.1f} 拍。"
                "可增加高远过渡与多拍耐训，避免过早失误。"
            ),
        })

    if not insights:
        insights.append({
            "tone": "primary",
            "title": "双方移动数据已采集",
            "text": "建议结合标注视频复核关键分拍，并在后续训练中针对性补短板。",
        })
    return insights[:3]


def _build_coach_tips(p1, p2, dims1, dims2, adv_label):
    tips = []
    # 优先：较弱维度
    weak_dim = min(dims1.items(), key=lambda x: x[1])
    tips.append({
        "level": "01 · 优先提升",
        "tone": "primary",
        "title": f"{adv_label if dims1[weak_dim[0]] <= dims2[weak_dim[0]] else '双方'} · {weak_dim[0]}",
        "text": (
            f"本场「{weak_dim[0]}」评分偏低（P1 {dims1[weak_dim[0]]} / P2 {dims2[weak_dim[0]]}）。"
            "建议 6 点米字步 + 半场多球，每组 45 秒×6 组，强调回中后的二次启动。"
        ),
    })
    tips.append({
        "level": "02 · 战术强化",
        "tone": "orange",
        "title": "网前抢点 + 推后场",
        "text": (
            f"利用前场活跃方（P1 前场 {p1['zoneRatio']['front']}% / "
            f"P2 {p2['zoneRatio']['front']}%）做勾对角后的直线推扑，限制对手反攻。"
        ),
    })
    tips.append({
        "level": "03 · 体能保持",
        "tone": "green",
        "title": "多拍节奏耐力",
        "text": (
            f"峰值速度 P1 {p1['maxSpeedKmh']} / P2 {p2['maxSpeedKmh']} km/h。"
            "采用 12 拍以上限制训练，目标末段击球质量保持率不低于 85%。"
        ),
    })
    return tips


def _tech_proxy(p1, p2):
    """无击球分类时，用双方前/中/后场占用合成技术分布代理。"""
    f = (p1["zoneRatio"]["front"] + p2["zoneRatio"]["front"]) / 2
    m = (p1["zoneRatio"]["mid"] + p2["zoneRatio"]["mid"]) / 2
    b = (p1["zoneRatio"]["back"] + p2["zoneRatio"]["back"]) / 2
    # 归一到约 100
    raw = [
        ("杀球/突击（代理：高速后场）", b * 0.45 + min(20, (p1["maxSpeed"] + p2["maxSpeed"]) * 2)),
        ("高远球（代理：后场）", b * 0.55),
        ("吊球（代理：中后过渡）", m * 0.5 + b * 0.15),
        ("网前球（代理：前场）", f * 0.9),
        ("其他/相持", m * 0.45),
    ]
    total = sum(v for _, v in raw) or 1
    shots = [{"label": k, "value": round(100 * v / total, 1)} for k, v in raw]
    attack_share = round(shots[0]["value"] + shots[3]["value"] * 0.35, 1)
    return shots, attack_share


def build_match_report(
    *,
    frames: int,
    fps: float,
    rally_count: int,
    shuttle_frames: int,
    total_persons: int,
    player_distances: dict,
    player_max_speed: dict,
    player_states: dict,
    court_pos_by_tid: dict,
    shuttle_court_list: list,
    rally_lengths: list,
    final_slot_map: dict,
    source_name: str = "",
    model_key: str = "",
    court_img_pts=None,
    net_img_pts=None,
    shuttle_track=None,
) -> dict:
    """生成前端分析结果仪表盘所需结构化报告。"""
    fps = float(fps or 25.0)
    duration_sec = frames / fps if fps > 0 else 0.0
    effective_sec = shuttle_frames / fps if fps > 0 else 0.0

    # tid -> slot（上场 0 / 下场 1）；缺省按 Y 中位数推断
    tid_slot = dict(final_slot_map or {})
    for tid, pts in court_pos_by_tid.items():
        if tid in tid_slot or not pts:
            continue
        ys = [y for _, y in pts]
        tid_slot[tid] = _side_of(sum(ys) / len(ys))

    # 每半场选活跃 tid（距离最大）
    slot_best = {}
    for tid, slot in tid_slot.items():
        dist = float(player_distances.get(tid, player_distances.get(str(tid), 0)) or 0)
        prev = slot_best.get(slot)
        if prev is None or dist > prev[1]:
            slot_best[slot] = (tid, dist)

    def _pick(slot, fallback_label):
        if slot in slot_best:
            tid = slot_best[slot][0]
        else:
            # 任意剩余
            for t in court_pos_by_tid:
                if t not in [slot_best.get(0, (None,))[0], slot_best.get(1, (None,))[0]]:
                    tid = t
                    break
            else:
                tid = next(iter(court_pos_by_tid), None)
        if tid is None:
            return {
                "label": fallback_label,
                "tid": None,
                "score": 0,
                "distance": 0,
                "maxSpeed": 0,
                "maxSpeedKmh": 0,
                "avgSpeed": 0,
                "zoneRatio": {"front": 0, "mid": 0, "back": 0},
                "lateral": {"left": 50, "right": 50},
                "positions": [],
                "advantage": False,
            }
        st = player_states.get(tid) or {}
        dist = float(player_distances.get(tid, player_distances.get(str(tid), st.get("total_dist", 0))) or 0)
        spd = float(player_max_speed.get(tid, player_max_speed.get(str(tid), st.get("max_speed_total", 0))) or 0)
        m = _player_metrics(tid, dist, spd, court_pos_by_tid.get(tid, []), st.get("active_frames", 0), fps)
        m["label"] = fallback_label
        return m

    p1 = _pick(0, "球员 P1")
    p2 = _pick(1, "球员 P2")
    dims1 = _dimension_scores(p1)
    dims2 = _dimension_scores(p2)
    dimensions = [
        {"label": k, "p1": dims1[k], "p2": dims2[k]} for k in dims1
    ]

    adv = "P1" if p1["score"] >= p2["score"] else "P2"
    adv_style = "进攻主导" if (dims1 if adv == "P1" else dims2)["进攻压迫"] >= 70 else "综合均衡"
    p1["advantage"] = adv == "P1"
    p2["advantage"] = adv == "P2"
    overall = _clamp((p1["score"] + p2["score"]) / 2 + 5)

    avg_rally_frames = (sum(rally_lengths) / len(rally_lengths)) if rally_lengths else 0
    # 粗估拍数：约每 0.55s 一拍
    avg_rally_shots = (avg_rally_frames / fps / 0.55) if fps > 0 and avg_rally_frames else 0
    max_rally_shots = max((lf / fps / 0.55) for lf in rally_lengths) if rally_lengths and fps else 0

    total_dist = p1["distance"] + p2["distance"]
    dist_note = (
        f"P2 多移动 {abs(p2['distance'] - p1['distance']) / max(p1['distance'], 1e-6) * 100:.1f}%"
        if p2["distance"] >= p1["distance"]
        else f"P1 多移动 {abs(p1['distance'] - p2['distance']) / max(p2['distance'], 1e-6) * 100:.1f}%"
    )

    metrics = [
        {
            "label": "比赛时长",
            "value": _fmt_duration(duration_sec),
            "unit": "",
            "note": f"有效检出约 {_fmt_duration(effective_sec)}",
        },
        {
            "label": "总回合数",
            "value": str(int(rally_count or 0)),
            "unit": "回合",
            "note": f"最长约 {max_rally_shots:.0f} 拍" if max_rally_shots else "发球至死球为一回合",
        },
        {
            "label": "平均回合",
            "value": f"{avg_rally_shots:.1f}",
            "unit": "拍",
            "note": "由回合时长估算",
        },
        {
            "label": "总移动距离",
            "value": f"{total_dist:.1f}",
            "unit": "m",
            "note": dist_note if total_dist else "暂无移动数据",
        },
    ]

    shots, attack_share = _tech_proxy(p1, p2)
    insights = _build_insights(p1, p2, dims1, dims2, rally_count, avg_rally_shots, shuttle_frames)
    tips = _build_coach_tips(p1, p2, dims1, dims2, adv)

    # 球落地：仅死球落点（长失检/视频末落地），非每次过网
    track = shuttle_track if shuttle_track is not None else shuttle_court_list
    landings = []
    if track and court_img_pts is not None:
        landings = extract_shot_landings(
            track, court_img_pts, fps=fps, net_pts=net_img_pts, total_frames=frames)
    elif track:
        # 无四角时退化为球场中线半场 + 落地提取
        fake_corners = [
            (0.0, 0.0), (COURT_W_M, 0.0),
            (COURT_W_M, COURT_L_M), (0.0, COURT_L_M),
        ]
        landings = extract_shot_landings(
            track, fake_corners, fps=fps, net_pts=net_img_pts, total_frames=frames)
    if not landings and not track:
        for pl, tone in ((p1, "p1"), (p2, "p2")):
            for pt in (pl.get("positions") or [])[:: max(1, len(pl.get("positions") or [1]) // 20)]:
                landings.append({"x": pt["x"], "y": pt["y"], "player": tone, "kind": "player_proxy"})

    edge = sum(1 for L in landings if L["x"] < COURT_W_M * 0.18 or L["x"] > COURT_W_M * 0.82)
    edge_util = _pct(edge, len(landings) or 1)

    # 热区：按网格统计密度点（百分比定位，供前端 CSS 渲染）
    heat_cells = defaultdict(int)
    for tid, pts in court_pos_by_tid.items():
        for x, y in pts:
            gx = min(7, max(0, int(x / COURT_W_M * 8)))
            gy = min(9, max(0, int(y / COURT_L_M * 10)))
            heat_cells[(gx, gy)] += 1
    if heat_cells:
        mx = max(heat_cells.values())
        heat_dots = [
            {
                "left": round((gx + 0.5) / 8 * 100, 1),
                "top": round((gy + 0.5) / 10 * 100, 1),
                "level": "high" if c >= mx * 0.66 else ("mid" if c >= mx * 0.33 else "low"),
            }
            for (gx, gy), c in sorted(heat_cells.items(), key=lambda x: -x[1])[:12]
        ]
    else:
        heat_dots = []

    conf = 0.0
    if frames > 0:
        conf = min(99.5, 70 + (shuttle_frames / frames) * 20 + min(10, rally_count) * 0.5)

    return {
        "title": f"{p1['label']} 对阵 {p2['label']} · 技战术分析报告",
        "subtitle": (
            f"{source_name or '比赛视频'} · 时长 {_fmt_duration(duration_sec)} · "
            f"模型 {model_key or 'pose'}"
        ),
        "overallScore": overall,
        "advantage": {"label": adv, "style": adv_style},
        "confidence": round(conf, 1),
        "metrics": metrics,
        "players": [p1, p2],
        "dimensions": dimensions,
        "insights": insights,
        "coachTips": tips,
        "shots": shots,
        "attackShare": attack_share,
        "heatDots": heat_dots,
        "landings": landings,
        "landingCount": len(landings),
        "shuttleDetectionCount": int(shuttle_frames or 0),
        "edgeUtilization": edge_util,
        "summary": {
            "frames": frames,
            "fps": round(fps, 2),
            "rallyCount": rally_count,
            "shuttleDetections": shuttle_frames,
            "totalPersons": total_persons,
        },
    }
