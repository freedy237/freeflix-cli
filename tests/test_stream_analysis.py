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
        "HiAnime (SUB - ZokoAnime) [Multi]"
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
        "Vidlink - Multi (DASH)  —  1080p ~5.3 Mbps"
    ]


def test_labels_keep_static_quality_when_analysis_fails():
    streams = [{"source": "HiAnime (DUB - HD-1)", "quality": "Multi",
                "url": "https://cdn/master.m3u8"}]
    labels = hianime._stream_labels(streams, {"https://cdn/master.m3u8": "✗"})
    assert labels == ["HiAnime (DUB - HD-1) [Multi]"]


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
