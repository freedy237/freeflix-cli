"""
Test the fsvid/vidzy real-stream decoder (scraping.player._fsvid_decode).

The player JS ships a decoy '/troll/master.m3u8' but computes the REAL URL via
an IIFE: base64-decode a payload, XOR each byte with an 8-byte key. This pins
that we reproduce it correctly (offline — real sample captured from fsvid.lol).
"""

import base64

from freeflix_cli.scraping import player


def _encode(url: str, key: list) -> str:
    """Inverse of the decoder — XOR then base64 — to build a test payload."""
    xored = bytes((ord(ch) ^ key[i % len(key)]) & 0xFF for i, ch in enumerate(url))
    return base64.b64encode(xored).decode()


def test_decode_roundtrip():
    key = [214, 91, 173, 44, 122, 250, 19, 88]
    url = "https://r1.fsvid.lol/hls2/02/00001/abc_n/master.m3u8?t=TOKEN&e=86400"
    payload = _encode(url, key)
    code = (
        'sources:[{src:(function(s){var k = [214, 91, 173, 44, 122, 250, 19, 88],'
        'b=atob(s),r="";for(var i=0;i<b.length;i++){r+=String.fromCharCode('
        'b.charCodeAt(i)^k[i%8])}return r})("' + payload + '"),type:"application/x-mpegURL"}]'
    )
    assert player._fsvid_decode(code) == url


def test_decode_real_sample():
    # Real payload+key captured from a fsvid.lol embed.
    key = [214, 91, 173, 44, 122, 250, 19, 88]
    s = ("vi/ZXAnAPHekaoNKCYx6PPg3wkBVkn8r5HSdHlXKI2jmaoIAGZd0PL5v2hQOgisziTWBQBuUdHezNco"
         "DGZd0PL5v2hQOgisziT7DS1aWcjaxdMteH9VwNbE/xRgNwmcg7jDySgifP3ajKcFfH448Nbco2UkI1H"
         "5ro2OSWEeceC/uCf5CCaVqL5N2mmACwmIQomzbSyy2PjWBA916MZVDLI854UYSySA/8CiQHU3CJmzuY"
         "pkfTdx2Ze5tmRxK3HVl72OeG1yTLmj4a4tfCscjfrApkE8XnXcw4iyVWALCeA==")
    code = f'var k = [{",".join(map(str,key))}],b=atob(s);}})("{s}")'
    out = player._fsvid_decode(code)
    assert out is not None
    assert out.startswith("https://r1.fsvid.lol/hls2/") and "master.m3u8" in out


def test_decode_new_algorithm_real_sample():
    """2026 fsvid algorithm: hostname-seeded, positional XOR key, reversed body.

    Real payload captured from a fsvid.lol embed. The key is
    ``(0x3d + i*89 + H) & 255`` where H = sum(hostname chars) & 255, applied to
    the REVERSED base64 body. Must decode with hostname='fsvid.lol'.
    """
    payload = (
        "YMzVO8H8CY7sRaPoFKIROPVRY8lHOIFmwM1twKx10rsIuqUa4Uwp/lBxnVA/iGTOlXrLrXDV/BDt7BK"
        "wIxCyBCeMLUfGEbPiLJnQCbqpQorDGapLFKUaSYstfPEfMPYDoKUX1+UH5/MeuVVQrARk3wgjxz9yxD"
        "2Ds2iO4F+/sh6jDROuR3DeF3XedGfbNtj5K43/FobmSolIFL0DKaRRZtQte8B+n/EjwvNVg+UcuSEQ/"
        "AVr8Qw53jx10zjVj3bfpQzTpQXoUBS+GHPtBX/bcGHFJYnHZt7kEsuxQan0U6Y="
    )
    code = (
        'var b = atob(s), a = b.split("").reverse().join(""), r = "";'
        'for (var i = 0; i < a.length; i++) {'
        'var kk = (0x3d + i * 89 + H) & 255;'
        'r += String.fromCharCode(a.charCodeAt(i) ^ kk)}'
        'return /^https?:/.test(r) ? r : "https://s1.fsvid.lol/troll/master.m3u8"'
        '})("' + payload + '")'
    )
    out = player._fsvid_decode(code, "fsvid.lol")
    assert out is not None
    assert out.startswith("https://r1.fsvid.lol/hls2/") and ".m3u8" in out
    # Wrong hostname must NOT decode to a valid URL (proves H is used).
    assert player._fsvid_decode(code, "wronghost.example") is None


def _encode_new(url: str, offset: int, mult: int, host: str, bc: int) -> str:
    """Inverse of the NEW algorithm — build a payload for a synthetic sample."""
    H = sum(map(ord, host)) & 255
    body = "".join(
        chr(ord(ch) ^ ((offset + i * mult + H + bc) & 255))
        for i, ch in enumerate(url)
    )[::-1]
    return base64.b64encode(body.encode("latin-1")).decode()


def test_decode_new_algorithm_with_bc():
    """2026 fsvid rotation: key is ``(OFFSET + i*MULT + H + BC) & 255`` where
    BC = offsetWidth of a hidden 1in div (96 at 100% zoom)."""
    url = "https://r1.fsvid.lol/hls2/02/00009/uxqd73s5fd60_n/master.m3u8?t=TOKEN&e=86400"
    payload = _encode_new(url, 0x3D, 89, "fsvid.lol", 96)
    code = (
        'var b = atob(s), a = b.split("").reverse().join(""), r = "";'
        'for (var i = 0; i < a.length; i++) {'
        'var kk = (0x3d + i * 89 + H + BC) & 255;'
        'r += String.fromCharCode(a.charCodeAt(i) ^ kk)}'
        'return /^https?:/.test(r) ? r : "https://s1.fsvid.lol/troll/master.m3u8"'
        '})("' + payload + '")'
    )
    assert player._fsvid_decode(code, "fsvid.lol") == url


def test_decode_missing_returns_none():
    assert player._fsvid_decode("no key here") is None
    assert player._fsvid_decode("") is None


def test_troll_still_rejected_as_decoy():
    assert player._is_decoy_stream("https://s1.fsvid.lol/troll/master.m3u8") is True


def test_voe_redirect_and_config_decode(monkeypatch):
    """2026 voe: stub page → rotating mirror → doubly-obfuscated JSON config."""
    import base64
    import json

    from freeflix_cli.scraping import player as pl

    payload = json.dumps({
        "source": "https://cdn.example/hls2/01/x_.urlset/master.m3u8?t=1",
        "fallback": [{"file": "https://cdn.example/mp4/x.mp4"}],
    })
    # Exact inverse of _voe_decode_config:
    # json → b64 → reverse → +3 → b64 → "_" → markers → ROT13.
    step = base64.b64encode(payload.encode()).decode()[::-1]
    step = "".join(chr(ord(c) + 3) for c in step)
    step = base64.b64encode(step.encode("latin-1")).decode()
    step = step.replace("_", "@$")
    cur = step.translate(pl._VOE_ROT13)
    page_html = (
        "<html><body><script>window.location.href="
        "'https://mirror.example/e/abc';</script>"
        '<script type="application/json">' + cur + "</script></body></html>"
    )

    class _Resp:
        status_code = 200

        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if "voe" in url:
            return _Resp(page_html)
        return _Resp(page_html)

    monkeypatch.setattr(pl, "_get", fake_get)
    got = pl.get_hls_link_voe("https://voe.sx/e/abc", {})
    assert got == "https://cdn.example/hls2/01/x_.urlset/master.m3u8?t=1"
    assert any("mirror.example" in u for u in calls)


def test_banned_embed_decoy_is_reported_as_unavailable(monkeypatch):
    """A mirror that only serves the /troll/ decoy must not be listed as a
    working player (it used to show up, then fail on play/download)."""

    class _Resp:
        status_code = 200
        text = (
            '<script>var _fsvHls="https://v6.vidzy.cc/troll/master.m3u8";'
            'var player=videojs("vjsplayer",{});</script>'
        )
        url = "https://vidzy.cc/embed-x.html"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(player, "_get", lambda *a, **k: _Resp())
    assert player.get_hls_link_fsvid(
        "https://vidzy.cc/embed-x.html", {"Referer": "https://vidzy.cc/"}
    ) is None


def test_healthy_embed_is_not_mistaken_for_decoy(monkeypatch):
    payload = base64.b64encode(b"x" * 80).decode()

    class _Resp:
        status_code = 200
        text = (
            'var decoy="https://v6.vidzy.cc/troll/master.m3u8";'
            'sources: [{src: (function(s){...})("' + payload + '")}]'
        )
        url = "https://vidzy.cc/embed-x.html"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(player, "_get", lambda *a, **k: _Resp())
    assert player._has_real_player_payload(_Resp.text) is True


def test_vidzy_gate_appends_gk_and_remembers_cookie(monkeypatch):
    """Vidzy's CDN 403s without the browser gate cookie; mpv/yt-dlp need it."""
    real = (
        "https://u14.vidzy.cc/hls2/08/00057/abc_n/master.m3u8"
        "?t=TOKEN&s=1&e=14400"
    )
    monkeypatch.setattr(player, "_fsvid_decode", lambda code, host: real)

    class _Resp:
        status_code = 200
        text = "embed"
        url = "https://vidzy.cc/embed-test.html"

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": 1, "gk": "GATE123"}

    monkeypatch.setattr(player, "_get", lambda *a, **k: _Resp())

    out = player.get_hls_link_fsvid(
        "https://vidzy.cc/embed-test.html", {"Referer": "https://vidzy.cc/"}
    )
    assert out == real + "&gk=GATE123"
    assert player.get_stream_headers(out) == {
        "Cookie": "vz_ok=GATE123",
        "Referer": "https://vidzy.cc/",
        "Origin": "https://vidzy.cc",
    }
