"""animes-sama.fr: the mirror that changed everything.

That domain (with an **s**) diverged from anime-sama.to in three ways, and all
three broke FreeFlix silently:

1. Search cards use a third layout (``div.card-title``, no heading), so every
   query returned 0 results.
2. ``<lang>/episodes.js`` answers 404 — the episode arrays are inlined in the
   season page instead, so every season showed "No episodes found".
3. Those inline arrays hold only ``"1"``/``""`` availability flags: the real
   player URL is minted on demand by the site's signed ``/api/player/sign``
   endpoint, so even with episodes listed no player was playable.
"""

import pytest

from freeflix_cli.scraping import anime_sama as asm
from freeflix_cli.scraping import player as pl
from freeflix_cli.scraping.resilient import DEFAULT_SELECTORS
from freeflix_cli.scraping.utils import (
    ANIME_SAMA_SIGNED_SENTINEL,
    parse_episodes_from_js,
)


@pytest.fixture(autouse=True)
def _reset_resolver():
    pl.set_signed_player_resolver(None)
    yield
    pl.set_signed_player_resolver(None)


# ── 1. search layout ─────────────────────────────────────────────────
def test_card_title_selector_is_available():
    titles = DEFAULT_SELECTORS["anime-sama"]["search_title"]
    assert "div.card-title" in titles
    cards = DEFAULT_SELECTORS["anime-sama"]["search_card"]
    assert "div.catalog-card" in cards


# ── 2. episodes come from the season page ────────────────────────────
def test_availability_flags_become_players():
    js = 'var eps1 = ["1","1","",""];\nvar eps2 = ["1","","1",""];'
    episodes = parse_episodes_from_js(js)
    assert len(episodes) == 3
    assert [p.name for p in episodes[0].players] == ["Lecteur 1", "Lecteur 2"]
    assert episodes[0].players[0].url == ANIME_SAMA_SIGNED_SENTINEL


def test_availability_slots_carry_episode_and_reader():
    """The reader index is its real position (a gap in eps2 is kept)."""
    js = 'var eps1 = ["1","1"];\nvar eps3 = ["","1"];'
    episodes = parse_episodes_from_js(js)
    slots = [p.meta["slot"] for p in episodes[1].players]
    assert slots == [{"ep": 2, "lecteur": 1}, {"ep": 2, "lecteur": 3}]


def test_url_arrays_still_parse_unchanged():
    """The .to/.pw format must keep working byte for byte."""
    js = ("var eps1 = ['https://video.sibnet.ru/shell.php?videoid=1'];"
          "\nvar eps2 = ['https://ansembed.net/embed-x.html'];")
    episodes = parse_episodes_from_js(js)
    assert len(episodes) == 1
    assert [p.url for p in episodes[0].players] == [
        "https://video.sibnet.ru/shell.php?videoid=1",
        "https://ansembed.net/embed-x.html",
    ]
    assert episodes[0].players[0].meta == {}


# ── 3. signed player resolution ──────────────────────────────────────
def test_sentinel_is_unsupported_without_a_resolver():
    assert pl.is_supported(ANIME_SAMA_SIGNED_SENTINEL) is False


def test_sentinel_is_supported_with_a_resolver():
    pl.set_signed_player_resolver(lambda headers: "https://x/y")
    assert pl.is_supported(ANIME_SAMA_SIGNED_SENTINEL) is True


def test_resolver_receives_the_slot(monkeypatch):
    seen = {}

    def resolver(headers):
        seen.update(headers)
        return "https://animes-sama.fr/player/media?t=abc"

    pl.set_signed_player_resolver(resolver)
    link = pl.get_hls_link(ANIME_SAMA_SIGNED_SENTINEL,
                           {"_anime_sama_slot": {"ep": 4, "lecteur": 2}})
    assert seen.get("_anime_sama_slot") == {"ep": 4, "lecteur": 2}
    # An already-resolved media URL is returned as-is (nothing to scrape).
    assert link == "https://animes-sama.fr/player/media?t=abc"


def test_resolver_failure_returns_none(monkeypatch):
    pl.set_signed_player_resolver(lambda headers: None)
    assert pl.get_hls_link(ANIME_SAMA_SIGNED_SENTINEL, {}) is None


def test_signed_helper_reads_csrf_and_posts(monkeypatch):
    """resolve_signed_player must sign with the SAME session that holds the
    CSRF cookie, otherwise the site answers 419."""
    calls = {}

    class _Resp:
        def __init__(self, text, status=200):
            self.text = text
            self.status_code = status
            self.ok = True

        def raise_for_status(self):
            pass

    class _Sess:
        def __init__(self, *a, **k):
            self.curl_options = {}

        def get(self, url, **k):
            calls["get"] = url
            if "/player/" in url:
                return _Resp('data-resolve-token="TOK"')
            return _Resp('csrf: "' + "a0" * 32 + '"')

        def post(self, url, **k):
            calls.setdefault("post", url)
            if "/api/player/sign/" in url:
                return _Resp('{"ok":true,"url":"/player/x?ep=1&lecteur=2"}')
            if "/api/player/resolve" in url:
                return _Resp('{"play_url":"/player/media?t=zzz"}')
            raise AssertionError("unexpected post " + url)

        def close(self):
            pass

    monkeypatch.setattr(asm, "cffi_requests", type("M", (), {"Session": _Sess}))
    monkeypatch.setattr(asm, "website_origin", "https://animes-sama.fr")

    out = asm.resolve_signed_player(
        "https://animes-sama.fr/catalogue/serie/saison1/vostfr", 1, 2)
    assert out == "https://animes-sama.fr/player/media?t=zzz"
    assert calls["post"].endswith("/api/player/sign/serie/saison1/vostfr")
