"""HLS playability preflight.

A signed CDN link can expire between resolution and playback: the manifest
still answers 200 (with every segment listed) but each segment is refused
with 403. mpv then dies with a bare ``[lavf] avformat_open_input() failed``
and VLC shows a black window, which reads like a broken install. The probe
turns that into "this link has expired".
"""

from freeflix_cli import player_manager as pm


class _Resp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


_PLAYLIST = "#EXTM3U\n#EXTINF:10,\nseg-1.ts\n#EXTINF:10,\nseg-2.ts\n"
_MASTER = (
    "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\nlow/index.m3u8\n"
    "#EXT-X-STREAM-INF:BANDWIDTH=2400000\nhigh/index.m3u8\n"
)


def _fake_session(by_url):
    class _S:
        def get(self, url, headers=None, timeout=None, allow_redirects=True):
            if url not in by_url:
                raise RuntimeError("unexpected url " + url)
            value = by_url[url]
            if isinstance(value, Exception):
                raise value
            return value

    return _S()


def test_expired_segments_are_reported(monkeypatch):
    """Manifest OK + segment 403 = an expired link, not a broken player."""
    url = "https://cdn.example/x/index.m3u8?t=abc"
    # A relative segment inherits only the directory: the manifest's query is
    # NOT repeated (real HLS players resolve it exactly this way).
    seg = "https://cdn.example/x/seg-1.ts"
    monkeypatch.setattr(pm, "shared_session", lambda: _fake_session({
        url: _Resp(200, _PLAYLIST),
        seg: _Resp(403, ""),
    }))
    assert pm.probe_hls_playable(url, {}) == (False, "expired")


def test_410_is_also_expired(monkeypatch):
    url = "https://cdn.example/x/index.m3u8"
    monkeypatch.setattr(pm, "shared_session", lambda: _fake_session({
        url: _Resp(200, _PLAYLIST),
        "https://cdn.example/x/seg-1.ts": _Resp(410, ""),
    }))
    assert pm.probe_hls_playable(url, {}) == (False, "expired")


def test_missing_segment_is_offline(monkeypatch):
    url = "https://cdn.example/x/index.m3u8"
    monkeypatch.setattr(pm, "shared_session", lambda: _fake_session({
        url: _Resp(200, _PLAYLIST),
        "https://cdn.example/x/seg-1.ts": _Resp(404, ""),
    }))
    assert pm.probe_hls_playable(url, {}) == (False, "offline")


def test_playable_stream_passes(monkeypatch):
    url = "https://cdn.example/x/index.m3u8"
    monkeypatch.setattr(pm, "shared_session", lambda: _fake_session({
        url: _Resp(200, _PLAYLIST),
        "https://cdn.example/x/seg-1.ts": _Resp(200, "\x47"),
    }))
    assert pm.probe_hls_playable(url, {}) == (True, "")


def test_master_playlist_follows_first_variant(monkeypatch):
    url = "https://cdn.example/x/master.m3u8"
    variant = "https://cdn.example/x/low/index.m3u8"
    monkeypatch.setattr(pm, "shared_session", lambda: _fake_session({
        url: _Resp(200, _MASTER),
        variant: _Resp(200, _PLAYLIST),
        "https://cdn.example/x/low/seg-1.ts": _Resp(403, ""),
    }))
    assert pm.probe_hls_playable(url, {}) == (False, "expired")


def test_network_noise_never_blocks_playback(monkeypatch):
    """A flaky probe must not refuse a stream the player could have opened."""
    url = "https://cdn.example/x/index.m3u8"
    monkeypatch.setattr(pm, "shared_session", lambda: _fake_session({
        url: RuntimeError("timeout"),
    }))
    assert pm.probe_hls_playable(url, {}) == (True, "")


def test_non_hls_urls_are_skipped(monkeypatch):
    def boom():
        raise AssertionError("must not touch the network for a direct file")

    monkeypatch.setattr(pm, "shared_session", boom)
    assert pm.probe_hls_playable("https://cdn.example/movie.mp4", {}) == (True, "")
