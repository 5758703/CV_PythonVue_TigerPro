"""MTMC 在线 Active Gallery（L1）：FAISS IndexFlatIP 加速 Global 候选检索。"""
from __future__ import annotations

import threading
from typing import Any

import numpy as np

from services.reid_gallery import l2_normalize

_lock = threading.Lock()


def _import_faiss():
    try:
        import faiss  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("未安装 faiss-cpu，请执行: pip install faiss-cpu") from e
    return faiss


class MtmcActiveGallery:
    """会话级内存向量库：object_type -> global_id -> camera_id -> embedding。"""

    def __init__(self):
        # object_type -> global_id -> camera_id -> embedding
        self._vecs: dict[str, dict[str, dict[int, np.ndarray]]] = {}
        self._dirty: set[str] = set()
        self._index: dict[str, Any] = {}
        self._gids: dict[str, list[str]] = {}
        self._dim: dict[str, int] = {}

    def clear(self, object_type: str | None = None) -> None:
        with _lock:
            if object_type is None:
                self._vecs.clear()
                self._dirty.clear()
                self._index.clear()
                self._gids.clear()
                self._dim.clear()
                return
            self._vecs.pop(object_type, None)
            self._dirty.discard(object_type)
            self._index.pop(object_type, None)
            self._gids.pop(object_type, None)
            self._dim.pop(object_type, None)

    def upsert(
        self,
        object_type: str,
        global_id: str,
        embedding: np.ndarray | None,
        *,
        camera_id: int | None = None,
    ) -> None:
        if embedding is None:
            return
        v = l2_normalize(np.asarray(embedding, dtype=np.float32).reshape(-1))
        cam_key = int(camera_id) if camera_id is not None else -1
        with _lock:
            bucket = self._vecs.setdefault(object_type, {})
            cam_map = bucket.setdefault(str(global_id), {})
            cam_map[cam_key] = v
            self._dirty.add(object_type)

    def remove(self, object_type: str, global_id: str) -> None:
        with _lock:
            bucket = self._vecs.get(object_type)
            if bucket and global_id in bucket:
                bucket.pop(global_id, None)
                self._dirty.add(object_type)

    def size(self, object_type: str) -> int:
        with _lock:
            return len(self._vecs.get(object_type, {}))

    def max_similarity(
        self,
        object_type: str,
        global_id: str,
        embedding: np.ndarray,
        *,
        exclude_camera_id: int | None = None,
    ) -> float:
        """与某 Global 已存原型的最大余弦；可排除本相机原型（跨镜匹配用）。"""
        q = l2_normalize(np.asarray(embedding, dtype=np.float32).reshape(-1))
        with _lock:
            cam_map = self._vecs.get(object_type, {}).get(str(global_id), {})
            if not cam_map:
                return -1.0
            best = -1.0
            for cam_id, vec in cam_map.items():
                if exclude_camera_id is not None and int(cam_id) == int(exclude_camera_id):
                    continue
                dim = max(q.size, vec.size)
                qa = np.zeros(dim, dtype=np.float32)
                va = np.zeros(dim, dtype=np.float32)
                qa[: q.size] = q
                va[: vec.size] = vec
                best = max(best, float(np.dot(qa, va)))
            return best

    def _rebuild(self, object_type: str) -> None:
        faiss = _import_faiss()
        bucket = self._vecs.get(object_type, {})
        flat_gids: list[str] = []
        rows: list[np.ndarray] = []
        for gid, cam_map in bucket.items():
            for _cam, vec in cam_map.items():
                flat_gids.append(gid)
                rows.append(vec)
        if not rows:
            self._index[object_type] = faiss.IndexFlatIP(128)
            self._gids[object_type] = []
            self._dim[object_type] = 128
            self._dirty.discard(object_type)
            return
        mat = np.stack(rows, axis=0).astype(np.float32)
        dim = int(mat.shape[1])
        index = faiss.IndexFlatIP(dim)
        index.add(mat)
        self._index[object_type] = index
        self._gids[object_type] = flat_gids
        self._dim[object_type] = dim
        self._dirty.discard(object_type)

    def search(
        self,
        object_type: str,
        embedding: np.ndarray,
        *,
        topk: int = 50,
    ) -> list[tuple[str, float]]:
        q = l2_normalize(np.asarray(embedding, dtype=np.float32).reshape(-1))
        with _lock:
            if object_type in self._dirty:
                self._rebuild(object_type)
            index = self._index.get(object_type)
            flat_gids = self._gids.get(object_type, [])
            if index is None or not flat_gids or index.ntotal <= 0:
                return []
            k = min(int(topk) * 3, int(index.ntotal))
        scores, idxs = index.search(q.reshape(1, -1).astype(np.float32), k)
        best_by_gid: dict[str, float] = {}
        for score, idx in zip(scores[0].tolist(), idxs[0].tolist()):
            if idx < 0:
                continue
            gid = flat_gids[int(idx)]
            best_by_gid[gid] = max(best_by_gid.get(gid, -1.0), float(score))
        ranked = sorted(best_by_gid.items(), key=lambda x: -x[1])
        return ranked[: int(topk)]

    def faiss_available(self) -> bool:
        try:
            _import_faiss()
            return True
        except RuntimeError:
            return False
