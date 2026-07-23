"""
Tests for the hot-patchable extractor layer (scraping.resilient) and the
Anime-Sama search/series parsing that now rides on it.

These are fully offline (BeautifulSoup over sample HTML) — they pin that the
default selectors still work AND that a remote override takes effect, so a
broken source can be repaired via config without a release.
"""

from bs4 import BeautifulSoup

from freeflix_cli.scraping import resilient as R


def test_defaults_extract_title_cover_genres():
    soup = BeautifulSoup(
        '<html><head><meta property="og:image" content="https://cdn/x.jpg"></head>'
        '<body><h1>Dandadan</h1>'
        '<a class="text-sm text-gray-300">Action, Comédie</a></body></html>',
        "html5lib",
    )
    assert R.first_text(soup, "anime-sama", "series_title") == "Dandadan"
    assert R.first_attr(soup, "anime-sama", "series_cover", "content", "src") == "https://cdn/x.jpg"
    el = R.first(soup, "anime-sama", "series_genres")
    assert el.get_text(strip=True) == "Action, Comédie"


def test_cover_lazy_attr_fallback():
    soup = BeautifulSoup('<img id="coverOeuvre" data-src="//h/p.jpg">', "html5lib")
    got = R.first_attr(soup, "anime-sama", "series_cover", "content", "src", "data-src")
    assert got == "//h/p.jpg"


def test_missing_returns_default():
    soup = BeautifulSoup("<div>nothing</div>", "html5lib")
    assert R.first_text(soup, "anime-sama", "series_title", default="?") == "?"
    assert R.first(soup, "anime-sama", "series_title") is None


def test_remote_override_string_and_list():
    R._merge({"anime-sama": {"series_title": ".newtitle"}})
    try:
        soup = BeautifulSoup('<span class="newtitle">Patched</span>', "html5lib")
        assert R.first_text(soup, "anime-sama", "series_title") == "Patched"
    finally:
        # restore the default so other tests aren't affected
        R._merge({"anime-sama": {"series_title": R.DEFAULT_SELECTORS["anime-sama"]["series_title"]}})


def test_unknown_source_is_empty():
    assert R.get("does-not-exist", "whatever") == []


def test_anime_sama_search_parses_with_defaults(monkeypatch):
    from freeflix_cli.scraping import anime_sama as a
    html = """
    <div id="list_catalog">
      <div>
        <a href="https://x/catalogue/one-piece/"><img src="//cdn/op.jpg"></a>
        <div class="card-content"><h2>One Piece</h2><p class="info-value">Action, Aventure</p></div>
      </div>
      <div>
        <p class="info-value">Scans</p>
        <a href="https://x/catalogue/scan-only/"><img src="//cdn/s.jpg"></a>
        <div class="card-content"><h2>Scan Only</h2></div>
      </div>
    </div>
    """

    class _Resp:
        text = html
        status_code = 200

        def raise_for_status(self):
            return None

    monkeypatch.setattr(a, "website_origin", "https://x")
    monkeypatch.setattr(a, "_get", lambda *args, **kw: _Resp())

    results = a.search("one piece")
    titles = [r.title for r in results]
    assert "One Piece" in titles
    assert "Scan Only" not in titles  # scan-only entries are skipped
