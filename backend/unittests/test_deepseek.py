import json
import pytest
import deepseek


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_chat_json_parses_content(monkeypatch):
    content = json.dumps({"summary": "ok", "risk": {"level": "低", "desc": "无"}})
    payload = {"choices": [{"message": {"content": content}}]}
    monkeypatch.setattr(deepseek.requests, "post",
                        lambda *a, **k: _FakeResp(payload))
    out = deepseek.chat_json("sys", "user")
    assert out["summary"] == "ok"
    assert out["risk"]["level"] == "低"


def test_chat_json_raises_on_network_error(monkeypatch):
    def _boom(*a, **k):
        raise deepseek.requests.exceptions.Timeout("timeout")
    monkeypatch.setattr(deepseek.requests, "post", _boom)
    with pytest.raises(deepseek.DeepSeekError):
        deepseek.chat_json("sys", "user")
