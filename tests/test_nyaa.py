"""
Tests for the modernized Nyaa provider (search params, badges, helpers).
All offline (fixture HTML + monkeypatched fetch).
"""

from freeflix_cli.scraping import nyaa


ROW = (
    '<tr class="{cls}">'
    '<td><a href="/?c=1_0"><i class="fa"></i></a></td>'
    '<td><a href="/view/1952386">{title}</a></td>'
    '<td><a href="magnet:?xt=urn:btih:ABC123">M</a></td>'
    "<td>{size}</td><td>{date}</td><td>{seeds}</td>"
    "<td>{leech}</td><td>12919</td></tr>"
)

HTML = (
    "<html><body><table class='torrent-list'><thead><tr>"
    "<th>Category</th><th>Name</th><th>Link</th><th>Size</th>"
    "<th>Date</th><th>S</th><th>L</th><th>D</th>"
    "</tr></thead><tbody>"
    + ROW.format(cls="success", title="[Breeze] Solo Leveling S01 [1080p]",
                 size="9.7 GiB", date="2025-03-26 06:54",
                 seeds="238", leech="5")
    + ROW.format(cls="danger", title="[X] Old Remake [720p]",
                 size="1.2 GiB", date="2024-01-01 00:00",
                 seeds="0", leech="0")
    + "</tbody></table></body></html>"
)


class _Resp:
    text = HTML
    status_code = 200

    def raise_for_status(self):
        pass


def _patch(monkeypatch, seen=None):
    def _fake(session, url, **kw):
        if seen is not None:
            seen.append(url)
        return _Resp()
    monkeypatch.setattr(nyaa.cloudflare, "cf_get", _fake)


def test_badges_and_fields(monkeypatch):
    _patch(monkeypatch)
    res = nyaa.search("solo leveling")
    assert len(res) == 2
    good, dead = res
    assert good["trusted"] is True and good["remake"] is False
    assert good["quality"] == "1080p"
    assert good["size"] == "9.7 GiB"
    assert good["size_bytes"] == int(9.7 * 1024 ** 3)
    assert good["date"] == "2025-03-26"
    assert good["seeders"] == 238 and good["leechers"] == 5
    assert good["torrent_id"] == "1952386"
    assert good["torrent_url"].endswith("/download/1952386.torrent")
    assert dead["remake"] is True and dead["trusted"] is False
    assert dead["quality"] == "720p"
    assert dead["seeders"] == 0


def test_search_params_in_url(monkeypatch):
    seen = []
    _patch(monkeypatch, seen)
    nyaa.search("naruto", category="anime", trusted_only=True,
                min_seeders=5, page=2)
    url = seen[0]
    assert "c=1_0" in url and "f=2" in url and "p=3" in url
    # min_seeders filters client-side (0-seed remake dropped)
    res = nyaa.search("naruto", min_seeders=5)
    assert [r["title"] for r in res] == ["[Breeze] Solo Leveling S01 [1080p]"]


def test_size_to_bytes_and_quality():
    assert nyaa.size_to_bytes("9.7 GiB") == int(9.7 * 1024 ** 3)
    assert nyaa.size_to_bytes("nonsense") == 0
    assert nyaa.detect_quality("[Group] Show - 12 [1080p][HEVC]") == "1080p"
    assert nyaa.detect_quality("Some DVD Rip") == "DVD"
    assert nyaa.detect_quality("no clue here") == "?"


def test_format_row_badges():
    from freeflix_cli.handlers import nyaa as h
    row = h._format_row({
        "title": "T", "size": "1.0 GiB", "seeders": 3,
        "quality": "1080p", "trusted": True,
    })
    assert "✓" in row and "1080p" in row
    row0 = h._format_row({
        "title": "T", "size": "1.0 GiB", "seeders": 0,
        "quality": "?", "trusted": False,
    })
    assert "0" in row0  # dead-torrent marker path exercised


def test_parse_progress_metadata_state():
    from freeflix_cli.progress import parse_progress
    info = parse_progress("[#28e2d3 0B/0B CN:0 SD:0 DL:0B]\nFILE: [MEMORY][METADATA]foo.mkv")
    assert info["meta"] is True
    assert info["frac"] is None
    info2 = parse_progress("[#28e2d3 45% CN:4 DL:1.2MiB]")
    assert info2["meta"] is False
    assert info2["frac"] == 0.45


def test_aria_cmd_modern_flags():
    from freeflix_cli.handlers import nyaa as h
    cmd = h._base_aria_cmd("magnet:?xt=urn:btih:ABC")
    joined = " ".join(cmd)
    assert "--dht-entry-point=router.bittorrent.com:6881" in joined
    assert "--bt-stop-timeout=300" in joined
    assert "--continue=true" not in joined  # added by caller, not base
    assert cmd[-1].startswith("magnet:")


def test_yts_clean_and_mirrors():
    from freeflix_cli.scraping import yts
    m = {
        "id": 1, "title": "X", "title_english": "Superman", "year": 2025,
        "rating": 7.0, "runtime": 120, "genres": ["Action"],
        "synopsis": "S", "medium_cover_image": "https://x/p.jpg",
        "url": "https://yts.lt/movie/x", "imdb_code": "tt1",
        "torrents": [
            {"quality": "1080p", "size": "2 GB", "size_bytes": 2,
             "seeds": 5, "peers": 1, "hash": "ABC123",
             "date_uploaded": "2026-10-01 00:00:00"},
            {"quality": "nohash"},
        ],
    }
    c = yts._clean(m)
    assert c["title"] == "Superman" and len(c["qualities"]) == 1
    q = c["qualities"][0]
    assert q["magnet"].startswith("magnet:?xt=urn:btih:ABC123")
    assert "&tr=" in q["magnet"]
    assert yts._clean({"title": "No torrents"}) is None


def test_yts_search_uses_api(monkeypatch):
    from freeflix_cli.scraping import yts
    seen = []

    class _R:
        status_code = 200

        def json(self):
            return {"status": "ok", "data": {"movies": []}}

    def _fake(url, params=None, **kw):
        seen.append((url, params))
        return _R()

    monkeypatch.setattr(yts.scraper, "get", _fake)
    assert yts.search("Dune") == []
    assert yts.latest(5) == []
    assert any("/api/v2/list_movies.json" in u for u, _ in seen)
    assert any((p or {}).get("query_term") == "Dune" for _, p in seen)


def test_guess_show():
    from freeflix_cli.handlers.yts import _guess_show
    title, season, ep = _guess_show("[Breeze] Solo Leveling S01 v2 [1080p BD AV1][Dual Audio]")
    assert season == 1 and ep == 1 and "Solo Leveling" in title
    assert "Breeze" not in title and "1080p" not in title
    title, _s, ep = _guess_show("[SubsPlease] One Piece - 1090 (1080p) [ABC].mkv")
    assert ep == 1090 and "One Piece" in title
    title, _s, ep = _guess_show("[Judas] Frieren E12 [720p]")
    assert ep == 12
