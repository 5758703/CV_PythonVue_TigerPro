"""行人 ReID 底库匹配：按 model_key + modality 加载 embedding，余弦相似度 1:N / Top-K。"""
from __future__ import annotations

import logging
import threading

import numpy as np

_lock = threading.Lock()
# (model_key, modality, dim) -> (person_ids, names, matrix, face_person_ids)
_gallery_cache: dict = {}
log = logging.getLogger(__name__)


def pack_embedding(vec: np.ndarray) -> bytes:
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    return arr.tobytes()


def unpack_embedding(blob: bytes, dim: int | None = None) -> np.ndarray:
    arr = np.frombuffer(blob, dtype=np.float32)
    if dim and arr.size != dim:
        raise ValueError(f"embedding 维度不匹配: got {arr.size}, expect {dim}")
    return arr.copy()


def l2_normalize(vec: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    if n < eps:
        return v
    return v / n


def invalidate_gallery(model_key: str | None = None, modality: str | None = None, dim: int | None = None):
    with _lock:
        if model_key is None and modality is None:
            _gallery_cache.clear()
        else:
            keys = list(_gallery_cache.keys())
            for k in keys:
                mk, md, cached_dim = k
                if model_key is not None and mk != model_key:
                    continue
                if modality is not None and md != modality:
                    continue
                if dim is not None and cached_dim != int(dim):
                    continue
                _gallery_cache.pop(k, None)
    invalidate_faiss(model_key, modality)


def _load_gallery(model_key: str, modality: str = "appearance", dim: int | None = None):
    from models import ReidEmbedding, ReidPerson

    rows = (
        ReidEmbedding.query.join(ReidPerson)
        .filter(
            ReidEmbedding.model_key == model_key,
            ReidEmbedding.modality == modality,
            ReidPerson.status == "0",
        )
    )
    if dim is not None:
        rows = rows.filter(ReidEmbedding.dim == int(dim))
    rows = rows.all()
    if not rows:
        return [], [], np.zeros((0, 0), dtype=np.float32), []

    person_ids = []
    names = []
    face_person_ids = []
    vecs = []
    for emb in rows:
        person = emb.person
        if person is None:
            continue
        try:
            if dim is not None and int(emb.dim) != int(dim):
                continue
            v = l2_normalize(unpack_embedding(emb.vector, emb.dim))
        except (TypeError, ValueError) as e:
            log.warning("reid_gallery_invalid_embedding model_key=%s dim=%s error=%s", model_key, dim, e)
            continue
        person_ids.append(person.id)
        names.append(person.name)
        face_person_ids.append(person.face_person_id)
        vecs.append(v)
    if not vecs:
        return [], [], np.zeros((0, 0), dtype=np.float32), []
    mat = np.stack(vecs, axis=0).astype(np.float32)
    return person_ids, names, mat, face_person_ids


def get_gallery(model_key: str, modality: str = "appearance", dim: int | None = None):
    key = (model_key, modality, int(dim) if dim is not None else None)
    with _lock:
        cached = _gallery_cache.get(key)
        if cached is not None:
            return cached
        data = _load_gallery(model_key, modality, dim)
        _gallery_cache[key] = data
        return data


def match_embedding(
    embedding: np.ndarray,
    model_key: str,
    threshold: float = 0.45,
    modality: str = "appearance",
) -> dict:
    q = l2_normalize(embedding)
    person_ids, names, mat, face_person_ids = get_gallery(model_key, modality, dim=int(q.size))
    if mat.size == 0 or not person_ids:
        return {
            "personId": None,
            "facePersonId": None,
            "name": "未知",
            "score": 0.0,
            "matched": False,
        }
    if mat.ndim != 2 or mat.shape[1] != q.size:
        return {
            "personId": None,
            "facePersonId": None,
            "name": "未知",
            "score": 0.0,
            "matched": False,
        }
    scores = mat @ q
    idx = int(np.argmax(scores))
    score = float(scores[idx])
    matched = score >= float(threshold)
    return {
        "personId": person_ids[idx] if matched else None,
        "facePersonId": face_person_ids[idx] if matched else None,
        "name": names[idx] if matched else "未知",
        "candidatePersonId": person_ids[idx],
        "candidateFacePersonId": face_person_ids[idx],
        "candidateName": names[idx],
        "score": round(score, 4),
        "matched": matched,
    }


def topk_match(
    embedding: np.ndarray,
    model_key: str,
    topk: int = 5,
    modality: str = "appearance",
) -> list[dict]:
    q = l2_normalize(embedding)
    person_ids, names, mat, face_person_ids = get_gallery(model_key, modality, dim=int(q.size))
    if mat.size == 0 or not person_ids:
        return []
    if mat.ndim != 2 or mat.shape[1] != q.size:
        return []
    scores = mat @ q
    order = np.argsort(-scores)
    out = []
    seen = set()
    for i in order:
        pid = person_ids[int(i)]
        if pid in seen:
            continue
        seen.add(pid)
        out.append({
            "personId": pid,
            "facePersonId": face_person_ids[int(i)],
            "name": names[int(i)],
            "score": round(float(scores[int(i)]), 4),
        })
        if len(out) >= int(topk):
            break
    return out


def avg_embeddings(vectors: list[np.ndarray]) -> np.ndarray:
    if not vectors:
        raise ValueError("无有效外观特征")
    stacked = np.stack([l2_normalize(v) for v in vectors], axis=0)
    return l2_normalize(stacked.mean(axis=0))


_faiss_cache: dict = {}


def _import_faiss():
    try:
        import faiss  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("未安装 faiss-cpu，请执行: pip install faiss-cpu") from e
    return faiss


def invalidate_faiss(model_key: str | None = None, modality: str | None = None, dim: int | None = None):
    with _lock:
        if model_key is None and modality is None:
            _faiss_cache.clear()
            return
        for k in list(_faiss_cache.keys()):
            mk, md, cached_dim = k
            if model_key is not None and mk != model_key:
                continue
            if modality is not None and md != modality:
                continue
            if dim is not None and cached_dim != int(dim):
                continue
            _faiss_cache.pop(k, None)


def _build_faiss_index(model_key: str, modality: str = "appearance", dim: int | None = None):
    faiss = _import_faiss()
    person_ids, names, mat, face_person_ids = get_gallery(model_key, modality, dim=dim)
    if mat.size == 0 or not person_ids:
        dim = 512
        index = faiss.IndexFlatIP(dim)
        return {
            "index": index,
            "person_ids": [],
            "names": [],
            "face_person_ids": [],
            "dim": dim,
        }
    dim = int(mat.shape[1])
    index = faiss.IndexFlatIP(dim)
    index.add(mat.astype(np.float32))
    return {
        "index": index,
        "person_ids": person_ids,
        "names": names,
        "face_person_ids": face_person_ids,
        "dim": dim,
    }


def match_embedding_faiss(
    embedding: np.ndarray,
    model_key: str,
    threshold: float = 0.45,
    modality: str = "appearance",
) -> dict:
    """FAISS Top-1 匹配；维度不符或 faiss 不可用时回退矩阵乘法。"""
    q = l2_normalize(embedding)
    key = (model_key, modality, int(q.size))
    try:
        with _lock:
            cached = _faiss_cache.get(key)
            if cached is None:
                cached = _build_faiss_index(model_key, modality, dim=int(q.size))
                _faiss_cache[key] = cached
        index = cached["index"]
        person_ids = cached["person_ids"]
        if index.ntotal <= 0 or not person_ids:
            return {
                "personId": None,
                "facePersonId": None,
                "name": "未知",
                "score": 0.0,
                "matched": False,
            }
        dim = int(cached["dim"])
        if q.size != dim:
            return match_embedding(embedding, model_key, threshold=threshold, modality=modality)
        scores, idxs = index.search(q.reshape(1, -1).astype(np.float32), 1)
        idx = int(idxs[0][0])
        score = float(scores[0][0])
        matched = score >= float(threshold)
        return {
            "personId": person_ids[idx] if matched else None,
            "facePersonId": cached["face_person_ids"][idx] if matched else None,
            "name": cached["names"][idx] if matched else "未知",
            "candidatePersonId": person_ids[idx],
            "candidateFacePersonId": cached["face_person_ids"][idx],
            "candidateName": cached["names"][idx],
            "score": round(score, 4),
            "matched": matched,
        }
    except RuntimeError:
        return match_embedding(embedding, model_key, threshold=threshold, modality=modality)
