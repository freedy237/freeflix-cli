"""Windows/Linux feature-parity regressions (no Windows runner here).

The platform is SIMULATED — ``sys.platform`` patched, ``subprocess`` faked —
exactly like ``tests/test_windows_playback.py``. Each test pins ONE capability
that was (or could silently become) *less* capable on Windows than on Linux
while still being executable on this Linux/macOS host:

  * **Frozen binaries lose the package data dir.** ``--collect-submodules``
    only ships Python modules, so a PyInstaller build embedded neither
    ``src/freeflix_cli/data/clubs.json`` (curated team names, ~441 clubs) nor
    ``channel_logos.json`` (~30k logos) while a wheel install had both. Match
    then fell back to machine translation (``ليل`` → ``nuit``) and showed no
    logo: the reported "Windows version does less than the Linux one". The
    build recipes now pass ``--collect-data freeflix_cli`` and the loader
    resolves the files from ``_MEIPASS/freeflix_cli/data`` — pinned below.
  * The Windows bootstrap installs the same five media tools as install.sh
    (mpv, VLC, ffmpeg, aria2c, chafa) instead of a reduced set.
  * A frozen build on any OS is told to download the artifact of ITS OWN OS
    (the old hint always named ``freeflix-windows-x86_64.exe``, even on a
    frozen Linux/macOS build).
  * The robust ffmpeg→player pipe is still used for mpv on Windows; only
    VLC's stdin variant is POSIX-only and degrades to the local HLS proxy.
  * A chafa installed by the Windows winget fallback is usable in the SAME
    session (poster probe cache reset), not only after a restart.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parents[1]
PKG_DATA = REPO / "src" / "freeflix_cli" / "data"
BUILD_RECIPES = (
    ".github/workflows/binaries.yml",
    ".github/workflows/standalone-binaries.yml",
    "scripts/build-binary.sh",
)


# ── frozen binaries: Match's bundled reference data must be embedded ──


def test_package_reference_data_exists():
    """The two JSON indexes Match relies on live inside the package."""
    assert (PKG_DATA / "clubs.json").is_file()
    assert (PKG_DATA / "channel_logos.json").is_file()


@pytest.mark.parametrize("recipe", BUILD_RECIPES)
def test_every_build_recipe_collects_package_data(recipe):
    """`--collect-submodules` alone drops data/ → explicit --collect-data."""
    text = (REPO / recipe).read_text(encoding="utf-8")
    assert "--collect-data freeflix_cli" in text, (
        f"{recipe} would build a binary without Match's clubs/logos data")
    # The portal/selector JSONC files outside the package must stay bundled too.
    assert "data/source_portal.jsonc" in text
    assert "data/selectors.jsonc" in text


def test_ci_verifies_package_data_is_really_embedded():
    """The CI job must fail on a regression instead of shipping a downgrade.

    `--version`/`--doctor` short-circuit before Match data is ever read, so the
    old smoke test could not catch the missing files. The release workflow now
    runs the shared checker, which lists the PyInstaller archive and verifies
    EVERY repo data file is embedded (derived from the repo, never a fixed list).
    """
    text = (REPO / ".github/workflows/binaries.yml").read_text(encoding="utf-8")
    assert "scripts/check-binary-data.sh" in text
    checker = (REPO / "scripts" / "check-binary-data.sh").read_text(encoding="utf-8")
    assert "pyi-archive_viewer" in checker
    assert "freeflix_cli/data/" in checker


def test_loader_resolves_the_collected_data_location():
    """The loader's path must match what `--collect-data` creates.

    PyInstaller puts collected package data at ``_MEIPASS/freeflix_cli/data``;
    the loader computes ``Path(__file__).parent.parent / "data"``. Inside the
    frozen bundle that is the same directory, which is why no change to the
    (out-of-scope) scraper module was needed.
    """
    from freeflix_cli.scraping import yacine_match as ym

    expected = Path(ym.__file__).resolve().parent.parent / "data"
    assert Path(ym._DATA_DIR).resolve() == expected


def test_frozen_loader_reads_meipass_package_data(tmp_path, monkeypatch):
    """End-to-end: files at the --collect-data destination are found and parsed.

    The real indexes are copied into a fake ``_MEIPASS/freeflix_cli/data``
    directory (what PyInstaller creates) and the loader is pointed at it: this
    is the runtime behaviour of the fixed .exe.
    """
    from freeflix_cli.scraping import yacine_match as ym

    bundle = tmp_path / "_MEI1234567" / "freeflix_cli" / "data"
    bundle.mkdir(parents=True)
    for name in ("clubs.json", "channel_logos.json"):
        (bundle / name).write_bytes((PKG_DATA / name).read_bytes())

    monkeypatch.setattr(ym, "_DATA_DIR", bundle)
    monkeypatch.setattr(ym, "_DICT_CACHE", {})

    clubs = ym._load_data("clubs.json")
    logos = ym._load_data("channel_logos.json")
    assert len(clubs) > 400
    assert len(logos) > 10_000
    # The visible Match downgrade: Arabic names must use the curated FR name
    # instead of the machine-translation fallback ("ليل" → "nuit").
    assert ym._club_lookup("ليل", "fr") == "Lille"
    assert ym.channel_logo("beIN SPORTS 1").startswith("http")


def test_loader_degrades_without_data_like_the_old_binary(tmp_path, monkeypatch):
    """Documents the pre-fix .exe behaviour (and keeps it crash-free).

    Without the data dir Match silently lost curated names/logos; the loaders
    must never raise, so an old binary stays usable while the release is fixed.
    """
    from freeflix_cli.scraping import yacine_match as ym

    empty = tmp_path / "_MEI1234567" / "freeflix_cli" / "data"
    empty.mkdir(parents=True)
    monkeypatch.setattr(ym, "_DATA_DIR", empty)
    monkeypatch.setattr(ym, "_DICT_CACHE", {})

    assert ym._load_data("clubs.json") == {}
    assert ym.channel_logo("beIN SPORTS 1") == ""


# ── installers: Windows gets the same media tools as Linux ─────────────

_WINGET_MEDIA_IDS = {
    "mpv": ("shinchiro.mpv", "mpv-player.mpv-CI.MSVC", "mpv.net"),
    "vlc": ("VideoLAN.VLC",),
    "ffmpeg": ("Gyan.FFmpeg",),
    "aria2c": ("aria2.aria2",),
    "chafa": ("hpjansson.Chafa",),
}


def test_install_ps1_installs_every_media_tool_linux_gets():
    """Windows bootstrap must not ship a reduced tool set (posters/downloads)."""
    ps1 = (REPO / "scripts/install.ps1").read_text(encoding="utf-8")
    for label, ids in _WINGET_MEDIA_IDS.items():
        assert any(pkg_id in ps1 for pkg_id in ids), (
            f"install.ps1 no longer installs {label}")
    sh = (REPO / "scripts/install.sh").read_text(encoding="utf-8")
    for pkg in ("mpv", "vlc", "ffmpeg", "aria2", "chafa"):
        assert re.search(rf"\b{pkg}\b", sh), (
            f"install.sh lost {pkg} — parity reference is stale")


def test_setup_assistant_winget_fallback_covers_the_same_tools():
    """Users who installed with uv (no install.ps1) rely on the first-run gate."""
    from freeflix_cli import setup_assistant as sa

    tools = {}
    for label, pkg_id, _bins, _essential in sa._TOOLS:
        ids = (pkg_id,) if isinstance(pkg_id, str) else tuple(pkg_id)
        tools[label] = ids
    assert "hpjansson.Chafa" in tools["chafa"]
    assert "aria2.aria2" in tools["aria2"]
    assert "yt-dlp.yt-dlp" in tools["yt-dlp"]
    assert "Gyan.FFmpeg" in tools["ffmpeg"]
    assert "VideoLAN.VLC" in tools["player"] or any(
        "shinchiro.mpv" == i for i in tools["player"])


# ── frozen install hint names the artifact of the running OS ───────────


@pytest.mark.parametrize("platform,artifact", [
    ("win32", "freeflix-windows-x86_64.exe"),
    ("cygwin", "freeflix-windows-x86_64.exe"),
    ("linux", "freeflix-linux-x86_64"),
    ("darwin", "freeflix-macos-arm64"),
])
def test_frozen_cleanup_hint_names_the_artifact_of_this_os(
        monkeypatch, platform, artifact):
    """A frozen Linux binary used to be told to download the Windows .exe."""
    from freeflix_cli import install_health as ih

    monkeypatch.setattr(ih, "installer_kind", lambda: "frozen")
    monkeypatch.setattr(ih.sys, "platform", platform)
    hint = ih.cleanup_hint()
    assert artifact in hint
    assert "GitHub Releases" in hint


# ── playback parity: the ffmpeg pipe survives on Windows for mpv ───────


@pytest.mark.parametrize("windows", [True, False])
def test_play_direct_stream_mpv_uses_ffmpeg_pipe_on_both_os(
        monkeypatch, windows):
    """`_play_vlc_pipe` is POSIX-only, but mpv's pipe is NOT downgraded.

    Match streams are fed to mpv through the same ffmpeg TS pipe on Windows;
    only VLC's stdin mode is skipped there (unreliable) and falls back to the
    local HLS proxy — an equivalent path, not a missing feature.
    """
    from freeflix_cli import player_manager as pm, tracker

    monkeypatch.setattr(pm, "_is_windows", lambda: windows)
    monkeypatch.setattr(tracker.tracker, "get_player", lambda: "mpv")
    monkeypatch.setattr(tracker.tracker, "get_match_player", lambda: "mpv")
    exe = r"C:\mpv\mpv.exe" if windows else "/usr/bin/mpv"
    monkeypatch.setattr(pm, "_resolve_or_install", lambda name: exe)
    monkeypatch.setattr(pm, "_resolve_tool",
                        lambda name: r"C:\ff\ffmpeg.exe" if windows
                        else "/usr/bin/ffmpeg")
    seen = {}

    def fake_pipe(player_exe, url, headers, title):
        seen.update(exe=player_exe, url=url)
        return True

    monkeypatch.setattr(pm, "_play_ffmpeg_pipe", fake_pipe)
    assert pm.play_direct_stream("http://cdn/live.m3u8", {"Referer": "r"},
                                 "A - B", player_name="mpv") is True
    assert seen == {"exe": exe, "url": "http://cdn/live.m3u8"}


def test_play_direct_stream_vlc_pipe_is_posix_only(monkeypatch):
    """Windows: skip the stdin pipe, use the local proxy (documented fallback)."""
    from freeflix_cli import player_manager as pm, tracker, yacine_live_proxy

    class _Proxy:
        stopped = False

        def stop(self):
            self.stopped = True

    proxy = _Proxy()
    monkeypatch.setattr(pm, "_is_windows", lambda: True)
    monkeypatch.setattr(tracker.tracker, "get_player", lambda: "vlc")
    monkeypatch.setattr(tracker.tracker, "get_match_player", lambda: "vlc")
    monkeypatch.setattr(pm, "_resolve_or_install", lambda name: r"C:\vlc\vlc.exe")
    monkeypatch.setattr(pm, "_resolve_tool", lambda name: r"C:\ff\ffmpeg.exe")

    def must_not_pipe(*a, **k):
        raise AssertionError("the ffmpeg→VLC stdin pipe is POSIX-only")

    monkeypatch.setattr(pm, "_play_vlc_pipe", must_not_pipe)
    # The HTTP-TS upgrade is exercised separately; here force the last-resort
    # local HLS proxy so the fallback chain is what gets tested.
    monkeypatch.setattr(pm, "_play_vlc_http_ts", lambda *a, **k: False)
    monkeypatch.setattr(yacine_live_proxy, "start_live_proxy",
                        lambda url, headers: (proxy,
                                              "http://127.0.0.1:9/p/x.m3u8"))
    started = {}

    class _FakeProc:
        returncode = 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(cmd, **kw):
        started["cmd"] = list(cmd)
        return _FakeProc()

    monkeypatch.setattr(pm.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(pm, "_stop_vlc_keepalive", lambda: None)
    try:
        assert pm.play_direct_stream("http://cdn/live.m3u8", {"Referer": "r"},
                                     "A - B", player_name="vlc") is True
    finally:
        pm._VLC_KEEPALIVE.clear()
    assert started["cmd"][0] == r"C:\vlc\vlc.exe"
    assert started["cmd"][-1] == "http://127.0.0.1:9/p/x.m3u8"


# ── first-run Windows: chafa usable in the SAME session ───────────────


class _DummyLoadingScreen:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def status(self, *args, **kwargs):
        pass


def test_winget_chafa_is_usable_immediately(monkeypatch):
    """terminal_image caches its PATH lookup; a winget install in the first-run
    dependency gate must reset it or posters stay off until the next launch."""
    from freeflix_cli import progress
    from freeflix_cli import setup_assistant as sa
    from freeflix_cli import terminal_image as ti
    from freeflix_cli.tracker import tracker

    monkeypatch.setattr(tracker, "data", dict(tracker.data))
    tracker.data.pop("system_deps_ok", None)
    tracker.data.pop("system_deps_ok_version", None)
    monkeypatch.setattr(sa, "_get_installed_version", lambda: "test")
    monkeypatch.setattr(sa, "install_flatpak_shims", lambda: True)
    monkeypatch.setattr(sa, "_is_android", lambda: False)
    monkeypatch.setattr(sa, "detect_os", lambda: "windows")
    monkeypatch.setattr(sa, "_auto_install_managed", lambda os_name: None)
    monkeypatch.setattr(sa.shutil, "which",
                        lambda name: r"C:\winget.exe" if name == "winget"
                        else None)
    monkeypatch.setattr(sa, "missing_tools",
                        lambda: [("chafa", "hpjansson.Chafa", ("chafa",))])
    monkeypatch.setattr(sa, "_have", lambda bins: False)
    monkeypatch.setattr(sa, "_winget_install", lambda *a, **k: True)
    monkeypatch.setattr(sa, "_refresh_winget_path", lambda: None)
    monkeypatch.setattr(sa, "_mark_deps_ok", lambda version: None)
    monkeypatch.setattr(sa.time, "sleep", lambda s: None)
    # First check (enter the gate) fails, second one (after winget) succeeds.
    monkeypatch.setattr(sa, "runtime_ready", lambda: _runtime_calls.pop(0))
    _runtime_calls[:] = [False, True]
    monkeypatch.setattr(progress, "LoadingScreen", _DummyLoadingScreen)
    reset = mock.Mock()
    monkeypatch.setattr(ti, "reset_cache", reset)

    assert sa.ensure_runtime_deps() is True
    assert reset.called, (
        "chafa was installed by winget but the poster probe stayed cached off")


# tiny mutable list for the side_effect lambda above (kept at module level so
# monkeypatch restores it cleanly between tests).
_runtime_calls: list = []


# ── Windows portability of the managed tools / config paths ────────────


def test_chafa_is_found_in_winget_links_on_windows(tmp_path, monkeypatch):
    """Posters need chafa; winget only refreshes PATH for FUTURE processes.

    The resolver must also look in %LOCALAPPDATA%\\Microsoft\\WinGet\\Links (and
    the Program Files install) so posters work in the same session.
    """
    from freeflix_cli import terminal_image as ti

    links = tmp_path / "Microsoft" / "WinGet" / "Links"
    links.mkdir(parents=True)
    exe = links / "chafa.exe"
    exe.write_bytes(b"MZ")

    monkeypatch.setattr(ti.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.setattr(ti.shutil, "which", lambda name: None)
    monkeypatch.setattr(ti, "_CHAFA_PATH", None)
    assert ti.chafa_available() is True
    assert ti._CHAFA_PATH == str(exe)


def test_mpv_config_dir_on_windows_is_appdata(monkeypatch, tmp_path):
    """The dedicated --config-dir must land in %APPDATA%, not ~/.config."""
    from freeflix_cli import player_manager as pm

    monkeypatch.setattr(pm.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    cfg = pm.get_freeflix_mpv_config_dir()
    assert cfg == str(tmp_path / "AppData" / "Roaming" / "freeflix" / "mpv")


def test_refresh_winget_path_prepends_links_on_windows(monkeypatch, tmp_path):
    """winget only updates PATH for FUTURE processes; the current one must be
    patched in-memory or a just-installed mpv/VLC/chafa still looks missing."""
    from freeflix_cli import setup_assistant as sa

    links = tmp_path / "Microsoft" / "WinGet" / "Links"
    links.mkdir(parents=True)
    monkeypatch.setattr(sa.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # posixpath.expandvars does not expand %VAR% (ntpath does), and the raw
    # string uses backslashes: emulate the Windows expansion for this test.
    monkeypatch.setattr(
        sa.os.path, "expandvars",
        lambda p: p.replace("%LOCALAPPDATA%", str(tmp_path)).replace("\\", os.sep))
    monkeypatch.setenv("PATH", "/usr/bin" + sa.os.pathsep + "/bin")
    sa._refresh_winget_path()
    assert sa.os.environ["PATH"].split(sa.os.pathsep)[0] == str(links)


def test_download_path_budget_fits_windows_max_path(monkeypatch):
    """A long OneDrive Downloads path must not push the final file past 260."""
    from freeflix_cli import player_manager as pm

    monkeypatch.setattr(pm, "_is_windows", lambda: True)
    long_dir = "C:" + "\\a-very-long-onedrive-folder-name" * 3
    budget = pm._path_budget(long_dir)
    assert 40 <= budget <= 200
    assert len(long_dir) + 1 + budget + 24 <= 240
    monkeypatch.setattr(pm, "_is_windows", lambda: False)
    assert pm._path_budget(long_dir) == 200


# ── the Windows binary keeps its CLI entry points (no reduced interface) ──


def test_frozen_entry_point_exposes_scheduler_and_doctor():
    """Nothing in the Windows binary may drop flags the Linux build has."""
    cli_src = (REPO / "src" / "freeflix_cli" / "cli.py").read_text(
        encoding="utf-8")
    for flag in ("--version", "--help", "--doctor", "--scan-notifications",
                 "--setup"):
        assert flag in cli_src


# ── durable guards: packaging/data invariants for EVERY future release ──

REQUIRED_BUILD_FLAGS = (
    "--collect-all curl_cffi",
    "--collect-submodules freeflix_cli",
    "--collect-data freeflix_cli",
    "--hidden-import readchar",
    "--copy-metadata freeflix-cli",
    "data/source_portal.jsonc",
    "data/selectors.jsonc",
    "src/freeflix_cli/__main__.py",
)


@pytest.mark.parametrize("recipe", BUILD_RECIPES)
def test_all_build_recipes_share_the_same_pyinstaller_flags(recipe):
    """Release, CI and local builds must never drift apart.

    The 2.6.1 downgrade happened because one recipe (the release workflow) was
    missing --collect-data. Pinning the full flag set in EVERY recipe makes a
    future edit that forgets one fail here instead of in users' hands.
    """
    text = (REPO / recipe).read_text(encoding="utf-8")
    for token in REQUIRED_BUILD_FLAGS:
        assert token in text, f"{recipe} is missing: {token}"


@pytest.mark.parametrize("workflow", [
    ".github/workflows/binaries.yml",
    ".github/workflows/standalone-binaries.yml",
])
def test_every_workflow_verifies_embedded_data_with_the_shared_checker(workflow):
    text = (REPO / workflow).read_text(encoding="utf-8")
    assert "scripts/check-binary-data.sh" in text


def test_standalone_ci_builds_and_verifies_every_os():
    """"Windows only" was the original blind spot: validate all 3 OS pre-release."""
    text = (REPO / ".github/workflows/standalone-binaries.yml").read_text(
        encoding="utf-8")
    for runner in ("ubuntu-latest", "windows-latest", "macos-latest"):
        assert runner in text


def test_data_manifest_matches_the_shipped_files():
    """Adding a file to src/freeflix_cli/data/ must update the manifest.

    ``install_health.BUNDLED_DATA_FILES`` drives the invisible runtime repair;
    the CI checker derives its list from the directory. This test keeps both in
    sync forever, so a newly added data file can never ship missing unnoticed.
    """
    from freeflix_cli import install_health as ih

    on_disk = {p.name for p in PKG_DATA.iterdir() if p.is_file()}
    assert set(ih.BUNDLED_DATA_FILES) == on_disk, (
        "src/freeflix_cli/data/ and install_health.BUNDLED_DATA_FILES drifted")
    for name, floor in ih.BUNDLED_DATA_FILES.items():
        assert (PKG_DATA / name).stat().st_size >= floor


def test_bundled_data_helpers_detect_missing_files(tmp_path):
    from freeflix_cli import install_health as ih

    pkg = tmp_path / "freeflix_cli"
    (pkg / "data").mkdir(parents=True)
    assert ih.bundled_data_ok(str(pkg)) is False
    assert set(ih.bundled_data_missing(str(pkg))) == set(ih.BUNDLED_DATA_FILES)

    for name in ih.BUNDLED_DATA_FILES:
        (pkg / "data" / name).write_bytes((PKG_DATA / name).read_bytes())
    assert ih.bundled_data_ok(str(pkg)) is True
    assert ih.bundled_data_missing(str(pkg)) == []


def test_install_state_reports_bundle_data():
    """--doctor (ui agent) can surface this key without changing the contract."""
    from freeflix_cli import install_health as ih

    state = ih.install_state()
    assert state["bundle_data_ok"] is True
    assert state["bundle_data_missing"] == []


# ── durable, INVISIBLE self-heal for already-shipped broken builds ────


def test_match_data_self_heal_downloads_and_points_loader(tmp_path, monkeypatch):
    """An exe that shipped without the data repairs itself — no user action.

    Simulates the real 2.6.1 Windows binary: package dir without data/, no
    bundled files, and a cache that can be filled from the repository. After
    ``ensure_match_data()`` the Match loader must read curated data from the
    cache, so names/logos work again on the NEXT launch of the SAME exe.
    """
    from freeflix_cli import install_health as ih
    from freeflix_cli import setup_assistant as sa
    from freeflix_cli.scraping import yacine_match as ym

    empty_pkg = tmp_path / "fake_pkg"
    empty_pkg.mkdir()
    cache = tmp_path / "match-data"
    monkeypatch.setattr(ih, "package_dir", lambda: str(empty_pkg))
    monkeypatch.setattr(ih, "match_data_cache_dir", lambda: str(cache))
    monkeypatch.setattr(sa, "match_data_cache_dir", lambda: cache)

    def fake_download(url, dest, quiet=False):
        assert quiet is True, "background repair must stay silent"
        name = url.rsplit("/", 1)[-1]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((PKG_DATA / name).read_bytes())
        return True

    monkeypatch.setattr(sa, "_download", fake_download)
    monkeypatch.setattr(ym, "_DATA_DIR", tmp_path / "nowhere")
    monkeypatch.setattr(ym, "_DICT_CACHE", {})

    assert sa.ensure_match_data() is True
    assert ih.bundled_data_ok() is True
    assert len(ym._load_data("clubs.json")) > 400
    assert ym._club_lookup("ليل", "fr") == "Lille"
    # A second call is a cheap no-op (no re-download needed).
    assert sa.ensure_match_data() is True
    assert len(ym._load_data("channel_logos.json")) > 10_000


def test_match_data_self_heal_survives_offline(tmp_path, monkeypatch):
    """Offline: no crash, no user-visible warning, retried next launch."""
    from freeflix_cli import install_health as ih
    from freeflix_cli import setup_assistant as sa

    empty_pkg = tmp_path / "fake_pkg"
    empty_pkg.mkdir()
    cache = tmp_path / "match-data"
    monkeypatch.setattr(ih, "package_dir", lambda: str(empty_pkg))
    monkeypatch.setattr(ih, "match_data_cache_dir", lambda: str(cache))
    monkeypatch.setattr(sa, "match_data_cache_dir", lambda: cache)
    monkeypatch.setattr(sa, "_download", lambda *a, **k: False)

    assert sa.ensure_match_data() is False
    assert ih.bundled_data_ok() is False


def test_self_heal_runs_even_when_dependency_gate_is_cached(monkeypatch):
    """The repair must not be hidden by the 'all deps OK' fast path."""
    from freeflix_cli import setup_assistant as sa
    from freeflix_cli.tracker import tracker

    monkeypatch.setattr(tracker, "data", {"system_deps_ok": True})
    monkeypatch.setattr(sa, "_get_installed_version", lambda: "9.9.9")
    monkeypatch.setattr(sa, "_refresh_winget_path", lambda: None)
    monkeypatch.setattr(sa, "install_flatpak_shims", lambda: True)
    called = {}
    monkeypatch.setattr(sa, "_ensure_match_data_async",
                        lambda: called.setdefault("yes", True))
    assert sa.ensure_runtime_deps() is True
    assert called.get("yes") is True


# ── durable sixel detection on Windows (DA1 over the console) ──────────


def test_da1_parser_recognises_sixel_attribute():
    from freeflix_cli import terminal_image as ti

    assert ti._da1_has_sixel(b"\x1b[?62;4;22c") is True
    assert ti._da1_has_sixel(b"\x1b[?64;1;2;6;9;15;18;21;22c") is False
    assert ti._da1_has_sixel(b"") is False


def test_windows_sixel_probe_asks_the_console(monkeypatch):
    from freeflix_cli import terminal_image as ti

    monkeypatch.setattr(ti.os, "name", "nt")
    monkeypatch.setenv("WT_SESSION", "abc")
    monkeypatch.setattr(ti, "_SIXEL_OK", None)
    monkeypatch.setattr(ti, "_win_console_read_da1",
                        lambda timeout=0.4: b"\x1b[?62;4c")
    assert ti._terminal_supports_sixel() is True

    monkeypatch.setattr(ti, "_SIXEL_OK", None)
    monkeypatch.setattr(ti, "_win_console_read_da1",
                        lambda timeout=0.4: b"\x1b[?62;22c")
    assert ti._terminal_supports_sixel() is False


def test_windows_sixel_probe_skips_legacy_console(monkeypatch):
    """conhost/cmd.exe cannot render sixel: never probe, never emit garbage."""
    from freeflix_cli import terminal_image as ti

    monkeypatch.setattr(ti.os, "name", "nt")
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setattr(ti, "_SIXEL_OK", None)

    def boom(*a, **k):
        raise AssertionError("must not query a legacy Windows console")

    monkeypatch.setattr(ti, "_win_console_read_da1", boom)
    assert ti._terminal_supports_sixel() is False


# ── durable VLC live playback on Windows (TS over localhost HTTP) ──────


def test_ts_relay_streams_ffmpeg_ts_over_http():
    import threading
    import urllib.request

    from freeflix_cli.player_manager import _TsRelay

    relay = _TsRelay()
    assert relay.start() is True
    got = {}
    try:
        def client():
            with urllib.request.urlopen(relay.url, timeout=5) as resp:
                got["ctype"] = resp.headers.get("Content-Type")
                got["data"] = resp.read()

        thread = threading.Thread(target=client, daemon=True)
        thread.start()
        relay.feed(b"G" * 1024)
        relay.feed(b"G" * 2048)
        thread.join(timeout=5)
        relay.finish()
        thread.join(timeout=5)
    finally:
        relay.close()
    assert got.get("ctype") == "video/mp2t"
    assert got.get("data") == b"G" * 3072


def test_play_vlc_http_ts_feeds_ffmpeg_output_to_vlc_over_http(monkeypatch):
    from freeflix_cli import player_manager as pm

    class _FakeFF:
        def __init__(self):
            self.stdout = io.BytesIO(b"G" * 4096)
            self.returncode = None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    class _FakeVLC:
        returncode = 0

        def wait(self):
            return 0

    calls = []

    def fake_popen(cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        if "ffmpeg" in str(cmd[0]).lower():
            return _FakeFF()
        return _FakeVLC()

    monkeypatch.setattr(pm, "_resolve_tool", lambda name: r"C:\ff\ffmpeg.exe")
    monkeypatch.setattr(pm.subprocess, "Popen", fake_popen)
    assert pm._play_vlc_http_ts(
        r"C:\vlc\vlc.exe", "http://cdn/x.m3u8",
        {"Referer": "r"}, "T") is True

    ff_cmd = calls[0][0]
    vlc_cmd = calls[1][0]
    assert "-headers" in ff_cmd
    assert vlc_cmd[0] == r"C:\vlc\vlc.exe"
    assert "--demux=ts" in vlc_cmd
    assert vlc_cmd[-1].startswith("http://127.0.0.1:")
    assert vlc_cmd[-1].endswith("/live.ts")
    assert "-" not in vlc_cmd  # stdin playback must NOT be used on Windows


def test_play_direct_stream_vlc_windows_prefers_http_ts(monkeypatch):
    """Windows VLC gets the ffmpeg remux over HTTP before the HLS fallback."""
    from freeflix_cli import player_manager as pm, tracker

    monkeypatch.setattr(pm, "_is_windows", lambda: True)
    monkeypatch.setattr(tracker.tracker, "get_player", lambda: "vlc")
    monkeypatch.setattr(tracker.tracker, "get_match_player", lambda: "vlc")
    monkeypatch.setattr(pm, "_resolve_or_install", lambda name: r"C:\vlc\vlc.exe")
    monkeypatch.setattr(pm, "_resolve_tool", lambda name: r"C:\ff\ffmpeg.exe")
    monkeypatch.setattr(pm, "_play_vlc_pipe",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("stdin pipe must not run on Windows")))
    seen = {}
    monkeypatch.setattr(pm, "_play_vlc_http_ts",
                        lambda *a, **k: seen.setdefault("used", True) or True)
    from freeflix_cli import yacine_live_proxy
    monkeypatch.setattr(yacine_live_proxy, "start_live_proxy",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("proxy fallback must not be needed")))
    assert pm.play_direct_stream("http://cdn/live.m3u8", {"Referer": "r"},
                                 "A - B", player_name="vlc") is True
    assert seen.get("used") is True


# ── automation scripts (the maintainer's turnkey rebuild/verify path) ──

POSIX_SCRIPTS_ONLY = pytest.mark.skipif(
    os.name == "nt", reason="POSIX shell scripts (CI runs them on Linux/macOS)")


@POSIX_SCRIPTS_ONLY
def test_automation_scripts_have_valid_syntax():
    for script in ("scripts/check-binary-data.sh",
                   "scripts/build-binary.sh",
                   "scripts/rebuild-binaries.sh"):
        subprocess.run(["bash", "-n", str(REPO / script)], check=True)


@POSIX_SCRIPTS_ONLY
def test_rebuild_script_help_lists_every_mode():
    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "rebuild-binaries.sh"), "--help"],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    for mode in ("--local", "--windows-ci", "--verify-release", "--republish",
                 "--all"):
        assert mode in result.stdout


@POSIX_SCRIPTS_ONLY
def test_shared_binary_data_checker_reports_missing_files(tmp_path):
    """The generic checker must fail when ANY repo data file is not embedded.

    A fake archive viewer keeps the test fast and OS-independent: the checker
    derives the required list from src/freeflix_cli/data/ itself, so this also
    proves that adding a data file makes it mandatory automatically.
    """
    binary = tmp_path / "freeflix"
    binary.write_bytes(b"fake-binary")
    viewer = tmp_path / "fake-viewer.sh"
    entries = [f"'freeflix_cli/data/{p.name}'" for p in sorted(PKG_DATA.iterdir())
               if p.is_file()]
    entries += [f"'data/{p.name}'" for p in sorted((REPO / 'data').iterdir())
                if p.is_file()]
    listing = "\n".join(f"1, 1, 1, 0, 'x', {entry}" for entry in entries)
    viewer.write_text("#!/usr/bin/env bash\ncat <<'LIST'\n"
                      + listing + "\nLIST\n", encoding="utf-8")
    viewer.chmod(0o755)

    env = dict(os.environ, PYI_ARCHIVE_VIEWER=str(viewer))
    checker = str(REPO / "scripts" / "check-binary-data.sh")
    ok = subprocess.run(["bash", checker, str(binary)], env=env,
                        capture_output=True, text=True, timeout=30)
    assert ok.returncode == 0, ok.stderr

    # Drop the last package-data entry: must fail with a precise message.
    viewer.write_text("#!/usr/bin/env bash\ncat <<'LIST'\n"
                      + "\n".join(f"1, 1, 1, 0, 'x', {e}" for e in entries[:-1])
                      + "\nLIST\n", encoding="utf-8")
    viewer.chmod(0o755)
    bad = subprocess.run(["bash", checker, str(binary)], env=env,
                         capture_output=True, text=True, timeout=30)
    assert bad.returncode == 1
    assert "MISSING" in bad.stderr
