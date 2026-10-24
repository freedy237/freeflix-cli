"""Anime-Sama weekly planning: live parser + provider menu integration."""

from freeflix_cli.handlers import anime_sama as H
from freeflix_cli.i18n import t
from freeflix_cli.scraping import anime_sama_planning as P

# Trimmed-down real grid: anime VOSTFR (out), anime VF (upcoming), a scan tile
# (must be dropped) and a card without a release hour.
PLANNING_HTML = """
<div id="0" class="selectedRow px-1 py-4 rounded ">
  <h2 class="titreJours">Lundi</h2>
  <p class="text-white">19/10</p>
  <div class="categorieHome">
    <div class="as-carte as-carte-anime planning-card Anime VOSTFR  pl-sorti"
         data-url="/catalogue/abc/" data-cat="oeuvre" data-nom="Abc Show"
         data-img="https://img/abc.jpg" data-release-ts="1792414200"
         data-lien="/catalogue/abc/saison1/vostfr/" data-debut="1792339200">
      <a href="/catalogue/abc/"><h3>Abc Show</h3></a>
    </div>
    <div class="as-carte as-carte-scan as-carte-couleur planning-card Scan VF"
         data-url="/catalogue/scan-only/" data-nom="Scan Only">
      <a href="/catalogue/scan-only/">x</a>
    </div>
  </div>
</div>
<div id="1" class="selectedRow px-1 py-4 rounded pl-aujourdhui">
  <h2 class="titreJours">Mardi</h2>
  <p class="text-white">20/10</p>
  <div class="categorieHome">
    <div class="as-carte as-carte-anime planning-card Anime VF"
         data-url="/catalogue/xyz/" data-nom="Xyz VF"
         data-img="https://img/xyz.jpg" data-release-ts="1792500000"
         data-lien="/catalogue/xyz/saison2/vf/" data-debut="1792490000">
      <a href="/catalogue/xyz/"><h3>Xyz VF</h3></a>
    </div>
    <div class="as-carte as-carte-anime planning-card Anime"
         data-url="/catalogue/nohour/" data-nom="No Hour"
         data-img="https://img/nh.jpg" data-lien="/catalogue/nohour/saison1/vostfr/">
      <a href="/catalogue/nohour/"><h3>No Hour</h3></a>
    </div>
  </div>
</div>
"""


def test_parse_planning_keeps_only_animes(monkeypatch):
    monkeypatch.setattr(P.anime_sama, "website_origin", "https://anime-sama.to")
    titles = [e.title for e in P.parse_planning(PLANNING_HTML)]
    assert titles == ["Abc Show", "Xyz VF", "No Hour"]


def test_parse_planning_reads_day_state_hour_and_urls(monkeypatch):
    monkeypatch.setattr(P.anime_sama, "website_origin", "https://anime-sama.to")
    first = P.parse_planning(PLANNING_HTML)[0]
    assert (first.day, first.date_label) == ("Lundi", "19/10")
    assert first.released is True
    assert first.lang == "VOSTFR"
    assert first.has_hour is True
    assert first.url == "https://anime-sama.to/catalogue/abc/"
    assert first.season_url == (
        "https://anime-sama.to/catalogue/abc/saison1/vostfr/"
    )


def test_parse_planning_upcoming_and_missing_hour(monkeypatch):
    monkeypatch.setattr(P.anime_sama, "website_origin", "https://anime-sama.to")
    entries = P.parse_planning(PLANNING_HTML)
    assert entries[1].released is False and entries[1].lang == "VF"
    # No release timestamp → no invented hour, but still listed that day.
    assert entries[2].has_hour is False
    assert entries[2].hour_label == "?"


def test_parse_planning_language_filter(monkeypatch):
    monkeypatch.setattr(P.anime_sama, "website_origin", "https://anime-sama.to")
    # Cards with NO language tag always stay (their language is unknown).
    only_vf = P.parse_planning(PLANNING_HTML, lang_filter="VF")
    assert [e.title for e in only_vf] == ["Xyz VF", "No Hour"]


def test_sorties_endpoint_marks_an_uploaded_episode_released(monkeypatch):
    """The server HTML is only a snapshot: planning.js reads sorties.php.

    Link Click / JoJo can be uploaded while their card still lacks
    ``pl-sorti`` in the HTML. The live endpoint must flip them to "Sorti".
    """
    monkeypatch.setattr(P.anime_sama, "website_origin", "https://anime-sama.to")
    entries = P.parse_planning(PLANNING_HTML)
    xyz = next(e for e in entries if e.title == "Xyz VF")
    assert xyz.released is False and xyz.started_ts == 1792490000

    # Upload before the planning day starts does not count as this release.
    P.apply_release_status(entries, {"/catalogue/xyz/saison2/vf/": 1792480000})
    assert xyz.released is False
    P.apply_release_status(entries, {"/catalogue/xyz/saison2/vf/": 1792500001})
    assert xyz.released is True


def test_sorties_endpoint_keeps_postponed_state(monkeypatch):
    monkeypatch.setattr(P.anime_sama, "website_origin", "https://anime-sama.to")
    html = PLANNING_HTML.replace(
        'planning-card Anime VF"\n         data-url="/catalogue/xyz/"',
        'planning-card Anime VF" data-etat-db="Reporté"\n'
        '         data-url="/catalogue/xyz/"',
    )
    xyz = next(e for e in P.parse_planning(html) if e.title == "Xyz VF")
    P.apply_release_status([xyz], {"/catalogue/xyz/saison2/vf/": 1792500001})
    assert xyz.released is False


def test_get_planning_refreshes_every_document(monkeypatch):
    """No HTTP cache: entering the planning must always re-read release state."""
    monkeypatch.setattr(P.anime_sama, "website_origin", "https://anime-sama.to")
    monkeypatch.setattr(P.anime_sama, "get_website_url", lambda: None)
    calls = []

    class _Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    def fake_get(url, cache_ttl=0, **kw):
        calls.append((url, cache_ttl, kw.get("headers") or {}))
        if url.endswith("/planning/sorties.php"):
            return _Resp('{"\\/catalogue\\/xyz\\/saison2\\/vf\\/": 1792500001}')
        return _Resp(PLANNING_HTML)

    monkeypatch.setattr(P.anime_sama, "_get", fake_get)
    entries = P.get_planning()
    assert len(calls) == 2
    assert all(ttl == 0 for _url, ttl, _h in calls)
    assert all(h.get("Cache-Control") == "no-cache" for _u, _t, h in calls)
    xyz = next(e for e in entries if e.title == "Xyz VF")
    assert xyz.released is True


def test_group_by_day_orders_by_hour(monkeypatch):
    monkeypatch.setattr(P.anime_sama, "website_origin", "https://anime-sama.to")
    groups = P.group_by_day(P.parse_planning(PLANNING_HTML))
    assert [(d, c) for d, c, _ in groups] == [("Lundi", "19/10"), ("Mardi", "20/10")]
    assert isinstance(P.today_index(P.parse_planning(PLANNING_HTML)), int)


def test_planning_menu_offers_planning_and_search():
    calls = {}

    def fake_select(opts, prompt, **kw):
        calls["opts"] = opts
        return 2  # Back

    orig = H.select_from_list
    H.select_from_list = fake_select
    try:
        H._planning_menu()
    finally:
        H.select_from_list = orig
    assert len(calls["opts"]) == 3
    assert t("Weekly planning").lower() in calls["opts"][0].lower()
    assert t("Search an anime").lower() in calls["opts"][1].lower()


def test_planning_entry_actions_offer_follow_and_browse(monkeypatch):
    monkeypatch.setattr(P.anime_sama, "website_origin", "https://anime-sama.to")
    entry = P.parse_planning(PLANNING_HTML)[0]
    picked = {}

    def fake_select(opts, prompt, **kw):
        picked["opts"] = opts
        return 2  # Back

    class _Series:
        title = entry.title
        img = ""
        genres = []
        seasons = [object()]

    monkeypatch.setattr(H, "select_from_list", fake_select)
    monkeypatch.setattr(H, "print_info", lambda *a, **k: None)
    monkeypatch.setattr(H.anime_sama, "get_series", lambda url: _Series())
    monkeypatch.setattr(H, "spinner",
                        lambda _m: __import__("contextlib").nullcontext())
    monkeypatch.setattr("freeflix_cli.terminal_image.show_poster",
                        lambda *a, **k: None)
    H._planning_entry_actions(entry, "Lundi", "19/10")
    assert len(picked["opts"]) == 3
    joined = " ".join(picked["opts"]).lower()
    assert t("Follow the latest released episode").lower() in joined
    assert t("Browse seasons").lower() in joined


def test_planning_day_list_shows_release_count(monkeypatch):
    """The day picker summarises how many animes are already out."""
    monkeypatch.setattr(P.anime_sama, "website_origin", "https://anime-sama.to")
    monkeypatch.setattr(P, "get_planning", lambda lang_filter="":
                        P.parse_planning(PLANNING_HTML))
    monkeypatch.setattr(H.anime_sama, "get_website_url", lambda: None)
    monkeypatch.setattr(H.tracker, "get_anime_language", lambda: "")

    seen = []
    monkeypatch.setattr(H, "select_from_list",
                        lambda opts, prompt, **kw: (seen.append(opts) or len(opts) - 1))
    monkeypatch.setattr(H, "spinner", lambda _m: __import__("contextlib").nullcontext())
    H.handle_anime_sama_planning()
    # Lundi: the scan is dropped, the single anime is already out.
    assert "1/1" in seen[0][0]
    assert "0/2" in seen[0][1]  # Mardi: two animes, none released yet


def test_crumb_accepts_several_labels():
    """The planning pushes Anime-Sama › day › date in one level."""
    from freeflix_cli import cli_utils as cu

    cu.crumb_reset("Home")
    with cu.crumb("Anime-Sama", "Lundi", "19/10"):
        assert cu.crumbs_text() == "Home › Anime-Sama › Lundi › 19/10"
    assert cu.crumbs_text() == "Home"


def test_planning_entries_screen_renders_without_error(monkeypatch):
    """Regression: crumb() used to take ONE label (TypeError on the grid)."""
    monkeypatch.setattr(P.anime_sama, "website_origin", "https://anime-sama.to")
    entries = P.parse_planning(PLANNING_HTML)
    shown = {}

    def fake_swp(labels, prompt, previews):
        shown["labels"] = labels
        return len(labels)  # Back → day list

    class _Stop(Exception):
        pass

    # Day list: first pass picks Lundi, second pass Backs out (not 0 again,
    # or the loop would re-open the day forever).
    days = iter([0, 99])
    monkeypatch.setattr(H, "select_with_preview", fake_swp)
    monkeypatch.setattr(
        H, "select_from_list", lambda opts, prompt, **kw: next(days, 99)
    )
    monkeypatch.setattr(P, "get_planning", lambda lang_filter="": entries)
    monkeypatch.setattr(H.anime_sama, "get_website_url", lambda: None)
    monkeypatch.setattr(H.tracker, "get_anime_language", lambda: "")
    monkeypatch.setattr(H, "spinner", lambda _m: __import__("contextlib").nullcontext())
    # Never hit the network for the fake poster URLs in this offline test.
    monkeypatch.setattr("freeflix_cli.terminal_image.prefetch_many",
                        lambda urls: None)
    try:
        H.handle_anime_sama_planning()
    except _Stop:
        pass
    assert any("Abc Show" in x for x in shown["labels"])


def test_follow_latest_episode_opens_last_episode(monkeypatch):
    class Season:
        title = "Saison 2"
        episodes = {"vostfr": ["ep1", "ep2", "ep3"]}
        url = "https://x/saison2"

    class Acc:
        def __init__(self, title, url):
            self.title, self.url = title, url

    class Series:
        title = "Show"
        url = "https://x"
        img = ""
        genres = []
        seasons = [Acc("Saison 1", "https://x/saison1"),
                   Acc("Saison 2", "https://x/saison2")]

    played = {}
    monkeypatch.setattr(H.anime_sama, "get_season", lambda url: Season())
    monkeypatch.setattr(H, "play_episode_flow",
                        lambda **kw: played.update(kw) or True)
    monkeypatch.setattr(H.tracker, "get_anime_language", lambda: "vostfr")
    H._follow_latest_episode(Series())
    assert played["season_title"] == "Saison 2"
    assert played["episode"] == "ep3"
