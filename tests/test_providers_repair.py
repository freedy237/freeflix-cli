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
