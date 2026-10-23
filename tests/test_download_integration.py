"""Full-stack download tests: real ffmpeg HLS + real yt-dlp through the proxy.

These are deliberately end-to-end rather than mock-only: they prove the two
user-visible guarantees on an actual fragmented HLS stream —

1. a segment whose connection drops halfway is fetched AGAIN (Range resume)
   and the published MP4 still contains every second;
2. a permanently missing segment aborts the download and publishes NOTHING
   (no video with a hole / no silent skip).

Skipped only when the real tools are unavailable.
"""

import http.server
import re
import shutil
import subprocess
import threading
import urllib.parse
from pathlib import Path

import pytest

import freeflix_cli.player_manager as pm
from freeflix_cli import progress, proxy


FFMPEG = shutil.which("ffmpeg")
YTDLP = shutil.which("yt-dlp") or pm._resolve_tool("yt-dlp")

pytestmark = pytest.mark.skipif(
    not (FFMPEG and YTDLP),
    reason="requires real ffmpeg + yt-dlp for an end-to-end HLS download",
)


def _make_hls(root: Path) -> bytes:
    """6 s, 6 segments of 1 s with a keyframe every second."""
    src = root / "source"
    src.mkdir()
    subprocess.run(
        [
            FFMPEG, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10", "-t", "6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-g", "10", "-keyint_min", "10", "-sc_threshold", "0",
            "-f", "hls", "-hls_time", "1", "-hls_list_size", "0",
            "-hls_segment_filename", str(src / "seg%d.ts"),
            str(src / "media.m3u8"),
        ],
        check=True,
        timeout=90,
    )
    return (src / "media.m3u8").read_bytes()


def _handler_for(root: Path, drop_seg: str = None, missing_seg: str = None):
    """Serve the HLS files with Range support; optionally truncate or 404 one
    segment (first hit only for *drop_seg*)."""
    state = {"hits": {}, "dropped": False}

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            name = urllib.parse.urlparse(self.path).path.lstrip("/")
            state["hits"][name] = state["hits"].get(name, 0) + 1
            if missing_seg and name == missing_seg:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                return
            path = root / "source" / name
            if not path.is_file():
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = path.read_bytes()
            rng = self.headers.get("Range")
            start = 0
            if rng:
                m = re.match(r"bytes=(\d+)-", rng)
                start = int(m.group(1)) if m else 0
            chunk = body[start:]
            self.send_response(206 if start else 200)
            if start:
                self.send_header(
                    "Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}"
                )
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Connection", "close")
            self.send_header(
                "Content-Type",
                "application/vnd.apple.mpegurl" if name.endswith(".m3u8")
                else "video/mp2t",
            )
            self.end_headers()
            self.close_connection = True
            if name == drop_seg and not state["dropped"] and start == 0:
                state["dropped"] = True
                try:
                    self.wfile.write(chunk[: len(chunk) // 2])
                    self.wfile.flush()
                except Exception:
                    pass
            else:
                try:
                    self.wfile.write(chunk)
                except Exception:
                    pass

    return H, state


def _serve(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture()
def loopback_proxy(monkeypatch):
    # The upstream is on loopback; the SSRF guard is tested separately.
    monkeypatch.setattr(proxy, "_is_ssrf_blocked", lambda _u: False)
    proxy.stop_proxy_server()
    proxy.ensure_started()
    yield proxy.PROXY_URL
    proxy.stop_proxy_server()


def _download(monkeypatch, tmp_path, proxy_url, upstream_port):
    out = tmp_path / "Downloads"
    monkeypatch.setattr(pm, "DOWNLOAD_DIR", str(out))
    monkeypatch.setattr(pm, "TEMP_DIR", str(out / ".temp"))

    target = f"http://127.0.0.1:{upstream_port}/media.m3u8"
    stream_url = (
        f"{proxy_url}/stream?url={urllib.parse.quote(target)}"
        f"&headers=%7B%7D"
    )

    def fake_bar(cmd, title, batch_callback=None, cancel_check=None):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode:
            print(r.stdout[-3000:])
            print(r.stderr[-2000:])
        return r.returncode

    monkeypatch.setattr(progress, "run_download_with_bar", fake_bar)
    ok = pm._download_stream(
        stream_url, "", "", "Test Episode", is_mp4=False, _with_ui=True,
    )
    return ok, out


def _duration(path: Path) -> float:
    r = subprocess.run(
        [
            pm._resolve_tool("ffprobe") or "ffprobe", "-v", "error",
            "-show_entries", "format=duration", "-of",
            "default=nw=1:nk=1", str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    return float(r.stdout.strip())


def test_hls_download_survives_a_dropped_segment(monkeypatch, tmp_path,
                                                 loopback_proxy):
    playlist = _make_hls(tmp_path)
    assert playlist.count(b"#EXTINF") == 6
    H, state = _handler_for(tmp_path, drop_seg="seg3.ts")
    srv = _serve(H)
    try:
        ok, out = _download(monkeypatch, tmp_path, loopback_proxy,
                            srv.server_address[1])
    finally:
        srv.shutdown()

    published = out / "Test Episode.mp4"
    assert ok is True
    assert published.is_file() and published.stat().st_size > 0
    # Every second survived, including the one whose connection was cut.
    assert _duration(published) == pytest.approx(6.0, abs=0.35)
    assert state["hits"].get("seg3.ts", 0) >= 2
    assert not list(out.rglob("*.incomplete*"))


def test_hls_download_with_a_missing_segment_publishes_nothing(
        monkeypatch, tmp_path, loopback_proxy):
    _make_hls(tmp_path)
    H, state = _handler_for(tmp_path, missing_seg="seg3.ts")
    srv = _serve(H)

    # Keep the failure fast: one fragment retry, no backoff between.
    original = pm._ytdlp_download_cmd

    def fast_cmd(*args, **kwargs):
        cmd = original(*args, **kwargs)
        for flag, value in (("--fragment-retries", "1"),
                            ("--retries", "1"),
                            ("--retry-sleep", "0"),
                            ("--socket-timeout", "5")):
            if flag in cmd:
                cmd[cmd.index(flag) + 1] = value
        return cmd

    monkeypatch.setattr(pm, "_ytdlp_download_cmd", fast_cmd)
    try:
        ok, out = _download(monkeypatch, tmp_path, loopback_proxy,
                            srv.server_address[1])
    finally:
        srv.shutdown()

    assert ok is False
    # A hole in the timeline must NEVER become a published video.
    assert not list(out.glob("*.mp4"))
    assert state["hits"].get("seg3.ts", 0) >= 1
