"""开放平台全量目录 / 授权判定单测。"""
from services.openapi_catalog import (
    app_allows_endpoint,
    build_catalog,
    catalog_stats,
    list_domains,
    resolve_api_endpoint,
)


def test_catalog_covers_major_domains():
    stats = catalog_stats()
    assert stats["endpointCount"] >= 140
    assert stats["bridgeableCount"] >= 130
    ids = {d["id"] for d in list_domains()}
    for need in ("auth", "sys_user", "camera", "ai_model", "training", "face", "vehicle"):
        assert need in ids


def test_open_app_not_bridgeable():
    for e in build_catalog():
        if e["path"].startswith("/api/system/open-app"):
            assert e["bridgeable"] is False


def test_resolve_and_domain_scope():
    ep = resolve_api_endpoint("POST", "/api/ai/face/recognize")
    assert ep is not None
    assert ep["domain"] == "face"
    assert ep["bridgeable"] is True
    assert app_allows_endpoint(["domain:face"], ep) is True
    assert app_allows_endpoint(["ai:face:list"], ep) is True
    assert app_allows_endpoint(["domain:camera"], ep) is False
    assert app_allows_endpoint(["*:*:*"], ep) is True


def test_legacy_alias_expands():
    ep = resolve_api_endpoint("POST", "/api/ai/face/recognize")
    assert app_allows_endpoint(["face:recognize"], ep) is True
