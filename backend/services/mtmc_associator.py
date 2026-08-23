"""在线 MTMC 关联器（McByte++ 解耦风格）。

职责分层（对齐 McByte++）：
1. 短时：local_track_id 粘性续接 —— 不开放外观匹配（检测+Kalman/IoU/ByteTrack 负责）
2. 长时：仅「新生」local track 才用 OSNet/外观/车牌去复活「已丢失」Global，或跨镜关联
3. 同帧互斥：exclude_gids 保证一对一
4. Mask/CMC：在局部跟踪器层处理，本模块不参与短时代价矩阵

参考：arXiv:2608.15688 McByte++；项目 docs 与 mtmc_local_track。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

import numpy as np

_INVALID_IDENTITY_KEYS = frozenset({"", "UNKNOWN|U", "UNKNOWN", "NONE", "NULL"})


class AssocMode(str, Enum):
    """本次 associate 实际走的路径（便于日志/调试）。"""
    STICKY = "sticky"              # 短时：粘性续接，无外观匹配
    LONG_TERM = "long_term"        # 长时：新生 track 复活丢失 / 跨镜外观
    CANDIDATE = "candidate"        # 三档中间态：暂存候选，precision-first 不合并
    NEW = "new"                    # 新建 Global


def _l2(v: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(a))
    return a if n < eps else a / n


def _cos(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return -1.0
    x, y = _l2(a), _l2(b)
    dim = max(x.size, y.size)
    xa = np.zeros(dim, dtype=np.float32)
    ya = np.zeros(dim, dtype=np.float32)
    xa[: x.size] = x
    ya[: y.size] = y
    return float(np.dot(xa, ya))


def _valid_identity_key(key: str | None) -> str | None:
    if not key:
        return None
    k = str(key).strip()
    if not k or k.upper() in _INVALID_IDENTITY_KEYS or k in _INVALID_IDENTITY_KEYS:
        return None
    return k


@dataclass
class GlobalTrack:
    global_id: str
    object_type: str  # person|vehicle
    embedding: np.ndarray | None = None
    camera_id: int | None = None
    last_seen: float = field(default_factory=time.time)
    first_seen: float = field(default_factory=time.time)
    # 上次从「活跃」变为「丢失」的时间（局部轨迹消失时写入）
    lost_at: float | None = None
    reid_person_id: int | None = None
    face_person_id: int | None = None
    display_name: str | None = None
    plate: str | None = None
    identity_key: str | None = None
    visual_key: str | None = None
    hit_count: int = 1
    trail_by_cam: dict[int, list] = field(default_factory=dict)
    local_track_id: int | None = None
    last_assoc_mode: str = AssocMode.NEW.value


@dataclass
class AssocEvidence:
    """单次 associate 的决策证据（供 association_edge 落库）。"""
    decision: str
    target_global_id: str
    source_global_id: str | None = None
    candidate_global_id: str | None = None
    reid_score: float | None = None
    topology_score: float | None = None
    time_score: float | None = None
    final_score: float | None = None
    policy_version: str = "mtmc_v2"
    extra: dict = field(default_factory=dict)

    def to_scores(self) -> dict:
        return {
            "reid": self.reid_score,
            "topology": self.topology_score,
            "time": self.time_score,
            "final": self.final_score,
        }

    def to_dict(self) -> dict:
        d = self.to_scores()
        d.update(self.extra or {})
        d["decision"] = self.decision
        d["targetGlobalId"] = self.target_global_id
        d["sourceGlobalId"] = self.source_global_id
        d["candidateGlobalId"] = self.candidate_global_id
        d["policyVersion"] = self.policy_version
        return d


class MtmcAssociator:
    """跨摄像头全局关联（McByte++：短时粘性 / 长时选择性 ReID）。"""

    def __init__(
        self,
        *,
        appear_thresh: float = 0.48,
        vehicle_appear_thresh: float | None = None,
        time_window_sec: float = 90.0,
        topology: dict[tuple[int, int], tuple[float, float]] | None = None,
        same_cam_reuse: bool = True,
        # 同镜上 Global 视为「仍占用」的最短间隔（同帧互斥）
        same_cam_min_gap: float = 0.45,
        # 同镜「丢失」后才允许外观复活的最小间隔（McByte++ 长时门控）
        lost_revive_sec: float = 1.0,
        local_sticky_sec: float = 20.0,
        same_cam_appear_thresh: float | None = None,
        # True：严格 McByte++ —— 无粘性时只用外观匹配「丢失/跨镜」目标；禁止抢占同镜活跃 Global
        mcbyte_decouple: bool = True,
        confirm_thresh: float | None = None,
        candidate_thresh: float | None = None,
        use_faiss_gallery: bool = True,
        gallery_model_key: str | None = None,
    ):
        self.appear_thresh = float(appear_thresh)
        self.vehicle_appear_thresh = float(
            vehicle_appear_thresh if vehicle_appear_thresh is not None else appear_thresh
        )
        self.confirm_thresh = float(
            confirm_thresh if confirm_thresh is not None else appear_thresh
        )
        self.candidate_thresh = float(
            candidate_thresh
            if candidate_thresh is not None
            else max(0.2, float(appear_thresh) * 0.82)
        )
        self.use_faiss_gallery = bool(use_faiss_gallery)
        self.same_cam_appear_thresh = float(
            same_cam_appear_thresh if same_cam_appear_thresh is not None else min(0.72, appear_thresh + 0.2)
        )
        self.time_window_sec = float(time_window_sec)
        self.topology = topology or {}
        self.same_cam_reuse = bool(same_cam_reuse)
        self.same_cam_min_gap = float(same_cam_min_gap)
        self.lost_revive_sec = float(lost_revive_sec)
        self.local_sticky_sec = float(local_sticky_sec)
        self.mcbyte_decouple = bool(mcbyte_decouple)
        self._lock = threading.Lock()
        self.tracks: dict[str, GlobalTrack] = {}
        # (object_type, camera_id, local_track_id) -> global_id
        self._local_bind: dict[tuple[str, int, int], str] = {}
        self._seq = 0
        self.last_mode: AssocMode = AssocMode.NEW
        self.last_evidence: AssocEvidence | None = None
        from services.mtmc_active_gallery import MtmcActiveGallery

        self._gallery = MtmcActiveGallery()
        self._candidates: list[dict] = []

    def _gallery_upsert(self, g: GlobalTrack) -> None:
        if g.embedding is not None:
            self._gallery.upsert(g.object_type, g.global_id, g.embedding)

    def _gallery_remove(self, object_type: str, global_id: str) -> None:
        self._gallery.remove(object_type, global_id)

    def _hard_conflict(
        self,
        object_type: str,
        *,
        plate: str | None,
        identity_key: str | None,
        target: GlobalTrack,
    ) -> bool:
        """硬冲突：高置信车牌不一致时拒绝合并。

        NOPLATE|* 仅为无牌视觉代理，跨视角 hash 必然不同，不得视为冲突。
        """
        if object_type != "vehicle":
            return False
        ik = _valid_identity_key(identity_key)
        g_ik = _valid_identity_key(target.identity_key)
        if ik and g_ik and ik != g_ik:
            if ik.startswith("NOPLATE|") or g_ik.startswith("NOPLATE|"):
                pass
            else:
                p1 = ik.split("|", 1)[0]
                p2 = g_ik.split("|", 1)[0]
                if p1 != p2:
                    return True
        p = (plate or "").strip().upper()
        gp = (target.plate or "").strip().upper()
        if p and gp and p != gp and p not in _INVALID_IDENTITY_KEYS and gp not in _INVALID_IDENTITY_KEYS:
            return True
        return False

    def _iter_long_term_targets(
        self,
        object_type: str,
        embedding: np.ndarray | None,
        excluded: set[str],
        *,
        reid_person_id: int | None = None,
        plate: str | None = None,
        identity_key: str | None = None,
    ):
        seen: set[str] = set()
        plate_norm = (plate or "").strip().upper()
        if plate_norm:
            for gid, g in self.tracks.items():
                if gid in excluded or g.object_type != object_type:
                    continue
                gp = (g.plate or "").strip().upper()
                if gp and gp == plate_norm:
                    seen.add(gid)
                    yield g
        has_id_signal = bool(
            reid_person_id
            or plate_norm
            or (
                _valid_identity_key(identity_key)
                and not str(identity_key).startswith("NOPLATE|")
            )
        )
        if (
            not has_id_signal
            and self.use_faiss_gallery
            and embedding is not None
            and self._gallery.faiss_available()
            and self._gallery.size(object_type) > 0
        ):
            for gid, _sim in self._gallery.search(object_type, embedding, topk=50):
                if gid in excluded or gid in seen:
                    continue
                g = self.tracks.get(gid)
                if g is None or g.object_type != object_type:
                    continue
                seen.add(gid)
                yield g
        for gid, g in self.tracks.items():
            if gid in excluded or gid in seen or g.object_type != object_type:
                continue
            yield g

    def _prefer_on_tie(self, g_new: GlobalTrack, g_old: GlobalTrack, camera_id: int) -> bool:
        """同分 tie-break：优先跨镜 Global，避免同镜误建重复 ID 抢占。"""
        if g_new.camera_id != camera_id and g_old.camera_id == camera_id:
            return True
        return False

    def list_candidates(self) -> list[dict]:
        with self._lock:
            return [dict(x) for x in self._candidates[-200:]]

    def get_track(self, global_id: str) -> GlobalTrack | None:
        with self._lock:
            return self.tracks.get(global_id)

    def set_topology(self, edges: list[dict]):
        topo = {}
        for e in edges or []:
            a = int(e.get("fromCameraId") or e.get("from_camera_id") or 0)
            b = int(e.get("toCameraId") or e.get("to_camera_id") or 0)
            if a and b:
                topo[(a, b)] = (
                    float(e.get("minTransitSec") or e.get("min_transit_sec") or 0),
                    float(e.get("maxTransitSec") or e.get("max_transit_sec") or self.time_window_sec),
                )
                topo[(b, a)] = topo[(a, b)]
        with self._lock:
            self.topology = topo

    def _new_gid(self, object_type: str) -> str:
        self._seq += 1
        prefix = "P" if object_type == "person" else "V"
        return f"{prefix}{self._seq:06d}-{uuid.uuid4().hex[:6]}"

    def _time_fit_score(self, prev_cam: int | None, cur_cam: int, dt: float) -> float:
        if prev_cam is None:
            return 1.0
        if prev_cam == cur_cam:
            return 1.0 if dt <= self.time_window_sec else 0.0
        key = (int(prev_cam), int(cur_cam))
        if key in self.topology:
            lo, hi = self.topology[key]
            if dt < lo or dt > hi:
                return 0.0
            mid = (lo + hi) * 0.5
            span = max(hi - lo, 1e-6)
            return float(max(0.0, 1.0 - abs(dt - mid) / span))
        if dt > self.time_window_sec:
            return 0.0
        return 0.55

    def _topology_ok(self, prev_cam: int | None, cur_cam: int, dt: float) -> float:
        if prev_cam is None or prev_cam == cur_cam:
            return 1.0 if dt <= self.time_window_sec else 0.0
        key = (int(prev_cam), int(cur_cam))
        if key in self.topology:
            lo, hi = self.topology[key]
            if dt < lo or dt > hi:
                return 0.0
            return 1.0
        if dt > self.time_window_sec:
            return 0.0
        return 0.55

    def _bind_key(self, object_type: str, camera_id: int, local_track_id: int) -> tuple[str, int, int]:
        return (object_type, int(camera_id), int(local_track_id))

    def peek_sticky(
        self,
        *,
        object_type: str,
        camera_id: int,
        local_track_id: int,
        now: float | None = None,
    ) -> str | None:
        """引擎侧：判断 local 是否已有粘性 Global（可跳过 OSNet 提特征）。"""
        now = float(now if now is not None else time.time())
        with self._lock:
            bkey = self._bind_key(object_type, camera_id, int(local_track_id))
            gid = self._local_bind.get(bkey)
            if not gid:
                return None
            g = self.tracks.get(gid)
            if g is None or g.object_type != object_type:
                return None
            if now - g.last_seen > self.local_sticky_sec:
                return None
            return gid

    def _purge_expired(self, now: float):
        dead = [
            gid for gid, g in self.tracks.items()
            if now - g.last_seen > self.time_window_sec * 2
        ]
        for gid in dead:
            g = self.tracks.pop(gid, None)
            if g is not None:
                self._gallery_remove(g.object_type, gid)
        if dead:
            dead_set = set(dead)
            self._local_bind = {
                k: v for k, v in self._local_bind.items() if v not in dead_set
            }

    def _mark_lost_if_unbound(self, gid: str, now: float):
        g = self.tracks.get(gid)
        if g is None:
            return
        still_bound = any(v == gid for v in self._local_bind.values())
        if not still_bound and g.lost_at is None:
            g.lost_at = now

    def _update_track(
        self,
        g: GlobalTrack,
        *,
        camera_id: int,
        embedding: np.ndarray | None,
        identity_key: str | None,
        plate: str | None,
        reid_person_id: int | None,
        face_person_id: int | None,
        display_name: str | None,
        visual_key: str | None,
        local_track_id: int | None,
        now: float,
        mode: AssocMode,
        update_embedding: bool = True,
    ) -> GlobalTrack:
        g.last_seen = now
        g.camera_id = camera_id
        g.hit_count += 1
        g.lost_at = None  # 复活/续接后清除丢失标记
        g.last_assoc_mode = mode.value
        if local_track_id is not None:
            g.local_track_id = int(local_track_id)
        if update_embedding and embedding is not None:
            if g.embedding is None:
                g.embedding = _l2(embedding)
            else:
                a, b = _l2(g.embedding), _l2(embedding)
                dim = max(a.size, b.size)
                aa = np.zeros(dim, dtype=np.float32)
                bb = np.zeros(dim, dtype=np.float32)
                aa[: a.size] = a
                bb[: b.size] = b
                # 粘性短时：弱更新；长时复活：稍强写入新观测
                alpha = 0.15 if mode == AssocMode.STICKY else 0.35
                g.embedding = _l2((1.0 - alpha) * aa + alpha * bb)
        if reid_person_id:
            g.reid_person_id = reid_person_id
        if face_person_id:
            g.face_person_id = face_person_id
        if display_name:
            g.display_name = display_name
        if plate:
            g.plate = plate
        ik = _valid_identity_key(identity_key)
        if ik:
            g.identity_key = ik
        if visual_key:
            g.visual_key = visual_key
        return g

    def _is_lost_for_revive(self, g: GlobalTrack, camera_id: int, now: float) -> bool:
        """McByte++：仅丢失足够久的身份允许被新生 track 用外观复活。"""
        dt = now - g.last_seen
        if g.camera_id != camera_id:
            # 跨镜：只要拓扑时间窗内，允许长时外观关联（对方相机上可能仍「活跃」）
            return True
        # 同镜：必须已丢失一段时间，禁止抢占仍在画面中的 Global
        if dt < max(self.same_cam_min_gap, self.lost_revive_sec):
            return False
        if g.lost_at is not None and (now - g.lost_at) < self.lost_revive_sec * 0.5:
            # 刚标记丢失，略放宽也可；仍要求 last_seen 间隔够
            pass
        return dt >= self.lost_revive_sec

    def _score_long_term(
        self,
        g: GlobalTrack,
        *,
        object_type: str,
        camera_id: int,
        embedding: np.ndarray | None,
        identity_key: str | None,
        plate: str | None,
        reid_person_id: int | None,
        now: float,
    ) -> tuple[float | None, dict]:
        """仅用于新生 local track 的长时/跨镜外观匹配。返回 (final_score, breakdown)。"""
        dt = now - g.last_seen
        topo_w = self._topology_ok(g.camera_id, camera_id, dt)
        time_w = self._time_fit_score(g.camera_id, camera_id, dt)
        if topo_w <= 0:
            return None, {"topology": topo_w, "time": time_w, "reid": None, "final": None}

        same_cam = g.camera_id == camera_id
        if self.mcbyte_decouple:
            if not self._is_lost_for_revive(g, camera_id, now):
                return None, {"topology": topo_w, "time": time_w, "reid": None, "final": None}
            if same_cam and not self.same_cam_reuse:
                return None, {"topology": topo_w, "time": time_w, "reid": None, "final": None}
        else:
            if same_cam:
                if dt < self.same_cam_min_gap:
                    return None, {"topology": topo_w, "time": time_w, "reid": None, "final": None}
                if not self.same_cam_reuse:
                    return None, {"topology": topo_w, "time": time_w, "reid": None, "final": None}

        appear_need = self.same_cam_appear_thresh if same_cam else self.appear_thresh
        if object_type == "vehicle":
            appear_need = max(appear_need, self.vehicle_appear_thresh)
            if not same_cam:
                appear_need = min(appear_need, max(0.42, self.vehicle_appear_thresh - 0.06))
        if same_cam:
            appear_need = max(appear_need, self.appear_thresh + 0.12)

        score = 0.0
        reid_raw = None
        ik = _valid_identity_key(identity_key)
        g_ik = _valid_identity_key(g.identity_key)

        if object_type == "vehicle":
            if ik and g_ik and ik == g_ik:
                cos = _cos(embedding, g.embedding)
                min_cos = appear_need
                if cos >= 0 and cos < min_cos:
                    return None, {"topology": topo_w, "time": time_w, "reid": cos, "final": None}
                score, reid_raw = 0.99, cos if cos >= 0 else None
            elif plate and g.plate and plate == g.plate:
                cos = _cos(embedding, g.embedding)
                if embedding is not None and g.embedding is not None and cos < appear_need * 0.65:
                    return None, {"topology": topo_w, "time": time_w, "reid": cos, "final": None}
                score, reid_raw = 0.92, cos if cos >= 0 else None
            else:
                reid_raw = _cos(embedding, g.embedding)
                score = reid_raw
                if score < appear_need:
                    return None, {"topology": topo_w, "time": time_w, "reid": reid_raw, "final": None}
        else:
            if reid_person_id and g.reid_person_id and reid_person_id == g.reid_person_id:
                score, reid_raw = 0.99, 1.0
            else:
                reid_raw = _cos(embedding, g.embedding)
                score = reid_raw
                if score < appear_need:
                    return None, {"topology": topo_w, "time": time_w, "reid": reid_raw, "final": None}
        final = float(score * topo_w)
        return final, {
            "reid": reid_raw,
            "topology": topo_w,
            "time": time_w,
            "final": final,
            "candidateGlobalId": g.global_id,
        }

    def associate(
        self,
        *,
        object_type: str,
        camera_id: int,
        embedding: np.ndarray | None,
        identity_key: str | None = None,
        plate: str | None = None,
        reid_person_id: int | None = None,
        face_person_id: int | None = None,
        display_name: str | None = None,
        visual_key: str | None = None,
        local_track_id: int | None = None,
        exclude_gids: Iterable[str] | None = None,
        now: float | None = None,
        force_long_term: bool = False,
    ) -> GlobalTrack:
        """
        McByte++ 路径：
        1) 有粘性 → STICKY（不搜外观）
        2) 新生 local（或 force_long_term）→ 仅对丢失/跨镜 Global 做外观 LONG_TERM
        3) 否则 NEW
        """
        now = float(now if now is not None else time.time())
        excluded = set(exclude_gids or ())
        identity_key = _valid_identity_key(identity_key)

        with self._lock:
            self._purge_expired(now)

            # ---- 1) 短时粘性：Kalman/IoU/ByteTrack 已保证同一 local_id ----
            is_new_local = True
            if local_track_id is not None and not force_long_term:
                bkey = self._bind_key(object_type, camera_id, int(local_track_id))
                sticky_gid = self._local_bind.get(bkey)
                if sticky_gid and sticky_gid not in excluded:
                    g = self.tracks.get(sticky_gid)
                    if g is not None and g.object_type == object_type:
                        if now - g.last_seen <= self.local_sticky_sec:
                            self.last_mode = AssocMode.STICKY
                            self.last_evidence = AssocEvidence(
                                decision=AssocMode.STICKY.value,
                                target_global_id=g.global_id,
                                source_global_id=g.global_id,
                                final_score=1.0,
                            )
                            # 短时不依赖外观；embedding 可空（引擎可跳过 OSNet）
                            self._update_track(
                                g,
                                camera_id=camera_id,
                                embedding=embedding,
                                identity_key=identity_key,
                                plate=plate,
                                reid_person_id=reid_person_id,
                                face_person_id=face_person_id,
                                display_name=display_name,
                                visual_key=visual_key,
                                local_track_id=int(local_track_id),
                                now=now,
                                mode=AssocMode.STICKY,
                                update_embedding=embedding is not None,
                            )
                            self._gallery_upsert(g)
                            return g
                        self._local_bind.pop(bkey, None)
                        self._mark_lost_if_unbound(sticky_gid, now)
                else:
                    # 无绑定 = 新生（或其它相机的新局部轨迹）
                    is_new_local = True
            elif local_track_id is None:
                # 无 local id：只能走长时/新建（兼容旧调用）
                is_new_local = True

            # ---- 2) 长时：仅新生 track 开放外观（OSNet / 车牌）----
            allow_appearance = is_new_local or force_long_term or local_track_id is None
            best_gid = None
            best_score = -1.0
            best_breakdown: dict = {}
            if allow_appearance and (
                embedding is not None
                or _valid_identity_key(identity_key)
                or plate
                or reid_person_id
            ):
                for g in self._iter_long_term_targets(
                    object_type,
                    embedding,
                    excluded,
                    reid_person_id=reid_person_id,
                    plate=plate,
                    identity_key=identity_key,
                ):
                    if self._hard_conflict(
                        object_type,
                        plate=plate,
                        identity_key=identity_key,
                        target=g,
                    ):
                        continue
                    score, breakdown = self._score_long_term(
                        g,
                        object_type=object_type,
                        camera_id=camera_id,
                        embedding=embedding,
                        identity_key=identity_key,
                        plate=plate,
                        reid_person_id=reid_person_id,
                        now=now,
                    )
                    if score is None:
                        continue
                    if score > best_score:
                        best_score = score
                        best_gid = g.global_id
                        best_breakdown = breakdown
                    elif (
                        score == best_score
                        and best_gid is not None
                        and self._prefer_on_tie(g, self.tracks[best_gid], camera_id)
                    ):
                        best_gid = g.global_id
                        best_breakdown = breakdown

            prev_gid = None
            if local_track_id is not None:
                prev_gid = self._local_bind.get(self._bind_key(object_type, camera_id, int(local_track_id)))

            tier = "new"
            candidate_gid = best_gid
            tier_score = (
                best_breakdown.get("reid")
                if best_breakdown.get("reid") is not None
                else best_score
            )
            if best_gid is not None:
                if tier_score >= self.confirm_thresh:
                    tier = "confirm"
                elif tier_score >= self.candidate_thresh:
                    tier = "candidate"
                else:
                    best_gid = None
                    tier = "new"

            if best_gid is not None and tier == "confirm":
                self.last_mode = AssocMode.LONG_TERM
                g = self._update_track(
                    self.tracks[best_gid],
                    camera_id=camera_id,
                    embedding=embedding,
                    identity_key=identity_key,
                    plate=plate,
                    reid_person_id=reid_person_id,
                    face_person_id=face_person_id,
                    display_name=display_name,
                    visual_key=visual_key,
                    local_track_id=int(local_track_id) if local_track_id is not None else None,
                    now=now,
                    mode=AssocMode.LONG_TERM,
                    update_embedding=True,
                )
                self.last_evidence = AssocEvidence(
                    decision=AssocMode.LONG_TERM.value,
                    target_global_id=g.global_id,
                    source_global_id=prev_gid,
                    candidate_global_id=best_breakdown.get("candidateGlobalId"),
                    reid_score=best_breakdown.get("reid"),
                    topology_score=best_breakdown.get("topology"),
                    time_score=best_breakdown.get("time"),
                    final_score=best_breakdown.get("final"),
                )
                self._gallery_upsert(g)
            elif tier == "candidate" and candidate_gid is not None:
                self.last_mode = AssocMode.CANDIDATE
                gid = self._new_gid(object_type)
                g = GlobalTrack(
                    global_id=gid,
                    object_type=object_type,
                    embedding=_l2(embedding) if embedding is not None else None,
                    camera_id=camera_id,
                    last_seen=now,
                    first_seen=now,
                    reid_person_id=reid_person_id,
                    face_person_id=face_person_id,
                    display_name=display_name,
                    plate=plate,
                    identity_key=identity_key,
                    visual_key=visual_key,
                    local_track_id=int(local_track_id) if local_track_id is not None else None,
                    last_assoc_mode=AssocMode.CANDIDATE.value,
                )
                self.tracks[gid] = g
                self._gallery_upsert(g)
                self._candidates.append({
                    "globalId": gid,
                    "candidateGlobalId": candidate_gid,
                    "objectType": object_type,
                    "cameraId": camera_id,
                    "localTrackId": local_track_id,
                    "finalScore": best_score,
                    "reidScore": best_breakdown.get("reid"),
                    "topologyScore": best_breakdown.get("topology"),
                    "timeScore": best_breakdown.get("time"),
                    "ts": now,
                })
                self.last_evidence = AssocEvidence(
                    decision=AssocMode.CANDIDATE.value,
                    target_global_id=g.global_id,
                    source_global_id=prev_gid,
                    candidate_global_id=candidate_gid,
                    reid_score=best_breakdown.get("reid"),
                    topology_score=best_breakdown.get("topology"),
                    time_score=best_breakdown.get("time"),
                    final_score=best_score,
                    extra={"tier": "candidate", "confirmThresh": self.confirm_thresh},
                )
            else:
                self.last_mode = AssocMode.NEW
                gid = self._new_gid(object_type)
                g = GlobalTrack(
                    global_id=gid,
                    object_type=object_type,
                    embedding=_l2(embedding) if embedding is not None else None,
                    camera_id=camera_id,
                    last_seen=now,
                    first_seen=now,
                    reid_person_id=reid_person_id,
                    face_person_id=face_person_id,
                    display_name=display_name,
                    plate=plate,
                    identity_key=identity_key,
                    visual_key=visual_key,
                    local_track_id=int(local_track_id) if local_track_id is not None else None,
                    last_assoc_mode=AssocMode.NEW.value,
                )
                self.tracks[gid] = g
                self._gallery_upsert(g)
                self.last_evidence = AssocEvidence(
                    decision=AssocMode.NEW.value,
                    target_global_id=g.global_id,
                    source_global_id=prev_gid,
                    reid_score=None,
                    topology_score=None,
                    time_score=None,
                    final_score=None,
                )

            if local_track_id is not None:
                self._local_bind[self._bind_key(object_type, camera_id, int(local_track_id))] = g.global_id
            return g

    def merge_globals(self, keep_gid: str, drop_gid: str, now: float | None = None) -> GlobalTrack | None:
        """P2：将 drop_gid 合并进 keep_gid（候选晋升）。"""
        now = float(now if now is not None else time.time())
        with self._lock:
            keep = self.tracks.get(keep_gid)
            drop = self.tracks.get(drop_gid)
            if keep is None or drop is None or keep.object_type != drop.object_type:
                return None
            if drop.embedding is not None:
                if keep.embedding is None:
                    keep.embedding = _l2(drop.embedding)
                else:
                    a, b = _l2(keep.embedding), _l2(drop.embedding)
                    dim = max(a.size, b.size)
                    aa = np.zeros(dim, dtype=np.float32)
                    bb = np.zeros(dim, dtype=np.float32)
                    aa[: a.size] = a
                    bb[: b.size] = b
                    keep.embedding = _l2(0.5 * aa + 0.5 * bb)
            keep.hit_count += int(drop.hit_count or 1)
            if drop.reid_person_id and not keep.reid_person_id:
                keep.reid_person_id = drop.reid_person_id
            if drop.face_person_id and not keep.face_person_id:
                keep.face_person_id = drop.face_person_id
            if drop.display_name and not keep.display_name:
                keep.display_name = drop.display_name
            if drop.plate and not keep.plate:
                keep.plate = drop.plate
            if drop.identity_key and not keep.identity_key:
                keep.identity_key = drop.identity_key
            if drop.visual_key and not keep.visual_key:
                keep.visual_key = drop.visual_key
            keep.last_seen = max(keep.last_seen, drop.last_seen)
            keep.first_seen = min(keep.first_seen, drop.first_seen)
            keep.camera_id = drop.camera_id
            keep.lost_at = None
            keep.last_assoc_mode = AssocMode.LONG_TERM.value
            for k, v in list(self._local_bind.items()):
                if v == drop_gid:
                    self._local_bind[k] = keep_gid
            self._gallery_remove(drop.object_type, drop_gid)
            self.tracks.pop(drop_gid, None)
            self._gallery_upsert(keep)
            self.last_mode = AssocMode.LONG_TERM
            self.last_evidence = AssocEvidence(
                decision="promoted",
                target_global_id=keep_gid,
                source_global_id=drop_gid,
                candidate_global_id=keep_gid,
                policy_version="mtmc_v2",
            )
            return keep

    def release_local(self, object_type: str, camera_id: int, local_track_ids: Iterable[int] | None = None):
        now = time.time()
        with self._lock:
            if local_track_ids is None:
                affected = [
                    v for k, v in self._local_bind.items()
                    if k[0] == object_type and k[1] == int(camera_id)
                ]
                self._local_bind = {
                    k: v for k, v in self._local_bind.items()
                    if not (k[0] == object_type and k[1] == int(camera_id))
                }
            else:
                drop = {int(x) for x in local_track_ids}
                affected = [
                    v for k, v in self._local_bind.items()
                    if k[0] == object_type and k[1] == int(camera_id) and k[2] in drop
                ]
                self._local_bind = {
                    k: v for k, v in self._local_bind.items()
                    if not (k[0] == object_type and k[1] == int(camera_id) and k[2] in drop)
                }
            for gid in affected:
                self._mark_lost_if_unbound(gid, now)

    def prune_inactive_locals(self, object_type: str, camera_id: int, active_local_ids: Iterable[int]):
        """局部轨迹消失 → Global 标记 lost，供后续新生 track 长时复活。"""
        active = {int(x) for x in active_local_ids}
        now = time.time()
        with self._lock:
            removed_gids = []
            keep = {}
            for k, v in self._local_bind.items():
                if k[0] == object_type and k[1] == int(camera_id) and k[2] not in active:
                    removed_gids.append(v)
                    continue
                keep[k] = v
            self._local_bind = keep
            for gid in removed_gids:
                self._mark_lost_if_unbound(gid, now)

    def snapshot(self) -> list[dict]:
        with self._lock:
            out = []
            for g in self.tracks.values():
                out.append({
                    "globalId": g.global_id,
                    "objectType": g.object_type,
                    "cameraId": g.camera_id,
                    "reidPersonId": g.reid_person_id,
                    "facePersonId": g.face_person_id,
                    "displayName": g.display_name,
                    "plate": g.plate,
                    "identityKey": g.identity_key,
                    "visualKey": g.visual_key,
                    "localTrackId": g.local_track_id,
                    "hitCount": g.hit_count,
                    "lastSeen": g.last_seen,
                    "firstSeen": g.first_seen,
                    "lostAt": g.lost_at,
                    "assocMode": g.last_assoc_mode,
                })
            return out
