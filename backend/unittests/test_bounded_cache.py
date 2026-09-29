from services.bounded_cache import BoundedCache


def test_lru_eviction_preserves_recently_used_model():
    cache = BoundedCache(2)
    cache["first"] = object()
    cache["second"] = object()
    assert cache.get("first") is not None
    cache["third"] = object()
    assert "first" in cache
    assert "second" not in cache
    assert len(cache) == 2


def test_invalid_capacity_is_rejected():
    try:
        BoundedCache(0)
    except ValueError:
        return
    assert False, "Expected ValueError for zero capacity"
