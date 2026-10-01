"""
Tests for the proxy's SSRF guard and its lazy (idempotent) start.

The proxy binds to 127.0.0.1 on a random port. Without a guard it would act as
an open proxy any local process could use to reach internal / cloud-metadata
services. We refuse target URLs whose host is loopback / private / link-local /
reserved (or a localhost literal), while public CDN hosts are always allowed.
"""

from freeflix_cli import proxy


def test_ssrf_blocks_private_and_localhost():
    blocked = [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1:8080/x",                    # loopback
        "http://10.0.0.5/x",                          # private
        "http://192.168.1.1/x",                       # private
        "http://172.16.0.1/x",                        # private
        "http://[::1]/x",                             # ipv6 loopback
        "http://localhost/x",                         # localhost literal
        "http://0.0.0.0/x",                           # unspecified
    ]
    for u in blocked:
        assert proxy._is_ssrf_blocked(u), u


def test_ssrf_allows_public_hosts():
    allowed = [
        "https://example.com/master.m3u8",
        "https://cdn.some-stream.net/seg1.ts",
        "http://8.8.8.8/x",              # public IP
        "https://vidmoly.net/embed",
    ]
    for u in allowed:
        assert not proxy._is_ssrf_blocked(u), u


def test_ssrf_non_http_schemes_blocked():
    # Seuls http/https sortent vers un CDN : file://, gopher://, URL sans
    # schéma ou sans host sont refusés (anti-LFI / anti-SSRF).
    assert proxy._is_ssrf_blocked("")
    assert proxy._is_ssrf_blocked("not a url")
    assert proxy._is_ssrf_blocked("file:///etc/passwd")
    assert proxy._is_ssrf_blocked("gopher://127.0.0.1:70/x")
    assert proxy._is_ssrf_blocked("dict://127.0.0.1:11211/x")


def test_ssrf_blocks_ip_obfuscation():
    # Formes hex/octal/décimales/short que ipaddress rejette mais que les
    # stacks résolvent vers loopback/privé.
    for u in [
        "http://0x7f.0.0.1/x",
        "http://0x7f000001/x",
        "http://2130706433/x",      # 127.0.0.1 décimal
        "http://0177.0.0.1/x",      # 127.0.0.1 octal
        "http://127.1/x",           # forme courte
        "http://0xC0.0xA8.0x01.0x01/x",
    ]:
        assert proxy._is_ssrf_blocked(u), u


class TestDnsVerdict:
    """On juge la réponse DNS, pas le nom (anti DNS-rebinding)."""

    def _check(self, host, fake_ips):
        import socket as _sock
        orig = _sock.getaddrinfo
        _sock.getaddrinfo = lambda *a, **k: [
            (None, None, None, None, (ip, 0)) for ip in fake_ips
        ]
        try:
            with proxy._DNS_VERDICT_LOCK:
                proxy._DNS_VERDICT_CACHE.pop(host, None)
            return proxy._is_ssrf_blocked(f"http://{host}/x")
        finally:
            _sock.getaddrinfo = orig

    def test_rebinding_to_loopback_blocked(self):
        assert self._check("cdn.evil.test", ["127.0.0.1"])

    def test_rebinding_to_metadata_blocked(self):
        assert self._check("cdn.evil.test", ["169.254.169.254"])

    def test_public_answer_allowed(self):
        assert not self._check("cdn.good.test", ["93.184.216.34"])


def test_ensure_started_is_idempotent():
    p1 = proxy.ensure_started()
    p2 = proxy.ensure_started()
    assert p1 == p2
    assert proxy.PROXY_URL == f"http://{proxy.PROXY_HOST}:{p1}"
    proxy.stop_proxy_server()


class _StubHandler:
    """Appelle _h_subtitle sans serveur : capture _send_bytes."""

    def __init__(self):
        self.calls = []

    def _send_bytes(self, status, body, content_type="text/plain; charset=utf-8",
                    extra=None):
        self.calls.append((status, body, content_type, extra))


def _subtitle_status(path):
    stub = _StubHandler()
    proxy._ProxyHandler._h_subtitle(stub, {"path": path})
    assert stub.calls, "no response sent"
    return stub.calls[-1]


class TestSubtitleJail:
    """?path= ne sort jamais des dossiers autorisés (anti-LFI)."""

    def test_outside_allowed_dirs_forbidden(self):
        for p in ["/etc/passwd", "/etc/hosts", "/proc/self/environ"]:
            status, *_ = _subtitle_status(p)
            assert status == 403, p

    def test_symlink_escape_forbidden(self):
        import os
        import tempfile
        link = os.path.join(tempfile.gettempdir(), "freeflix_test_link.srt")
        try:
            os.symlink("/etc/hostname", link)
        except (OSError, NotImplementedError):
            return  # FS sans symlinks : rien à tester
        try:
            # Le lien est DANS tempdir mais pointe DEHORS : realpath doit le voir.
            status, *_ = _subtitle_status(link)
            assert status == 403
        finally:
            try:
                os.unlink(link)
            except OSError:
                pass

    def test_legit_temp_subtitle_served_without_cors(self, tmp_path):
        import os
        import tempfile
        sub = os.path.join(tempfile.gettempdir(), "freeflix_test_ok.srt")
        with open(sub, "w") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,000\nhello\n")
        try:
            status, body, ctype, extra = _subtitle_status(sub)
            assert status == 200
            assert ctype == "text/vtt"
            assert extra is None  # plus de CORS ouvert sur cette route
            assert b"hello" in (body if isinstance(body, bytes) else body.encode())
        finally:
            os.unlink(sub)

    def test_oversized_subtitle_rejected(self, tmp_path):
        import os
        import tempfile
        sub = os.path.join(tempfile.gettempdir(), "freeflix_test_big.srt")
        with open(sub, "wb") as f:
            f.truncate(proxy._SUBTITLE_MAX_BYTES + 1)  # creux, pas 2 Mo écrits
        try:
            status, *_ = _subtitle_status(sub)
            assert status == 413
        finally:
            os.unlink(sub)

    def test_missing_subtitle_404(self):
        status, *_ = _subtitle_status("/tmp/freeflix_nope_does_not_exist.srt")
        assert status == 404
