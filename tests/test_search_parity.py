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
