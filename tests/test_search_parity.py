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


def test_french_stream_walks_every_page(monkeypatch):
    """A search must aggregate ALL pages, not just page 1.

    Real case: "from" → 19 cards on page 1, then 25/page up to page 8
    (185 total). The app used to show only the 19 from page 1.
    """
    from freeflix_cli import httpcache

    def card(n):
        return (f"<div class='search-item' onclick=\"location.href='/{n}-x.html'\">"
                f"<div class='search-title'>Title {n}</div></div>")

    pages = {
        1: card(1) + card(2) + card(3),
        2: card(4) + card(5),
        3: "",  # past the last page
    }

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

    out = french_stream.search("from")
    assert [r.title for r in out] == ["Title 1", "Title 2", "Title 3", "Title 4", "Title 5"]
    assert calls == [1, 2, 3]


def test_french_stream_stops_when_pages_repeat(monkeypatch):
    """Out-of-range pages may repeat the last page: never loop forever."""
    from freeflix_cli import httpcache

    card = ("<div class='search-item' onclick=\"location.href='/9-x.html'\">"
            "<div class='search-title'>Same</div></div>")

    class _Resp:
        status_code = 200
        text = card

        def raise_for_status(self):
            return None

    calls = []

    def fake_post(url, data=None, **kw):
        calls.append((data or {}).get("page"))
        return _Resp()

    monkeypatch.setattr(french_stream, "_post", fake_post)
    monkeypatch.setattr(httpcache, "get", lambda *a, **k: None)
    monkeypatch.setattr(httpcache, "store", lambda *a, **k: None)

    out = french_stream.search("same")
    assert [r.title for r in out] == ["Same"]
    assert calls == [1, 2]  # page 2 repeated page 1 → stop


def test_hianime_search_walks_pages(monkeypatch):
    """HiAnime search is paginated too (34 on page 1, 30 on page 2…)."""
    from freeflix_cli import httpcache
    from freeflix_cli.scraping import goldenanime

    def block(n):
        return (f'<div class="flw-item"><img src="https://cdn/{n}.jpg">'
                f'<div class="tick-item tick-sub">1</div>'
                f'<a href="https://hianime.at/watch/show-{n}" '
                f'title="Show {n}"></a></div>')

    pages = {1: block(1) + block(2), 2: block(3), 3: "", 4: ""}

    class _Resp:
        status_code = 200

        def __init__(self, text):
            self.text = text

    calls = []

    def fake_get(url, **kw):
        page = int(url.rsplit("page=", 1)[-1]) if "page=" in url else 1
        calls.append(page)
        return _Resp(pages.get(page, ""))

    monkeypatch.setattr(goldenanime, "_get", fake_get)
    monkeypatch.setattr(httpcache, "get", lambda *a, **k: None)
    monkeypatch.setattr(httpcache, "store", lambda *a, **k: None)

    out = goldenanime.goldenanime.search_hianime_shows("show")
    assert [x["title"] for x in out] == ["Show 1", "Show 2", "Show 3"]
    assert calls == [1, 2, 3]
