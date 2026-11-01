"""False positives: a resolved stream that is an ad/preview must be flagged."""

import freeflix_cli.player_manager as pm


def test_short_hls_is_flagged_as_ad():
    assert pm.is_likely_ad_placeholder({"ok": True, "duration": 30.0}) is True
    assert pm.is_likely_ad_placeholder({"ok": True, "duration": 89}) is True


def test_real_episode_is_not_flagged():
    assert pm.is_likely_ad_placeholder({"ok": True, "duration": 1380}) is False


def test_unknown_duration_is_never_flagged():
    assert pm.is_likely_ad_placeholder({"ok": True}) is False
    assert pm.is_likely_ad_placeholder({}) is False
    assert pm.is_likely_ad_placeholder(None) is False


def test_quality_label_shows_the_ad_instead_of_a_fake_quality():
    info = {"ok": True, "duration": 30.0,
            "qualities": [{"height": 720, "mbps": 1.0}]}
    assert pm.format_quality_label(info) == "\u26a0 30.0s"


def test_quality_label_keeps_real_quality():
    info = {"ok": True, "duration": 1380,
            "qualities": [{"height": 1080, "mbps": 5.0}]}
    assert "1080p" in pm.format_quality_label(info)


def test_quality_suffix_flags_the_ad():
    from freeflix_cli.handlers.playback import quality_suffix
    info = {"ok": True, "duration": 30.0}
    assert quality_suffix("720p ~1.0 Mbps", info).strip().startswith("\u2014")
    assert "30.0s" in quality_suffix("720p ~1.0 Mbps", info)


def test_xtremestream_keeps_the_player_referer():
    """xs1.php answers 403 without the player page as Referer."""
    from freeflix_cli.scraping import player
    embed = ("https://lecteur1.xtremestream.xyz/player/index.php"
             "?data=569ff987c643b4bedf504efda8f786c2")
    link = player.get_hls_link_xtremestream(embed, {})
    assert link.endswith("/player/xs1.php?data=569ff987c643b4bedf504efda8f786c2")
    stored = player.get_stream_headers(link)
    assert stored["Referer"] == embed
    assert stored["Origin"] == "https://lecteur1.xtremestream.xyz"


def test_probe_cap_is_lifted_for_hls_lists():
    """One Piece style playlists (~1100 segments) exceed the 2 MB video cap."""
    assert pm._HLS_LIST_MAX_BYTES >= 4 * 1024 * 1024
    assert pm._HLS_LIST_MAX_BYTES > pm._PROBE_MAX_BYTES


def test_extensionless_manifest_is_measured():
    """xtremestream serves /player/xs1.php?data=… (no .m3u8): duration must
    still be read, otherwise the ad check would be skipped."""
    info = {"ok": True, "duration": 3688.5}
    assert pm.is_likely_ad_placeholder(info) is False
    from freeflix_cli.player_manager import _DIRECT_MEDIA_EXTS
    url = "https://lecteur1.xtremestream.xyz/player/xs1.php?data=abc"
    is_manifest = not url.split("?")[0].lower().endswith(_DIRECT_MEDIA_EXTS)
    assert is_manifest is True


def test_media_playlist_without_variants_is_parsed():
    text = (
        "#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:6.0,\na.ts\n"
        "#EXTINF:5.5,\nb.ts\n#EXT-X-ENDLIST\n"
    )
    assert pm.m3u8_has_variants(text) is False
    master = (
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=900000\nmedia.m3u8\n"
    )
    assert pm.m3u8_has_variants(master) is True


def test_dead_embed_404_is_marked_dead():
    """A player whose embed itself 404s must read as unavailable, not hide it."""
    from freeflix_cli.scraping import player
    assert player.embed_status(404) == "dead"
    assert player.embed_status(410) == "dead"
    assert player.embed_status(403) == "blocked"
    assert player.embed_status(200) == "ok"
