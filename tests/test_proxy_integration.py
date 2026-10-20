"""
End-to-end integration test for the stdlib (no-Flask) proxy.

A fake upstream serves an HLS master + segments and an MP4 with Range support.
We start the real proxy and drive it over HTTP : it must rewrite the manifest's
segment URLs back through itself, deliver the segments byte-for-byte, honour a
Range request on the MP4, and serve the web player. The SSRF guard is patched
off for this test only (the upstream is on loopback); it's covered separately.
"""

import re
import threading
import urllib.request
import http.server

import pytest

from freeflix_cli import proxy

SEG0 = b"SEGMENT-ZERO-" * 1000
SEG1 = b"SEGMENT-ONE--" * 1000
MP4 = bytes([i % 256 for i in range(200000)])
MEDIA_M3U8 = (
    "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:4\n"
    "#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-PLAYLIST-TYPE:VOD\n"
    "#EXTINF:4.0,\nseg0.ts\n#EXTINF:4.0,\nseg1.ts\n#EXT-X-ENDLIST\n"
)


class _Upstream(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/master.m3u8":
            body = MEDIA_M3U8.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        elif path in ("/seg0.ts", "/seg1.ts"):
            body = SEG0 if path.endswith("0.ts") else SEG1
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        elif path in ("/movie.mp4", "/movie.bin"):
            rng = self.headers.get("Range")
            start = 0
            if rng:
                m = re.match(r"bytes=(\d+)-", rng)
                start = int(m.group(1)) if m else 0
            body = MP4[start:]
            self.send_response(206 if start else 200)
            if start:
                self.send_header("Content-Range", f"bytes {start}-{len(MP4)-1}/{len(MP4)}")
            # /movie.bin exercises the content sniffing fallback: a direct
            # media file whose URL has no extension.
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()


@pytest.fixture()
def upstream():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture()
def running_proxy(monkeypatch):
    # Upstream is on loopback → allow it for this test (SSRF tested elsewhere).
    monkeypatch.setattr(proxy, "_is_ssrf_blocked", lambda url: False)
    proxy.ensure_started()
    yield proxy.PROXY_URL
    proxy.stop_proxy_server()


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.read()


def test_hls_manifest_rewrite_and_segment(upstream, running_proxy):
    import urllib.parse as up
    master = f"{upstream}/master.m3u8"
    murl = f"{running_proxy}/stream?url={up.quote(master)}&headers=%7B%7D"
    status, body = _get(murl)
    text = body.decode()
    assert status == 200
    # Segments must be rewritten back through the proxy's /ts endpoint.
    ts_urls = re.findall(r"(http://[^\s]+/ts\?url=[^\s]+)", text)
    assert len(ts_urls) == 2, text
    # Fetching a rewritten segment returns the exact upstream bytes.
    st, seg = _get(ts_urls[0])
    assert st == 200 and seg == SEG0


def test_mp4_range(upstream, running_proxy):
    import urllib.parse as up
    vurl = f"{running_proxy}/video?url={up.quote(upstream + '/movie.mp4')}&headers=%7B%7D"
    req = urllib.request.Request(vurl, headers={"Range": "bytes=1000-"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = r.read()
    assert data == MP4[1000:]


def test_stream_direct_mp4_falls_back_to_video(upstream, running_proxy):
    """A .mp4 opened through /stream must be served raw, not as a playlist."""
    import urllib.parse as up
    url = f"{running_proxy}/stream?url={up.quote(upstream + '/movie.mp4')}&headers=%7B%7D"
    st, body = _get(url)
    assert st == 200
    assert body == MP4


def test_stream_extensionless_direct_media_falls_back(upstream, running_proxy):
    """Content sniffing protects mislabelled/extensionless direct media too."""
    import urllib.parse as up
    url = f"{running_proxy}/stream?url={up.quote(upstream + '/movie.bin')}&headers=%7B%7D"
    st, body = _get(url)
    assert st == 200
    assert body == MP4


def test_player_html_and_heartbeat(running_proxy):
    st, body = _get(f"{running_proxy}/player")
    assert st == 200 and b"FreeFlix Web Player" in body
    st, body = _get(f"{running_proxy}/player/heartbeat")
    assert st == 200 and body == b"ok"


def test_unknown_path_404(running_proxy):
    try:
        _get(f"{running_proxy}/nope")
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404
