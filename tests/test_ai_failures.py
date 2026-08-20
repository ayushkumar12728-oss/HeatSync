"""Nemotron failure-state tests (Phase 21).

Every failure category is exercised with a mocked ``requests.post`` so no real
NIM call is made. The backend must never crash because Nemotron fails and must
return the exact documented category.
"""

from __future__ import annotations

import pytest

from backend.services.nemotron import (
    ERROR_AUTH,
    ERROR_EMPTY,
    ERROR_MALFORMED,
    ERROR_PROVIDER,
    ERROR_RATE_LIMIT,
    ERROR_TIMEOUT,
    NemotronClient,
    NemotronConfig,
    NemotronError,
)

SYSTEM_PROMPT = "You are a helpful assistant."


def _client(monkeypatch, fake_post) -> NemotronClient:
    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    return NemotronClient(NemotronConfig(
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        model="nvidia/nvidia-nemotron-nano-9b-v2",
        timeout_seconds=5.0,
        max_retries=1,
        max_tokens=512,
        temperature=0.2,
    ))


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body

    @property
    def text(self):
        return str(self._body)


def test_missing_key_is_auth_error(monkeypatch):
    import requests
    called = {"n": 0}

    def _post(*a, **k):
        called["n"] += 1
        raise AssertionError("must not call the provider without a key")

    monkeypatch.setattr(requests, "post", _post)
    client = NemotronClient(NemotronConfig(
        api_key=None, base_url="https://x/v1", model="m",
        timeout_seconds=5.0, max_retries=0, max_tokens=512, temperature=0.2,
    ))
    with pytest.raises(NemotronError) as exc_info:
        client.ask("question", SYSTEM_PROMPT)
    assert exc_info.value.category == ERROR_AUTH
    assert called["n"] == 0  # no network call without a key


def test_401_is_auth_error(monkeypatch):
    client = _client(monkeypatch, lambda *a, **k: _Resp(401, {"detail": "bad key"}))
    with pytest.raises(NemotronError) as exc_info:
        client.ask("q", SYSTEM_PROMPT)
    assert exc_info.value.category == ERROR_AUTH


def test_403_is_auth_error(monkeypatch):
    client = _client(monkeypatch, lambda *a, **k: _Resp(403))
    with pytest.raises(NemotronError) as exc_info:
        client.ask("q", SYSTEM_PROMPT)
    assert exc_info.value.category == ERROR_AUTH


def test_429_is_rate_limit(monkeypatch):
    client = _client(monkeypatch, lambda *a, **k: _Resp(429))
    with pytest.raises(NemotronError) as exc_info:
        client.ask("q", SYSTEM_PROMPT)
    assert exc_info.value.category == ERROR_RATE_LIMIT


def test_500_is_provider_unavailable(monkeypatch):
    client = _client(monkeypatch, lambda *a, **k: _Resp(500))
    with pytest.raises(NemotronError) as exc_info:
        client.ask("q", SYSTEM_PROMPT)
    assert exc_info.value.category == ERROR_PROVIDER


def test_timeout_is_timeout_category(monkeypatch):
    import requests

    def _timeout(*a, **k):
        raise requests.exceptions.Timeout("slow")

    client = _client(monkeypatch, _timeout)
    with pytest.raises(NemotronError) as exc_info:
        client.ask("q", SYSTEM_PROMPT)
    assert exc_info.value.category == ERROR_TIMEOUT


def test_connection_error_is_provider_unavailable(monkeypatch):
    import requests

    def _conn(*a, **k):
        raise requests.exceptions.ConnectionError("dns")

    client = _client(monkeypatch, _conn)
    with pytest.raises(NemotronError) as exc_info:
        client.ask("q", SYSTEM_PROMPT)
    assert exc_info.value.category == ERROR_PROVIDER


def test_empty_response(monkeypatch):
    client = _client(monkeypatch, lambda *a, **k: _Resp(200, {"choices": []}))
    with pytest.raises(NemotronError) as exc_info:
        client.ask("q", SYSTEM_PROMPT)
    assert exc_info.value.category == ERROR_EMPTY


def test_empty_content(monkeypatch):
    client = _client(monkeypatch, lambda *a, **k: _Resp(
        200, {"choices": [{"message": {"content": "   "}}]}))
    with pytest.raises(NemotronError) as exc_info:
        client.ask("q", SYSTEM_PROMPT)
    assert exc_info.value.category == ERROR_EMPTY


def test_malformed_response(monkeypatch):
    class _Bad:
        status_code = 200

        def json(self):
            raise ValueError("not json")

    client = _client(monkeypatch, lambda *a, **k: _Bad())
    with pytest.raises(NemotronError) as exc_info:
        client.ask("q", SYSTEM_PROMPT)
    assert exc_info.value.category == ERROR_MALFORMED


def test_retries_bounded(monkeypatch):
    """max_retries=1 -> at most 2 attempts for a transient 500."""
    calls = {"n": 0}

    def _flaky(*a, **k):
        calls["n"] += 1
        return _Resp(500)

    client = _client(monkeypatch, _flaky)
    with pytest.raises(NemotronError) as exc_info:
        client.ask("q", SYSTEM_PROMPT)
    assert exc_info.value.category == ERROR_PROVIDER
    assert calls["n"] == 2  # 1 + max_retries(1)


def test_success_returns_answer(monkeypatch):
    client = _client(monkeypatch, lambda *a, **k: _Resp(
        200, {"choices": [{"message": {"content": "A clear answer."}}]}))
    assert client.ask("q", SYSTEM_PROMPT) == "A clear answer."


def test_max_tokens_capped(monkeypatch):
    """A caller cannot exceed the configured max_tokens budget."""
    seen = {}

    def _capture(*a, **k):
        seen["payload"] = k.get("json", {})
        return _Resp(200, {"choices": [{"message": {"content": "ok"}}]})

    client = _client(monkeypatch, _capture)
    client.ask("q", SYSTEM_PROMPT, max_tokens=10_000)
    assert seen["payload"]["max_tokens"] == 512  # capped at config
