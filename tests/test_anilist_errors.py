"""AniList failures must be actionable, not raw HTTP dumps."""

import pytest

from freeflix_cli.anilist import AniListClient


@pytest.fixture(autouse=True)
def _english_ui(monkeypatch):
    """Messages are asserted in English (the local UI may be French)."""
    monkeypatch.setattr("freeflix_cli.anilist.t", lambda s: s)


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def _client(monkeypatch, responses):
    c = AniListClient("token")
    calls = []

    def fake_post(*a, **k):
        calls.append(k)
        return responses[min(len(calls), len(responses)) - 1]

    monkeypatch.setattr("freeflix_cli.anilist.requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    return c, calls


def test_invalid_token_is_reported_once_and_not_retried(monkeypatch, capsys):
    body = {"data": None,
            "errors": [{"message": "Invalid token", "status": 400}]}
    c, calls = _client(monkeypatch, [_Resp(400, body)])
    assert c.validate_token() is None
    assert len(calls) == 1
    assert c.last_status == 400 and "Invalid token" in c.last_error
    out = capsys.readouterr().out
    assert "invalid or expired" in out


def test_expired_token_401_uses_the_same_message(monkeypatch, capsys):
    c, calls = _client(
        monkeypatch, [_Resp(401, {"errors": [{"message": "Unauthorized."}]})]
    )
    assert c._query("query { Viewer { id } }") is None
    assert len(calls) == 1
    assert "invalid or expired" in capsys.readouterr().out


def test_transient_5xx_is_retried_then_succeeds(monkeypatch):
    c, calls = _client(monkeypatch, [
        _Resp(503, {}),
        _Resp(200, {"data": {"Page": {"media": [{"id": 1}]}}}),
    ])
    assert c._query("query { Page(page:1, perPage:1){ media(type: ANIME){ id } } }")
    assert len(calls) == 2


def test_trending_never_sends_a_dead_token(monkeypatch):
    c, calls = _client(
        monkeypatch, [_Resp(200, {"data": {"Page": {"media": [{"id": 3}]}}})]
    )
    assert c.trending(1) == [{"id": 3}]
    assert "Authorization" not in calls[0]["headers"]
