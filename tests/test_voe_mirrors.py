"""Rotating Voe mirrors on Anime-Sama.

Anime-Sama swaps its Voe player between throwaway domains (``…/e/<id>``) every
few days. The hardcoded allow-list fell behind — 8 new hosts appeared during a
single day — and because ``is_supported`` returned False the whole row was
hidden as "unsupported" even though the episode played. These tests pin the
generic detection that replaced the list.
"""

import pytest

from freeflix_cli.scraping import player as pl


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    """The host probe is cached in-process: reset it between tests."""
    pl._VOE_UNKNOWN.clear()
    yield
    pl._VOE_UNKNOWN.clear()


def test_known_voe_mirror_is_supported():
    for host in (
        "claireguessthousand.com",
        "derricknationtop.com",
        "susanexpectcare.com",
        "ashleyhardat.com",
        "shanelocaldog.com",
    ):
        url = f"https://{host}/e/abc123"
        assert pl.is_voe_url(url) is True, host
        assert pl.is_supported(url) is True, host


def test_unknown_voe_shaped_host_is_probed(monkeypatch):
    """A brand-new mirror must be accepted without a code release."""
    monkeypatch.setattr(pl, "_get", lambda *a, **k: _Resp(200, "<title>VOE</title>"))
    assert pl.is_supported("https://brandnewmirror.xyz/e/abc123") is True


def test_non_voe_host_is_rejected(monkeypatch):
    monkeypatch.setattr(pl, "_get", lambda *a, **k: _Resp(200, "<html>hello</html>"))
    assert pl.is_supported("https://brandnewmirror.xyz/e/abc123") is False


def test_probe_failure_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(pl, "_get", boom)
    assert pl.is_supported("https://deadmirror.xyz/e/abc123") is False


def test_url_without_voe_shape_is_not_probed(monkeypatch):
    """Never spend a network call on an arbitrary catalogue host."""
    calls = []
    monkeypatch.setattr(pl, "_get", lambda *a, **k: calls.append(a) or _Resp(200, "voe"))

    assert pl.is_supported("https://vk.com/video_ext.php?oid=1") is False
    assert calls == []


def test_voe_extractor_runs_for_unlisted_host(monkeypatch):
    """get_hls_link must dispatch to the Voe parser, not return None."""
    monkeypatch.setattr(pl, "is_voe_url", lambda url: True)
    monkeypatch.setattr(pl, "get_hls_link_voe",
                        lambda url, headers: "https://cdn.example/x/master.m3u8")
    assert pl.get_hls_link("https://newmirror.xyz/e/abc") == \
        "https://cdn.example/x/master.m3u8"


class _Resp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
