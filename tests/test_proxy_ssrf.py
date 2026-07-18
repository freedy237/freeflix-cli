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


def test_ssrf_malformed_url_is_not_blocked():
    # No host to judge → don't block (route still validates downstream).
    assert not proxy._is_ssrf_blocked("")
    assert not proxy._is_ssrf_blocked("not a url")


def test_ensure_started_is_idempotent():
    p1 = proxy.ensure_started()
    p2 = proxy.ensure_started()
    assert p1 == p2
    assert proxy.PROXY_URL == f"http://{proxy.PROXY_HOST}:{p1}"
    proxy.stop_proxy_server()
