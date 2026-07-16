"""人脸底库匹配：按 model_key 加载 embedding 矩阵，余弦相似度 1:N。"""
from __future__ import annotations

import threading

import numpy as np

_lock = threading.Lock()
# model_key -> (person_ids list, names list, matrix NxD float32 L2-normalized, version stamp)
_gallery_cache: dict = {}


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


def invalidate_gallery(model_key: str | None = None):
    """底库变更后清缓存；model_key=None 清全部。"""
    with _lock:
        if model_key is None:
            _gallery_cache.clear()
        else:
            _gallery_cache.pop(model_key, None)


def _load_gallery(model_key: str):
    from models import FaceEmbedding, FacePerson

    rows = (
        FaceEmbedding.query.join(FacePerson)
        .filter(
            FaceEmbedding.model_key == model_key,
            FacePerson.status == "0",
        )
        .all()
    )
    if not rows:
        return [], [], np.zeros((0, 0), dtype=np.float32)

    person_ids = []
    names = []
    vecs = []
    for emb in rows:
        person = emb.person
        if person is None:
            continue
        v = l2_normalize(unpack_embedding(emb.vector, emb.dim))
        person_ids.append(person.id)
        names.append(person.name)
        vecs.append(v)
    if not vecs:
        return [], [], np.zeros((0, 0), dtype=np.float32)
    mat = np.stack(vecs, axis=0).astype(np.float32)
    return person_ids, names, mat


def get_gallery(model_key: str):
    with _lock:
        cached = _gallery_cache.get(model_key)
        if cached is not None:
            return cached
        person_ids, names, mat = _load_gallery(model_key)
        _gallery_cache[model_key] = (person_ids, names, mat)
        return person_ids, names, mat


def match_embedding(
    embedding: np.ndarray,
    model_key: str,
    threshold: float = 0.4,
) -> dict:
    """返回最佳匹配 {personId, name, score, matched}。"""
    q = l2_normalize(embedding)
    person_ids, names, mat = get_gallery(model_key)
    if mat.size == 0 or not person_ids:
        return {
            "personId": None,
            "name": "unknown",
            "score": 0.0,
            "matched": False,
        }
    scores = mat @ q  # cosine
    idx = int(np.argmax(scores))
    score = float(scores[idx])
    matched = score >= float(threshold)
    return {
        "personId": person_ids[idx] if matched else None,
        "name": names[idx] if matched else "unknown",
        "score": round(score, 4),
        "matched": matched,
    }


def avg_embeddings(vectors: list[np.ndarray]) -> np.ndarray:
    """多图登记：平均后 L2 归一化。"""
    if not vectors:
        raise ValueError("无有效人脸特征")
    stacked = np.stack([l2_normalize(v) for v in vectors], axis=0)
    return l2_normalize(stacked.mean(axis=0))
