"""行人 ReID 底库匹配：按 model_key + modality 加载 embedding，余弦相似度 1:N / Top-K。"""
from __future__ import annotations

import threading

import numpy as np

_lock = threading.Lock()
# (model_key, modality) -> (person_ids, names, matrix, face_person_ids)
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


def invalidate_gallery(model_key: str | None = None, modality: str | None = None):
    with _lock:
        if model_key is None and modality is None:
            _gallery_cache.clear()
            return
        keys = list(_gallery_cache.keys())
        for k in keys:
            mk, md = k
            if model_key is not None and mk != model_key:
                continue
            if modality is not None and md != modality:
                continue
            _gallery_cache.pop(k, None)


def _load_gallery(model_key: str, modality: str = "appearance"):
    from models import ReidEmbedding, ReidPerson

    rows = (
        ReidEmbedding.query.join(ReidPerson)
        .filter(
            ReidEmbedding.model_key == model_key,
            ReidEmbedding.modality == modality,
            ReidPerson.status == "0",
        )
        .all()
    )
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
        v = l2_normalize(unpack_embedding(emb.vector, emb.dim))
        person_ids.append(person.id)
        names.append(person.name)
        face_person_ids.append(person.face_person_id)
        vecs.append(v)
    if not vecs:
        return [], [], np.zeros((0, 0), dtype=np.float32), []
    mat = np.stack(vecs, axis=0).astype(np.float32)
    return person_ids, names, mat, face_person_ids


def get_gallery(model_key: str, modality: str = "appearance"):
    key = (model_key, modality)
    with _lock:
        cached = _gallery_cache.get(key)
        if cached is not None:
            return cached
        data = _load_gallery(model_key, modality)
        _gallery_cache[key] = data
        return data


def match_embedding(
    embedding: np.ndarray,
    model_key: str,
    threshold: float = 0.45,
    modality: str = "appearance",
) -> dict:
    q = l2_normalize(embedding)
    person_ids, names, mat, face_person_ids = get_gallery(model_key, modality)
    if mat.size == 0 or not person_ids:
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
    person_ids, names, mat, face_person_ids = get_gallery(model_key, modality)
    if mat.size == 0 or not person_ids:
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
