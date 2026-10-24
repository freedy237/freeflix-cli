"""
Tests for the anti-scraper decoy-stream filter (scraping.player._is_decoy_stream).

Some hosts (e.g. french-stream's fsvid.lol) return a "troll" placeholder video
to bots instead of the real content — get_hls_link must reject it so the player
is marked unavailable and playback falls back to a host that works.
"""

from freeflix_cli.scraping import player


def test_troll_stream_is_decoy():
    assert player._is_decoy_stream("https://s1.fsvid.lol/troll/master.m3u8") is True
    assert player._is_decoy_stream("https://host/fake/master.m3u8") is True
    assert player._is_decoy_stream("https://host/decoy/x.m3u8") is True


def test_real_stream_is_not_decoy():
    assert player._is_decoy_stream(
        "https://strm4.uqload.is/hls2/04/02505/p44nkmonx8pe_n/master.m3u8?t=abc"
    ) is False
    assert player._is_decoy_stream("https://cdn.example.com/master.m3u8") is False


def test_empty_or_none_is_not_decoy():
    assert player._is_decoy_stream(None) is False
    assert player._is_decoy_stream("") is False


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_hls_duration_and_uqload_short_placeholder(monkeypatch):
    master = (
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=720x304\n"
        "variant.m3u8\n"
    )
    short = (
        "#EXTM3U\n#EXTINF:15.0,\nseg1\n#EXTINF:15.0,\nseg2\n"
        "#EXT-X-ENDLIST\n"
    )
    long = (
        "#EXTM3U\n#EXTINF:60.0,\nseg1\n#EXTINF:60.0,\nseg2\n"
        "#EXT-X-ENDLIST\n"
    )

    def fake_get(url, **kw):
        if ".html" in url:
            return _Resp('var player={file:"https://cdn/master.m3u8"}')
        if "master.m3u8" in url:
            return _Resp(master)
        return _Resp(short)

    monkeypatch.setattr(player, "_get", fake_get)
    assert player._hls_duration_seconds("https://cdn/master.m3u8") == 30.0
    assert player.get_hls_link_uqload(
        "https://uqload.vc/embed-x.html", {}
    ) is None

    monkeypatch.setattr(
        player, "_get",
        lambda url, **kw: _Resp(long) if "variant" in url else (
            _Resp(master) if "master" in url else _Resp(
                'var player={file:"https://cdn/master.m3u8"}')),
    )
    assert player.get_hls_link_uqload(
        "https://uqload.vc/embed-x.html", {}
    ) == "https://cdn/master.m3u8"
