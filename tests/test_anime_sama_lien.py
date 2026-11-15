"""Anime-Sama 12/11/2026 format: rows are ids, not URLs.

The season page stopped publishing player URLs. Its arrays now hold
``"lien:<row id>"`` and ``epsMeta`` maps each id to a host (``["ansembed.net"]``
or ``["host", 1]`` for a deleted row). The real embed comes from
``/api/lien.php?j=<page token>&l=<id>``, which rejects any request it reads as
cross-site with 403 ``{"erreur":"origine"}`` — browser impersonation sends
``Sec-Fetch-Site: none`` and triggered exactly that.

These tests pin the parsing, the slot metadata, the request shape and the
de-duplication (every indirect row shares one placeholder URL, so keying on
the URL alone collapsed an episode to a single "Lecteur 1").
"""

import pytest

from freeflix_cli.handlers import playback as pb
from freeflix_cli.scraping import anime_sama as asm
from freeflix_cli.scraping.utils import (
    ANIME_SAMA_SIGNED_SENTINEL,
    parse_episodes_from_js,
)

_PAGE = (
    'var eps1 = ["lien:111","lien:112"];'
    'var eps2 = ["lien:113",""];'
    'var epsMeta = {"111":["ansembed.net"],"112":["uqload.vc"],'
    '"113":["sendvid.com",1]};'
    'var languesDispo = ["vostfr"];'
    'var epsJeton = "tok-123";'
)


def test_lien_rows_become_players_with_ids_and_hosts():
    host_map = {"111": ["ansembed.net"], "112": ["uqload.vc"],
                "113": ["sendvid.com", 1]}
    eps = parse_episodes_from_js(_PAGE, host_map=host_map)
    assert len(eps) == 2
    first = eps[0].players
    assert [p.url for p in first] == [ANIME_SAMA_SIGNED_SENTINEL] * 2
    assert first[0].meta["slot"]["lien_id"] == "111"
    assert first[0].meta["host"] == "ansembed.net"
    assert first[0].meta["slot"]["lecteur"] == 1
    assert first[1].meta["slot"]["lien_id"] == "113"   # eps2[0]
    assert eps[1].players[0].meta["slot"]["lien_id"] == "112"  # eps1[1]


def test_deleted_row_is_flagged():
    host_map = {"111": ["ansembed.net"], "112": ["uqload.vc"],
                "113": ["sendvid.com", 1]}
    eps = parse_episodes_from_js(_PAGE, host_map=host_map)
    third = [p for e in eps for p in e.players
             if p.meta["slot"].get("lien_id") == "113"]
    assert third and third[0].meta.get("dead") is True


def test_inline_page_completes_the_slots():
    parsed = asm._parse_inline_season(
        _PAGE, "https://anime-sama.to/catalogue/x/saison1", "vostfr")
    assert parsed
    slot = parsed[0].players[0].meta["slot"]
    assert slot["mode"] == "lien"
    assert slot["jeton"] == "tok-123"
    assert slot["season_url"] == (
        "https://anime-sama.to/catalogue/x/saison1/vostfr")


def test_url_arrays_are_untouched():
    """Older mirrors still publish plain URLs: keep that path byte-identical."""
    js = ("var eps1 = ['https://video.sibnet.ru/shell.php?videoid=1'];"
          "\nvar eps2 = ['https://ansembed.net/embed-x.html'];")
    eps = parse_episodes_from_js(js)
    assert eps[0].players[0].url.startswith("https://video.sibnet.ru/")
    assert eps[0].players[0].meta == {}


class _Resp:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text


class _Scraper:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("headers") or {}))
        for fragment, resp in self.responses:
            if fragment in url:
                return resp
        raise AssertionError("unexpected url " + url)


def test_lien_api_declares_same_origin(monkeypatch):
    """Impersonation alone sends Sec-Fetch-Site:none → 403 "origine"."""
    fake = _Scraper([("/api/lien.php", _Resp(200, '{"u":"https://ansembed.net/e/x.html"}'))])
    monkeypatch.setattr(asm, "scraper", fake)
    monkeypatch.setattr(asm, "website_origin", "https://anime-sama.to")

    url = asm.resolve_lien_id(
        "https://anime-sama.to/catalogue/x/saison1/vostfr", "111", "tok-123")

    assert url == "https://ansembed.net/e/x.html"
    called_url, headers = fake.calls[0]
    assert "l=111" in called_url and "j=tok-123" in called_url
    assert headers.get("Sec-Fetch-Site") == "same-origin"
    assert headers.get("Referer", "").endswith("/vostfr/")


def test_expired_token_is_refreshed_once(monkeypatch):
    fake = _Scraper([
        ("/api/lien.php", _Resp(200, '{"erreur":"expire"}')),
        ("/vostfr/", _Resp(200, 'var epsJeton = "fresh";')),
    ])
    monkeypatch.setattr(asm, "scraper", fake)
    monkeypatch.setattr(asm, "website_origin", "https://anime-sama.to")

    # First call with the stale token → expire; a page read must supply a new
    # one. The same fake answers "expire" again, so the result is None, but we
    # can prove the refresh path ran.
    asm.resolve_lien_id(
        "https://anime-sama.to/catalogue/x/saison1/vostfr", "111", "stale")

    urls = [u for u, _ in fake.calls]
    assert any("/vostfr/" in u for u in urls), "expected a jeton refresh"
    assert any("j=fresh" in u for u in urls), "expected the fresh token used"


def test_absent_row_does_not_retry():
    fake = _Scraper([("/api/lien.php", _Resp(404, '{"erreur":"absent"}'))])
    old = asm.scraper
    asm.scraper = fake
    try:
        assert asm.resolve_lien_id(
            "https://anime-sama.to/catalogue/x/saison1/vostfr",
            "111", "tok") is None
    finally:
        asm.scraper = old
    assert len(fake.calls) == 1, "an absent row must not trigger a page read"


def test_dedup_keeps_each_indirect_reader():
    from freeflix_cli.scraping.objects import Player

    rows = [
        Player("Lecteur 1", ANIME_SAMA_SIGNED_SENTINEL,
               {"slot": {"ep": 1, "lecteur": 1, "lien_id": "1"}}),
        Player("Lecteur 3", ANIME_SAMA_SIGNED_SENTINEL,
               {"slot": {"ep": 1, "lecteur": 3, "lien_id": "2"}}),
    ]
    assert len(pb._dedup_players(rows)) == 2


def test_dedup_still_collapses_real_duplicates():
    from freeflix_cli.scraping.objects import Player

    rows = [Player("Lecteur 1", "https://ansembed.net/e/a.html"),
            Player("Lecteur 2", "https://ansembed.net/e/a.html")]
    assert len(pb._dedup_players(rows)) == 1


@pytest.mark.parametrize("host,expected", [
    ("https://ansembed.net/x", "ansembed"),
    ("", ""),
])
def test_player_host_badge(host, expected):
    from freeflix_cli.scraping.objects import Player

    p = Player("Lecteur 1", host)
    assert pb._player_host(p) == expected


def test_player_host_uses_meta_when_url_is_placeholder():
    from freeflix_cli.scraping.objects import Player

    p = Player("Lecteur 1", ANIME_SAMA_SIGNED_SENTINEL,
               {"slot": {}, "host": "uqload.vc"})
    assert pb._player_host(p) == "uqload"


# ── end-to-end selection path (hermetic) ─────────────────────────────
class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _episode_with_slot():
    from freeflix_cli.scraping.objects import Episode, Player

    return Episode("Épisode 20", [Player(
        "Lecteur 1", ANIME_SAMA_SIGNED_SENTINEL,
        {"slot": {"ep": 20, "lecteur": 1, "lien_id": "111",
                  "mode": "lien", "jeton": "tok",
                  "season_url": "https://anime-sama.to/catalogue/x/saison1/vostfr"}},
    )])


def _stub_flow(monkeypatch, resolver_result):
    from freeflix_cli.tracker import tracker

    played = []
    monkeypatch.setattr(pb.player, "is_supported", lambda url: True)
    monkeypatch.setattr(pb.player, "is_known_offline", lambda url: False)
    monkeypatch.setattr(pb.player, "get_hls_link",
                        lambda url, headers=None: resolver_result)
    monkeypatch.setattr(pb, "spinner", lambda *a, **k: _Ctx())
    monkeypatch.setattr(pb, "play_video",
                        lambda url, **kw: played.append((url, kw)) or True)
    monkeypatch.setattr(pb, "select_from_list", lambda opts, *a, **k: 0)
    monkeypatch.setattr(tracker, "get_analyze_players", lambda: False)
    monkeypatch.setattr(tracker, "get_subtitle_search", lambda: False)
    monkeypatch.setattr(tracker, "set_last_server", lambda *a, **k: None)
    monkeypatch.setattr(tracker, "mark_episode_watched", lambda *a, **k: None)
    monkeypatch.setattr(tracker, "save_progress", lambda *a, **k: None)
    return played


def test_selected_slot_is_resolved_before_playing(monkeypatch):
    played = _stub_flow(monkeypatch, "https://cdn.example/x/master.m3u8")

    ok = pb.play_episode_flow(
        provider_name="Anime-Sama", series_title="X", season_title="Saison 1",
        episode=_episode_with_slot(), series_url="https://anime-sama.to/catalogue/x",
        season_url="https://anime-sama.to/catalogue/x/saison1/vostfr",
        headers={"Referer": "https://anime-sama.to/"},
    )

    assert ok is True
    assert len(played) == 1
    url, kwargs = played[0]
    assert url == "https://cdn.example/x/master.m3u8"
    # The media URL goes straight to the player: no second resolution.
    assert kwargs.get("is_direct") is True


def test_unopenable_slot_does_not_launch_the_player(monkeypatch):
    played = _stub_flow(monkeypatch, None)
    # First pass picks the slot (fails), second pass picks Back.
    calls = {"n": 0}

    def pick(options, *a, **k):
        calls["n"] += 1
        return 0 if calls["n"] == 1 else len(options) - 1

    monkeypatch.setattr(pb, "select_from_list", pick)

    ok = pb.play_episode_flow(
        provider_name="Anime-Sama", series_title="X", season_title="Saison 1",
        episode=_episode_with_slot(), series_url="https://anime-sama.to/catalogue/x",
        season_url="https://anime-sama.to/catalogue/x/saison1/vostfr",
        headers={"Referer": "https://anime-sama.to/"},
    )

    assert ok is False
    assert played == []
