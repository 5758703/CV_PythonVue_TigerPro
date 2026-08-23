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
    """会话级内存向量库：object_type -> {global_id: embedding}。"""

    def __init__(self):
        self._vecs: dict[str, dict[str, np.ndarray]] = {}
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

    def upsert(self, object_type: str, global_id: str, embedding: np.ndarray | None) -> None:
        if embedding is None:
            return
        v = l2_normalize(np.asarray(embedding, dtype=np.float32).reshape(-1))
        with _lock:
            bucket = self._vecs.setdefault(object_type, {})
            bucket[str(global_id)] = v
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

    def _rebuild(self, object_type: str) -> None:
        faiss = _import_faiss()
        bucket = self._vecs.get(object_type, {})
        gids = list(bucket.keys())
        if not gids:
            self._index[object_type] = faiss.IndexFlatIP(128)
            self._gids[object_type] = []
            self._dim[object_type] = 128
            self._dirty.discard(object_type)
            return
        mat = np.stack([bucket[g] for g in gids], axis=0).astype(np.float32)
        dim = int(mat.shape[1])
        index = faiss.IndexFlatIP(dim)
        index.add(mat)
        self._index[object_type] = index
        self._gids[object_type] = gids
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
            gids = self._gids.get(object_type, [])
            if index is None or not gids or index.ntotal <= 0:
                return []
            k = min(int(topk), int(index.ntotal))
        scores, idxs = index.search(q.reshape(1, -1).astype(np.float32), k)
        out: list[tuple[str, float]] = []
        for score, idx in zip(scores[0].tolist(), idxs[0].tolist()):
            if idx < 0:
                continue
            out.append((gids[int(idx)], float(score)))
        return out

    def faiss_available(self) -> bool:
        try:
            _import_faiss()
            return True
        except RuntimeError:
            return False
