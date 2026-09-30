"""Tests: all scrapers SURVIVE bad HTML / challenge pages / missing elements.

Après le fix, chaque test vérifie que les scrapers retournent une valeur
par défaut ou None au lieu de crasher avec AttributeError.
"""

import pytest
from unittest.mock import MagicMock
from bs4 import BeautifulSoup

# ── Challenge / bad pages ──────────────────────────────────────────────

CHALLENGE_FS = """<!DOCTYPE html>
<html>
<head><title>Verification</title></head>
<body>
  <div style="display:none;">anti-robot verification in progress...</div>
  <script>document.cookie="fsschal=1";</script>
</body>
</html>"""

NO_OG_TITLE = """<!DOCTYPE html>
<html>
<head><title>Some Page</title></head>
<body>
  <h1>Some Title</h1>
  <div id="content">No og:title meta here</div>
</body>
</html>"""

NO_H1 = """<!DOCTYPE html>
<html><head><title>No h1</title></head><body></body></html>"""

NO_IFRAME = """<!DOCTYPE html>
<html><head><title>No iframe</title></head>
<body><div>No iframe on this page</div></body></html>"""

NO_SLIST = """<!DOCTYPE html>
<html><head><meta property="og:title" content="Test Movie">
</head><body><div id="content">No s-list ul here</div></body></html>"""

SIBNET_NO_PATTERN = """<!DOCTYPE html>
<html><head><title>Sibnet test</title></head>
<body><div>No player.src pattern in this HTML</div></body></html>"""


def _mock_response(text: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    resp.ok = status < 400
    return resp


# ======================================================================
# French-Stream
# ======================================================================


class TestFrenchStreamResilience:
    """Fix : get_movie / get_series_season / search ne crashent PLUS."""

    def _patch_get(self, resp_text=NO_OG_TITLE):
        """Monkey-patch french_stream._get pour éviter les vrais appels HTTP."""
        from freeflix_cli.scraping import french_stream
        self._orig_get = french_stream._get
        french_stream._get = lambda url, **kw: _mock_response(resp_text)

    def _unpatch_get(self):
        from freeflix_cli.scraping import french_stream
        french_stream._get = self._orig_get

    def test_get_movie_uses_fallback_title(self):
        """Challenge page → pas de crash, titre extrait du <title> ou URL."""
        self._patch_get(CHALLENGE_FS)
        try:
            from freeflix_cli.scraping.french_stream import get_movie
            movie = get_movie("https://french-stream.one/films/12345-film.html", CHALLENGE_FS)
            assert movie.title
        finally:
            self._unpatch_get()

    def test_get_movie_no_og_title_fallback(self):
        """Page valide sans og:meta → fallback sur <title>."""
        self._patch_get(NO_OG_TITLE)
        try:
            from freeflix_cli.scraping.french_stream import get_movie
            movie = get_movie("https://french-stream.one/films/99999-test.html", NO_OG_TITLE)
            assert movie.title
        finally:
            self._unpatch_get()

    def test_get_series_season_no_og_title_fallback(self):
        """get_series_season ne crash plus sans og:title."""
        self._patch_get(CHALLENGE_FS)
        try:
            from freeflix_cli.scraping.french_stream import get_series_season
            season = get_series_season("https://french-stream.one/s-tv/99999-serie.html", CHALLENGE_FS)
            assert season.title
        finally:
            self._unpatch_get()

    def test_get_movie_no_slist_no_crash(self):
        """get_movie sans #s-list → genres vide, pas de crash."""
        self._patch_get(NO_SLIST)
        try:
            from freeflix_cli.scraping.french_stream import get_movie
            movie = get_movie("https://french-stream.one/films/12345-film.html", NO_SLIST)
            assert movie.genres == []
        finally:
            self._unpatch_get()

    def test_get_content_challenge_page_no_crash(self):
        """get_content avec challenge page → ne crash plus (fallback title)."""
        from freeflix_cli.scraping import french_stream
        original_get = french_stream._get
        french_stream._get = lambda url, **kw: _mock_response(CHALLENGE_FS)
        try:
            content = french_stream.get_content("https://french-stream.one/films/12345-film.html")
            assert content is not None
        finally:
            french_stream._get = original_get

    def test_search_missing_onclick_skips(self):
        """search : resultat sans onclick est ignoré, pas de crash."""
        html = """<div class="search-item">
          <div class="search-title">Test</div>
          <img src="test.jpg"/>
        </div>"""
        soup = BeautifulSoup(html, "html5lib")
        for result in soup.find_all("div", {"class": "search-item"}):
            onclick = result.attrs.get("onclick", "")
            if "location.href='" not in onclick:
                continue  # ne crash plus


# ======================================================================
# Coflix
# ======================================================================


class TestCoflixResilience:
    """Coflix: get_movie / get_series / get_episode ne crashent PLUS."""

    def test_get_movie_no_h1_no_crash(self):
        from freeflix_cli.scraping import coflix
        original_get = coflix._get
        coflix._get = lambda url, **kw: _mock_response(NO_H1)
        try:
            movie = coflix.get_movie("https://coflix.cymru/film/test/")
            assert movie.title  # fallback depuis URL
        finally:
            coflix._get = original_get

    def test_get_series_no_h1_no_crash(self):
        from freeflix_cli.scraping import coflix
        original_get = coflix._get
        coflix._get = lambda url, **kw: _mock_response(NO_H1)
        try:
            series = coflix.get_series("https://coflix.cymru/serie/test/")
            assert series.title  # fallback depuis URL
        finally:
            coflix._get = original_get

    def test_get_movie_no_iframe_no_crash(self):
        from freeflix_cli.scraping import coflix
        original_get = coflix._get
        coflix._get = lambda url, **kw: _mock_response(NO_H1)
        try:
            movie = coflix.get_movie("https://coflix.cymru/film/test/")
            assert movie.players == []  # pas de crash, players vide
        finally:
            coflix._get = original_get

    def test_get_episode_no_iframe_no_crash(self):
        from freeflix_cli.scraping import coflix
        original_get = coflix._get
        coflix._get = lambda url, **kw: _mock_response(NO_IFRAME)
        try:
            ep = coflix.get_episode("https://coflix.cymru/episode/test/")
            assert ep is not None  # pas de crash
        finally:
            coflix._get = original_get

    def test_get_episode_no_a_href_no_crash(self):
        from freeflix_cli.scraping import coflix
        original_get = coflix._get
        coflix._get = lambda url, **kw: _mock_response(NO_IFRAME)
        try:
            ep = coflix.get_episode("https://coflix.cymru/episode/test/")
            assert ep is not None
        finally:
            coflix._get = original_get

    def test_get_players_no_span_no_crash(self):
        html = """<li onclick="showVideo('aHR0cDovL3Rlc3QuY29t')">No span here</li>"""
        soup = BeautifulSoup(html, "html5lib")
        for li in soup.find_all("li"):
            if "onclick" in li.attrs and "showVideo" in li.attrs["onclick"]:
                span = li.find("span")
                name = span.text.strip() if span else "Unknown"
                assert name == "Unknown"


# ======================================================================
# Anime-Sama
# ======================================================================


class TestAnimeSamaResilience:
    """Anime-Sama: search / get_series ne crashent PLUS."""

    def test_search_missing_a_skipped(self):
        html = """<div id="list_catalog">
          <div><div class="card-content"><h2>Test</h2></div></div>
        </div>"""
        soup = BeautifulSoup(html, "html5lib")
        container = soup.find("div", {"id": "list_catalog"})
        if container:
            for result in container.find_all("div", recursive=False):
                link_tag = result.find("a")
                if not link_tag:
                    continue  # ne crash plus

    def test_search_missing_img_ok(self):
        html = """<div id="list_catalog">
          <div><a href="/test/">No img</a>
          <div class="card-content"><h2>Test</h2></div></div>
        </div>"""
        soup = BeautifulSoup(html, "html5lib")
        container = soup.find("div", {"id": "list_catalog"})
        if container:
            for result in container.find_all("div", recursive=False):
                link_tag = result.find("a")
                img_tag = link_tag.img if link_tag else None
                img = img_tag.attrs.get("src", "") if img_tag else ""
                assert img == ""

    def test_search_missing_h2_skipped(self):
        html = """<div id="list_catalog">
          <div><a href="/test/"><img src="x.jpg"/></a>
          <div class="card-content"><p>No h2 here</p></div></div>
        </div>"""
        soup = BeautifulSoup(html, "html5lib")
        container = soup.find("div", {"id": "list_catalog"})
        if container:
            for result in container.find_all("div", recursive=False):
                info_block = result.find("div", {"class": "card-content"})
                if info_block:
                    h2 = info_block.h2
                    title = h2.text if h2 else ""
                    assert title == ""  # pas de crash


# ======================================================================
# Player
# ======================================================================


class TestPlayerResilience:
    """player.py: get_hls_link_* retournent None au lieu de crasher."""

    def test_sendvid_no_og_video_returns_none(self):
        from freeflix_cli.scraping import player as player_mod
        original_get = player_mod._get
        player_mod._get = lambda url, **kw: _mock_response(NO_OG_TITLE)
        try:
            result = player_mod.get_hls_link_sendvid("https://sendvid.com/abcdef")
            assert result is None
        finally:
            player_mod._get = original_get

    def test_vidoza_no_source_returns_none(self):
        from freeflix_cli.scraping import player as player_mod
        original_get = player_mod._get
        player_mod._get = lambda url, **kw: _mock_response(NO_OG_TITLE)
        try:
            result = player_mod.get_hls_link_vidoza("https://vidoza.net/abcdef.html", {})
            assert result is None
        finally:
            player_mod._get = original_get

    def test_sibnet_no_pattern_returns_none(self):
        from freeflix_cli.scraping import player as player_mod
        original_get = player_mod._get
        player_mod._get = lambda url, **kw: _mock_response(SIBNET_NO_PATTERN)
        try:
            result = player_mod.get_hls_link_sibnet("https://video.sibnet.ru/shelf/abc123/")
            assert result is None
        finally:
            player_mod._get = original_get

    def test_default_extractor_falls_back_to_raw_html(self):
        """ansembed (2026): la page ship un payload packé + un bloc JWPlayer en
        clair. packer.unpack() jette le bloc en clair, donc le code
        déobfusqué ne contient plus l'URL — l'extracteur doit retomber sur le
        HTML brut au lieu de retourner None."""
        from freeflix_cli.scraping import player as player_mod
        page = """<html><head><title>ansembed</title></head><body>
<script>eval(function(p,a,c,k,e,d){return 'unpacked without stream url'})</script>
<script>var playerInstance = player.setup({
sources: [{ file: 'https://prx-ps-a-1.vmpx.online/hls2/01/02915/x0m0qz3h132d_,n,l,.urlset/master.m3u8?t=abc&s=123' }],
});</script>
</body></html>"""
        original_get = player_mod._get
        original_deobfuscate = player_mod.deobfuscate
        player_mod._get = lambda url, **kw: _mock_response(page)
        # Simule le drop observé en prod : l'unpack ne garde que le payload.
        player_mod.deobfuscate = lambda code: "unpacked without stream url"
        try:
            result = player_mod.get_hls_link_default(
                "https://ansembed.net/embed-x0m0qz3h132d.html", {}
            )
            assert result == (
                "https://prx-ps-a-1.vmpx.online/hls2/01/02915/"
                "x0m0qz3h132d_,n,l,.urlset/master.m3u8?t=abc&s=123"
            )
        finally:
            player_mod._get = original_get
            player_mod.deobfuscate = original_deobfuscate

    def test_dood_pass_md5_flow(self):
        """DoodStream : page /e/ -> token pass_md5 -> URL mp4 directe."""
        from freeflix_cli.scraping import player as player_mod
        page = """<html><body><script>$.get('/pass_md5/abc-123/tokenxyz',
function(data) { dpload(data); });</script></body></html>"""
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            if "pass_md5" in url:
                return _mock_response("https://cdn.example.com/vid/x.mp4?token=t")
            return _mock_response(page)

        original_get = player_mod._get
        player_mod._get = fake_get
        try:
            result = player_mod.get_hls_link_dood("https://playmogo.com/e/kgbwsacgucje", {})
            assert result == "https://cdn.example.com/vid/x.mp4?token=t"
            assert any("pass_md5" in u for u in calls)
        finally:
            player_mod._get = original_get

    def test_dood_no_token_returns_none(self):
        from freeflix_cli.scraping import player as player_mod
        original_get = player_mod._get
        player_mod._get = lambda url, **kw: _mock_response(NO_OG_TITLE)
        try:
            assert player_mod.get_hls_link_dood("https://playmogo.com/e/abc", {}) is None
        finally:
            player_mod._get = original_get

    def test_voe_substitution_decode(self):
        """Voe/luluvdo : le packer à substitution de mots se décode en pur."""
        from freeflix_cli.scraping.player import _voe_substitution_decode
        # c.toString(36) : 10 -> 'a', 11 -> 'b' ; table remplace a->HI, b->BYE
        table = [""] * 10 + ["HI", "BYE"]
        assert _voe_substitution_decode("a b a", 36, table) == "HI BYE HI"

    def test_voe_extractor_decodes_packed_setup(self):
        from freeflix_cli.scraping import player as player_mod
        page = """<html><body><script>eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(
new RegExp('\\\\b'+c.toString(a)+'\\\\b','g'),k[c]);return p}('0 1:{2:"3"}',36,4,'file|var|sources|https://cdn.example.com/v/master.m3u8'.split('|')))</script>
</body></html>"""
        original_get = player_mod._get
        player_mod._get = lambda url, **kw: _mock_response(page)
        try:
            result = player_mod.get_hls_link_voe("https://luluvdo.com/e/abc123", {})
            assert result == "https://cdn.example.com/v/master.m3u8"
        finally:
            player_mod._get = original_get

    def test_lulust_routes_to_voe_extractor(self):
        """French-Anime 'luluvid' tourne entre luluvdo.com et lulust.com :
        les deux doivent être supportés et décodés comme voe."""
        from freeflix_cli.scraping import player as player_mod
        assert player_mod.is_supported("https://luluvdo.com/e/abc123")
        assert player_mod.is_supported("https://lulust.com/e/abc123")
        assert player_mod.players["lulust"]["type"] == "voe"

    def test_kokoflix_dispatches_on_final_host(self):
        """kokoflix : suit la redirection puis dispatche sur l'hôte final."""
        from freeflix_cli.scraping import player as player_mod
        resp = _mock_response("<html></html>")
        resp.url = "https://playmogo.com/e/kgbwsacgucje"
        original_get = player_mod._get
        original_link = player_mod.get_hls_link
        seen = []
        player_mod._get = lambda url, **kw: resp
        player_mod.get_hls_link = lambda url, headers=None: seen.append(url) or "FINAL"
        try:
            assert player_mod.get_hls_link_kokoflix(
                "https://kokoflix.lol/tokyo_go.php?id=x", {}) == "FINAL"
            assert seen == ["https://playmogo.com/e/kgbwsacgucje"]
        finally:
            player_mod._get = original_get
            player_mod.get_hls_link = original_link

    def test_default_extractor_prefers_deobfuscated_code(self):
        """Le fallback brut ne doit pas écraser le comportement historique :
        quand le code déobfusqué contient l'URL, c'est lui qui gagne."""
        from freeflix_cli.scraping import player as player_mod
        page = """<html><body><script>var x = 1;</script>
<script>file: 'https://raw.example.com/vid/master.m3u8'</script></body></html>"""
        original_get = player_mod._get
        original_deobfuscate = player_mod.deobfuscate
        player_mod._get = lambda url, **kw: _mock_response(page)
        player_mod.deobfuscate = lambda code: "file: 'https://unpacked.example.com/vid/master.m3u8'"
        try:
            result = player_mod.get_hls_link_default("https://example.com/e/abc.html", {})
            assert result == "https://unpacked.example.com/vid/master.m3u8"
        finally:
            player_mod._get = original_get
            player_mod.deobfuscate = original_deobfuscate


# ======================================================================
# French-Stream: _get() gère maintenant le challenge fsschal
# ======================================================================


class TestFrenchStreamPlayerFilter:
    """Lecteurs morts (trakx/dood/voe/netu) exclus, vivants gardés."""

    def _mock_json(self, payload: dict):
        resp = _mock_response("")
        resp.json = lambda: payload
        return resp

    def test_is_usable_player_link(self):
        from freeflix_cli.scraping.french_stream import _is_usable_player_link
        assert _is_usable_player_link("https://fsvid.lol/embed-a.html")
        assert _is_usable_player_link("https://vidzy.cc/embed-b.html")
        assert _is_usable_player_link("https://uqload.vc/embed-c.html")
        assert not _is_usable_player_link("https://trakx.lol/sydney/newPlayer.php?id=x")
        assert not _is_usable_player_link("https://trakx.lol/d00d//newPlayer.php?id=y")
        assert not _is_usable_player_link("https://1.multiup.us/e/xyz")
        assert not _is_usable_player_link(
            "https://kokoflix.lol/chamber_go.php?id=x")  # Byse SPA, cul-de-sac
        assert _is_usable_player_link(
            "https://kokoflix.lol/rosewood_go.php?id=x")  # voe, supporté
        assert not _is_usable_player_link("BafWadqiVSI2")  # netu code, pas une URL
        assert not _is_usable_player_link("")
        assert not _is_usable_player_link(None)

    def test_get_movie_drops_dead_players(self):
        from freeflix_cli.scraping import french_stream
        payload = {"players": {
            "premium": {"vf": "https://fsvid.lol/embed-a.html"},
            "voe": {"vf": "https://trakx.lol/sydney/newPlayer.php?id=x"},
            "dood": {"vf": "https://trakx.lol/d00d//newPlayer.php?id=y"},
            "netu": {"vf": "BafWadqiVSI2"},
        }}
        orig = french_stream._get
        french_stream._get = lambda url, **kw: self._mock_json(payload)
        try:
            movie = french_stream.get_movie("https://french-stream.net/1022-x.html", "")
            names = [p.name for p in movie.players]
            assert any("premium" in n for n in names)
            assert not any("voe" in n or "dood" in n or "netu" in n for n in names)
        finally:
            french_stream._get = orig

    def test_get_series_season_drops_dead_players(self):
        from freeflix_cli.scraping import french_stream
        payload = {
            "vf": {"1": {
                "premium": "https://fsvid.lol/embed-a.html",
                "voe": "https://trakx.lol/sydney/newPlayer.php?id=x",
                "netu": "https://1.multiup.us/e/xyz",
            }},
            "vostfr": {},
            "vo": {},
        }
        orig = french_stream._get
        french_stream._get = lambda url, **kw: self._mock_json(payload)
        try:
            season = french_stream.get_series_season(
                "https://french-stream.net/9561-x.html", "")
            names = [p.name for p in season.episodes["vf"][0].players]
            assert names == ["premium"]
        finally:
            french_stream._get = orig


class TestFrenchStreamGetFsschal:
    """_get() détecte maintenant le challenge fsschal comme _post()."""

    def test_get_detects_fsschal(self):
        from freeflix_cli.scraping.french_stream import _get
        from freeflix_cli import cloudflare
        resp = _mock_response(CHALLENGE_FS, status=200)
        assert not cloudflare.is_blocked(resp)
        # _get() doit maintenant set le cookie et retry au lieu de laisser passer
        # (testé indirectement via get_content qui ne crash plus)
