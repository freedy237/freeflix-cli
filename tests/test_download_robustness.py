"""Integrity checks for downloads: no skipped HLS segments / truncated MP4.

The user-visible bug was a video that "jumps" over bad parts. yt-dlp/aria2c
can exit 0 while the produced file is shorter than the source; these tests
pin the verification gate that refuses to publish such a file.
"""

import os

import pytest

import freeflix_cli.player_manager as pm


VOD_PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-PLAYLIST-TYPE:VOD
#EXTINF:6.0,
seg1.ts
#EXTINF:5.5,
seg2.ts
#EXT-X-ENDLIST
"""

LIVE_PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXTINF:6.0,
seg1.ts
#EXTINF:5.5,
seg2.ts
"""

MASTER_PLAYLIST = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=1280x720
media.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1920x1080
media1080.m3u8
"""


def test_expected_hls_seconds_sums_vod_segments(monkeypatch):
    seen = []

    def fake_probe(_sess, url, _headers, timeout=12):
        seen.append(url)
        return VOD_PLAYLIST

    monkeypatch.setattr(pm, "_safe_probe_text", fake_probe)
    assert pm._expected_hls_seconds("https://cdn/media.m3u8") == pytest.approx(11.5)
    assert seen == ["https://cdn/media.m3u8"]


def test_expected_hls_seconds_descends_master(monkeypatch):
    def fake_probe(_sess, url, _headers, timeout=12):
        if url.endswith("master.m3u8"):
            return MASTER_PLAYLIST
        return VOD_PLAYLIST

    monkeypatch.setattr(pm, "_safe_probe_text", fake_probe)
    # Highest-bandwidth variant is probed first.
    assert pm._expected_hls_seconds("https://cdn/master.m3u8") == pytest.approx(11.5)


def test_expected_hls_seconds_none_for_live(monkeypatch):
    monkeypatch.setattr(pm, "_safe_probe_text",
                        lambda *a, **k: LIVE_PLAYLIST)
    assert pm._expected_hls_seconds("https://cdn/live.m3u8") is None


def test_expected_hls_seconds_none_for_direct_file(monkeypatch):
    monkeypatch.setattr(pm, "_safe_probe_text", lambda *a, **k: None)
    assert pm._expected_hls_seconds("https://cdn/video.mp4") is None


def test_expected_hls_info_reports_shortest_segment(monkeypatch):
    monkeypatch.setattr(pm, "_safe_probe_text", lambda *a, **k: VOD_PLAYLIST)
    assert pm._expected_hls_info("https://cdn/media.m3u8") == (11.5, 5.5)


def test_verify_rejects_one_missing_second_with_segment_tolerance(
        tmp_path, monkeypatch):
    """A 1 s hole in a 6 s video must fail: tolerance stays below one segment."""
    p = _write(tmp_path / "ep.mp4")
    monkeypatch.setattr(pm, "_ffprobe_file_info", lambda path: (5.0, 100))
    ok, reason = pm._verify_download(p, expected_duration=6.0, tolerance=0.5)
    assert (ok, reason) == (False, "short")


def test_purge_download_temp_removes_corrupt_fragments_but_keeps_incomplete(
        tmp_path):
    (tmp_path / "Ep.mp4.part").write_bytes(b"partial")
    (tmp_path / "Ep.mp4.part-Frag3").write_bytes(b"corrupt")
    (tmp_path / "Ep.mp4.ytdl").write_text("{}")
    keep = tmp_path / "Ep.incomplete.mp4"
    keep.write_bytes(b"bad")
    pm._purge_download_temp(str(tmp_path))
    assert keep.exists()
    assert not (tmp_path / "Ep.mp4.part").exists()
    assert not (tmp_path / "Ep.mp4.part-Frag3").exists()
    assert not (tmp_path / "Ep.mp4.ytdl").exists()


def _write(path, size=100):
    path.write_bytes(b"x" * size)
    return str(path)


def test_verify_rejects_short_file_size(tmp_path, monkeypatch):
    p = _write(tmp_path / "ep.mp4", 100)
    monkeypatch.setattr(pm, "_ffprobe_file_info", lambda path: (60.0, 100))
    ok, reason = pm._verify_download(p, expected_duration=None,
                                     expected_size=200)
    assert (ok, reason) == (False, "size")


def test_verify_rejects_short_duration(tmp_path, monkeypatch):
    p = _write(tmp_path / "ep.mp4")
    monkeypatch.setattr(pm, "_ffprobe_file_info", lambda path: (80.0, 100))
    ok, reason = pm._verify_download(p, expected_duration=120.0)
    assert (ok, reason) == (False, "short")


def test_verify_accepts_small_container_rounding(tmp_path, monkeypatch):
    p = _write(tmp_path / "ep.mp4")
    monkeypatch.setattr(pm, "_ffprobe_file_info", lambda path: (119.8, 100))
    ok, reason = pm._verify_download(p, expected_duration=120.0)
    assert (ok, reason) == (True, "ok")


def test_verify_rejects_unreadable_when_ffprobe_exists(tmp_path, monkeypatch):
    p = _write(tmp_path / "ep.mp4")
    monkeypatch.setattr(pm, "_ffprobe_file_info", lambda path: (None, 100))
    monkeypatch.setattr(pm, "_resolve_tool",
                        lambda name: "/usr/bin/ffprobe" if name == "ffprobe" else None)
    ok, reason = pm._verify_download(p)
    assert (ok, reason) == (False, "unreadable")


def test_verify_accepts_when_ffprobe_missing(tmp_path, monkeypatch):
    p = _write(tmp_path / "ep.mp4")
    monkeypatch.setattr(pm, "_ffprobe_file_info", lambda path: (None, 100))
    monkeypatch.setattr(pm, "_resolve_tool", lambda name: None)
    assert pm._verify_download(p) == (True, "ok")


def test_verify_rejects_empty_file(tmp_path):
    p = _write(tmp_path / "ep.mp4", 0)
    assert pm._verify_download(p)[0] is False


def test_find_staged_output_ignores_partial_and_incomplete(tmp_path):
    _write(tmp_path / "Show.mp4.part", 500)
    _write(tmp_path / "Show.incomplete.mp4", 700)
    good = _write(tmp_path / "Show.mp4", 300)
    assert pm._find_staged_output(str(tmp_path), "Show") == good


def test_ytdlp_command_is_gap_proof():
    cmd = pm._ytdlp_download_cmd(
        "/usr/bin/yt-dlp", "https://cdn/master.m3u8", "Show", "/tmp/home",
        "/tmp/frag", {"Referer": "https://site"}, format_arg="bv*+ba",
        concurrent=8,
    )
    joined = " ".join(cmd)
    for flag in ("--no-playlist", "--abort-on-unavailable-fragments",
                 "--downloader native", "--fragment-retries 50",
                 "--retries 20", "--file-access-retries 10",
                 "--socket-timeout 30", "--concurrent-fragments 8"):
        assert flag in joined
    assert "Referer:https://site" in joined
    assert cmd[-2:] == ["bv*+ba", "https://cdn/master.m3u8"]


def test_aria2c_command_retries_and_limits_connections():
    cmd = pm._aria2c_download_cmd(
        "/usr/bin/aria2c", "https://cdn/file.mp4", "Show", "/tmp/frag",
        {"Cookie": "a=b"},
    )
    joined = " ".join(cmd)
    for flag in ("--max-tries=10", "--retry-wait=2", "--timeout=60",
                 "--connect-timeout=20", "--continue=true",
                 "--max-connection-per-server=8", "--split=8",
                 "--file-allocation=none", "--no-conf"):
        assert flag in joined
    assert cmd[-1] == "https://cdn/file.mp4"


def _install_fake_hls(monkeypatch, tmp_path, verify_result):
    monkeypatch.setattr(pm, "DOWNLOAD_DIR", str(tmp_path / "Downloads"))
    monkeypatch.setattr(pm, "TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setattr(pm, "_stable_temp_dir",
                        lambda safe_title, subfolder=None: str(tmp_path / "temp"))
    os.makedirs(tmp_path / "temp", exist_ok=True)
    monkeypatch.setattr(pm, "_resolve_tool",
                        lambda name: "/usr/bin/yt-dlp" if name == "yt-dlp" else None)
    monkeypatch.setattr(pm, "_tool_works", lambda path: True)
    monkeypatch.setattr(pm, "_expected_hls_info", lambda *a, **k: (None, None))
    monkeypatch.setattr(pm, "_verify_download", lambda *a, **k: verify_result)

    def fake_run(cmd, title, batch_callback=None, cancel_check=None):
        (tmp_path / "temp" / "Episode 1.mp4").write_bytes(b"x" * 100)
        return 0

    from freeflix_cli import progress
    monkeypatch.setattr(progress, "run_download_with_bar", fake_run)


def test_download_does_not_publish_an_incomplete_file(monkeypatch, tmp_path):
    _install_fake_hls(monkeypatch, tmp_path, (False, "short"))
    ok = pm._download_stream(
        "https://cdn/master.m3u8", "", "", "Episode 1", _with_ui=True,
    )
    assert ok is False
    assert not (tmp_path / "Downloads" / "Episode 1.mp4").exists()
    # Kept for a retry / inspection, but never in the user's folder.
    assert (tmp_path / "temp" / "Episode 1.incomplete.mp4").exists()


def test_download_publishes_only_after_verification(monkeypatch, tmp_path):
    _install_fake_hls(monkeypatch, tmp_path, (True, "ok"))
    ok = pm._download_stream(
        "https://cdn/master.m3u8", "", "", "Episode 1", _with_ui=True,
    )
    assert ok is True
    assert (tmp_path / "Downloads" / "Episode 1.mp4").exists()
    assert not (tmp_path / "temp" / "Episode 1.mp4").exists()
