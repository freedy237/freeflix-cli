"""
Offline parsing tests for Coflix (the WordPress theme).

These pin the CURRENT HTML structure (search grid + season tabs + episode
panels) against small fixtures, so if Coflix migrates its layout again the
tests fail in CI — instead of the source silently returning nothing (which is
exactly what happened when it moved to WordPress).
"""

import types

from freeflix_cli.scraping import coflix


def _resp(html):
    r = types.SimpleNamespace(text=html, status_code=200)
    r.raise_for_status = lambda: None
    return r


SEARCH_HTML = """
<div class="md-films-grid">
  <div class="md-manga-card">
    <div class="md-manga-card-cover">
      <a href="https://coflix.esq/film/matrix/">
        <img alt="Matrix" src="//image.tmdb.org/t/p/w342/abc.jpg">
      </a>
    </div>
  </div>
  <div class="md-manga-card">
    <div class="md-manga-card-cover">
      <a href="https://coflix.esq/serie/from/">
        <img alt="From" src="//image.tmdb.org/t/p/w342/def.jpg">
      </a>
    </div>
  </div>
</div>
"""

SERIES_HTML = """
<html><body>
<h1>Game of Thrones</h1>
<img class="cf-poster" src="//image.tmdb.org/t/p/w500/poster.jpg">
<div class="cf-seasons-tabs">
  <button class="cf-server-tab" data-season="0">Saison 1 <span class="cf-server-tab-lang">10 ep</span></button>
  <button class="cf-server-tab" data-season="1">Saison 2 <span class="cf-server-tab-lang">10 ep</span></button>
</div>
<div class="cf-episodes-panel" data-panel="0">
  <div class="cf-episode-item" onclick="window.location.href='https://coflix.esq/episode/got-1x1/'">
    <span class="cf-episode-title">Game of Thrones 1x1</span></div>
  <div class="cf-episode-item" onclick="window.location.href='https://coflix.esq/episode/got-1x2/'">
    <span class="cf-episode-title">Game of Thrones 1x2</span></div>
</div>
<div class="cf-episodes-panel" data-panel="1">
  <div class="cf-episode-item" onclick="window.location.href='https://coflix.esq/episode/got-2x1/'">
    <span class="cf-episode-title">Game of Thrones 2x1</span></div>
</div>
</body></html>
"""


def test_search_grid_parses_title_url_poster(monkeypatch):
    monkeypatch.setattr(coflix, "website_origin", "https://coflix.esq")
    monkeypatch.setattr(coflix, "_get", lambda *a, **k: _resp(SEARCH_HTML))
    res = coflix.search("matrix")
    titles = {r.title for r in res}
    assert "Matrix" in titles and "From" in titles
    matrix = next(r for r in res if r.title == "Matrix")
    assert matrix.url.endswith("/film/matrix/")
    assert matrix.img == "https://image.tmdb.org/t/p/w342/abc.jpg"   # // → https:


def test_series_seasons_and_cover(monkeypatch):
    monkeypatch.setattr(coflix, "website_origin", "https://coflix.esq")
    monkeypatch.setattr(coflix, "_get", lambda *a, **k: _resp(SERIES_HTML))
    s = coflix.get_series("https://coflix.esq/serie/game-of-thrones/")
    assert s.title == "Game of Thrones"
    assert "image.tmdb.org/t/p/w500/" in s.img
    # Season labels now carry their episode counts (no extra fetch).
    assert [t.split("·")[0].strip() for t in [sa.title for sa in s.seasons]] == [
        "Saison 1",
        "Saison 2",
    ]
    assert s.seasons[0].title.startswith("Saison 1 · 2")
    assert s.seasons[1].title.startswith("Saison 2 · 1")
    assert s.seasons[0].url.endswith("#panel=0")


def test_season_episodes_from_panel(monkeypatch):
    monkeypatch.setattr(coflix, "website_origin", "https://coflix.esq")
    monkeypatch.setattr(coflix, "_get", lambda *a, **k: _resp(SERIES_HTML))
    sea = coflix.get_season("https://coflix.esq/serie/game-of-thrones/#panel=1")
    assert sea.title == "Saison 2"
    assert [e.title for e in sea.episodes] == ["Game of Thrones 2x1"]
    assert sea.episodes[0].url.endswith("/episode/got-2x1/")


# ── 2026-11 layout: episodes list their mirrors directly ────────────────

EPISODE_CFSERVERS = """
<html><body>
<h1>Frieren — S01E01</h1>
<div class="cfp-videowrap"><video class="cfp-video"></video></div>
<script>
  var cfPlayerToken = "jwt";
  var cfServers = [
    {"nombre":"LECTEUR MyTV","embed_url":"https:\\/\\/vidmoly.biz\\/embed-hncfog3k416q.html","idioma":"VF"},
    {"nombre":"LECTEUR MOON","embed_url":"https:\\/\\/gn1r5n.org\\/e\\/dsd6mjvfxjwq","idioma":"VF"},
    {"nombre":"LECTEUR VOE","embed_url":"https:\\/\\/voe.sx\\/e\\/tfhh5va6r3nc","idioma":"VF"}
  ];
</script>
</body></html>
"""

MOVIE_AGGREGATOR = """
<html><body>
<script>
  var cfServers = [
    {"nombre":"Lecteurvideo","embed_url":"https:\\/\\/lecteurvideo.com\\/embed.php?id=34359"}
  ];
</script>
</body></html>
"""


def test_cfservers_direct_entries_become_players():
    entries = coflix._cfservers_entries(EPISODE_CFSERVERS)
    assert [p.name for p in entries] == [
        "LECTEUR MyTV", "LECTEUR MOON", "LECTEUR VOE",
    ]
    assert entries[0].url == "https://vidmoly.biz/embed-hncfog3k416q.html"
    assert coflix._cfservers_url(EPISODE_CFSERVERS) == entries[0].url


def test_episode_players_use_direct_mirrors(monkeypatch):
    monkeypatch.setattr(coflix, "website_origin", "https://coflix.esq")
    monkeypatch.setattr(coflix, "_get", lambda *a, **k: _resp(EPISODE_CFSERVERS))
    monkeypatch.setattr(coflix, "_get_cached", lambda *a, **k: EPISODE_CFSERVERS)
    ep = coflix.get_episode("https://coflix.esq/episode/frieren-1x01/")
    # The regression: only the aggregator URL was read, so an episode page
    # listing mirrors directly produced ZERO players.
    assert len(ep.players) == 3
    assert ep.players[0].url.startswith("https://vidmoly.biz/")


def test_movie_still_expands_lecteurvideo_aggregator(monkeypatch):
    from freeflix_cli.scraping.objects import Player
    monkeypatch.setattr(coflix, "website_origin", "https://coflix.esq")
    monkeypatch.setattr(
        coflix, "get_players",
        lambda url: [Player("Lecteurvideo 1", "https://voe.sx/e/abc")],
    )
    from freeflix_cli.scraping.utils import parse_html
    players = coflix._players_from_page(
        parse_html(MOVIE_AGGREGATOR), MOVIE_AGGREGATOR
    )
    assert [p.name for p in players] == ["Lecteurvideo 1"]


def test_latest_uses_shortlinks_and_resolves_them(monkeypatch):
    home = """
    <html><body>
      <a href="https://coflix.esq/?p=101"><img alt="The Chosen"
           src="https://coflix.esq/cover-a.webp"></a>
      <a href="https://coflix.esq/?p=102"><img alt="Lupin"
           src="https://coflix.esq/cover-b.webp"></a>
    </body></html>
    """
    monkeypatch.setattr(coflix, "website_origin", "https://coflix.esq")
    monkeypatch.setattr(coflix, "_get_cached", lambda *a, **k: home)
    monkeypatch.setattr(
        coflix, "_canonical_links",
        lambda ids: {101: "https://coflix.esq/serie/the-chosen/",
                     102: "https://coflix.esq/serie/lupin/"},
    )
    rows = coflix.latest(2)
    assert [r.title for r in rows] == ["The Chosen", "Lupin"]
    assert rows[0].url == "https://coflix.esq/serie/the-chosen/"
    assert rows[0].img == "https://coflix.esq/cover-a.webp"
