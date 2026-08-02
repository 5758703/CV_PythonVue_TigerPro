"""离岗检测用 FAISS 人脸底库：IndexFlatIP（L2 归一化后内积=余弦）。"""
from __future__ import annotations

import threading
from typing import Any

import numpy as np

from services.face_gallery import l2_normalize, unpack_embedding

_lock = threading.Lock()
# model_key -> {index, person_ids, names, dim}
_faiss_cache: dict[str, dict[str, Any]] = {}


def invalidate(model_key: str | None = None) -> None:
    """底库变更后清 FAISS 缓存；model_key=None 清全部。"""
    with _lock:
        if model_key is None:
            _faiss_cache.clear()
        else:
            _faiss_cache.pop(model_key, None)


def _import_faiss():
    try:
        import faiss  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "未安装 faiss-cpu，请执行: pip install faiss-cpu"
        ) from e
    return faiss


def _load_rows(model_key: str):
    from models import FaceEmbedding, FacePerson

    rows = (
        FaceEmbedding.query.join(FacePerson)
        .filter(
            FaceEmbedding.model_key == model_key,
            FacePerson.status == "0",
        )
        .all()
    )
    person_ids: list[int] = []
    names: list[str] = []
    vecs: list[np.ndarray] = []
    for emb in rows:
        person = emb.person
        if person is None:
            continue
        v = l2_normalize(unpack_embedding(emb.vector, emb.dim))
        person_ids.append(int(person.id))
        names.append(str(person.name or ""))
        vecs.append(v)
    return person_ids, names, vecs


def build_index_from_vectors(
    person_ids: list[int],
    names: list[str],
    vectors: list[np.ndarray],
) -> dict[str, Any]:
    """由内存向量构建 FAISS 索引（单测/无 DB 场景）。"""
    faiss = _import_faiss()
    if not vectors:
        dim = 512
        index = faiss.IndexFlatIP(dim)
        return {
            "index": index,
            "person_ids": [],
            "names": [],
            "dim": dim,
        }
    mat = np.stack([l2_normalize(v) for v in vectors], axis=0).astype(np.float32)
    dim = int(mat.shape[1])
    index = faiss.IndexFlatIP(dim)
    index.add(mat)
    return {
        "index": index,
        "person_ids": list(person_ids),
        "names": list(names),
        "dim": dim,
    }


def get_index(model_key: str) -> dict[str, Any]:
    with _lock:
        cached = _faiss_cache.get(model_key)
        if cached is not None:
            return cached
        person_ids, names, vecs = _load_rows(model_key)
        packed = build_index_from_vectors(person_ids, names, vecs)
        _faiss_cache[model_key] = packed
        return packed


def put_index(model_key: str, packed: dict[str, Any]) -> None:
    """测试/注入用：直接放入缓存。"""
    with _lock:
        _faiss_cache[model_key] = packed


def search(
    embedding: np.ndarray,
    model_key: str,
    *,
    threshold: float = 0.4,
    topk: int = 5,
    staff_ids: list[int] | set[int] | None = None,
    index_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """FAISS 1:N。若 staff_ids 非空，仅名单内命中才算 matched。"""
    q = l2_normalize(embedding).astype(np.float32).reshape(1, -1)
    pack = index_pack if index_pack is not None else get_index(model_key)
    index = pack["index"]
    person_ids: list[int] = pack["person_ids"]
    names: list[str] = pack["names"]
    allow = {int(x) for x in (staff_ids or [])} if staff_ids is not None else None

    empty = {
        "personId": None,
        "name": "unknown",
        "score": 0.0,
        "matched": False,
    }
    if index.ntotal <= 0 or not person_ids:
        return empty

    k = min(int(topk), int(index.ntotal))
    scores, idxs = index.search(q, k)
    best = empty
    for score, idx in zip(scores[0].tolist(), idxs[0].tolist()):
        if idx < 0:
            continue
        pid = int(person_ids[idx])
        name = names[idx]
        sc = float(score)
        if allow is not None and pid not in allow:
            continue
        if sc < float(threshold):
            continue
        return {
            "personId": pid,
            "name": name,
            "score": round(sc, 4),
            "matched": True,
        }
    # 若允许名单过滤后无命中，返回全局最高分（未匹配）便于调试
    if idxs[0][0] >= 0:
        i0 = int(idxs[0][0])
        best = {
            "personId": None,
            "name": "unknown",
            "score": round(float(scores[0][0]), 4),
            "matched": False,
            "topPersonId": int(person_ids[i0]),
            "topName": names[i0],
        }
    return best
