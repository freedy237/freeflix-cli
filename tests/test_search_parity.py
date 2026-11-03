"""Search results must match the source catalogue (no silent empties).

The app used to show fewer results than the site because:
  * French-Stream cached the raw ANTI-BOT page for 5 min (0 cards);
  * Coflix stopped at the 3 HTML cards and never merged the complete REST
    index (series + /anime/ pages were missing);
  * parsers required a single quote style / a .search-title node.
"""

from freeflix_cli.scraping import coflix, french_stream


def test_french_stream_parses_both_quote_styles():
    body = (
        "<div class='search-item' onclick=\"location.href='/1-a.html'\">"
        "<div class='search-title'>Alpha (2020)</div></div>"
        "<div class='search-item' onclick='location.href=\"/2-b.html\"'>"
        "<div class='search-title'>Beta (2021)</div></div>"
    )
    out = french_stream._parse_search_cards(body)
    assert [r.title for r in out] == ["Alpha (2020)", "Beta (2021)"]


def test_french_stream_keeps_card_without_title_class():
    body = (
        "<div class='search-item' onclick=\"location.href='/3-c.html'\">"
        "<img src='https://x/p.jpg' alt='Gamma (2022)'></div>"
    )
    out = french_stream._parse_search_cards(body)
    assert [r.title for r in out] == ["Gamma (2022)"]


def test_french_stream_dedups_repeated_cards():
    card = ("<div class='search-item' onclick=\"location.href='/4-d.html'\">"
            "<div class='search-title'>Delta</div></div>")
    out = french_stream._parse_search_cards(card + card)
    assert len(out) == 1


def test_coflix_merges_html_and_rest(monkeypatch):
    html_rows = [
        coflix.SearchResult("Naruto the Last", "https://c/film/naruto-the-last/", "p.jpg", []),
    ]
    rest_rows = [
        coflix.SearchResult("Naruto the Last", "https://c/film/naruto-the-last/", "", []),
        coflix.SearchResult("Naruto Shippuden", "https://c/anime/naruto-shippuden/", "", []),
    ]
    monkeypatch.setattr(coflix, "_search_html", lambda q: html_rows)
    monkeypatch.setattr(coflix, "_search_rest", lambda q, per_page=50: rest_rows)
    out = coflix.search("naruto")
    assert [r.title for r in out] == ["Naruto the Last", "Naruto Shippuden"]
    # the HTML row keeps its poster (it comes first, REST never overwrites)
    assert out[0].img == "p.jpg"


def test_coflix_rest_only_is_returned(monkeypatch):
    monkeypatch.setattr(coflix, "_search_html", lambda q: [])
    monkeypatch.setattr(
        coflix, "_search_rest",
        lambda q, per_page=50: [
            coflix.SearchResult("Boruto", "https://c/anime/boruto/", "", []),
        ],
    )
    assert [r.title for r in coflix.search("naruto")] == ["Boruto"]


def test_coflix_skips_same_work_under_another_type(monkeypatch):
    monkeypatch.setattr(
        coflix, "_search_html",
        lambda q: [coflix.SearchResult("Dune", "https://c/film/dune/", "p.jpg", [])],
    )
    monkeypatch.setattr(
        coflix, "_search_rest",
        lambda q, per_page=50: [coflix.SearchResult("Dune", "https://c/anime/dune/", "", [])],
    )
    assert len(coflix.search("dune")) == 1


def test_french_stream_search_page_is_one_page_at_a_time(monkeypatch):
    """The UI shows page 1 + "Afficher la suite", not 191 rows at once."""
    from freeflix_cli import httpcache

    def card(n):
        return (f"<div class='search-item' onclick=\"location.href='/{n}-x.html'\">"
                f"<div class='search-title'>Title {n}</div></div>")

    more = ('<div class="search-item search-more" data-page="2" data-q="from">'
            '<div>Afficher la suite</div></div>')
    pages = {1: card(1) + card(2) + card(3) + more,
             2: card(4) + card(5)}

    class _Resp:
        status_code = 200

        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    calls = []

    def fake_post(url, data=None, **kw):
        page = (data or {}).get("page", 1)
        calls.append(page)
        return _Resp(pages.get(page, ""))

    monkeypatch.setattr(french_stream, "_post", fake_post)
    monkeypatch.setattr(httpcache, "get", lambda *a, **k: None)
    monkeypatch.setattr(httpcache, "store", lambda *a, **k: None)

    first, has_more = french_stream.search_page("from", 1)
    assert [r.title for r in first] == ["Title 1", "Title 2", "Title 3"]
    assert has_more is True
    assert calls == [1]

    second, has_more2 = french_stream.search_page("from", 2)
    assert [r.title for r in second] == ["Title 4", "Title 5"]
    assert has_more2 is False
    assert calls == [1, 2]


def test_french_stream_search_returns_first_page_only(monkeypatch):
    from freeflix_cli import httpcache

    card = ("<div class='search-item' onclick=\"location.href='/9-x.html'\">"
            "<div class='search-title'>Same</div></div>")
    called = []

    class _Resp:
        status_code = 200
        text = card

        def raise_for_status(self):
            return None

    def fake_post(url, data=None, **kw):
        called.append((data or {}).get("page"))
        return _Resp()

    monkeypatch.setattr(french_stream, "_post", fake_post)
    monkeypatch.setattr(httpcache, "get", lambda *a, **k: None)
    monkeypatch.setattr(httpcache, "store", lambda *a, **k: None)

    out = french_stream.search("same")
    assert [r.title for r in out] == ["Same"]
    assert called == [1]  # never fetches page 2 behind the user's back


def test_french_stream_parses_series_cards_with_seasons():
    """A `search-item search-series` has no onclick: seasons live in
    data-seasons. Skipping it hid whole shows (e.g. "FROM - série")."""
    import json
    from freeflix_cli.scraping import french_stream

    seasons = [
        {"n": 1, "l": "/15110779-from-saison-1.html",
         "p": "https://img/from1.jpg"},
        {"n": 2, "l": "/15113990-from-saison-2.html",
         "p": "https://img/from2.jpg"},
    ]
    body = (
        '<div class="search-item search-series" data-seasons=\''
        + json.dumps(seasons).replace("'", "&#39;")
        + '\' onclick="showSeasons(this)">'
        '<div class="search-poster"><img alt="FROM" src="https://img/from1.jpg"></div>'
        '<div class="search-info"><div class="search-title">FROM - série</div></div>'
        '</div>'
    )
    out = french_stream._parse_search_cards(body)
    assert len(out) == 1
    assert out[0].title == "FROM - série"
    assert out[0].url.endswith("/15110779-from-saison-1.html")
    assert [s["n"] for s in out[0].seasons] == [1, 2]
    assert out[0].seasons[1]["url"].endswith("/15113990-from-saison-2.html")


def test_french_stream_handler_offers_series_seasons(monkeypatch):
    """Selecting "FROM - série" must ask for a season and load ITS URL."""
    from types import SimpleNamespace
    from freeflix_cli.handlers import french_stream as H
    from freeflix_cli.scraping.objects import SearchResult

    series = SearchResult(
        "FROM - série",
        "https://french-stream.net/15110779-from-saison-1.html",
        "https://img/from1.jpg",
        [],
        [
            {"n": 1, "url": "https://french-stream.net/15110779-from-saison-1.html",
             "poster": "https://img/from1.jpg"},
            {"n": 2, "url": "https://french-stream.net/15113990-from-saison-2.html",
             "poster": "https://img/from2.jpg"},
            {"n": 3, "url": "https://french-stream.net/15118486-from-saison-3-2022.html",
             "poster": "https://img/from3.jpg"},
        ],
    )
    loaded = []

    def fake_content(url):
        loaded.append(url)
        return SimpleNamespace(
            title="FROM - Saison 3",
            url=url,
            img="https://img/from3.jpg",
            episodes={"vf": [SimpleNamespace(title="Episode 1", players=[])]},
        )

    monkeypatch.setattr(H.french_stream, "search_page",
                        lambda q, page=1: ([series], False))
    monkeypatch.setattr(H.french_stream, "get_content", fake_content)
    monkeypatch.setattr(H, "play_episode_flow", lambda **kw: False)
    monkeypatch.setattr(H.tracker, "get_search_history", lambda: [])
    monkeypatch.setattr(H.tracker, "add_search_query", lambda q: None)
    monkeypatch.setattr(H.tracker, "get_series_progress", lambda *a, **k: None)
    from freeflix_cli import terminal_image
    monkeypatch.setattr(terminal_image, "show_poster", lambda *a, **k: None)

    inputs = iter(["from", "exit"])
    monkeypatch.setattr(H, "get_user_input", lambda *a, **k: next(inputs))
    previews = iter([0, 1])  # pick first result, then Back to search
    monkeypatch.setattr(H, "select_with_preview", lambda *a, **k: next(previews))
    menus = iter([2, 2])  # season 3, then episode-list Back
    prompts = []

    def fake_select(opts, prompt, **kw):
        prompts.append(prompt)
        return next(menus)

    monkeypatch.setattr(H, "select_from_list", fake_select)

    H.handle_french_stream()
    assert any(("Season" in p or "aison" in p) for p in prompts)
    assert loaded == ["https://french-stream.net/15118486-from-saison-3-2022.html"]
