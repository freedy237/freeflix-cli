"""Player-menu quality badges for the providers that build their own list."""

from freeflix_cli.handlers import goldenms, hianime
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
