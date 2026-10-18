"""
Tests for the sendvid extractor (scraping.player.get_hls_link_sendvid).

Regression: the extractor returned the ``og:video`` meta URL
(``https://sendvid.com/xxx.mp4``) which answers ``text/html`` — mpv failed
with "Failed to recognize file format" and 0 MB consumed (Tokyo Revengers
S4E1, Lecteur sendvid). The REAL file is the signed
``videosN.sendvid.com/…mp4?…`` URL in ``<source src=…>``.
"""

from freeflix_cli.scraping import player


class _Resp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        pass


_HTML = """<html><head>
<meta property="og:video" content="https://sendvid.com/oxhyare2.mp4"/>
</head><body>
<video><source src="https://videos4.sendvid.com/ff/6b/oxhyare2.mp4?validfrom=1&validto=2&rate=250k&hash=ABC" type="video/mp4"/></video>
</body></html>"""

_HTML_OG_ONLY = """<html><head>
<meta property="og:video" content="https://sendvid.com/abc123.mp4"/>
</head><body></body></html>"""


def test_prefers_source_tag_over_og_video(monkeypatch):
    monkeypatch.setattr(player, "_get", lambda *a, **k: _Resp(_HTML))
    monkeypatch.setattr(player, "_is_sendvid_placeholder", lambda *a, **k: False)
    out = player.get_hls_link_sendvid("https://sendvid.com/embed/oxhyare2")
    assert out.startswith("https://videos4.sendvid.com/")
    assert out.endswith(".mp4?validfrom=1&validto=2&rate=250k&hash=ABC")


def test_falls_back_to_og_video_when_no_source(monkeypatch):
    monkeypatch.setattr(player, "_get", lambda *a, **k: _Resp(_HTML_OG_ONLY))
    out = player.get_hls_link_sendvid("https://sendvid.com/embed/abc123")
    assert out == "https://sendvid.com/abc123.mp4"


def test_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr(player, "_get", lambda *a, **k: _Resp("<html></html>"))
    assert player.get_hls_link_sendvid("https://sendvid.com/embed/zzz") is None


class _HeadResp:
    def __init__(self, length):
        self.headers = {"Content-Length": str(length)} if length is not None else {}


def _fake_head_factory(length):
    class _S:
        def head(self, *a, **k):
            return _HeadResp(length)
    return _S()


def test_placeholder_guard_rejects_tiny_file(monkeypatch):
    monkeypatch.setattr(player, "_scraper", lambda: _fake_head_factory(36789))
    assert player._is_sendvid_placeholder("https://videos4.sendvid.com/x.mp4?t=1") is True


def test_placeholder_guard_keeps_real_episode(monkeypatch):
    monkeypatch.setattr(player, "_scraper", lambda: _fake_head_factory(276616053))
    assert player._is_sendvid_placeholder("https://videos4.sendvid.com/x.mp4?t=1") is False


def test_placeholder_guard_fail_open_without_length(monkeypatch):
    monkeypatch.setattr(player, "_scraper", lambda: _fake_head_factory(None))
    assert player._is_sendvid_placeholder("https://videos4.sendvid.com/x.mp4?t=1") is False


def test_dedup_players_drops_duplicate_urls():
    from freeflix_cli.handlers import playback
    from freeflix_cli.scraping.objects import Player

    ps = [
        Player("Lecteur 1", "https://ansembed.net/embed-aaa.html"),
        Player("Lecteur 2", "https://ansembed.net/embed-aaa.html"),
        Player("Lecteur 3", "https://sendvid.com/embed/bbb"),
    ]
    out = playback._dedup_players(ps)
    assert [p.url for p in out] == [
        "https://ansembed.net/embed-aaa.html",
        "https://sendvid.com/embed/bbb",
    ]


def test_analyze_ffprobe_timeout_is_bounded(monkeypatch):
    """The quality menu must not stall on a throttled MP4: ffprobe now gets
    the caller's bounded timeout (default 9 s, 5 s from the menu) instead of
    the old fixed 20 s."""
    from freeflix_cli import player_manager as pm

    seen = {}

    def _fake_ffprobe(url, headers, timeout=12):
        seen["timeout"] = timeout
        return {"height": 720, "mbps": 1.4}

    monkeypatch.setattr(pm, "_probe_stream", lambda *a, **k: {"variants": [], "blocked": None})
    monkeypatch.setattr(pm, "_ffprobe_quality", _fake_ffprobe)
    monkeypatch.setattr(
        pm.player, "get_hls_link", lambda *a, **k: "https://videos4.sendvid.com/x.mp4?t=1"
    )
    out = pm.analyze_stream_quality("https://sendvid.com/embed/x", {})
    assert out["qualities"] == [{"height": 720, "mbps": 1.4}]
    assert 0 < seen["timeout"] <= 9
    assert pm.format_quality_label(out) == "720p ~1.4 Mbps"


def test_analyze_is_cached(monkeypatch):
    """Re-entering the same episode must not re-extract every player."""
    from freeflix_cli import player_manager as pm

    calls = {"n": 0}

    def _fake_link(*a, **k):
        calls["n"] += 1
        return "https://cdn.example.com/master.m3u8"

    monkeypatch.setattr(pm.player, "get_hls_link", _fake_link)
    monkeypatch.setattr(
        pm, "_probe_stream",
        lambda *a, **k: {"variants": [{"label": "1080p", "bandwidth": 5_000_000,
                                       "height": 1080, "uri": "v.m3u8"}],
                         "blocked": None},
    )
    pm._quality_cache.clear()
    first = pm.analyze_stream_quality("https://player.example/embed/cache-test", {})
    second = pm.analyze_stream_quality("https://player.example/embed/cache-test", {})
    assert first["ok"] and second["ok"]
    assert calls["n"] == 1  # second call served from the cache
