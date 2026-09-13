"""开放平台全量目录 / 授权判定单测。"""
from services.openapi_catalog import (
    all_scopes,
    app_allows_endpoint,
    build_catalog,
    catalog_stats,
    list_domains,
    resolve_api_endpoint,
    scopes_for_domain,
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


def test_open_scope_decorators_feed_catalog_scope_enumeration_and_domain_grants():
    endpoints = {
        (entry["method"], entry["path"]): entry
        for entry in build_catalog()
    }
    assert endpoints[("GET", "/openapi/v1/model-scenarios")]["scope"] == (
        "model-scenario:read"
    )
    assert endpoints[
        ("GET", "/openapi/v1/model-scenarios/<string:model_key>")
    ]["scope"] == "model-scenario:read"
    assert endpoints[
        ("POST", "/openapi/v1/model-scenarios/<string:model_key>/infer")
    ]["scope"] == "model-scenario:infer"

    expected = {"model-scenario:read", "model-scenario:infer"}
    assert expected <= set(all_scopes())
    assert expected <= set(scopes_for_domain("openapi", include_fine=True))
