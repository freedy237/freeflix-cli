"""Player-menu quality badges for the providers that build their own list."""

from types import SimpleNamespace

from freeflix_cli import player_manager as pm
from freeflix_cli.handlers import goldenms, hianime, playback
from freeflix_cli.handlers.playback import quality_suffix


def test_quality_suffix_skips_unknown_or_failed():
    assert quality_suffix("1080p ~5.0 Mbps") == "  —  1080p ~5.0 Mbps"
    assert quality_suffix("✓") == ""
    assert quality_suffix("✗") == ""
    assert quality_suffix("") == ""


def test_hianime_labels_show_probed_resolution_and_bitrate():
    streams = [
        {
            "source": "HiAnime (SUB - ZokoAnime)",
            "quality": "Multi",
            "url": "https://cdn/master.m3u8",
            "subtitles": [{"url": "https://x/sub.vtt"}],
        }
    ]
    labels = hianime._stream_labels(
        streams,
        {"https://cdn/master.m3u8": "1080p ~5.3 · 720p ~3.0 Mbps"},
    )
    assert labels == [
        "HiAnime (SUB - ZokoAnime)"
        "  —  1080p ~5.3 · 720p ~3.0 Mbps  ·  1 subs"
    ]


def test_goldenms_labels_show_probed_resolution_and_bitrate():
    results = [
        {
            "source": "Vidlink",
            "quality": "Multi",
            "type": "DASH",
            "url": "https://sacdn/master.mpd",
        }
    ]
    labels = goldenms._stream_labels(
        results, {"https://sacdn/master.mpd": "1080p ~5.3 Mbps"}
    )
    assert labels == [
        "Vidlink  —  1080p ~5.3 Mbps (DASH)"
    ]


def test_labels_keep_static_quality_when_analysis_fails():
    streams = [{"source": "HiAnime (DUB - HD-1)", "quality": "Multi",
                "url": "https://cdn/master.m3u8"}]
    labels = hianime._stream_labels(streams, {"https://cdn/master.m3u8": "✗"})
    assert labels == ["HiAnime (DUB - HD-1) [Multi]"]


def test_download_headers_forward_signed_tokens():
    from freeflix_cli.player_manager import _download_headers

    out = _download_headers({
        "Referer": "https://vidlink.pro/",
        "Cookie": "CloudFront-Policy=x;CloudFront-Signature=y",
        "X-Playback-Environment": "dash-hevc",
        "Connection": "keep-alive",
        "Accept-Encoding": "gzip",
        "Range": "bytes=0-1024",
    })
    assert out["Cookie"] == "CloudFront-Policy=x;CloudFront-Signature=y"
    assert out["X-Playback-Environment"] == "dash-hevc"
    assert out["Referer"] == "https://vidlink.pro/"
    assert "Connection" not in out
    assert "Accept-Encoding" not in out
    assert "Range" not in out


def test_cinemeta_retries_then_uses_stale_cache(monkeypatch):
    """A flaky Cinemeta used to blank the whole GoldenMS provider."""
    from freeflix_cli import httpcache
    from freeflix_cli.handlers import goldenms as H

    calls = {"n": 0}

    def fake_get(url, **kw):
        calls["n"] += 1
        raise RuntimeError("curl: (28) timed out")

    monkeypatch.setattr(H.requests, "get", fake_get)
    monkeypatch.setattr(H.time, "sleep", lambda *_: None)
    monkeypatch.setattr(httpcache, "get", lambda key, ttl=0: None)
    try:
        H._cinemeta_json("https://v3-cinemeta.strem.io/x.json", 60)
        raise AssertionError("should have raised")
    except RuntimeError:
        pass
    assert calls["n"] == 3

    monkeypatch.setattr(
        httpcache, "get",
        lambda key, ttl=0: '{"metas": [{"name": "Nightborn"}]}',
    )
    assert H._cinemeta_json("https://x/y.json", 60)["metas"][0]["name"] == "Nightborn"


def test_goldenms_extract_does_not_wait_for_slow_sources(monkeypatch):
    """A hanging upstream must not hide the fast sources' players."""
    import time

    from freeflix_cli.scraping.goldenms import goldenms_extractor as x

    def slow(*a, **k):
        time.sleep(5)
        return []

    def fast(*a, **k):
        return [{"source": "Vidlink", "quality": "Multi", "type": "DASH",
                 "url": "https://cdn/master.mpd"}]

    monkeypatch.setattr(x, "search_vidlink", fast)
    monkeypatch.setattr(x, "search_xpass", fast)
    monkeypatch.setattr(x, "search_hexa", slow)
    monkeypatch.setattr(x, "search_mapple", slow)
    monkeypatch.setattr(x, "search_videasy", slow)

    started = time.monotonic()
    out = x.extract(title="Nightborn", tmdb_id=964849, year="2026")
    # Fast sources are returned long before the slow ones finish.
    assert time.monotonic() - started < 4.0
    assert len(out) == 1 and out[0]["source"] == "Vidlink"


def test_dedup_players_ignores_language_suffix_duplicates():
    """French-Stream lists the same embed as 'voe default/vostfr/vff'."""
    from types import SimpleNamespace

    from freeflix_cli.handlers.playback import _dedup_players

    def P(name, url):
        return SimpleNamespace(name=name, url=url)

    same = "https://voe.sx/e/garmrwf0shom"
    other = "https://voe.sx/e/w7hhkc7y5a2f"
    out = _dedup_players([
        P("voe default", same),
        P("voe vostfr", other),
        P("voe vff", same),
        P("vidzy default", "https://vidzy.cc/embed-a.html"),
        P("vidzy vostfr", "https://vidzy.cc/embed-a.html"),
    ])
    # Same host+name collapsed (voe vff == voe default), different embeds kept.
    assert [p.name for p in out] == ["voe default", "vidzy default"]


def test_french_stream_dedups_same_embed_across_languages(monkeypatch):
    from freeflix_cli.scraping import french_stream as fs

    html = '<html><head><meta property="og:title" content="Nightborn"></head></html>'
    body = {
        "players": {
            "vidzy": {"default": "https://vidzy.cc/embed-a.html",
                      "vostfr": "https://vidzy.cc/embed-a.html"},
            "voe": {"default": "https://voe.sx/e/aaa",
                    "vostfr": "https://voe.sx/e/bbb",
                    "vff": "https://voe.sx/e/aaa"},
        }
    }

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return body

    monkeypatch.setattr(fs, "_get", lambda *a, **k: _Resp())
    # Embed-liveness check (vidzy/fsvid) is network: pretend they answer.
    from freeflix_cli.scraping import player as _pl
    monkeypatch.setattr(
        _pl, "get_hls_link", lambda url, headers=None: "https://cdn/master.m3u8"
    )
    movie = fs.get_movie("https://french-stream.net/1-nightborn.html", html)
    assert [(p.name, p.url) for p in movie.players] == [
        ("vidzy default", "https://vidzy.cc/embed-a.html"),
        ("voe default", "https://voe.sx/e/aaa"),
        ("voe vostfr", "https://voe.sx/e/bbb"),
    ]


def test_tool_works_rejects_broken_shim(monkeypatch):
    class _R:
        def __init__(self, rc):
            self.returncode = rc

    monkeypatch.setattr(pm.subprocess, "run", lambda *a, **k: _R(1))
    assert pm._tool_works("/broken/yt-dlp") is False
    monkeypatch.setattr(pm.subprocess, "run", lambda *a, **k: _R(0))
    assert pm._tool_works("/working/yt-dlp") is True
    assert pm._tool_works("") is False


def test_install_hint_is_platform_specific(monkeypatch):
    monkeypatch.setattr(pm.os, "name", "nt")
    assert "winget install yt-dlp.yt-dlp" in pm._install_hint("yt-dlp")
    monkeypatch.setattr(pm.os, "name", "posix")
    monkeypatch.setattr(pm.sys, "platform", "darwin")
    assert pm._install_hint("yt-dlp").startswith("brew install")
    monkeypatch.setattr(pm.sys, "platform", "linux")
    assert pm._install_hint("yt-dlp").startswith("sudo dnf install")


def test_resume_download_reuses_signed_headers(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        pm, "_download_stream",
        lambda **kw: (captured.update(kw) or True),
    )
    assert pm.resume_download({
        "stream_url": "https://sacdn/master.mpd",
        "headers": {"Cookie": "CloudFront-Policy=x"},
    }) is True
    assert captured["headers"] == {"Cookie": "CloudFront-Policy=x"}


def test_player_back_returns_to_episode_without_clearing(monkeypatch):
    """Back from the source-player menu is still inside the series view."""
    captured = {}
    episode = SimpleNamespace(
        players=[SimpleNamespace(name="vidmoly", url="https://vidmoly/e/x")],
        title="Episode 1",
    )
    monkeypatch.setattr(playback.player, "is_supported", lambda url: True)
    monkeypatch.setattr(playback, "_dedup_players", lambda ps: ps)
    monkeypatch.setattr(playback.tracker, "get_analyze_players", lambda: False)
    monkeypatch.setattr(playback.tracker, "get_subtitle_search", lambda: False)
    monkeypatch.setattr(playback.tracker, "get_last_server", lambda: "")
    monkeypatch.setattr(pm, "prefetch_stream", lambda *a, **k: None)
    monkeypatch.setattr(
        playback, "select_from_list",
        lambda opts, prompt, **kw: (
            captured.update(kw) or len(opts) - 1
        ),
    )

    assert playback.play_episode_flow(
        "Anime-Sama", "Dragon Ball Super", "Saison 1", episode,
        "https://x/catalogue/dbs", "https://x/dbs/saison1/vostfr", headers={},
    ) is False
    assert captured.get("clear_on_back") is False


def test_quality_analysis_primes_playback_resolution_cache(monkeypatch):
    """The quality menu resolves once; pressing Enter must not re-scrape.

    fsvid/vidzy rate-limit a second scrape and answer with the /troll/ decoy —
    that produced "quality shown, then Could not resolve stream URL".
    """
    pm._resolve_cache.clear()
    calls = []
    monkeypatch.setattr(
        pm.player, "get_hls_link",
        lambda url, headers=None: calls.append(url) or "https://cdn/master.m3u8",
    )
    monkeypatch.setattr(pm, "_proxy_request_headers", lambda *a, **k: {})
    monkeypatch.setattr(pm.player, "get_stream_headers", lambda url: {})
    monkeypatch.setattr(
        pm, "_probe_stream",
        lambda url, headers, timeout=12: {
            "variants": [{"height": 304, "bandwidth": 900000,
                          "uri": "https://cdn/304.m3u8"}],
            "blocked": None,
        },
    )
    try:
        info = pm._analyze_stream_quality_uncached(
            "https://fsvid.lol/embed-or1b267mrn9t.html"
        )
        assert info["ok"] is True
        assert pm._cached_resolve(
            "https://fsvid.lol/embed-or1b267mrn9t.html", {}
        ) == "https://cdn/master.m3u8"
        assert calls == ["https://fsvid.lol/embed-or1b267mrn9t.html"]
    finally:
        pm._resolve_cache.clear()
