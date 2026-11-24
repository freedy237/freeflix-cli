"""Tiny local HLS proxy for YacineTV live streams.

mpv/VLC double-encode non-ASCII HTTP headers (the CDN's Referer contains
zero-width characters), and ffmpeg refuses ``.php``/``.pdf`` segment
extensions.  This proxy fetches the upstream playlist/segments itself with
the exact UTF-8 header bytes, rewrites every URI to a local ``.ts``/``.m3u8``
path, and serves it on 127.0.0.1.  Players then talk plain localhost.
"""

from __future__ import annotations

import http.client
import http.server
import secrets
import threading
import urllib.parse


class _LiveProxy:
    def __init__(self, playlist_url: str, headers: dict):
        self.playlist_url = playlist_url
        self.headers = dict(headers or {})
        self.token = secrets.token_urlsafe(12)
        self.items: dict[str, tuple[str, str]] = {}
        self._counter = 0
        self.httpd: http.server.ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        # Set by the request handler on an upstream failure; read by callers /
        # diagnostics. Must exist even before the first request (attribute
        # access on a proxy that was only preflighted used to raise).
        self.last_error: str | None = None
        # Set when a master playlist was collapsed to its first media one, so
        # 404 recovery re-fetches THAT media playlist (not the master).
        self.master_url: str | None = None

    # ── upstream ─────────────────────────────────────────────────────
    @staticmethod
    def _request(url: str, headers: dict, hops: int = 5):
        if hops <= 0:
            raise RuntimeError("too many redirects")
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("http", "https"):
            raise RuntimeError("unsupported scheme")
        cls = (http.client.HTTPSConnection if p.scheme == "https"
               else http.client.HTTPConnection)
        conn = cls(p.hostname, p.port, timeout=20)
        path = p.path or "/"
        if p.query:
            path += "?" + p.query
        conn.putrequest("GET", path, skip_host=False, skip_accept_encoding=True)
        skip = {"host", "connection", "content-length", "transfer-encoding",
                "accept-encoding"}
        for k, v in headers.items():
            if str(k).lower() in skip or v is None:
                continue
            # Header values are bytes on the wire: send their exact UTF-8
            # encoding (http.client passes bytes through unchanged).
            conn.putheader(str(k).encode("latin-1", "replace"),
                           str(v).encode("utf-8"))
        conn.putheader("Connection", "close")
        conn.endheaders()
        resp = conn.getresponse()
        if resp.status in (301, 302, 303, 307, 308):
            loc = resp.getheader("Location") or ""
            resp.read()
            conn.close()
            return _LiveProxy._request(urllib.parse.urljoin(url, loc),
                                       headers, hops - 1)
        if resp.status not in (200, 206):
            code = resp.status
            resp.read()
            conn.close()
            raise RuntimeError(f"upstream HTTP {code}")
        return conn, resp

    def _refresh_playlist_items(self) -> None:
        """Re-fetch the upstream playlist and re-map the MOST RECENT segments.

        Some CDNs answer 404 for a segment that was valid when the playlist
        was fetched. The live playlist keeps moving, so the newest segments
        almost always work: drop the old mappings and rebuild them from a
        fresh fetch before giving up on a 404.
        """
        try:
            conn, resp = self._request(self.master_url or self.playlist_url,
                                       self.headers)
            try:
                text = resp.read().decode("utf-8", "replace")
            finally:
                conn.close()
        except Exception:
            return
        segs = [ln.strip() for ln in text.splitlines()
                if ln.strip() and not ln.startswith("#")]
        if not segs:
            return
        base = self.master_url or self.playlist_url
        for old, (_url, kind) in list(self.items.items()):
            if kind == "segment":
                self.items.pop(old, None)
        for ln in segs[-6:]:
            self._register(urllib.parse.urljoin(base, ln), "segment")

    def _register(self, url: str, kind: str) -> str:
        self._counter += 1
        key = f"{self._counter}.{'m3u8' if kind == 'playlist' else 'ts'}"
        self.items[key] = (url, kind)
        return key

    def _rewrite(self, text: str, base: str) -> str:
        out = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                out.append(line)
                continue
            if s.startswith("#"):
                # #EXT-X-KEY / #EXT-X-MAP carry URIs we must proxy too.
                if 'URI="' in s:
                    pre, rest = s.split('URI="', 1)
                    uri, post = rest.split('"', 1)
                    absu = urllib.parse.urljoin(base, uri)
                    key = self._register(absu, "segment")
                    s = f'{pre}URI="/p/{self.token}/{key}"{post}'
                out.append(s)
                continue
            absu = urllib.parse.urljoin(base, s)
            kind = "playlist" if ".m3u8" in absu.lower().split("?")[0] else "segment"
            key = self._register(absu, kind)
            out.append(f"/p/{self.token}/{key}")
        return "\n".join(out) + "\n"

    def _playlist(self, url: str) -> bytes:
        conn, resp = self._request(url, self.headers)
        try:
            raw = resp.read()
            base = url
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw
            text = self._resolve_master(text, url)
            return self._rewrite(text, base).encode("utf-8")
        finally:
            conn.close()

    def _resolve_master(self, text: str, url: str) -> str:
        """Collapse a MASTER playlist into its first playable media playlist.

        YacineTV's non-"Multi" sources are served through a master manifest
        whose variants point at *.php/.pdf paths (and often a backup host).
        mpv's HLS demuxer then fails on those extensions ("Failed to
        recognize file format" / "Failed to open"), which is what made
        HD/SD/Low unpublishable while "Multi" (a plain media playlist)
        worked. Proxying the FIRST variant that actually answers gives every
        player a normal media playlist of local .ts URIs.

        Returns the media playlist text, or the original text when this is
        already a media playlist / no variant works (the caller then keeps
        the per-URI proxying, which is the old behaviour).
        """
        if "#EXT-X-STREAM-INF" not in text:
            return text  # already a media playlist
        lines = [ln.strip() for ln in text.splitlines()]
        candidates = [
            lines[i] for i, ln in enumerate(lines[:-1])
            if ln.startswith("#EXT-X-STREAM-INF")
            and lines[i + 1] and not lines[i + 1].startswith("#")
        ]
        for rel in candidates[:4]:
            media_url = urllib.parse.urljoin(url, rel)
            try:
                conn, resp = self._request(media_url, self.headers)
                try:
                    media = resp.read().decode("utf-8", "replace")
                finally:
                    conn.close()
            except Exception:
                continue
            if "#EXTINF" not in media:
                continue  # a nested master: keep the per-URI proxy instead
            self.master_url = media_url
            return media
        return text


    # ── HTTP handler ────────────────────────────────────────────────
    def _make_handler(self):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # keep the TUI clean
                pass

            def _send_error(self, code, msg=""):
                body = (msg or "error").encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                p = urllib.parse.urlsplit(self.path)
                prefix = f"/p/{outer.token}/"
                if not p.path.startswith(prefix):
                    return self._send_error(404)
                key = p.path[len(prefix):]
                item = outer.items.get(key)
                if not item:
                    return self._send_error(404)
                url, kind = item
                try:
                    if kind == "playlist":
                        data = outer._playlist(url)
                        self.send_response(200)
                        self.send_header("Content-Type",
                                         "application/vnd.apple.mpegurl")
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    try:
                        conn, resp = outer._request(url, outer.headers)
                    except Exception:
                        # Stale segment id: rebuild from the fresh playlist.
                        outer._refresh_playlist_items()
                        newest = [u for u, k in reversed(list(outer.items.values()))
                                  if k == "segment"]
                        if not newest or newest[0] == url:
                            raise
                        conn, resp = outer._request(newest[0], outer.headers)
                    try:
                        self.send_response(200)
                        # Upstream labels segments as application/pdf; VLC's
                        # adaptive demuxer rejects that. They are MPEG-TS.
                        self.send_header("Content-Type", "video/mp2t")
                        # Forward the upstream framing when it is known: some
                        # players (stricter on Windows) wait for a length.
                        try:
                            cl = resp.getheader("Content-Length")
                        except Exception:
                            cl = None
                        if cl and str(cl).isdigit():
                            self.send_header("Content-Length", str(cl))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    finally:
                        conn.close()
                except Exception as exc:
                    outer.last_error = f"{type(exc).__name__}: {exc}"
                    try:
                        self._send_error(502, f"upstream unavailable: {exc}")
                    except Exception:
                        pass

        return Handler

    def start(self) -> str:
        self.httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), self._make_handler())
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        self._register(self.playlist_url, "playlist")
        port = self.httpd.server_address[1]
        return f"http://127.0.0.1:{port}/p/{self.token}/1.m3u8"

    def stop(self) -> None:
        try:
            if self.httpd:
                self.httpd.shutdown()
                self.httpd.server_close()
        except Exception:
            pass


def start_live_proxy(playlist_url: str, headers: dict) -> tuple[_LiveProxy, str]:
    proxy = _LiveProxy(playlist_url, headers)
    return proxy, proxy.start()
