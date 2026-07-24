"""开放平台鉴权与 Job 公共结构单测（无 DB）。"""
from security_open import _match_scope, generate_api_key, hash_api_key, key_prefix
from services import job_store
from services.metrics_registry import incr, render_prometheus, snapshot
from services.webhook import _sign


def test_hash_api_key_stable():
    k = "tp_live_demo_change_me_in_production_01"
    assert hash_api_key(k) == hash_api_key(k)
    assert hash_api_key(k) != hash_api_key(k + "x")
    assert len(hash_api_key(k)) == 64


def test_generate_api_key_format():
    k = generate_api_key()
    assert k.startswith("tp_live_")
    assert len(k) > 20
    assert key_prefix(k) == k[:12]


def test_match_scope():
    assert _match_scope("", ["vision:detect"]) is True
    assert _match_scope("vision:detect", ["vision:detect"]) is True
    assert _match_scope("vision:detect", ["vision:*"]) is True
    assert _match_scope("vision:detect", ["*"]) is True
    assert _match_scope("vision:detect", ["face:recognize"]) is False
    assert _match_scope("face:recognize", ["vision:*"]) is False


def test_public_job_shape():
    pub = job_store.public_job({
        "id": "abc",
        "capability": "vision:detect",
        "status": "queued",
        "progress": 0,
        "message": "",
        "result": None,
        "error": None,
        "meta": {"x": 1},
        "createdAt": 1.0,
        "updatedAt": 2.0,
    })
    assert pub["id"] == "abc"
    assert "meta" not in pub


def test_webhook_sign():
    sig = _sign("secret", b'{"a":1}')
    assert len(sig) == 64
    assert sig == _sign("secret", b'{"a":1}')


def test_metrics_registry():
    incr("tigerpro_test_counter", 2, route="x")
    text = render_prometheus()
    assert "tigerpro_up 1" in text
    snap = snapshot()
    assert "uptimeSec" in snap
