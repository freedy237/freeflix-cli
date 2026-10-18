"""
Offline tests for the all-providers repair round :
- Coflix cfServers layout (no more <iframe>)
- Vidlink per-quality MP4 shape
- Nyaa size column (header colspan shift)
"""

from freeflix_cli.scraping import coflix


CF_HTML = (
    '<html><body><div class="cfp-player" data-cfp="x"></div>'
    '<script>var cfServers = [{"nombre":"Lecteurvideo",'
    '"embed_url":"https:\\/\\/lecteurvideo.com\\/embed.php?id=34359",'
    '"idioma":"Autre"}];</script></body></html>'
)


def test_cfservers_url_extracted():
    assert coflix._cfservers_url(CF_HTML) == (
        "https://lecteurvideo.com/embed.php?id=34359"
    )


def test_cfservers_url_missing():
    assert coflix._cfservers_url("<html></html>") == ""
    assert coflix._cfservers_url("") == ""
    assert coflix._cfservers_url("var cfServers = not json;") == ""


def test_players_url_prefers_iframe_then_cfservers():
    from freeflix_cli.scraping.utils import parse_html
    soup = parse_html(
        '<html><body><iframe src="https://lecteurvideo.com/embed.php?id=1">'
        "</iframe></body></html>"
    )
    assert coflix._players_url_from_page(soup, CF_HTML) == (
        "https://lecteurvideo.com/embed.php?id=1"
    )
    soup2 = parse_html(CF_HTML)
    assert coflix._players_url_from_page(soup2, CF_HTML) == (
        "https://lecteurvideo.com/embed.php?id=34359"
    )


def test_vidlink_qualities_shape(monkeypatch):
    from freeflix_cli.scraping import goldenms as G

    api = {
        "stream": {
            "type": "file",
            "qualities": {
                str(h): {
                    "type": "mp4",
                    "url": f"https://cdn.example.com/{h}.mp4?sign=x",
                }
                for h in (360, 720, 1080)
            },
            "captions": [{"language": "English", "url": "https://cdn.example.com/en.srt"}],
        }
    }

    class _R:
        def json(self):
            return api

    monkeypatch.setattr(G, "_get", lambda *a, **k: _R())

    class _E:
        def json(self):
            return {"result": "enc"}

    # enc endpoint returns a different shape; route by URL.
    def _route(url, **kw):
        if "enc-vidlink" in url:
            return _E()
        return _R()

    monkeypatch.setattr(G, "_get", _route)
    g = G.MediaExtractor()
    out = g.search_vidlink(1396, season=1, episode=1)
    assert [o["quality"] for o in out] == ["360p", "720p", "1080p"]
    assert all(o["type"] == "VIDEO" for o in out)
    assert out[0]["subtitles"] == [
        {"lang": "English", "url": "https://cdn.example.com/en.srt"}
    ]


def test_vidlink_legacy_playlist_still_works(monkeypatch):
    from freeflix_cli.scraping import goldenms as G

    class _E:
        def json(self):
            return {"result": "enc"}

    class _R:
        def json(self):
            return {"stream": {"playlist": "https://cdn.example.com/master.m3u8"}}

    def _route(url, **kw):
        return _E() if "enc-vidlink" in url else _R()

    monkeypatch.setattr(G, "_get", _route)
    out = G.MediaExtractor().search_vidlink(1396)
    assert out == [
        {
            "source": "Vidlink",
            "quality": "Multi",
            "url": "https://cdn.example.com/master.m3u8",
            "type": "M3U8",
            "headers": out[0]["headers"],
        }
    ]


def test_nyaa_size_detected_by_content():
    # Simulates the real nyaa row : header mapping lands on the date cell,
    # the size must still be recovered from the "9.7 GiB" cell.
    from freeflix_cli.scraping.utils import parse_html
    import re

    row = (
        "<tr><td></td><td></td><td></td>"
        "<td>9.7 GiB</td><td>2025-03-26 06:54</td>"
        "<td>238</td><td>5</td><td>12919</td></tr>"
    )
    tds = parse_html(f"<table>{row}</table>").find_all("td")
    size = tds[4].get_text(strip=True)  # what the shifted header map gives
    assert size == "2025-03-26 06:54"
    if not re.match(r"^[\d.]+\s*(GiB|MiB|KiB|B)$", size):
        for _td in tds[2:6]:
            _txt = _td.get_text(strip=True)
            if re.match(r"^[\d.]+\s*(GiB|MiB|KiB|B)$", _txt):
                size = _txt
                break
    assert size == "9.7 GiB"


def _hianime_payload(url="https://cdn.example.com/master.m3u8"):
    import base64, json
    data = json.dumps({"src": url, "subtitles": [
        {"label": "English", "src": "https://cdn.example.com/en.vtt"}]})
    raw = data.encode()
    key = b"otaku-embed-v1"
    enc = bytes(c ^ key[i % len(key)] for i, c in enumerate(raw))
    return base64.b64encode(enc).decode()


def test_hianime_full_chain(monkeypatch):
    from freeflix_cli.scraping import goldenms as _g  # noqa (route helper)
    from freeflix_cli.scraping import goldenanime as GA

    search_html = (
        '<div class="flw-item flw-item-big">'
        '<div class="film-detail">'
        '<h3 class="film-name"><a href="/watch/solo-leveling-235"'
        ' title="Solo Leveling">x</a></h3></div></div>'
    )
    eps_html = ('<a class="ssl-item ep-item" data-number="1" data-id="4341"'
                ' href="/watch/solo-leveling-235?ep=4341">')
    servers_html = (
        '<div class="item server-item" data-type="sub"'
        ' data-server-name="ZokoAnime"'
        ' data-hash="aHR0cHM6Ly9lbWJlZC5leGFtcGxlL3Y="></div>'
        '<div class="item server-item" data-type="dub"'
        ' data-server-name="ZokoAnime"'
        ' data-hash="aHR0cHM6Ly9lbWJlZC5leGFtcGxlL2Q="></div>'
    )
    import base64
    payload = _hianime_payload()

    class _R:
        def __init__(self, text="", js=None):
            self.text = text
            self._js = js
            self.status_code = 200

        def json(self):
            return self._js

    def _route(url, **kw):
        if "/search?" in url:
            return _R(text=search_html)
        if "/episode/list/" in url:
            return _R(js={"html": eps_html})
        if "/episode/servers" in url:
            return _R(js={"html": servers_html})
        return _R(text=f'window.__P="{payload}"')

    monkeypatch.setattr(GA, "_get", _route)
    g = GA.AnimeExtractor()
    out = g.search_hianime("Solo Leveling", episode=1)
    assert len(out) == 2
    assert {o["source"] for o in out} == {
        "HiAnime (SUB - ZokoAnime)", "HiAnime (DUB - ZokoAnime)"}
    assert all(o["type"] == "M3U8" for o in out)
    assert out[0]["subtitles"] == [
        {"lang": "English", "url": "https://cdn.example.com/en.vtt"}]
    assert "Referer" in out[0]["headers"]


def test_hianime_no_match_or_episode(monkeypatch):
    from freeflix_cli.scraping import goldenanime as GA

    class _R:
        text = "<html></html>"
        status_code = 200

        def json(self):
            return {"html": ""}

    monkeypatch.setattr(GA, "_get", lambda *a, **k: _R())
    g = GA.AnimeExtractor()
    assert g.search_hianime("No Such Anime 12345") == []


def test_hianime_shows_parse(monkeypatch):
    from freeflix_cli.scraping import goldenanime as GA

    html = (
        '<div class="flw-item flw-item-big"><div class="film-poster">'
        '<div class="tick-item tick-sub"><i class="x"></i>12</div>'
        '<div class="tick-item tick-dub"><i class="x"></i>12</div>'
        '<img src="https://cdn.example.com/p.png"></div>'
        '<div class="film-detail"><h3 class="film-name">'
        '<a href="https://hianime.at/solo-leveling-235"'
        ' title="Solo Leveling &amp; Co">x</a></h3></div></div>'
        '<div id="main-sidebar"><div class="film-detail">'
        '<h3 class="film-name"><a href="https://hianime.at/nope-1"'
        ' title="Sidebar Dup">x</a></h3></div></div>'
    )

    class _R:
        text = html
        status_code = 200

    monkeypatch.setattr(GA, "_get", lambda *a, **k: _R())
    shows = GA.AnimeExtractor().search_hianime_shows("Solo Leveling")
    assert len(shows) == 1  # sidebar dup cut off
    s = shows[0]
    assert s["slug"] == "solo-leveling-235"
    assert s["title"] == "Solo Leveling & Co"
    assert s["poster"] == "https://cdn.example.com/p.png"
    assert (s["sub"], s["dub"]) == ("12", "12")


def test_hianime_episodes_parse(monkeypatch):
    from freeflix_cli.scraping import goldenanime as GA

    class _R:
        status_code = 200

        def json(self):
            return {"html": '<a data-number="1" data-id="4341" x>'
                            '<a data-number="2" data-id="4342" x>'}

    monkeypatch.setattr(GA, "_get", lambda *a, **k: _R())
    assert GA.AnimeExtractor().get_hianime_episodes(
        "solo-leveling-235") == [(1, "4341"), (2, "4342")]


def test_coflix_latest_uses_homepage_grid(monkeypatch):
    from freeflix_cli.scraping import coflix
    html = (
        "<html><body>"
        '<a href="https://coflix.ac/film/dune/"><img alt="Dune"'
        ' src="https://image.tmdb.org/t/p/w500/x.jpg"></a>'
        '<a href="https://coflix.ac/serie/breaking-bad/"><img alt="Breaking Bad"'
        ' src="https://image.tmdb.org/t/p/w500/y.jpg"></a>'
        "</body></html>"
    )

    class _R:
        text = html
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(coflix, "_get", lambda *a, **k: _R())
    monkeypatch.setattr(coflix, "website_origin", "https://coflix.ac")
    out = coflix.latest(5)
    assert [r.title for r in out] == ["Dune", "Breaking Bad"]


def test_top_catalog_normalizes(monkeypatch):
    from freeflix_cli.handlers import goldenms as G
    metas = [{"name": "X", "year": "2026", "id": "tt1",
              "poster": "https://x/p.jpg"}]
    monkeypatch.setattr(G, "_cinemeta_json", lambda *a, **k: {"metas": metas})
    out = G.top_catalog(True, 5)
    assert out[0]["releaseInfo"] == "2026"


def test_anilist_trending_shape(monkeypatch):
    from freeflix_cli import anilist as A
    media = [{"id": 1, "title": {"english": "X", "romaji": "Y"}}]
    monkeypatch.setattr(A.AniListClient, "_query",
                        lambda self, q, v=None: {"Page": {"media": media}})
    assert A.AniListClient().trending(3) == media


def test_eztv_latest_sorted(monkeypatch):
    from freeflix_cli.scraping import eztv
    batch = {"torrents": [
        {"title": "Old", "filename": "old.mkv", "hash": "A" * 40,
         "season": 1, "episode": 1, "seeds": 1,
         "date_released_unix": 100, "size_bytes": 10,
         "magnet_url": "magnet:?xt=1", "imdb_id": "tt1"},
        {"title": "New", "filename": "new.mkv", "hash": "B" * 40,
         "season": 2, "episode": 3, "seeds": 9,
         "date_released_unix": 200, "size_bytes": 20,
         "magnet_url": "magnet:?xt=2", "imdb_id": "tt2"},
    ]}

    class _R:
        status_code = 200

        def json(self):
            return batch

    monkeypatch.setattr(eztv.scraper, "get", lambda *a, **k: _R())
    out = eztv.latest(5)
    assert [r["filename"] for r in out] == ["new.mkv", "old.mkv"]


def test_xpass_decrypt_roundtrip():
    """Xpass /data/* crypto: encrypt with the documented scheme, the helper
    must recover the JSON ; tampered input must yield None (fail-closed)."""
    import base64
    import hashlib
    import json
    import os

    from Crypto.Cipher import AES

    from freeflix_cli.scraping import goldenms

    path = "/data/movie/550"
    token = "djN8cGF0aHxi" + "." + "ab" * 32
    payload = [{"name": "TIK 1", "url": "/mdata/abc/1/playlist.json"}]
    key = bytes.fromhex(hashlib.sha256(
        (goldenms._XPASS_KEY_PREFIX + path + "|" + token).encode()
    ).hexdigest())
    nonce = os.urandom(12)
    ct, tag = AES.new(key, AES.MODE_GCM, nonce=nonce).encrypt_and_digest(
        json.dumps(payload).encode()
    )
    body = base64.urlsafe_b64encode(nonce + ct + tag).decode().rstrip("=")

    assert goldenms._xpass_decrypt_data(body, path, token) == payload
    # Tampered / wrong shapes fail closed.
    assert goldenms._xpass_decrypt_data(body[:-4] + "AAAA", path, token) is None
    assert goldenms._xpass_decrypt_data(body, path, "badtoken") is None
    assert goldenms._xpass_decrypt_data("", path, token) is None


def test_xpass_search_uses_dataurl(monkeypatch):
    """search_xpass follows var dataUrl → decrypt → playlist.json files."""
    import json as _json

    from freeflix_cli.scraping import goldenms

    entries = [{"name": "TIK 1", "url": "/mdata/abc/1/playlist.json"}]

    class _R:
        def __init__(self, text="", payload=None):
            self._text = text
            self._payload = payload
            self.status_code = 200

        @property
        def text(self):
            return self._text

        def json(self):
            return self._payload

        def raise_for_status(self):
            pass

    calls = {}

    def _fake_get(url, **kw):
        calls.setdefault("urls", []).append(url)
        if url.endswith("/e/movie/550"):
            return _R(text='<script>var dataUrl="/data/movie/550?token=T.{}";</script>'.format("ab" * 32))
        if "/data/movie/550" in url:
            import base64
            import hashlib

            from Crypto.Cipher import AES

            token = "T." + "ab" * 32
            key = bytes.fromhex(hashlib.sha256(
                (goldenms._XPASS_KEY_PREFIX + "/data/movie/550" + "|" + token).encode()
            ).hexdigest())
            import os

            nonce = os.urandom(12)
            ct, tag = AES.new(key, AES.MODE_GCM, nonce=nonce).encrypt_and_digest(
                _json.dumps(entries).encode()
            )
            blob = base64.urlsafe_b64encode(nonce + ct + tag).decode().rstrip("=")
            return _R(text=blob)
        if url.endswith("playlist.json"):
            return _R(payload={"playlist": [{"sources": [
                {"file": "https://cdn.example.com/master.m3u8", "label": "TIK 2"}]}]})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(goldenms, "_get", _fake_get)
    out = goldenms.goldenms_extractor.search_xpass(550)
    assert len(out) == 1
    assert out[0]["url"] == "https://cdn.example.com/master.m3u8"
    assert out[0]["source"] == "Xpass (TIK 1)"
    assert out[0]["type"] == "M3U8"


def test_clean_text_normalises_scraped_strings():
    from freeflix_cli.scraping.utils import clean_text

    assert clean_text("  Tokyo   Ravens  ") == "Tokyo Ravens"
    assert clean_text("Dune &amp; Co") == "Dune & Co"
    assert clean_text("\u00a0One\u200b Piece") == "One Piece"
    assert clean_text("  - | ") == ""
    assert clean_text(None) == ""


def test_show_poster_does_not_repeat_title():
    """After a menu printed the title, show_poster must not print it again,
    and info lines are whitespace-collapsed (no '1 saison(s)' mess)."""
    import io

    from rich.console import Console

    from freeflix_cli import terminal_image

    buf = io.StringIO()
    old = terminal_image._console
    old_title = terminal_image._last_poster_title
    old_render = terminal_image.render_url
    terminal_image._console = Console(file=buf, force_terminal=False, width=80)
    terminal_image.render_url = lambda *a, **k: False
    terminal_image._last_poster_title = ""
    try:
        terminal_image.show_poster("", title="Tokyo   Ravens",
                                   info_lines=["1 saison", "  "])
        terminal_image.show_poster("", title="Tokyo Ravens", info_lines=["2 saisons"])
    finally:
        terminal_image._console = old
        terminal_image._last_poster_title = old_title
        terminal_image.render_url = old_render
    out = buf.getvalue()
    assert out.count("Tokyo Ravens") == 1
    assert "2 saisons" in out and "1 saison" in out
