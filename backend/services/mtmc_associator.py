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

from services.vehicle_reid_feat import plate_reliable, vehicle_class_conflict

try:
    from services.strong_reid import color_sig_cosine, fuse_similarity_scores
except ImportError:  # pragma: no cover
    def color_sig_cosine(a, b):  # type: ignore
        return -1.0

    def fuse_similarity_scores(scores, weights):  # type: ignore
        return None

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
    if x.size != y.size:
        return -1.0
    return float(np.dot(x, y))


def _space_id(model_key: str, embedding: np.ndarray, model_version: str | None = None) -> tuple[str, int, str | None]:
    return (str(model_key), int(np.asarray(embedding).size), model_version)


def _normalize_embedding_spaces(
    embedding: np.ndarray | None,
    embedding_spaces: dict[str, np.ndarray] | None,
    association_model_key: str | None,
    model_version: str | None,
) -> tuple[dict[tuple[str, int, str | None], np.ndarray], tuple[str, int, str | None] | None]:
    source = dict(embedding_spaces or {})
    if embedding is not None and not source:
        source[association_model_key or "legacy"] = embedding
    spaces = {
        (key if isinstance(key, tuple) else _space_id(key, value, model_version)): _l2(value)
        for key, value in source.items() if value is not None
    }
    if association_model_key:
        for space in spaces:
            if space[0] == association_model_key:
                return spaces, space
    return spaces, next(iter(spaces), None)


def _valid_identity_key(key: str | None) -> str | None:
    if not key:
        return None
    k = str(key).strip()
    if not k or k.upper() in _INVALID_IDENTITY_KEYS or k in _INVALID_IDENTITY_KEYS:
        return None
    return k


@dataclass
class CameraObservationState:
    """Lifecycle of one Global's observation in one camera."""

    active: bool = True
    active_since: float = field(default_factory=time.time)
    lost_at: float | None = None
    last_observed_at: float = field(default_factory=time.time)


@dataclass
class GlobalTrack:
    global_id: str
    object_type: str  # person|vehicle
    embedding: np.ndarray | None = None
    embedding_spaces: dict[tuple[str, int, str | None], np.ndarray] = field(default_factory=dict)
    association_model_space: tuple[str, int, str | None] | None = None
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
    vehicle_class: str | None = None
    vehicle_class_by_cam: dict[int, str] = field(default_factory=dict)
    color_sig: np.ndarray | None = None
    hit_count: int = 1
    trail_by_cam: dict[int, list] = field(default_factory=dict)
    local_track_id: int | None = None
    last_assoc_mode: str = AssocMode.NEW.value
    # Candidate Globals are durable review objects, not provisional confirmed
    # identities.  They can only become confirmed through explicit promotion.
    confirmed: bool = True
    candidate: bool = False
    # Canonical concurrent state; camera_id/last_seen above remain compatibility
    # summaries for legacy HTTP and table consumers.
    camera_observations: dict[int, CameraObservationState] = field(default_factory=dict)


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


@dataclass(frozen=True)
class AssociationResult:
    global_track: GlobalTrack
    evidence: AssocEvidence | None

    def __getattr__(self, name):
        return getattr(self.global_track, name)


@dataclass(frozen=True)
class TopologyRule:
    """Immutable policy for one directed camera transition."""

    min_sec: float
    max_sec: float
    weight: float = 1.0
    edge_type: str = "non_overlap"


class MtmcAssociator:
    """跨摄像头全局关联（McByte++：短时粘性 / 长时选择性 ReID）。"""

    @staticmethod
    def _space_score_weights(
        scores: dict[tuple[str, int, str | None], float], weights: dict | None,
    ) -> dict[tuple[str, int, str | None], float]:
        """Split each configured model-family weight across its live versions."""
        raw_weights = dict(weights or {})
        family_counts: dict[str, int] = {}
        for model_key, _dim, _version in scores:
            family_counts[model_key] = family_counts.get(model_key, 0) + 1
        return {
            space: float(raw_weights[space]) if space in raw_weights else (
                float(raw_weights.get(space[0], 1.0)) / family_counts[space[0]]
            )
            for space in scores
        }

    @staticmethod
    def _fuse_space_scores(scores: dict[tuple[str, int, str | None], float], weights: dict | None) -> float | None:
        """Fuse scores while retaining the complete model-space identity."""
        space_weights = MtmcAssociator._space_score_weights(scores, weights)
        return fuse_similarity_scores(scores, space_weights)

    def __init__(
        self,
        *,
        appear_thresh: float = 0.48,
        vehicle_appear_thresh: float | None = None,
        time_window_sec: float = 90.0,
        topology: dict[tuple[int, int], TopologyRule | tuple[float, float] | dict] | None = None,
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
        # 车辆：local 绑定后短时内仍允许外观重匹配（避免首帧误绑 sticky）
        vehicle_sticky_warmup_sec: float = 2.0,
        # 分数接近时仍走 tie-break（同类多 Global / 跨镜优先）
        cross_cam_tie_band: float = 0.025,
        min_match_margin: float = 0.04,
        prototype_quality_thresh: float = 0.08,
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
        self.topology = {
            (int(a), int(b)): self._coerce_topology_rule(rule)
            for (a, b), rule in (topology or {}).items()
        }
        self._topology_loaded = topology is not None
        self.same_cam_reuse = bool(same_cam_reuse)
        self.same_cam_min_gap = float(same_cam_min_gap)
        self.lost_revive_sec = float(lost_revive_sec)
        self.local_sticky_sec = float(local_sticky_sec)
        self.mcbyte_decouple = bool(mcbyte_decouple)
        self.vehicle_sticky_warmup_sec = float(vehicle_sticky_warmup_sec)
        self.cross_cam_tie_band = float(cross_cam_tie_band)
        self.min_match_margin = max(0.0, float(min_match_margin))
        self.prototype_quality_thresh = max(0.0, min(1.0, float(prototype_quality_thresh)))
        self._lock = threading.Lock()
        self.tracks: dict[str, GlobalTrack] = {}
        # (object_type, camera_id, local_track_id) -> global_id
        self._local_bind: dict[tuple[str, int, int], str] = {}
        self._local_bind_at: dict[tuple[str, int, int], float] = {}
        self._seq = 0
        self.last_mode: AssocMode = AssocMode.NEW
        self.last_evidence: AssocEvidence | None = None
        from services.mtmc_active_gallery import MtmcActiveGallery

        self._gallery = MtmcActiveGallery()
        self._candidates: list[dict] = []

    def _gallery_upsert(
        self,
        g: GlobalTrack,
        observation: np.ndarray | None = None,
        *,
        observation_spaces: dict[tuple[str, int, str | None], np.ndarray] | None = None,
        confirmed: bool = True,
        observation_quality: float | None = None,
    ) -> None:
        if (
            not confirmed
            or not g.confirmed
            or g.last_assoc_mode not in {AssocMode.NEW.value, AssocMode.LONG_TERM.value}
            or not self._quality_qualified(observation_quality)
        ):
            return
        # Do not copy the blended global centroid into every camera slot: that
        # makes different camera prototypes converge and lose discrimination.
        spaces = observation_spaces or g.embedding_spaces
        if not spaces and observation is not None:
            spaces = {_space_id("legacy", observation): observation}
        for (model_key, _dim, model_version), prototype in spaces.items():
            self._gallery.upsert(
                g.object_type,
                g.global_id,
                prototype,
                camera_id=g.camera_id,
                model_key=model_key,
                model_version=model_version,
            )

    def _quality_qualified(self, observation_quality: float | None) -> bool:
        # Legacy direct callers do not carry frame quality.  They remain
        # compatible, while engine calls supply the measured quality.
        return observation_quality is None or float(observation_quality) >= self.prototype_quality_thresh

    def _gallery_remove(self, object_type: str, global_id: str) -> None:
        self._gallery.remove(object_type, global_id)

    def _peer_vehicle_class(self, g: GlobalTrack, camera_id: int) -> str | None:
        """跨镜比对时用对侧相机记录的类别，避免本侧误标污染。"""
        peer = [cls for cam, cls in g.vehicle_class_by_cam.items() if int(cam) != int(camera_id)]
        if peer:
            return peer[-1]
        return g.vehicle_class

    def _cameras_for_global(self, g: GlobalTrack) -> set[int]:
        return self._gallery.cameras_for_global(g.object_type, g.global_id)

    def _cross_cam_established(self, g: GlobalTrack, camera_id: int) -> bool:
        """Global 在对侧相机已有原型（可跨镜续接）。"""
        peer = {c for c in self._cameras_for_global(g) if int(c) != int(camera_id)}
        return len(peer) > 0

    def _cross_cam_recency_weight(self, g: GlobalTrack, camera_id: int, now: float) -> float:
        """跨镜：优先刚在对侧相机出现的 Global；本侧 centroid 已污染则略降权。"""
        if int(g.camera_id or -1) == int(camera_id):
            return 0.90
        dt = now - g.last_seen
        if dt <= 5.0:
            return 1.0 + 0.05 * max(0.0, (5.0 - dt) / 5.0)
        return 1.0

    def _cross_cam_established_boost(self, g: GlobalTrack, camera_id: int) -> float:
        cams = self._cameras_for_global(g)
        cur = int(camera_id)
        peer = {c for c in cams if int(c) != cur}
        if peer and cur not in cams:
            return 1.08
        if peer:
            return 1.04
        if int(g.camera_id or -1) != cur:
            return 1.02
        return 1.0

    def _hard_conflict(
        self,
        object_type: str,
        *,
        plate: str | None,
        identity_key: str | None,
        vehicle_class: str | None = None,
        camera_id: int | None = None,
        target: GlobalTrack,
    ) -> bool:
        """硬冲突：高置信车牌不一致时拒绝合并。

        NOPLATE|* 仅为无牌视觉代理，跨视角 hash 必然不同，不得视为冲突。
        """
        if object_type != "vehicle":
            return False
        ref_cls = (
            self._peer_vehicle_class(target, int(camera_id))
            if camera_id is not None
            else target.vehicle_class
        )
        if vehicle_class_conflict(vehicle_class, ref_cls):
            return True
        ik = _valid_identity_key(identity_key)
        g_ik = _valid_identity_key(target.identity_key)
        if ik and g_ik and ik != g_ik:
            if ik.startswith("NOPLATE|") or g_ik.startswith("NOPLATE|"):
                pass
            else:
                p1 = ik.split("|", 1)[0]
                p2 = g_ik.split("|", 1)[0]
                if p1 != p2 and plate_reliable(p1) and plate_reliable(p2):
                    return True
        p = (plate or "").strip().upper()
        gp = (target.plate or "").strip().upper()
        if (
            plate_reliable(p)
            and plate_reliable(gp)
            and p != gp
        ):
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
                if gid in excluded or g.object_type != object_type or not g.confirmed:
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
                if g is None or g.object_type != object_type or not g.confirmed:
                    continue
                seen.add(gid)
                yield g
        for gid, g in self.tracks.items():
            if (
                gid in excluded
                or gid in seen
                or g.object_type != object_type
                or not g.confirmed
            ):
                continue
            yield g

    def _prefer_on_tie(
        self,
        g_new: GlobalTrack,
        g_old: GlobalTrack,
        camera_id: int,
        *,
        vehicle_class: str | None = None,
        cross_proto_new: float = -1.0,
        cross_proto_old: float = -1.0,
    ) -> bool:
        """同分/近分 tie-break：已有跨镜 Global > 对侧原型更高 > 类别一致。"""
        new_x = self._cross_cam_established(g_new, camera_id)
        old_x = self._cross_cam_established(g_old, camera_id)
        new_peer_only = int(camera_id) not in self._cameras_for_global(g_new) and bool(
            {c for c in self._cameras_for_global(g_new) if int(c) != int(camera_id)}
        )
        old_peer_only = int(camera_id) not in self._cameras_for_global(g_old) and bool(
            {c for c in self._cameras_for_global(g_old) if int(c) != int(camera_id)}
        )
        if new_peer_only and not old_peer_only:
            return True
        if old_peer_only and not new_peer_only:
            return False
        if new_x and not old_x:
            return True
        if old_x and not new_x:
            return False
        if vehicle_class and g_new.vehicle_class and not vehicle_class_conflict(vehicle_class, g_new.vehicle_class):
            if not g_old.vehicle_class or vehicle_class_conflict(vehicle_class, g_old.vehicle_class):
                return True
        if cross_proto_new >= 0 and cross_proto_old >= 0 and cross_proto_new > cross_proto_old + 1e-6:
            return True
        if int(g_new.camera_id or -1) != int(camera_id) and int(g_old.camera_id or -1) == int(camera_id):
            return True
        new_peers = len({c for c in self._cameras_for_global(g_new) if int(c) != int(camera_id)})
        old_peers = len({c for c in self._cameras_for_global(g_old) if int(c) != int(camera_id)})
        if new_peers > old_peers:
            return True
        return False

    def list_candidates(self) -> list[dict]:
        with self._lock:
            return [dict(x) for x in self._candidates[-200:]]

    def get_track(self, global_id: str) -> GlobalTrack | None:
        with self._lock:
            return self.tracks.get(global_id)

    @staticmethod
    def _coerce_topology_rule(value: TopologyRule | tuple[float, float] | dict) -> TopologyRule:
        if isinstance(value, TopologyRule):
            return value
        if isinstance(value, dict):
            weight = value.get("weight")
            return TopologyRule(
                min_sec=float(value.get("minTransitSec") or value.get("min_sec") or 0),
                max_sec=float(value.get("maxTransitSec") or value.get("max_sec") or 0),
                weight=float(1 if weight is None else weight),
                edge_type=str(value.get("edgeType") or value.get("edge_type") or "non_overlap").strip().lower(),
            )
        min_sec, max_sec = value
        min_sec = float(min_sec)
        return TopologyRule(
            min_sec,
            float(max_sec),
            edge_type="overlap" if min_sec == 0 else "non_overlap",
        )

    def set_topology(self, edges: list[dict]):
        topo: dict[tuple[int, int], TopologyRule] = {}
        for e in edges or []:
            a = int(e.get("fromCameraId") or e.get("from_camera_id") or 0)
            b = int(e.get("toCameraId") or e.get("to_camera_id") or 0)
            if a and b:
                weight = e.get("weight")
                topo[(a, b)] = TopologyRule(
                    min_sec=float(e.get("minTransitSec") or e.get("min_transit_sec") or 0),
                    max_sec=float(e.get("maxTransitSec") or e.get("max_transit_sec") or self.time_window_sec),
                    weight=float(1 if weight is None else weight),
                    edge_type=str(e.get("edgeType") or e.get("edge_type") or "non_overlap").strip().lower(),
                )
        with self._lock:
            self.topology = topo
            self._topology_loaded = True

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
        rule = self.topology.get(key)
        if rule is not None:
            rule = self._coerce_topology_rule(rule)
            if (
                dt < rule.min_sec or dt > rule.max_sec
                or (rule.edge_type != "overlap" and dt <= 0)
            ):
                return 0.0
            if rule.edge_type == "overlap":
                return float(max(0.0, 1.0 - dt / max(rule.max_sec, 1e-6)))
            mid = (rule.min_sec + rule.max_sec) * 0.5
            span = max(rule.max_sec - rule.min_sec, 1e-6)
            return float(max(0.0, 1.0 - abs(dt - mid) / span))
        if not self._topology_loaded:
            return 1.0 if dt <= self.time_window_sec else 0.0
        return 0.0

    def _topology_ok(self, prev_cam: int | None, cur_cam: int, dt: float) -> float:
        if prev_cam is None or prev_cam == cur_cam:
            return 1.0 if dt <= self.time_window_sec else 0.0
        key = (int(prev_cam), int(cur_cam))
        rule = self.topology.get(key)
        if rule is None:
            if not self._topology_loaded:
                return 1.0 if dt <= self.time_window_sec else 0.0
            return 0.0
        rule = self._coerce_topology_rule(rule)
        if (
            dt < rule.min_sec or dt > rule.max_sec
            or (rule.edge_type != "overlap" and dt <= 0)
        ):
            return 0.0
        return max(0.0, rule.weight)

    def _bind_key(self, object_type: str, camera_id: int, local_track_id: int) -> tuple[str, int, int]:
        return (object_type, int(camera_id), int(local_track_id))

    def _evict_same_cam_sibling_binds(
        self,
        object_type: str,
        camera_id: int,
        local_track_id: int,
        global_id: str,
    ) -> None:
        """同镜另一 local 误占同一 Global 时解除粘性，让外观重匹配。"""
        g = self.tracks.get(global_id)
        if g is not None:
            state = g.camera_observations.get(int(camera_id))
            if state is not None and state.active:
                return
        keep = self._bind_key(object_type, camera_id, int(local_track_id))
        for k in list(self._local_bind.keys()):
            if k == keep:
                continue
            if k[0] == object_type and k[1] == int(camera_id) and self._local_bind.get(k) == global_id:
                self._local_bind.pop(k, None)
                self._local_bind_at.pop(k, None)

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
        for camera_id, state in g.camera_observations.items():
            still_bound_here = any(
                key[1] == camera_id and bound_gid == gid
                for key, bound_gid in self._local_bind.items()
            )
            if state.active and not still_bound_here:
                state.active = False
                state.lost_at = now
        still_active = any(state.active for state in g.camera_observations.values())
        if not still_active and g.lost_at is None:
            g.lost_at = now

    @staticmethod
    def _observe_camera(g: GlobalTrack, camera_id: int, now: float) -> None:
        camera_id = int(camera_id)
        state = g.camera_observations.get(camera_id)
        if state is None:
            g.camera_observations[camera_id] = CameraObservationState(
                active=True, active_since=now, last_observed_at=now,
            )
            return
        if not state.active:
            state.active = True
            state.active_since = now
            state.lost_at = None
        state.last_observed_at = now

    def _same_camera_active_occupied(
        self,
        g: GlobalTrack,
        object_type: str,
        camera_id: int,
        local_track_id: int | None,
    ) -> bool:
        state = g.camera_observations.get(int(camera_id))
        if state is None or not state.active:
            return False
        if local_track_id is None:
            return True
        return any(
            key[0] == object_type
            and key[1] == int(camera_id)
            and bound_gid == g.global_id
            and key[2] != int(local_track_id)
            for key, bound_gid in self._local_bind.items()
        )

    def _update_track(
        self,
        g: GlobalTrack,
        *,
        camera_id: int,
        embedding: np.ndarray | None,
        embedding_spaces: dict[tuple[str, int, str | None], np.ndarray] | None = None,
        association_model_space: tuple[str, int, str | None] | None = None,
        identity_key: str | None,
        plate: str | None,
        reid_person_id: int | None,
        face_person_id: int | None,
        display_name: str | None,
        visual_key: str | None,
        vehicle_class: str | None,
        color_sig: np.ndarray | None = None,
        local_track_id: int | None,
        now: float,
        mode: AssocMode,
        update_embedding: bool = True,
    ) -> GlobalTrack:
        g.last_seen = now
        g.camera_id = camera_id
        self._observe_camera(g, camera_id, now)
        g.hit_count += 1
        g.lost_at = None  # 复活/续接后清除丢失标记
        g.last_assoc_mode = mode.value
        if local_track_id is not None:
            g.local_track_id = int(local_track_id)
        if update_embedding and embedding_spaces:
            alpha = 0.15 if mode == AssocMode.STICKY else 0.35
            for space, value in embedding_spaces.items():
                current = g.embedding_spaces.get(space)
                if current is None:
                    g.embedding_spaces[space] = _l2(value)
                else:
                    g.embedding_spaces[space] = _l2((1.0 - alpha) * _l2(current) + alpha * _l2(value))
            if association_model_space in g.embedding_spaces:
                g.association_model_space = association_model_space
                g.embedding = g.embedding_spaces[association_model_space]
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
        if vehicle_class:
            vc_norm = str(vehicle_class).strip().lower()
            g.vehicle_class = vc_norm
            g.vehicle_class_by_cam[int(camera_id)] = vc_norm
        if color_sig is not None:
            cs = _l2(np.asarray(color_sig, dtype=np.float32).reshape(-1))
            if g.color_sig is None:
                g.color_sig = cs
            else:
                a, b = _l2(g.color_sig), cs
                dim = max(a.size, b.size)
                aa = np.zeros(dim, dtype=np.float32)
                bb = np.zeros(dim, dtype=np.float32)
                aa[: a.size] = a
                bb[: b.size] = b
                alpha = 0.2 if mode == AssocMode.STICKY else 0.4
                g.color_sig = _l2((1.0 - alpha) * aa + alpha * bb)
        return g

    def _is_lost_for_revive(self, g: GlobalTrack, camera_id: int, now: float) -> bool:
        """McByte++：仅丢失足够久的身份允许被新生 track 用外观复活。"""
        state = g.camera_observations.get(int(camera_id))
        last_observed = state.last_observed_at if state is not None else g.last_seen
        dt = now - last_observed
        if g.camera_id != camera_id and state is None:
            # 跨镜：只要拓扑时间窗内，允许长时外观关联（对方相机上可能仍「活跃」）
            return True
        # 同镜：必须已丢失一段时间，禁止抢占仍在画面中的 Global
        if state is not None and state.active:
            return False
        if dt < max(self.same_cam_min_gap, self.lost_revive_sec):
            return False
        if g.lost_at is not None and (now - g.lost_at) < self.lost_revive_sec * 0.5:
            # 刚标记丢失，略放宽也可；仍要求 last_seen 间隔够
            pass
        return dt >= self.lost_revive_sec

    def _same_cam_sibling_occupied(
        self,
        object_type: str,
        camera_id: int,
        global_id: str,
        local_track_id: int | None,
    ) -> bool:
        if local_track_id is None:
            return False
        want = int(local_track_id)
        for bkey, bgid in self._local_bind.items():
            if (
                bgid == global_id
                and bkey[0] == object_type
                and bkey[1] == int(camera_id)
                and bkey[2] != want
            ):
                return True
        return False

    def _score_long_term(
        self,
        g: GlobalTrack,
        *,
        object_type: str,
        camera_id: int,
        embedding: np.ndarray | None,
        embedding_spaces: dict[tuple[str, int, str | None], np.ndarray] | None = None,
        score_weights: dict[str, float] | None = None,
        identity_key: str | None,
        plate: str | None,
        reid_person_id: int | None,
        local_track_id: int | None = None,
        vehicle_class: str | None = None,
        color_sig: np.ndarray | None = None,
        visual_key: str | None = None,
        now: float,
    ) -> tuple[float | None, dict]:
        """仅用于新生 local track 的长时/跨镜外观匹配。返回 (final_score, breakdown)。"""
        dt = now - g.last_seen
        topo_w = self._topology_ok(g.camera_id, camera_id, dt)
        time_w = self._time_fit_score(g.camera_id, camera_id, dt)
        if topo_w <= 0:
            return None, {"topology": topo_w, "time": time_w, "reid": None, "final": None}

        same_cam = g.camera_id == camera_id
        per_space_scores: dict[tuple[str, int, str | None], float] = {}
        per_space_cross: dict[tuple[str, int, str | None], float] = {}
        for (model_key, _dim, model_version), vector in (embedding_spaces or {}).items():
            space = (model_key, int(vector.size), model_version)
            prototype = g.embedding_spaces.get(space)
            if prototype is not None:
                per_space_scores[space] = _cos(vector, prototype)
            cross = self._gallery.max_similarity(
                object_type, g.global_id, vector, exclude_camera_id=camera_id,
                model_key=model_key, model_version=model_version,
            )
            if cross >= 0:
                per_space_cross[space] = cross
        centroid_cos = self._fuse_space_scores(per_space_scores, score_weights)
        cross_proto = self._fuse_space_scores(per_space_cross, score_weights)
        centroid_cos = float(centroid_cos) if centroid_cos is not None else -1.0
        cross_proto = float(cross_proto) if cross_proto is not None else -1.0

        sibling_occupied = self._same_cam_sibling_occupied(
            object_type, camera_id, g.global_id, local_track_id,
        )
        if self._same_camera_active_occupied(g, object_type, camera_id, local_track_id):
            return None, {
                "topology": topo_w, "time": time_w, "reid": None,
                "final": None, "occupied": True,
            }

        cross_takeover = False

        if cross_takeover:
            pass
        elif self.mcbyte_decouple:
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
            if not same_cam or cross_takeover:
                appear_need = min(appear_need, max(0.42, self.vehicle_appear_thresh - 0.06))
        elif not same_cam:
            # 行人跨视角外观弱于车辆：阈值更松，依赖拓扑+对侧原型
            if object_type == "person":
                appear_need = min(appear_need, max(0.28, self.appear_thresh - 0.18))
                if cross_proto >= 0.28:
                    appear_need = min(appear_need, max(0.26, float(cross_proto) - 0.02))
            else:
                appear_need = min(appear_need, max(0.40, self.appear_thresh - 0.06))
                if (
                    cross_proto >= 0.38
                    and self._cross_cam_established(g, camera_id)
                ):
                    appear_need = min(appear_need, max(0.36, cross_proto - 0.02))
        if same_cam and not cross_takeover:
            appear_need = max(appear_need, self.appear_thresh + 0.12)

        score = 0.0
        reid_raw = None
        ik = _valid_identity_key(identity_key)
        g_ik = _valid_identity_key(g.identity_key)

        if object_type == "vehicle":
            if cross_takeover:
                reid_raw = cross_proto
                score = reid_raw
                if score < appear_need:
                    return None, {"topology": topo_w, "time": time_w, "reid": reid_raw, "final": None}
            elif ik and g_ik and ik == g_ik:
                cos = centroid_cos
                min_cos = appear_need
                if cos >= 0 and cos < min_cos:
                    return None, {"topology": topo_w, "time": time_w, "reid": cos, "final": None}
                score, reid_raw = 0.99, cos if cos >= 0 else None
            elif plate and g.plate and plate == g.plate:
                cos = centroid_cos
                if embedding is not None and g.embedding is not None and cos < appear_need * 0.65:
                    return None, {"topology": topo_w, "time": time_w, "reid": cos, "final": None}
                score, reid_raw = 0.92, cos if cos >= 0 else None
            else:
                peer_cls = self._peer_vehicle_class(g, camera_id)
                if not same_cam and cross_proto >= 0:
                    if vehicle_class_conflict(vehicle_class, peer_cls):
                        return None, {
                            "topology": topo_w, "time": time_w,
                            "reid": centroid_cos, "final": None, "classConflict": True,
                        }
                    reid_raw = cross_proto
                else:
                    reid_raw = centroid_cos
                score = reid_raw
                if score < appear_need:
                    return None, {"topology": topo_w, "time": time_w, "reid": reid_raw, "final": None}
        else:
            if reid_person_id and g.reid_person_id and reid_person_id == g.reid_person_id:
                score, reid_raw = 0.99, 1.0
            else:
                if not same_cam and cross_proto >= 0:
                    reid_raw = cross_proto
                else:
                    reid_raw = centroid_cos
                # 颜色签名：跨视角外观弱时抬分（红帽/米色衫/白盔等）
                csim = color_sig_cosine(color_sig, g.color_sig)
                # One view may detect the full person while the opposite view
                # only sees the motorcycle-derived rider proxy.
                rider_pair = visual_key == "rider" or g.visual_key == "rider"
                if not same_cam and csim >= 0.55 and reid_raw is not None and reid_raw >= 0:
                    # Rider pose changes sharply between cameras; clothing color
                    # is more stable than a person model distorted by the bike.
                    reid_weight = 0.45 if rider_pair else 0.62
                    color_weight = 1.0 - reid_weight
                    reid_raw = float(reid_weight * reid_raw + color_weight * max(reid_raw, csim))
                    if csim >= 0.72 and reid_raw < appear_need:
                        reid_raw = max(reid_raw, min(appear_need + 0.02, 0.55 * reid_raw + 0.45 * csim))
                score = reid_raw
                if score < appear_need:
                    return None, {
                        "topology": topo_w, "time": time_w,
                        "reid": reid_raw, "color": csim if csim >= 0 else None, "final": None,
                    }
        recency_w = (
            self._cross_cam_recency_weight(g, camera_id, now)
            if not same_cam
            else 1.0
        )
        xcam_boost = (
            self._cross_cam_established_boost(g, camera_id)
            if not same_cam
            else 1.0
        )
        final = float(score * topo_w * time_w * recency_w * xcam_boost)
        return final, {
            "reid": reid_raw,
            "reidByModelKey": per_space_scores or None,
            "crossProto": cross_proto if cross_proto >= 0 else None,
            "topology": topo_w,
            "time": time_w,
            "recency": recency_w,
            "xcamBoost": xcam_boost,
            "final": final,
            "candidateGlobalId": g.global_id,
        }

    def _select_long_term_target(
        self,
        *,
        object_type: str,
        camera_id: int,
        embedding: np.ndarray | None,
        embedding_spaces: dict[tuple[str, int, str | None], np.ndarray],
        score_weights: dict[str, float] | None,
        identity_key: str | None,
        plate: str | None,
        reid_person_id: int | None,
        local_track_id: int | None,
        vehicle_class: str | None,
        color_sig: np.ndarray | None,
        visual_key: str | None,
        excluded: set[str],
        now: float,
    ) -> tuple[str | None, float, dict, list[tuple[str, float]]]:
        best_gid = None
        best_score = -1.0
        best_breakdown: dict = {}
        ranked_scores: list[tuple[str, float]] = []
        for g in self._iter_long_term_targets(
            object_type, embedding, excluded,
            reid_person_id=reid_person_id, plate=plate, identity_key=identity_key,
        ):
            if self._hard_conflict(
                object_type, plate=plate, identity_key=identity_key,
                vehicle_class=vehicle_class, camera_id=camera_id, target=g,
            ):
                continue
            score, breakdown = self._score_long_term(
                g, object_type=object_type, camera_id=camera_id,
                embedding=embedding, embedding_spaces=embedding_spaces,
                score_weights=score_weights, identity_key=identity_key, plate=plate,
                reid_person_id=reid_person_id, local_track_id=local_track_id,
                vehicle_class=vehicle_class, color_sig=color_sig,
                visual_key=visual_key, now=now,
            )
            if score is None:
                continue
            ranked_scores.append((g.global_id, float(score)))
            cross_proto = float(breakdown.get("crossProto") or -1.0)
            if score > best_score:
                best_gid, best_score, best_breakdown = g.global_id, score, breakdown
            elif (
                best_gid is not None
                and (best_score - score) <= self.cross_cam_tie_band
                and self._prefer_on_tie(
                    g, self.tracks[best_gid], camera_id,
                    vehicle_class=vehicle_class, cross_proto_new=cross_proto,
                    cross_proto_old=float(best_breakdown.get("crossProto") or -1.0),
                )
            ):
                best_gid, best_score, best_breakdown = g.global_id, score, breakdown
        return best_gid, float(best_score), best_breakdown, ranked_scores

    def associate(
        self,
        *,
        object_type: str,
        camera_id: int,
        embedding: np.ndarray | None = None,
        embedding_spaces: dict[str, np.ndarray] | None = None,
        association_model_key: str | None = None,
        model_version: str | None = None,
        score_weights: dict[str, float] | None = None,
        identity_key: str | None = None,
        plate: str | None = None,
        reid_person_id: int | None = None,
        face_person_id: int | None = None,
        display_name: str | None = None,
        visual_key: str | None = None,
        vehicle_class: str | None = None,
        color_sig: np.ndarray | None = None,
        local_track_id: int | None = None,
        exclude_gids: Iterable[str] | None = None,
        now: float | None = None,
        force_long_term: bool = False,
        observation_quality: float | None = None,
        force_candidate: bool = False,
    ) -> GlobalTrack:
        """Compatibility API returning only the associated GlobalTrack."""
        return self.associate_with_evidence(
            object_type=object_type,
            camera_id=camera_id,
            embedding=embedding,
            embedding_spaces=embedding_spaces,
            association_model_key=association_model_key,
            model_version=model_version,
            score_weights=score_weights,
            identity_key=identity_key,
            plate=plate,
            reid_person_id=reid_person_id,
            face_person_id=face_person_id,
            display_name=display_name,
            visual_key=visual_key,
            vehicle_class=vehicle_class,
            color_sig=color_sig,
            local_track_id=local_track_id,
            exclude_gids=exclude_gids,
            now=now,
            force_long_term=force_long_term,
            observation_quality=observation_quality,
            force_candidate=force_candidate,
        ).global_track

    def vehicle_candidate_prototype(
        self,
        *,
        camera_id: int,
        embedding: np.ndarray | None,
        vehicle_class: str | None = None,
        now: float | None = None,
    ) -> np.ndarray | None:
        """Return the selected existing vehicle prototype for visual evidence.

        The caller must never substitute its observation embedding when no
        target exists: that would turn a candidate score into self-similarity.
        """
        if embedding is None:
            return None
        ts = float(now if now is not None else time.time())
        spaces, _ = _normalize_embedding_spaces(embedding, None, None, None)
        with self._lock:
            self._purge_expired(ts)
            gid, _score, _breakdown, _ranked = self._select_long_term_target(
                object_type="vehicle", camera_id=int(camera_id), embedding=embedding,
                embedding_spaces=spaces, score_weights=None, identity_key=None,
                plate=None, reid_person_id=None, local_track_id=None,
                vehicle_class=vehicle_class, color_sig=None, visual_key=None,
                excluded=set(), now=ts,
            )
            candidate = self.tracks.get(gid) if gid else None
            if candidate is None or candidate.embedding is None:
                return None
            return np.asarray(candidate.embedding, dtype=np.float32).copy()

    def associate_with_evidence(
        self,
        *,
        object_type: str,
        camera_id: int,
        embedding: np.ndarray | None = None,
        embedding_spaces: dict[str, np.ndarray] | None = None,
        association_model_key: str | None = None,
        model_version: str | None = None,
        score_weights: dict[str, float] | None = None,
        identity_key: str | None = None,
        plate: str | None = None,
        reid_person_id: int | None = None,
        face_person_id: int | None = None,
        display_name: str | None = None,
        visual_key: str | None = None,
        vehicle_class: str | None = None,
        color_sig: np.ndarray | None = None,
        local_track_id: int | None = None,
        exclude_gids: Iterable[str] | None = None,
        now: float | None = None,
        force_long_term: bool = False,
        observation_quality: float | None = None,
        force_candidate: bool = False,
    ) -> AssociationResult:
        """
        McByte++ 路径：
        1) 有粘性 → STICKY（不搜外观）
        2) 新生 local（或 force_long_term）→ 仅对丢失/跨镜 Global 做外观 LONG_TERM
        3) 否则 NEW
        """
        now = float(now if now is not None else time.time())
        spaces, association_space = _normalize_embedding_spaces(
            embedding, embedding_spaces, association_model_key, model_version,
        )
        if association_space is not None:
            embedding = spaces[association_space]
        excluded = set(exclude_gids or ())
        identity_key = _valid_identity_key(identity_key)
        vc = str(vehicle_class).strip().lower() if vehicle_class else None

        with self._lock:
            self._purge_expired(now)
            evidence: AssocEvidence | None = None

            # ---- 1) 短时粘性：Kalman/IoU/ByteTrack 已保证同一 local_id ----
            is_new_local = True
            if local_track_id is not None and not force_long_term:
                bkey = self._bind_key(object_type, camera_id, int(local_track_id))
                sticky_gid = self._local_bind.get(bkey)
                if sticky_gid and sticky_gid not in excluded:
                    g = self.tracks.get(sticky_gid)
                    if g is not None and g.object_type == object_type:
                        skip_sticky = False
                        if (
                            object_type == "vehicle"
                            and embedding is not None
                            and g.confirmed
                            and self.vehicle_sticky_warmup_sec > 0
                        ):
                            bind_at = self._local_bind_at.get(bkey)
                            if bind_at is not None and (now - bind_at) < self.vehicle_sticky_warmup_sec:
                                skip_sticky = True
                        if (
                            not skip_sticky
                            and object_type == "vehicle"
                            and vc
                        ):
                            peer_cls = self._peer_vehicle_class(g, camera_id)
                            if vehicle_class_conflict(vc, peer_cls):
                                skip_sticky = True
                        if (
                            not skip_sticky
                            and object_type == "vehicle"
                            and embedding is not None
                            and g.embedding is not None
                        ):
                            cur_cos = _cos(embedding, g.embedding)
                            drift_need = max(0.40, self.vehicle_appear_thresh - 0.08)
                            if cur_cos >= 0 and cur_cos < drift_need:
                                skip_sticky = True
                            elif (
                                self.use_faiss_gallery
                                and self._gallery.size(object_type) > 0
                                and self._gallery.faiss_available()
                            ):
                                best_cross = -1.0
                                for alt_gid, _sim in self._gallery.search(
                                    object_type, embedding, topk=12,
                                ):
                                    if alt_gid == g.global_id:
                                        continue
                                    cp = self._gallery.max_similarity(
                                        object_type,
                                        alt_gid,
                                        embedding,
                                        exclude_camera_id=camera_id,
                                    )
                                    if cp > best_cross:
                                        best_cross = cp
                                if (
                                    best_cross >= self.vehicle_appear_thresh
                                    and best_cross > cur_cos + 0.06
                                ):
                                    skip_sticky = True
                        if not skip_sticky and now - g.last_seen <= self.local_sticky_sec:
                            self.last_mode = AssocMode.STICKY
                            evidence = AssocEvidence(
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
                                embedding_spaces=spaces,
                                association_model_space=association_space,
                                identity_key=identity_key,
                                plate=plate,
                                reid_person_id=reid_person_id,
                                face_person_id=face_person_id,
                                display_name=display_name,
                                visual_key=visual_key,
                                vehicle_class=vc,
                                color_sig=color_sig,
                                local_track_id=int(local_track_id),
                                now=now,
                                mode=AssocMode.STICKY,
                                update_embedding=False,
                            )
                            self.last_evidence = evidence
                            return AssociationResult(g, evidence)
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
            ranked_scores: list[tuple[str, float]] = []
            if allow_appearance and (
                embedding is not None
                or _valid_identity_key(identity_key)
                or plate
                or reid_person_id
            ):
                best_gid, best_score, best_breakdown, ranked_scores = self._select_long_term_target(
                    object_type=object_type, camera_id=camera_id, embedding=embedding,
                    embedding_spaces=spaces, score_weights=score_weights,
                    identity_key=identity_key, plate=plate, reid_person_id=reid_person_id,
                    local_track_id=int(local_track_id) if local_track_id is not None else None,
                    vehicle_class=vc, color_sig=color_sig, visual_key=visual_key,
                    excluded=excluded, now=now,
                )

            prev_gid = None
            if local_track_id is not None:
                prev_gid = self._local_bind.get(self._bind_key(object_type, camera_id, int(local_track_id)))

            tier = "new"
            candidate_gid = best_gid
            tier_score = best_score
            # 行人：final 含颜色/时序加成，用作确认分；避免弱外观永远卡在 candidate
            if object_type == "person" and best_score is not None and best_score >= 0:
                tier_score = max(float(tier_score or -1), float(best_score))
            confirm_need = self.confirm_thresh
            if object_type == "person" and self.confirm_thresh <= self.appear_thresh + 0.08:
                # 默认配置下放宽；显式高 confirm（三档 candidate 测试）不受影响
                confirm_need = min(self.confirm_thresh, max(0.30, self.appear_thresh - 0.14))
            second_score = max(
                (score for gid, score in ranked_scores if gid != best_gid),
                default=None,
            )
            match_margin = (
                float(best_score - second_score)
                if second_score is not None else None
            )
            best_breakdown.update({
                "bestScore": best_score if best_gid is not None else None,
                "secondBestScore": second_score,
                "matchMargin": match_margin,
                "minMatchMargin": self.min_match_margin,
            })
            if best_gid is not None:
                if (
                    not force_candidate
                    and
                    tier_score >= confirm_need
                    and (match_margin is None or match_margin >= self.min_match_margin)
                ):
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
                    embedding_spaces=spaces,
                    association_model_space=association_space,
                    identity_key=identity_key,
                    plate=plate,
                    reid_person_id=reid_person_id,
                    face_person_id=face_person_id,
                    display_name=display_name,
                    visual_key=visual_key,
                    vehicle_class=vc,
                    color_sig=color_sig,
                    local_track_id=int(local_track_id) if local_track_id is not None else None,
                    now=now,
                    mode=AssocMode.LONG_TERM,
                    update_embedding=self._quality_qualified(observation_quality),
                )
                evidence = AssocEvidence(
                    decision=AssocMode.LONG_TERM.value,
                    target_global_id=g.global_id,
                    source_global_id=prev_gid,
                    candidate_global_id=best_breakdown.get("candidateGlobalId"),
                    reid_score=best_breakdown.get("reid"),
                    topology_score=best_breakdown.get("topology"),
                    time_score=best_breakdown.get("time"),
                    final_score=best_breakdown.get("final"),
                )
                self._gallery_upsert(
                    g, embedding, observation_spaces=spaces,
                    observation_quality=observation_quality,
                )
            elif tier == "candidate" and candidate_gid is not None:
                self.last_mode = AssocMode.CANDIDATE
                gid = self._new_gid(object_type)
                g = GlobalTrack(
                    global_id=gid,
                    object_type=object_type,
                    embedding=_l2(embedding) if embedding is not None else None,
                    embedding_spaces=dict(spaces),
                    association_model_space=association_space,
                    camera_id=camera_id,
                    last_seen=now,
                    first_seen=now,
                    reid_person_id=reid_person_id,
                    face_person_id=face_person_id,
                    display_name=display_name,
                    plate=plate,
                    identity_key=identity_key,
                    visual_key=visual_key,
                    vehicle_class=vc,
                    color_sig=_l2(color_sig) if color_sig is not None else None,
                    local_track_id=int(local_track_id) if local_track_id is not None else None,
                    last_assoc_mode=AssocMode.CANDIDATE.value,
                    confirmed=False,
                    candidate=True,
                    camera_observations={
                        int(camera_id): CameraObservationState(
                            active=True, active_since=now, last_observed_at=now,
                        )
                    },
                )
                self.tracks[gid] = g
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
                    "secondBestScore": second_score,
                    "matchMargin": match_margin,
                    "ts": now,
                })
                evidence = AssocEvidence(
                    decision=AssocMode.CANDIDATE.value,
                    target_global_id=g.global_id,
                    source_global_id=prev_gid,
                    candidate_global_id=candidate_gid,
                    reid_score=best_breakdown.get("reid"),
                    topology_score=best_breakdown.get("topology"),
                    time_score=best_breakdown.get("time"),
                    final_score=best_score,
                    extra={
                        "tier": "candidate",
                        "confirmThresh": self.confirm_thresh,
                        "bestScore": best_score,
                        "secondBestScore": second_score,
                        "matchMargin": match_margin,
                        "minMatchMargin": self.min_match_margin,
                    },
                )
            else:
                self.last_mode = AssocMode.NEW
                gid = self._new_gid(object_type)
                g = GlobalTrack(
                    global_id=gid,
                    object_type=object_type,
                    embedding=_l2(embedding) if embedding is not None else None,
                    embedding_spaces=dict(spaces),
                    association_model_space=association_space,
                    camera_id=camera_id,
                    last_seen=now,
                    first_seen=now,
                    reid_person_id=reid_person_id,
                    face_person_id=face_person_id,
                    display_name=display_name,
                    plate=plate,
                    identity_key=identity_key,
                    visual_key=visual_key,
                    vehicle_class=vc,
                    color_sig=_l2(color_sig) if color_sig is not None else None,
                    local_track_id=int(local_track_id) if local_track_id is not None else None,
                    last_assoc_mode=AssocMode.NEW.value,
                    camera_observations={
                        int(camera_id): CameraObservationState(
                            active=True, active_since=now, last_observed_at=now,
                        )
                    },
                )
                self.tracks[gid] = g
                self._gallery_upsert(
                    g, embedding, observation_spaces=spaces,
                    observation_quality=observation_quality,
                )
                evidence = AssocEvidence(
                    decision=AssocMode.NEW.value,
                    target_global_id=g.global_id,
                    source_global_id=prev_gid,
                    reid_score=None,
                    topology_score=None,
                    time_score=None,
                    final_score=None,
                )

            if local_track_id is not None:
                bkey = self._bind_key(object_type, camera_id, int(local_track_id))
                if bkey not in self._local_bind_at:
                    self._local_bind_at[bkey] = now
                self._local_bind[bkey] = g.global_id
            self.last_evidence = evidence
            return AssociationResult(g, evidence)

    def associate_batch(self, observations: Iterable[dict]) -> list[AssociationResult]:
        """Associate one same-frame batch with deterministic mutual-best gating.

        The single-observation ``associate`` API remains the compatibility
        wrapper.  Batch callers get a first scoring pass, then only an
        observation and Global that choose each other may confirm.
        """
        rows = [dict(row) for row in observations]
        if not rows:
            return []
        scores_by_row: dict[int, tuple[str, float] | None] = {}
        with self._lock:
            for index, row in enumerate(rows):
                now = float(row.get("now") if row.get("now") is not None else time.time())
                self._purge_expired(now)
                object_type = str(row["object_type"])
                camera_id = int(row["camera_id"])
                local_track_id = row.get("local_track_id")
                embedding = row.get("embedding")
                spaces, _association_space = _normalize_embedding_spaces(
                    embedding,
                    row.get("embedding_spaces"),
                    row.get("association_model_key"),
                    row.get("model_version"),
                )
                excluded = set(row.get("exclude_gids") or ())
                best_gid, best_score, _breakdown, _ranked = self._select_long_term_target(
                    object_type=object_type, camera_id=camera_id, embedding=embedding,
                    embedding_spaces=spaces, score_weights=row.get("score_weights"),
                    identity_key=row.get("identity_key"), plate=row.get("plate"),
                    reid_person_id=row.get("reid_person_id"),
                    local_track_id=(int(local_track_id) if local_track_id is not None else None),
                    vehicle_class=row.get("vehicle_class"), color_sig=row.get("color_sig"),
                    visual_key=row.get("visual_key"), excluded=excluded, now=now,
                )
                scores_by_row[index] = (
                    (best_gid, best_score) if best_gid is not None else None
                )

        best_row_by_global: dict[str, int] = {}
        for index, candidate in scores_by_row.items():
            if candidate is None:
                continue
            gid, score = candidate
            current = best_row_by_global.get(gid)
            if current is None:
                best_row_by_global[gid] = index
                continue
            current_score = scores_by_row[current][1]  # type: ignore[index]
            current_local = int(rows[current].get("local_track_id") or -1)
            local_id = int(rows[index].get("local_track_id") or -1)
            if score > current_score or (score == current_score and local_id < current_local):
                best_row_by_global[gid] = index

        mutual = {
            index for index, candidate in scores_by_row.items()
            if candidate is not None and best_row_by_global.get(candidate[0]) == index
        }
        execution_order = sorted(
            range(len(rows)),
            key=lambda index: (
                index not in mutual,
                -(scores_by_row[index][1] if scores_by_row[index] is not None else -1.0),
                str(rows[index].get("object_type")),
                int(rows[index].get("camera_id") or -1),
                int(rows[index].get("local_track_id") or -1),
            ),
        )
        claimed: set[str] = set()
        results: dict[int, AssociationResult] = {}
        for index in execution_order:
            row = dict(rows[index])
            excluded = set(row.pop("exclude_gids", ()) or ()) | claimed
            row["exclude_gids"] = excluded
            row["force_candidate"] = index not in mutual
            result = self.associate_with_evidence(**row)
            results[index] = result
            if index in mutual and result.last_assoc_mode == AssocMode.LONG_TERM.value:
                claimed.add(result.global_id)
        return [results[index] for index in range(len(rows))]

    def merge_globals(self, keep_gid: str, drop_gid: str, now: float | None = None) -> GlobalTrack | None:
        """P2：将 drop_gid 合并进 keep_gid（候选晋升）。"""
        now = float(now if now is not None else time.time())
        with self._lock:
            keep = self.tracks.get(keep_gid)
            drop = self.tracks.get(drop_gid)
            if keep is None or drop is None or keep.object_type != drop.object_type:
                return None
            for space, vector in drop.embedding_spaces.items():
                current = keep.embedding_spaces.get(space)
                keep.embedding_spaces[space] = (
                    _l2(vector) if current is None else _l2(0.5 * _l2(current) + 0.5 * _l2(vector))
                )
            if keep.association_model_space is None:
                keep.association_model_space = drop.association_model_space
            if keep.association_model_space in keep.embedding_spaces:
                keep.embedding = keep.embedding_spaces[keep.association_model_space]
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
            if drop.vehicle_class and not keep.vehicle_class:
                keep.vehicle_class = drop.vehicle_class
            for cam, cls in (drop.vehicle_class_by_cam or {}).items():
                if cls and int(cam) not in keep.vehicle_class_by_cam:
                    keep.vehicle_class_by_cam[int(cam)] = cls
            for camera_id, drop_state in drop.camera_observations.items():
                keep_state = keep.camera_observations.get(camera_id)
                if keep_state is None or drop_state.last_observed_at > keep_state.last_observed_at:
                    keep.camera_observations[camera_id] = drop_state
            keep.last_seen = max(keep.last_seen, drop.last_seen)
            keep.first_seen = min(keep.first_seen, drop.first_seen)
            keep.camera_id = drop.camera_id
            keep.lost_at = None
            keep.last_assoc_mode = AssocMode.LONG_TERM.value
            keep.confirmed = True
            keep.candidate = False
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

    def release_local(
        self,
        object_type: str,
        camera_id: int,
        local_track_ids: Iterable[int] | None = None,
        *,
        now: float | None = None,
    ):
        now = float(now if now is not None else time.time())
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
                    "vehicleClass": g.vehicle_class,
                    "localTrackId": g.local_track_id,
                    "hitCount": g.hit_count,
                    "lastSeen": g.last_seen,
                    "firstSeen": g.first_seen,
                    "lostAt": g.lost_at,
                    "assocMode": g.last_assoc_mode,
                    "confirmed": g.confirmed,
                    "candidate": g.candidate,
                    "cameraObservations": {
                        str(camera_id): {
                            "active": state.active,
                            "activeSince": state.active_since,
                            "lostAt": state.lost_at,
                            "lastObservedAt": state.last_observed_at,
                        }
                        for camera_id, state in g.camera_observations.items()
                    },
                })
            return out
