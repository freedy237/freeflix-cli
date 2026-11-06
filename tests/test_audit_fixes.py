"""Regression tests for the 2.1 audit fixes.

Each test pins one bug that was found in the 2026-11 audit and could silently
come back: the download-retry tuple, the destructive test fixture, the doctor
ffmpeg flag, opaque proxy headers, tracker shape validation, the tiny-terminal
breadcrumb loop, wordmark/selection colours and provider registration.
"""

import json
import re
from pathlib import Path

from freeflix_cli import doctor, install_health, proxy, themes, ui
from freeflix_cli.tracker import ProgressTracker


# ── downloads ────────────────────────────────────────────────────────

def test_sequential_retry_publishes_verified_file(monkeypatch, tmp_path):
    """_verify_download returns (ok, reason): the old `!= "ok"` check threw
    away every valid file and made the sequential retry fail forever."""
    from freeflix_cli import player_manager as pm

    staging = tmp_path / "stage"
    staging.mkdir()
    staged = staging / "Episode 1.mp4"
    staged.write_bytes(b"x" * 1024)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    monkeypatch.setattr(pm, "_ytdlp_meta", {"url": {
        "url": "https://cdn/master.m3u8", "title": "Episode 1",
        "dir": str(staging), "headers": {}, "format": None,
        "out_dir": str(out_dir), "subfolder": None,
    }})
    monkeypatch.setattr(pm, "_resolve_tool", lambda name: "yt-dlp")
    monkeypatch.setattr(pm, "_tool_works", lambda path: True)
    monkeypatch.setattr(pm, "_ytdlp_download_cmd", lambda *a, **k: ["true"])
    monkeypatch.setattr(pm, "_expected_hls_info", lambda *a, **k: (10.0, 2.0))
    monkeypatch.setattr(pm, "_find_staged_output", lambda *a, **k: str(staged))
    monkeypatch.setattr(pm, "_verify_download", lambda *a, **k: (True, "ok"))

    import freeflix_cli.progress as progress
    monkeypatch.setattr(progress, "run_download_with_bar", lambda *a, **k: 0)

    assert pm._retry_hls_sequential("url") is True
    published = out_dir / "Episode 1.mp4"
    assert published.exists()
    assert published.read_bytes() == b"x" * 1024


def test_verify_download_returns_a_tuple(tmp_path):
    from freeflix_cli import player_manager as pm

    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    result = pm._verify_download(f)
    assert isinstance(result, tuple) and len(result) == 2


# ── doctor ───────────────────────────────────────────────────────────

def test_doctor_uses_ffmpeg_single_dash_version():
    assert doctor._VERSION_FLAGS["ffmpeg"] == "-version"
    assert doctor._VERSION_FLAGS["ffprobe"] == "-version"


def test_doctor_checks_the_freeflix_mpv_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert doctor._mpv_config_dir().parts[-2:] == ("freeflix", "mpv")


# ── proxy: opaque header handles ─────────────────────────────────────

def test_proxy_header_token_is_opaque_and_reversible():
    headers = {"Cookie": "vz_ok=secret", "Referer": "https://vidzy.cc/"}
    token = proxy._headers_token(headers)
    assert token and len(token) == 24
    assert "secret" not in token
    assert proxy._HEADER_TOKENS[token] == headers

    class _Handler:
        _parse_headers_arg = proxy._ProxyHandler._parse_headers_arg

    assert _Handler()._parse_headers_arg({"h": token}) == headers
    # Unknown/expired handle → no headers, never a JSON parse of the token.
    assert _Handler()._parse_headers_arg({"h": "nope"}) == {}


def test_proxy_tokens_are_shared_for_identical_headers():
    h = {"Referer": "https://example.test"}
    assert proxy._headers_token(h) == proxy._headers_token(dict(h))


# ── tracker shape validation ─────────────────────────────────────────

def test_tracker_drops_malformed_container_keys(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text(json.dumps({
        "history": [],                 # wrong: should be a dict
        "episode_durations": [],       # wrong: should be a dict
        "episode_positions": {"k": 12},  # valid
        "language": "fr",
    }), encoding="utf-8")

    t = ProgressTracker.__new__(ProgressTracker)
    t.data_file = path
    data = t._load_data()
    assert "history" not in data
    assert "episode_durations" not in data
    assert data["episode_positions"] == {"k": 12}
    assert data["language"] == "fr"


def test_tracker_rejects_non_dict_root(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    t = ProgressTracker.__new__(ProgressTracker)
    t.data_file = path
    assert t._load_data() == {}


# ── UI ───────────────────────────────────────────────────────────────

def test_crumb_line_terminates_on_tiny_width():
    from freeflix_cli import cli_utils
    from rich.cells import cell_len

    cli_utils.crumb_reset("Home", "Sources", "A very long provider name")
    # The prefix itself is 6 cells wide, so tiny widths cannot be honoured;
    # what matters is that the loop terminates instead of hanging the app.
    for width in (1, 4, 5, 8, 12):
        line = cli_utils._crumb_line(width)
        assert cell_len(line.plain) <= max(width, 8)


def test_selection_text_falls_back_to_black(monkeypatch):
    from freeflix_cli.tracker import tracker

    monkeypatch.setattr(tracker, "get_theme", lambda: "dracula")
    monkeypatch.setattr(tracker, "get_custom_accent", lambda: None)
    assert themes.color("selection_text") == "black"


def test_wordmark_follows_non_noir_theme(monkeypatch):
    from freeflix_cli.tracker import tracker

    monkeypatch.setattr(tracker, "get_theme", lambda: "dracula")
    monkeypatch.setattr(tracker, "get_custom_accent", lambda: None)
    assert ui._on_black_theme() is False

    monkeypatch.setattr(tracker, "get_theme", lambda: "noir")
    assert ui._on_black_theme() is True


# ── providers ────────────────────────────────────────────────────────

def _registered_names(monkeypatch, lang):
    from freeflix_cli import main
    from freeflix_cli.providers_registry import registry

    monkeypatch.setattr(main.tracker, "get_anime_language", lambda: lang)
    monkeypatch.setattr(main.tracker, "get_language", lambda: lang)
    registry.clear()
    main._register_providers()
    return [p["name"] for p in registry.providers]


def test_providers_registered_once_per_language(monkeypatch):
    en = _registered_names(monkeypatch, "en")
    assert sum("HiAnime" in n for n in en) == 1
    assert sum("GoldenAnime" in n for n in en) == 1
    assert sum("Anime-Sama" in n for n in en) == 1

    fr = _registered_names(monkeypatch, "fr")
    assert not any("HiAnime" in n for n in fr)
    assert not any("GoldenAnime" in n for n in fr)
    assert sum("Anime-Sama" in n for n in fr) == 1
    assert sum("French-Anime" in n for n in fr) == 1


def test_papystreaming_stays_english(monkeypatch):
    """User decision: Papystreaming's catalogue is English, so it must stay
    tagged 'en' (the 2.0 audit's 'bug' was a false positive)."""
    names = _registered_names(monkeypatch, "en")
    assert any("Papystreaming" in n for n in names)


# ── release / version ────────────────────────────────────────────────

def test_code_version_matches_pyproject():
    root = Path(__file__).resolve().parents[1]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', text, re.M).group(1)
    assert install_health.CODE_VERSION == version


def test_notifications_toast_xml_is_escaped():
    from freeflix_cli import notifications as n

    xml = n._toast_xml("A&B", "<C>")
    assert "A&amp;B" in xml and "&lt;C&gt;" in xml


def test_installers_do_not_use_setx_percent_path():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "install.py").read_text(encoding="utf-8")
    assert '"setx"' not in text
    assert ";%PATH%" not in text

def test_ffprobe_quality_flags_short_direct_mp4(monkeypatch):
    """A 30 s MP4 ad must be flagged even on a direct (non-HLS) stream."""
    from freeflix_cli import player_manager as pm

    class _R:
        stdout = ('{"streams":[{"height":720,"bit_rate":"1200000"}],'
                  '"format":{"bit_rate":"1200000","duration":"30.0"}}')

    monkeypatch.setattr(pm.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(pm.subprocess, "run", lambda *a, **k: _R())
    q = pm._ffprobe_quality("https://cdn/ad.mp4", {})
    assert q["height"] == 720 and q["duration"] == 30.0
    assert pm.is_likely_ad_placeholder(q) is True


def test_proxy_download_url_carries_token_and_hides_cookies(monkeypatch):
    """Vidzy/fsvid downloads must use the local proxy WITH ?k= and ?h=.

    Regression found after 2.1: the download URL was built without the
    capability token, so the proxy answered 403 while streaming worked.
    """
    from urllib.parse import parse_qs, urlparse

    from freeflix_cli import player_manager as pm
    from freeflix_cli import proxy

    monkeypatch.setattr(proxy, "PROXY_URL", "http://127.0.0.1:9999")
    monkeypatch.setattr(proxy, "PROXY_TOKEN", "tok-123")
    monkeypatch.setattr(proxy, "ensure_started", lambda: None)
    headers = {"Referer": "https://vidzy.cc/", "Cookie": "vz_ok=secret"}
    url = pm._proxy_download_url(
        "https://cdn.vidzy.cc/master.m3u8?t=1", headers, {"type": "fsvid"}, False)
    q = parse_qs(urlparse(url).query)
    assert q["k"] == ["tok-123"]
    assert "h" in q and "headers" not in q
    assert "vz_ok" not in url and "secret" not in url
    assert url.startswith("http://127.0.0.1:9999/")


def test_proxy_download_url_leaves_plain_hosts_alone():
    from freeflix_cli import player_manager as pm

    plain = "https://cdn.example/master.m3u8"
    assert pm._proxy_download_url(plain, {}, {}, False) == plain


def test_anime4k_is_opt_in_and_osd_hint_installed(monkeypatch, tmp_path):
    from freeflix_cli import setup_assistant

    (tmp_path / "mpv.conf").write_text(
        'glsl-shaders="~~/shaders/Anime4K_A.glsl:~~/shaders/Anime4K_B.glsl"\n'
        "cache=yes\n"
        "[anime4k-skip-high-res]\n"
        "profile-cond=p[\"video-params/h\"] >= 1080\n"
        "profile-restore=copy-equal\n"
        "glsl-shaders=\n", encoding="utf-8")
    (tmp_path / "input.conf").write_text(
        'CTRL+1 change-list glsl-shaders set "~~/shaders/Anime4K_A.glsl:~~/shaders/Anime4K_B.glsl"\n',
        encoding="utf-8")
    monkeypatch.setattr(setup_assistant, "get_mpv_config_dir", lambda: tmp_path)
    setup_assistant._fix_anime4k_input_conf()
    mpv = (tmp_path / "mpv.conf").read_text(encoding="utf-8")
    assert "Anime4K_A" not in mpv
    assert "anime4k-skip-high-res" not in mpv
    assert "osd-playing-msg" in mpv
    assert "CTRL+1" in mpv
    inp = (tmp_path / "input.conf").read_text(encoding="utf-8")
    assert "glsl-shaders set" not in inp
    assert "append" in inp


def test_mpv_never_reads_global_config(monkeypatch, tmp_path):
    from freeflix_cli import player_manager as pm

    monkeypatch.setattr(pm, "get_freeflix_mpv_config_dir", lambda: str(tmp_path))
    assert pm._mpv_config_args() == ["--no-config"]
    (tmp_path / "mpv.conf").write_text("cache=yes\n", encoding="utf-8")
    assert pm._mpv_config_args() == [f"--config-dir={tmp_path}"]
