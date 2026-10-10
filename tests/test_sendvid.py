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


def test_analyze_gives_ffprobe_room_for_throttled_mp4(monkeypatch):
    """sendvid serves throttled MP4s needing ~15 s of ffprobe — the fallback
    must be called with a timeout that fits, or no quality is ever shown."""
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
    assert seen["timeout"] >= 18
    assert pm.format_quality_label(out) == "720p ~1.4 Mbps"
