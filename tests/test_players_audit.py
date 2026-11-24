"""Regression tests from the 2026-11 live audit of every reader/source.

The audit resolved real episodes from every FreeFlix source and probed the
resulting media (manifest + first segment / ffprobe). Two readers were broken
on the FreeFlix side and are covered here:

* **uqload** — the extractor only fetched the stripped ``/<id>.html`` page,
  while the current player lives on ``/embed-<id>.html`` (Anime-Sama's
  "Lecteur 3" resolved to nothing on every series). Both layouts coexist and
  some ids only answer on one of them, so every candidate form must be tried
  until one page actually carries the player.
* **dood / DoodStream mirrors** — the extractor kept the *source* Referer
  (coflix.ac, french-stream.net…), and Dood answers a 38-byte "Video embed
  restricted for this domain" page (HTTP 200) for any foreign domain. The
  Referer must be overridden with the player's own host.

Tests are network-free: both ``player._get`` and ``player.requests.get`` are
monkeypatched.
"""

from freeflix_cli.scraping import player as pl


# ── helpers ──────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.url = ""
        self.headers = {}

    def raise_for_status(self):
        return None


def _player_page(stream_url):
    return 'var player={file:"' + stream_url + '"}'


# ── uqload : page layout candidates ──────────────────────────────────────


def test_uqload_page_candidates_embed_form():
    assert pl._uqload_page_candidates("https://uqload.vc/embed-abc.html") == [
        "https://uqload.vc/embed-abc.html",
        "https://uqload.vc/abc.html",
    ]


def test_uqload_page_candidates_plain_form_adds_embed():
    assert pl._uqload_page_candidates("https://uqload.vc/abc.html") == [
        "https://uqload.vc/abc.html",
        "https://uqload.vc/embed-abc.html",
    ]


def test_uqload_page_candidates_short_e_path():
    cands = pl._uqload_page_candidates("https://uqload.vc/e/abc")
    assert cands[0] == "https://uqload.vc/e/abc"
    assert "https://uqload.vc/embed-abc.html" in cands


def test_uqload_page_candidates_empty():
    assert pl._uqload_page_candidates("") == []
    assert pl._uqload_page_candidates(None) == []


def test_uqload_embed_page_that_only_serves_legacy_layout(monkeypatch):
    """The embed- form answers a premium shell: the legacy form must be tried."""
    real = ("https://strm14.uqload.vc/hls2/01/06038/abc_,l,n,.urlset/"
            "master.m3u8?t=T&s=1&e=14400&i=0")
    called = []

    def fake_get(url, **kw):
        called.append(url)
        if "/embed-" in url:
            return _Resp("<html>premium shell, no player</html>")
        return _Resp(_player_page(real))

    monkeypatch.setattr(pl, "_get", fake_get)
    monkeypatch.setattr(pl, "requests",
                        type("R", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setattr(pl, "_hls_duration_seconds", lambda *a, **k: 1387.0)

    out = pl.get_hls_link_uqload(
        "https://uqload.vc/embed-abc.html", {"Referer": "https://anime-sama.to/"})
    assert out == real
    # Both candidate pages were attempted, in order.
    assert called[0] == "https://uqload.vc/embed-abc.html"
    assert "https://uqload.vc/abc.html" in called


def test_uqload_plain_page_falls_back_to_embed_player(monkeypatch):
    """A legacy-form URL whose page has no player must reach the embed page.

    This is the exact Anime-Sama "Lecteur 3" failure: the extractor asked only
    the stripped page and gave up although the real embed carried the stream.
    """
    real = ("https://strm2.uqload.vc/hls2/02/05873/ep_h/master.m3u8"
            "?t=T&s=2&e=14400")
    seen = []

    def fake_get(url, **kw):
        seen.append(url)
        if "/embed-" in url:
            return _Resp(_player_page(real))
        return _Resp("<html>landing page without a player</html>")

    monkeypatch.setattr(pl, "_get", fake_get)
    monkeypatch.setattr(pl, "requests",
                        type("R", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setattr(pl, "_hls_duration_seconds", lambda *a, **k: 1391.0)

    out = pl.get_hls_link_uqload("https://uqload.vc/ep.html", {})
    assert out == real
    assert any("/embed-ep.html" in u for u in seen)


def test_uqload_placeholder_page_returns_none(monkeypatch):
    page = "<div>File was locked by administrator</div>"
    monkeypatch.setattr(pl, "_get", lambda *a, **k: _Resp(page))
    monkeypatch.setattr(pl, "requests",
                        type("R", (), {"get": staticmethod(lambda *a, **k: _Resp(page))}))
    assert pl.get_hls_link_uqload("https://uqload.vc/embed-x.html", {}) is None


def test_uqload_stream_keeps_embed_headers(monkeypatch):
    real = "https://strm1.uqload.vc/hls2/01/0195/abc_n/master.m3u8?t=T"
    monkeypatch.setattr(pl, "_get",
                        lambda *a, **k: _Resp(_player_page(real)))
    monkeypatch.setattr(pl, "_hls_duration_seconds", lambda *a, **k: 1387.0)
    out = pl.get_hls_link_uqload(
        "https://uqload.vc/embed-abc.html",
        {"Referer": "https://anime-sama.to/"},
    )
    assert out == real
    headers = pl.get_stream_headers(out)
    assert headers["Referer"] == "https://uqload.vc/"
    assert headers["Origin"] == "https://uqload.vc"


def test_uqload_stream_from_page_extracts_plain_payload():
    url = "https://cdn.example.com/live/master.m3u8?t=abc"
    assert pl._uqload_stream_from_page(_player_page(url)) == url


def test_uqload_short_ad_placeholder_is_rejected(monkeypatch):
    page = _player_page("https://cdn.example.com/live/master.m3u8?t=abc")
    monkeypatch.setattr(pl, "_get", lambda *a, **k: _Resp(page))
    monkeypatch.setattr(pl, "_hls_duration_seconds", lambda *a, **k: 30.0)
    assert pl.get_hls_link_uqload("https://uqload.vc/embed-x.html", {}) is None


# ── dood / DoodStream : the player's own Referer is mandatory ────────────


def test_dood_overrides_source_referer_with_player_host(monkeypatch):
    """A Coflix/French-Stream Referer gets a "restricted" page from Dood."""
    page = (
        "<html><script>$.get('/pass_md5/285523768-143-105-1793609068-abc/"
        "8te4');var token='tok123';</script></html>"
    )
    page_headers = []

    class _Token(_Resp):
        def __init__(self):
            super().__init__("https://ec549vh.cloudatacdn.com/u5kj6ror/x~")

    def fake_get(url, **kw):
        if "pass_md5" in url:
            page_headers.append(kw.get("headers") or {})
            return _Token()
        page_headers.append(kw.get("headers") or {})
        return _Resp(page)

    monkeypatch.setattr(pl, "_get", fake_get)
    out = pl.get_hls_link_dood(
        "https://playmogo.com/e/abc",
        {"Referer": "https://coflix.ac/", "Origin": "https://coflix.ac"},
    )
    assert out
    first_headers = page_headers[0]
    # The SOURCE Referer must never be sent to Dood: only its own origin.
    assert first_headers["Referer"] == "https://playmogo.com/"
    assert "Origin" not in first_headers


def test_dood_token_request_uses_player_host_referer(monkeypatch):
    page = (
        "<html><script>$.get('/pass_md5/285523768-143-105-1793609050-abc/"
        "tokenxyz');var token='tok456';</script></html>"
    )
    seen = []

    def fake_get(url, **kw):
        seen.append((url, kw.get("headers") or {}))
        if "pass_md5" in url:
            return _Resp("https://cdn.example.com/vid/x.mp4?token=t")
        return _Resp(page)

    monkeypatch.setattr(pl, "_get", fake_get)
    out = pl.get_hls_link_dood(
        "https://kokoflix.lol/tokyo_go.php?id=ABC", {},
        player_host="playmogo.com",
    )
    assert out == "https://cdn.example.com/vid/x.mp4?token=t"
    # The first page is the kokoflix proxy: it must introduce itself as the
    # real mirror, never as the source that embedded it.
    assert seen[0][1]["Referer"] == "https://playmogo.com/"


def test_dood_placeholder_returns_none(monkeypatch):
    page = "WE ARE SORRY We can't find the video"
    monkeypatch.setattr(pl, "_get", lambda *a, **k: _Resp(page))
    assert pl.get_hls_link_dood("https://playmogo.com/e/abc", {}) is None


# ── dead hosts masked from the player menu ────────────────────────────────


def test_wishonly_is_masked():
    """Every wishonly embed answers the 38-byte "restricted" stub: never offer it."""
    assert pl.is_known_offline("https://wishonly.site/e/sueme6n0rww8") is True
    assert pl.is_known_offline("https://wishonly.site/d/52r9xc2jcj6l") is True


def test_working_hosts_are_not_masked_by_the_audit():
    """The audit must not over-hide readers that were proven playable."""
    for url in (
        "https://ansembed.net/embed-vwvhduqn5fvc.html",
        "https://voe.sx/e/mpaoixewfj5u",
        "https://uqload.vc/embed-x.html",
        "https://vidzy.org/embed-x.html",
        "https://fsvid.lol/embed-x.html",
        "https://lplaygo.com/e/x",
    ):
        assert pl.is_known_offline(url) is False, url
