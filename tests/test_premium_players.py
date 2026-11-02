"""fsvid / vidzy / dood / byse extraction — the French-Stream player set.

Vidzy "worked sometimes": the current embed ships its player inside a Dean
Edwards packer, so the plain `sources:[{src:"…"}]` line was invisible and the
only m3u8 left in the page was the `/troll/` decoy. These tests pin the
unpacker, the candidate order, the dead-host filter and the dood token.
"""



from freeflix_cli.scraping import player as pl


_UNPACK_ALPHA = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _tok62(i: int) -> str:
    if i == 0:
        return "0"
    out = ""
    while i:
        out = _UNPACK_ALPHA[i % 62] + out
        i //= 62
    return out


def _pack(js: str) -> str:
    """Faithful Dean Edwards packer (base 62).

    Words are indexed independently and only words that start on a word
    boundary are encoded, so a token can never collide with a digit already
    inside a URL and a word glued to a letter is emitted verbatim.
    """
    words, table, packed = {}, [], []
    i, n = 0, len(js)
    while i < n:
        ch = js[i]
        glued = i > 0 and (js[i - 1].isalnum() or js[i - 1] == "_")
        if (ch.isalpha() or ch == "_") and not glued:
            j = i
            while j < n and (js[j].isalnum() or js[j] == "_"):
                j += 1
            word = js[i:j]
            if word not in words:
                words[word] = len(table)
                table.append(word)
            packed.append(_tok62(words[word]))
            i = j
        else:
            packed.append(ch)
            i += 1
    return (
        "eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace("
        "new RegExp('\\\\b'+c.toString(a)+'\\\\b','g'),k[c]);return p}"
        f"('{''.join(packed)}',62,{len(table)},'{'|'.join(table)}'.split('|')))"
    )


def test_unpack_exposes_packed_sources():
    js = 'sources:[{src:"https://r1.fsvid.lol/hls2/02/00001/x_n/master.m3u8?t=1"}]'
    page = "<script>" + _pack(js) + "</script>"
    assert "sources:[{src:" in pl.unpack_dean_edwards(page)


def test_candidates_skip_troll_decoy(monkeypatch):
    real = "https://u14.vidzy.cc/hls2/07/00032/abc_o/master.m3u8?t=T"
    body = (
        'var _fsvHls="https://s1.fsvid.lol/troll/master.m3u8";'
        '<script>' + _pack('sources:[{src:"' + real + '"}]') + "</script>"
    )
    got = pl._fsvid_candidates(body, "vidzy.cc")
    assert got == [real]


def test_vidzy_packed_embed_resolves(monkeypatch):
    # Realistic signed URL: no bare word characters glued to a number, which
    # is what the packer actually produces for vidzy.
    real = "https://u14.vidzy.cc/hls2/07/00032/abc_o/master.m3u8?t=T&e=14400"

    class _Resp:
        status_code = 200
        text = (
            'var _fsvHls="https://s1.fsvid.lol/troll/master.m3u8";'
            '<script>' + _pack('sources:[{src:"' + real + '"}]') + "</script>"
        )

        def raise_for_status(self):
            return None

    monkeypatch.setattr(pl, "_get", lambda *a, **k: _Resp())
    out = pl.get_hls_link_fsvid(
        "https://vidzy.cc/embed-3e2wtwo8ffee.html", {"Referer": "https://x"}
    )
    assert out == real


def test_decoy_only_embed_is_unavailable(monkeypatch):
    class _Resp:
        status_code = 200
        text = 'var _fsvHls="https://s1.fsvid.lol/troll/master.m3u8";'

        def raise_for_status(self):
            return None

    monkeypatch.setattr(pl, "_get", lambda *a, **k: _Resp())
    assert pl.get_hls_link_fsvid(
        "https://fsvid.lol/embed-x.html", {"Referer": "https://x"}
    ) is None


def test_placeholder_embeds_are_detected():
    assert pl.embed_is_placeholder("<div>File was locked by administrator</div>")
    assert pl.embed_is_placeholder("<h1>File Not Found</h1><p>File expired</p>")
    assert pl.embed_is_placeholder("WE ARE SORRY We can't find the video")
    assert not pl.embed_is_placeholder('sources:[{src:"https://a/b.m3u8"}]')


def test_known_offline_hosts_are_hidden():
    for url in ("https://filemoon.sx/e/x", "https://bysewihe.com/e/x",
                "https://mixdrop.ag/e/x", "https://minochinos.com/e/x"):
        assert pl.is_known_offline(url) is True
    for url in ("https://fsvid.lol/embed-x.html", "https://vidzy.cc/embed-x.html",
                "https://uqload.vc/embed-x.html", "https://voe.sx/e/x"):
        assert pl.is_known_offline(url) is False


def test_dood_uses_player_host_for_pass_md5(monkeypatch):
    """A kokoflix proxy link must ask pass_md5 on playmogo, not on kokoflix."""
    calls = []

    page = (
        "<html><script>$.get('/pass_md5/285523768-143-105-1793609068-abc/"  # noqa
        "8te4');var token='tok123';</script></html>"
    )

    class _Resp:
        status_code = 200
        text = page

        def raise_for_status(self):
            return None

    class _Token:
        status_code = 200
        text = "https://ec549vh.cloudatacdn.com/u5kj6ror/x~"

        def raise_for_status(self):
            return None

    def fake_get(url, **kw):
        calls.append(url)
        return _Token() if "pass_md5" in url else _Resp()

    monkeypatch.setattr(pl, "_get", fake_get)
    out = pl.get_hls_link_dood(
        "https://kokoflix.lol/tokyo_go.php?id=ABC", {}, player_host="playmogo.com"
    )
    assert out.startswith("https://ec549vh.cloudatacdn.com/")
    assert "?token=tok123" in out
    assert any(c.startswith("https://kokoflix.lol/pass_md5/") for c in calls)
