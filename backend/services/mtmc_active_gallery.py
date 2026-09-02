"""MTMC 在线 Active Gallery（L1）：FAISS IndexFlatIP 加速 Global 候选检索。"""
from __future__ import annotations

import threading
from typing import Any

import numpy as np

from services.reid_gallery import l2_normalize

_lock = threading.Lock()


def _space_id(model_key: str | None, embedding: np.ndarray, model_version: str | None = None) -> tuple[str, int, str | None]:
    return (str(model_key or "legacy"), int(np.asarray(embedding).size), model_version)


def _import_faiss():
    try:
        import faiss  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("未安装 faiss-cpu，请执行: pip install faiss-cpu") from e
    return faiss


class MtmcActiveGallery:
    """会话级内存向量库：object_type -> global_id -> camera_id -> embedding。"""

    def __init__(self):
        # (object_type, model_key, dim, version) -> global_id -> camera_id -> embedding
        self._vecs: dict[tuple, dict[str, dict[int, np.ndarray]]] = {}
        self._dirty: set[tuple] = set()
        self._index: dict[tuple, Any] = {}
        self._gids: dict[tuple, list[str]] = {}
        self._dim: dict[tuple, int] = {}

    def clear(self, object_type: str | None = None) -> None:
        with _lock:
            if object_type is None:
                self._vecs.clear()
                self._dirty.clear()
                self._index.clear()
                self._gids.clear()
                self._dim.clear()
                return
            keys = [key for key in self._vecs if key[0] == object_type]
            for key in keys:
                self._vecs.pop(key, None)
                self._dirty.discard(key)
                self._index.pop(key, None)
                self._gids.pop(key, None)
                self._dim.pop(key, None)

    def upsert(
        self,
        object_type: str,
        global_id: str,
        embedding: np.ndarray | None,
        *,
        camera_id: int | None = None,
        model_key: str | None = None,
        model_version: str | None = None,
    ) -> None:
        if embedding is None:
            return
        v = l2_normalize(np.asarray(embedding, dtype=np.float32).reshape(-1))
        cam_key = int(camera_id) if camera_id is not None else -1
        bucket_key = (object_type, *_space_id(model_key, v, model_version))
        with _lock:
            bucket = self._vecs.setdefault(bucket_key, {})
            cam_map = bucket.setdefault(str(global_id), {})
            previous = cam_map.get(cam_key)
            if previous is None:
                cam_map[cam_key] = v
            else:
                # Keep a camera-specific prototype stable across weak or
                # partially occluded observations.
                if previous.size != v.size:
                    raise ValueError("active gallery model-space dimension changed")
                cam_map[cam_key] = l2_normalize(0.8 * previous + 0.2 * v)
            self._dirty.add(bucket_key)

    def remove(self, object_type: str, global_id: str) -> None:
        with _lock:
            for key, bucket in self._vecs.items():
                if key[0] == object_type and global_id in bucket:
                    bucket.pop(global_id, None)
                    self._dirty.add(key)

    def size(self, object_type: str) -> int:
        with _lock:
            return len({gid for key, bucket in self._vecs.items() if key[0] == object_type for gid in bucket})

    def cameras_for_global(self, object_type: str, global_id: str) -> set[int]:
        """某 Global 已存原型的相机集合（不含 -1 占位）。"""
        with _lock:
            return {
                int(c) for key, bucket in self._vecs.items() if key[0] == object_type
                for c in bucket.get(str(global_id), {}) if int(c) >= 0
            }

    def max_similarity(
        self,
        object_type: str,
        global_id: str,
        embedding: np.ndarray,
        *,
        exclude_camera_id: int | None = None,
        model_key: str | None = None,
        model_version: str | None = None,
    ) -> float:
        """与某 Global 已存原型的最大余弦；可排除本相机原型（跨镜匹配用）。"""
        q = l2_normalize(np.asarray(embedding, dtype=np.float32).reshape(-1))
        bucket_key = (object_type, *_space_id(model_key, q, model_version))
        with _lock:
            cam_map = self._vecs.get(bucket_key, {}).get(str(global_id), {})
            if not cam_map:
                return -1.0
            best = -1.0
            for cam_id, vec in cam_map.items():
                if exclude_camera_id is not None and int(cam_id) == int(exclude_camera_id):
                    continue
                if q.size != vec.size:
                    continue
                best = max(best, float(np.dot(q, vec)))
            return best

    def _rebuild(self, bucket_key: tuple) -> None:
        faiss = _import_faiss()
        bucket = self._vecs.get(bucket_key, {})
        flat_gids: list[str] = []
        rows: list[np.ndarray] = []
        for gid, cam_map in bucket.items():
            for _cam, vec in cam_map.items():
                flat_gids.append(gid)
                rows.append(vec)
        if not rows:
            self._index[bucket_key] = faiss.IndexFlatIP(int(bucket_key[2]))
            self._gids[bucket_key] = []
            self._dim[bucket_key] = int(bucket_key[2])
            self._dirty.discard(bucket_key)
            return
        mat = np.stack(rows, axis=0).astype(np.float32)
        dim = int(mat.shape[1])
        index = faiss.IndexFlatIP(dim)
        index.add(mat)
        self._index[bucket_key] = index
        self._gids[bucket_key] = flat_gids
        self._dim[bucket_key] = dim
        self._dirty.discard(bucket_key)

    def search(
        self,
        object_type: str,
        embedding: np.ndarray,
        *,
        topk: int = 50,
        model_key: str | None = None,
        model_version: str | None = None,
    ) -> list[tuple[str, float]]:
        q = l2_normalize(np.asarray(embedding, dtype=np.float32).reshape(-1))
        bucket_key = (object_type, *_space_id(model_key, q, model_version))
        with _lock:
            if bucket_key in self._dirty:
                self._rebuild(bucket_key)
            index = self._index.get(bucket_key)
            flat_gids = self._gids.get(bucket_key, [])
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
