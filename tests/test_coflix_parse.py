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
