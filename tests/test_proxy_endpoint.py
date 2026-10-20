"""Routing of resolved streams to the local proxy endpoints.

A direct MP4 behind a signed CDN URL (e.g. Vidlink) must go to /video, not
/stream: /stream rewrites a playlist and answers an unplayable empty manifest,
which mpv reports as "Failed to open".
"""

from freeflix_cli.player_manager import _proxy_endpoint


def test_signed_direct_mp4_uses_video():
    url = (
        "https://bcdn.hakunaymatata.com/resource/h265/"
        "517bd5fef19d9d671dd4a7692ad69ead.mp4?sign=abc&t=1792428582"
    )
    assert _proxy_endpoint(url, {}, False) == "video"


def test_other_direct_extensions_use_video():
    for ext in (".mkv", ".webm", ".avi", ".mov", ".m4v"):
        assert _proxy_endpoint(f"https://cdn.example/video{ext}?token=1", {}, False) == "video"


def test_hls_master_stays_on_stream_even_with_mp4_in_query():
    url = "https://cdn.example/master.m3u8?fallback=clip.mp4&token=1"
    assert _proxy_endpoint(url, {}, False) == "stream"


def test_txt_playlist_stays_on_stream():
    assert _proxy_endpoint("https://cdn.example/index.txt", {}, False) == "stream"


def test_unknown_extension_follows_config_and_flag():
    assert _proxy_endpoint("https://cdn.example/play?id=1", {}, False) == "stream"
    assert _proxy_endpoint("https://cdn.example/play?id=1", {"ext": "mp4"}, False) == "video"
    assert _proxy_endpoint("https://cdn.example/play?id=1", {}, True) == "video"
