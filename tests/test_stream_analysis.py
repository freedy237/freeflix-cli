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
