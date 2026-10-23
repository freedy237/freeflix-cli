"""
Tests for the proxy's resilient streaming (scraping-agnostic).

A tiny local HTTP server simulates a flaky link (drops mid-transfer, then
honours Range on reconnect) and an expired token (403 until re-resolution
supplies a fresh one). resilient_body must always deliver the complete,
byte-identical body.
"""

import http.server
import io
import re
import threading
import urllib.parse

import pytest

from freeflix_cli import proxy

PAYLOAD = bytes([i % 256 for i in range(300000)])


def _serve(handler_cls):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _range_start(headers):
    m = re.match(r"bytes=(\d+)-", headers.get("Range") or "")
    return int(m.group(1)) if m else 0


def test_resume_after_midstream_drop():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            start = _range_start(self.headers)
            body = PAYLOAD[start:]
            self.send_response(206 if start else 200)
            if start:
                self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD)-1}/{len(PAYLOAD)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if start == 0 and not getattr(self.server, "dropped", False):
                self.server.dropped = True
                try:
                    self.wfile.write(body[:len(body) // 2])
                    self.connection.close()
                except Exception:
                    pass
            else:
                try:
                    self.wfile.write(body)
                except Exception:
                    pass

        def log_message(self, *a):
            pass

    srv, port = _serve(H)
    try:
        got = b"".join(proxy.resilient_body(
            f"http://127.0.0.1:{port}/seg.ts", {}, first_resp=None))
    finally:
        srv.shutdown()
    assert got == PAYLOAD


def test_recover_from_expired_token():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if q.get("t") != "NEW":
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"expired")
                return
            start = _range_start(self.headers)
            body = PAYLOAD[start:]
            self.send_response(206 if start else 200)
            if start:
                self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD)-1}/{len(PAYLOAD)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv, port = _serve(H)
    proxy.set_stream_refresher(lambda: f"http://127.0.0.1:{port}/master.m3u8?t=NEW&e=9")
    try:
        got = b"".join(proxy.resilient_body(
            f"http://127.0.0.1:{port}/seg.ts?t=OLD", {}, first_resp=None))
    finally:
        srv.shutdown()
        proxy.clear_stream_refresher()
    assert got == PAYLOAD


def test_refreshed_url_swaps_token():
    proxy.set_stream_refresher(lambda: "https://cdn/x/master.m3u8?t=NEW&e=9&f=1")
    try:
        out = proxy._refreshed_url("https://cdn/x/seg3.ts?t=OLD&e=1&f=1")
        assert "t=NEW" in out and "seg3.ts" in out
        assert proxy._refreshed_url("https://cdn/x/master.m3u8?t=OLD").endswith("t=NEW&e=9&f=1")
    finally:
        proxy.clear_stream_refresher()


def test_truncated_body_raises_instead_of_returning_short():
    """A server that ignores Range after a drop must not yield a partial body
    as if it were complete (that is the 'video skips parts' bug)."""
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = PAYLOAD
            self.send_response(200)  # deliberately ignores Range
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body[:len(body) // 2])
                self.connection.close()
            except Exception:
                pass

        def log_message(self, *a):
            pass

    srv, port = _serve(H)
    try:
        with pytest.raises(proxy.StreamIncomplete):
            b"".join(proxy.resilient_body(
                f"http://127.0.0.1:{port}/seg.ts", {},
                first_resp=None, no_progress_budget=10))
    finally:
        srv.shutdown()


class _FakeHandler:
    def __init__(self):
        self.wfile = io.BytesIO()
        self.close_connection = False
        self.status = None
        self.out_headers = None

    def _send_headers(self, status, headers):
        self.status = status
        self.out_headers = headers


def _stream_fake(total, chunks, fail=False):
    h = _FakeHandler()

    def gen():
        for c in chunks:
            yield c
        if fail:
            raise proxy.StreamIncomplete("truncated")

    proxy._ProxyHandler._stream(h, 200, {}, gen(), total=total)
    return h


def test_stream_known_length_is_complete():
    h = _stream_fake(3, [b"abc"])
    assert h.out_headers["Content-Length"] == "3"
    assert "Transfer-Encoding" not in h.out_headers
    assert h.wfile.getvalue() == b"abc"
    assert h.close_connection is False


def test_stream_known_length_never_pretends_truncation_is_complete():
    h = _stream_fake(10, [b"abc"], fail=True)
    assert h.wfile.getvalue() == b"abc"  # no padding, no clean terminator
    assert h.close_connection is True


def test_stream_unknown_length_omits_final_chunk_on_failure():
    h = _FakeHandler()

    def gen():
        yield b"abc"
        raise proxy.StreamIncomplete("truncated")

    proxy._ProxyHandler._stream(h, 200, {}, gen(), total=None)
    raw = h.wfile.getvalue()
    assert b"0\r\n\r\n" not in raw
    assert h.close_connection is True


def test_stream_unknown_length_complete_emits_final_chunk():
    h = _FakeHandler()

    def gen():
        yield b"abc"

    proxy._ProxyHandler._stream(h, 200, {}, gen(), total=None)
    assert h.wfile.getvalue() == b"3\r\nabc\r\n0\r\n\r\n"


def test_refreshed_url_uses_new_manifest_host(monkeypatch):
    proxy.set_stream_refresher(lambda: "https://new.example/master.m3u8?t=NEW")
    monkeypatch.setattr(proxy, "_fresh_segment_map",
                        lambda master, headers, max_age=12.0:
                        {"seg3.ts": "https://new.example/seg3.ts?t=NEW"})
    try:
        out = proxy._refreshed_url("https://old.example/seg3.ts?t=OLD", {})
        assert out == "https://new.example/seg3.ts?t=NEW"
    finally:
        proxy.clear_stream_refresher()


def test_client_gone_stops_retry_loop():
    calls = []

    def gone():
        calls.append(True)
        return True

    out = b"".join(proxy.resilient_body(
        "http://127.0.0.1:1/never", {}, first_resp=None,
        no_progress_budget=None, client_gone=gone,
    ))
    assert out == b""
    assert calls


def test_recovers_after_a_real_server_outage(monkeypatch):
    """First attempts hit a closed port, then the server appears: the body must
    still be delivered in full (this is the Wi-Fi/operator switch case)."""
    import socket
    import time

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            start = _range_start(self.headers)
            body = PAYLOAD[start:]
            self.send_response(206 if start else 200)
            if start:
                self.send_header(
                    "Content-Range", f"bytes {start}-{len(PAYLOAD)-1}/{len(PAYLOAD)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def log_message(self, *a):
            pass

    srv = None

    def start_later():
        nonlocal srv
        time.sleep(0.9)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    t = threading.Thread(target=start_later, daemon=True)
    t.start()
    try:
        got = b"".join(proxy.resilient_body(
            f"http://127.0.0.1:{port}/seg.ts", {}, first_resp=None,
            no_progress_budget=None,
        ))
    finally:
        t.join(timeout=3)
        if srv is not None:
            srv.shutdown()
    assert got == PAYLOAD
