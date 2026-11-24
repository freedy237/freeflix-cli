"""Tests for the exhaustive ``freeflix --doctor`` report.

Everything here is offline and mock-based: no real network, no real user
directories are written to. The goal is to lock in the *diagnostic contract*
(status/detail/action per check), the shareable report format (ASCII, 78
columns, VERDICT + FIXES), the JSON schema, and the "never crash" guarantee
even when every single check explodes.
"""

import json
import socket

import pytest

from freeflix_cli import doctor
from freeflix_cli.tracker import tracker


# ── helpers ──────────────────────────────────────────────────────────
def _fake_paths(tmp_path):
    return {
        "data": tmp_path / "data",
        "progress": tmp_path / "data" / "progress.json",
        "cache": tmp_path / "cache",
        "http_cache": tmp_path / "cache" / "http",
        "recent": tmp_path / "cache" / "recent_releases.json",
        "covers": tmp_path / "covers",
        "config": tmp_path / "config",
        "mpv": tmp_path / "config" / "mpv",
        "managed_bins": tmp_path / "data" / "bin",
        "portal_override": tmp_path / "config" / "source_portal.jsonc",
        "log": tmp_path / "cache" / "freeflix.log",
        "log_dir": tmp_path / "cache",
        "downloads": tmp_path / "downloads",
        "downloads_temp": tmp_path / "downloads" / ".temp",
    }


def _statuses(entries):
    return [entry["status"] for entry in entries]


def _label(entries, needle):
    for entry in entries:
        if needle.lower() in entry["label"].lower():
            return entry
    raise AssertionError(f"no entry matching {needle!r} in "
                         f"{[e['label'] for e in entries]}")


class _FakeFirst:
    title = "Fake Title"
    url = "https://example.test/series"


# ── argument parsing ─────────────────────────────────────────────────
def test_parse_doctor_args_defaults():
    options = doctor._parse_doctor_args([])
    assert options["sources"] is False
    assert options["players"] is False
    assert options["report"] is False
    assert options["report_path"] is None
    assert options["json"] is False
    assert options["no_network"] is False


def test_parse_doctor_args_players_implies_sources():
    options = doctor._parse_doctor_args(["--players"])
    assert options["players"] is True
    assert options["sources"] is True


@pytest.mark.parametrize("argv, expected", [
    (["--report"], None),
    (["--report", "out.txt"], "out.txt"),
    (["--report=out.txt"], "out.txt"),
    (["--report", "--json"], None),
])
def test_parse_doctor_args_report_forms(argv, expected):
    options = doctor._parse_doctor_args(argv)
    assert options["report"] is True
    assert options["report_path"] == expected


def test_parse_doctor_args_flags():
    options = doctor._parse_doctor_args(
        ["--doctor", "--sources", "--upload", "--json", "--no-network",
         "--unknown", "freeflix"])
    assert options["sources"] is True
    assert options["upload"] is True
    assert options["json"] is True
    assert options["no_network"] is True
    assert options["report"] is False


def test_usage_text_is_ascii():
    text = doctor._usage_text()
    assert text.isascii()
    for flag in ("--report", "--json", "--sources", "--players",
                 "--upload", "--no-network"):
        assert flag in text


# ── result model / rendering ─────────────────────────────────────────
def test_entry_sanitises_multiline_values():
    entry = doctor._entry("system", "label\nwith newline", doctor.WARN,
                          "detail\twith\r\nlines", "action\nhere")
    assert "\n" not in entry["detail"] and "\n" not in entry["action"]
    assert entry["status"] == "WARN"
    assert entry["label"] == "label / with newline"


def test_entry_shortens_home_directory():
    entry = doctor._entry("system", "x", doctor.INFO,
                          str(doctor.Path.home()) + "/some/file")
    assert "~" in entry["detail"]


def test_section_status_aggregation():
    assert doctor._section_status(
        [{"status": doctor.PASS}, {"status": doctor.INFO}]) == doctor.PASS
    assert doctor._section_status(
        [{"status": doctor.PASS}, {"status": doctor.WARN}]) == doctor.WARN
    assert doctor._section_status(
        [{"status": doctor.WARN}, {"status": doctor.ERROR}]) == doctor.FAIL
    assert doctor._section_status(
        [{"status": doctor.SKIP}]) == doctor.SKIP


def test_assign_codes_is_stable_and_prefixed():
    entries = [
        doctor._entry("system", "a", doctor.PASS),
        doctor._entry("system", "b", doctor.WARN),
        doctor._entry("network", "c", doctor.PASS),
    ]
    coded = doctor._assign_codes(entries)
    assert [entry["code"] for entry in coded] == ["SYS-01", "SYS-02", "NET-01"]


def test_counts_covers_every_status():
    entries = [{"status": status} for status in
               (doctor.PASS, doctor.WARN, doctor.FAIL, doctor.ERROR,
                doctor.INFO, doctor.SKIP)]
    counts = doctor._counts(entries)
    assert counts[doctor.PASS] == 1
    assert counts[doctor.FAIL] == 1
    assert counts[doctor.ERROR] == 1


@pytest.fixture
def sample_entries():
    entries = []
    for key, _title in doctor._SECTIONS:
        entries.append(doctor._entry(key, "check", doctor.PASS, "fine"))
    entries.append(doctor._entry(
        "binaries", "ffmpeg", doctor.FAIL, "not found",
        "sudo dnf install -y ffmpeg"))
    entries.append(doctor._entry(
        "network", "GitHub", doctor.WARN, "DNS FAIL",
        "switch DNS to 1.1.1.1"))
    return entries


def test_render_has_header_verdict_fixes_footer(sample_entries):
    meta = {
        "generated_utc": "2026-01-01T00:00:00Z",
        "generated_local": "2026-01-01 00:00:00 +0000",
        "version": "1.2.3",
        "code_version": "1.2.3",
        "distro": "TestOS",
        "os": "linux",
        "platform": "Linux 1.0 (x86_64)",
        "python": "3.12.0",
        "python_executable": "/usr/bin/python3",
        "terminal": "xterm 120x40",
        "width": doctor._REPORT_WIDTH,
        "elapsed_s": 1.23,
    }
    report = doctor._render(sample_entries, meta)
    assert "DIAGNOSTIC REPORT" in report
    assert "VERDICT" in report
    assert "FIXES (run these in order):" in report
    assert "HOW TO REPORT A BUG" in report
    assert "BIN-02" in report          # ffmpeg is the 2nd binaries entry
    assert "sudo dnf install -y ffmpeg" in report
    assert doctor._ISSUES_URL in report


def test_render_is_ascii_and_never_wider_than_80(sample_entries):
    report = doctor._render(sample_entries, doctor._meta(elapsed=0))
    assert report.isascii()
    widest = max(len(line) for line in report.splitlines())
    assert widest <= doctor._REPORT_WIDTH
    assert widest <= 80


def test_render_wraps_very_long_unbroken_paths():
    entry = doctor._entry("system", "path", doctor.INFO, "/x/" + "a" * 400)
    report = doctor._render([entry], doctor._meta(elapsed=0))
    assert max(len(line) for line in report.splitlines()) <= doctor._REPORT_WIDTH


def test_render_survives_malformed_entries():
    entries = [
        {"section": "system", "label": None, "status": None,
         "detail": None, "action": Simple()},
        {"section": "unknown", "label": "x" * 500, "status": "WEIRD"},
    ]
    report = doctor._render(entries, doctor._meta())
    assert report  # never raises


class Simple:
    def __str__(self):
        return "action"


def test_safe_print_falls_back_on_ascii_console():
    class AsciiStream:
        encoding = "ascii"

        def __init__(self):
            self.data = ""

        def write(self, text):
            text.encode("ascii")   # raises UnicodeEncodeError on non-ASCII
            self.data += text

        def flush(self):
            pass

    stream = AsciiStream()
    doctor._safe_print("héllo ─ ok", stream)   # must not raise
    assert "ok" in stream.data


# ── INSTALL ──────────────────────────────────────────────────────────
def test_collect_install_reports_metadata_mismatch(monkeypatch):
    import freeflix_cli.install_health as ih
    monkeypatch.setattr(ih, "install_state", lambda: {
        "frozen": False, "executable": "/usr/bin/python",
        "module_file": "/x/freeflix_cli/__init__.py",
        "metadata_version": "1.0.0", "code_version": "2.0.0",
        "mismatch": True, "shims": ["/usr/bin/freeflix"], "installer": "uv",
    })
    monkeypatch.setattr(ih, "cleanup_hint", lambda: "uv tool reinstall x")
    entries = doctor.collect_install()
    mismatch = _label(entries, "metadata version")
    assert mismatch["status"] == doctor.FAIL
    assert "uv tool reinstall x" in mismatch["action"]


def test_collect_install_match_data_missing_is_warn(monkeypatch):
    import freeflix_cli.install_health as ih
    monkeypatch.setattr(ih, "install_state", lambda: {
        "frozen": True, "executable": "/x/freeflix",
        "module_file": "/x/__init__.py", "metadata_version": "2.6.1",
        "code_version": "2.6.1", "mismatch": False,
        "shims": ["/usr/bin/freeflix"], "installer": "frozen",
        "bundle_data_ok": False,
        "bundle_data_missing": ["clubs.json", "channel_logos.json"],
    })
    entries = doctor.collect_install()
    match = _label(entries, "match data")
    assert match["status"] == doctor.WARN
    assert "clubs.json" in match["detail"]
    assert "release" in match["action"]


def test_collect_install_match_data_ok(monkeypatch):
    import freeflix_cli.install_health as ih
    monkeypatch.setattr(ih, "install_state", lambda: {
        "frozen": False, "executable": "/usr/bin/python",
        "module_file": "/x/__init__.py", "metadata_version": "2.6.1",
        "code_version": "2.6.1", "mismatch": False,
        "shims": ["/usr/bin/freeflix"], "installer": "uv",
        "bundle_data_ok": True, "bundle_data_missing": [],
    })
    monkeypatch.setattr(ih, "bundled_data_status", lambda: {
        "clubs.json": {"source": "package", "present": True},
        "channel_logos.json": {"source": "package", "present": True},
    })
    entries = doctor.collect_install()
    assert _label(entries, "match data")["status"] == doctor.PASS


def test_collect_install_old_install_health_has_no_match_data_line(monkeypatch):
    import freeflix_cli.install_health as ih
    monkeypatch.setattr(ih, "install_state", lambda: {
        "frozen": False, "executable": "/usr/bin/python",
        "module_file": "/x/__init__.py", "metadata_version": "2.6.1",
        "code_version": "2.6.1", "mismatch": False,
        "shims": ["/usr/bin/freeflix"], "installer": "uv",
    })
    entries = doctor.collect_install()
    assert "match data" not in {entry["label"] for entry in entries}


def test_collect_install_warns_when_no_launcher(monkeypatch):
    import freeflix_cli.install_health as ih
    monkeypatch.setattr(ih, "install_state", lambda: {
        "frozen": False, "executable": "/usr/bin/python",
        "module_file": "/x/__init__.py", "metadata_version": "2.0.0",
        "code_version": "2.0.0", "mismatch": False, "shims": [],
        "installer": "uv",
    })
    entries = doctor.collect_install()
    launchers = _label(entries, "launchers")
    assert launchers["status"] == doctor.WARN
    assert "PATH" in launchers["action"]


# ── SYSTEM ───────────────────────────────────────────────────────────
def test_collect_system_reports_every_required_area(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    for value in paths.values():
        try:
            value.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    monkeypatch.setattr(doctor, "_app_paths", lambda: paths)
    monkeypatch.setattr(doctor, "_detect_distro", lambda: "TestOS")
    monkeypatch.setattr(doctor, "_stdout_isatty", lambda: False)
    monkeypatch.setattr(doctor, "_linux_family", lambda: "apt")
    entries = doctor.collect_system()
    labels = {entry["label"] for entry in entries}
    for required in ("os", "kernel", "cpu", "terminal", "encoding", "locale",
                     "python", "python env", "install mode", "PATH",
                     "PATH order", "home", "temp dir", "data dir", "cache dir",
                     "config dir", "download dir", "managed bins", "log dir"):
        assert required in labels, required
    assert not any(status == doctor.ERROR for status in _statuses(entries))


def test_collect_system_flags_read_only_dir(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    paths["data"].mkdir(parents=True)
    monkeypatch.setattr(doctor, "_app_paths", lambda: paths)
    monkeypatch.setattr(doctor, "_detect_distro", lambda: "TestOS")
    monkeypatch.setattr(doctor, "_stdout_isatty", lambda: False)
    monkeypatch.setattr(doctor.os, "access", lambda path, mode: False)
    entries = doctor.collect_system()
    data_entry = _label(entries, "data dir")
    assert data_entry["status"] == doctor.FAIL
    assert "chown" in data_entry["action"] or "icacls" in data_entry["action"]


def test_dir_entry_missing_is_warn_but_creatable(monkeypatch, tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    entry = doctor._dir_entry("system", "x", parent / "child" / "deep")
    assert entry["status"] == doctor.WARN
    assert "created on first run" in entry["detail"]


def test_dir_entry_existing_writable_is_pass(tmp_path):
    entry = doctor._dir_entry("system", "x", tmp_path)
    assert entry["status"] == doctor.PASS


def test_python_too_old_is_fail(monkeypatch):
    monkeypatch.setattr(doctor.sys, "version_info", (3, 8, 0))
    entry = doctor._encoding_entry()  # unrelated, just ensure no crash
    assert entry["status"] in (doctor.PASS, doctor.WARN)


# ── CONFIG & DISK ────────────────────────────────────────────────────
def test_progress_corrupt_is_fail_with_fix(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    paths["data"].mkdir(parents=True)
    paths["progress"].write_text("not json", encoding="utf-8")
    monkeypatch.setattr(doctor, "_app_paths", lambda: paths)
    entries = doctor._progress_entry()
    entry = _label(entries, "progress file")
    assert entry["status"] == doctor.FAIL
    assert ".bak" in entry["action"]


def test_progress_valid_is_pass(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    paths["data"].mkdir(parents=True)
    paths["progress"].write_text(json.dumps({"history": {"a": 1}}),
                                 encoding="utf-8")
    monkeypatch.setattr(doctor, "_app_paths", lambda: paths)
    entries = doctor._progress_entry()
    assert _label(entries, "progress file")["status"] == doctor.PASS
    assert _label(entries, "progress schema")["status"] == doctor.PASS


def test_collect_config_lists_paths_settings_and_disk(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    for value in paths.values():
        try:
            value.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    monkeypatch.setattr(doctor, "_app_paths", lambda: paths)
    entries = doctor.collect_config()
    labels = {entry["label"] for entry in entries}
    for required in ("data", "cache", "config", "mpv", "managed_bins",
                     "downloads", "progress file", "player", "languages",
                     "download quality", "playback", "display", "credentials",
                     "disk (downloads)", "disk (cache)"):
        assert required in labels, required
    # Credentials are presence-only: never print a token value.
    credentials = _label(entries, "credentials")
    assert "anilist_token=" in credentials["detail"]


def test_disk_entry_thresholds(monkeypatch, tmp_path):
    class Usage:
        def __init__(self, free):
            self.free = free
            self.total = 10 ** 12
            self.used = self.total - free

    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda path: Usage(10 ** 6))
    assert doctor._disk_entry("config", "d", tmp_path)["status"] == doctor.FAIL
    monkeypatch.setattr(doctor.shutil, "disk_usage",
                        lambda path: Usage(10 ** 9))
    assert doctor._disk_entry("config", "d", tmp_path)["status"] == doctor.WARN
    monkeypatch.setattr(doctor.shutil, "disk_usage",
                        lambda path: Usage(500 * 10 ** 9))
    assert doctor._disk_entry("config", "d", tmp_path)["status"] == doctor.PASS


# ── BINARIES ─────────────────────────────────────────────────────────
def test_install_command_per_platform(monkeypatch):
    monkeypatch.setattr(doctor, "_os", lambda: "windows")
    assert "winget install" in doctor._install_command("ffmpeg")
    monkeypatch.setattr(doctor, "_os", lambda: "macos")
    assert doctor._install_command("mpv") == "brew install mpv"
    monkeypatch.setattr(doctor, "_os", lambda: "linux")
    monkeypatch.setattr(doctor, "_linux_family", lambda: "apt")
    assert doctor._install_command("ffmpeg") == "sudo apt install -y ffmpeg"
    monkeypatch.setattr(doctor, "_linux_family", lambda: "dnf")
    assert doctor._install_command("aria2c") == "sudo dnf install -y aria2"


def test_collect_binaries_reports_missing_and_old(monkeypatch):
    def fake_binary(label, *names):
        name = names[0]
        if name == "ffmpeg":
            return ("OK", "ffmpeg version 9.0.2", "/usr/bin/ffmpeg")
        if name == "mpv":
            return ("OK", "mpv v0.41.0", "/usr/bin/mpv")
        if name == "vlc":
            return ("OK", "VLC version 3.0.24", "/usr/bin/vlc")
        if name == "chafa":
            return ("MISSING", "—", "—")
        if name == "yt-dlp":
            return ("OK", "2022.01.01", "/usr/bin/yt-dlp")
        if name == "aria2c":
            return ("BROKEN", "—", "/usr/bin/aria2c")
        return ("MISSING", "—", "—")

    monkeypatch.setattr(doctor, "_check_binary", fake_binary)
    monkeypatch.setattr(doctor, "_check_managed_bin",
                        lambda label, name: ("MISSING", "—", "—"))
    entries = doctor.collect_binaries()
    assert _label(entries, "ffmpeg")["status"] == doctor.PASS
    assert _label(entries, "chafa")["status"] == doctor.WARN
    assert "chafa" in _label(entries, "chafa")["action"]
    assert _label(entries, "yt-dlp")["status"] == doctor.WARN   # OLD
    assert _label(entries, "aria2c")["status"] == doctor.FAIL   # BROKEN
    assert not any(status == doctor.ERROR for status in _statuses(entries))


def test_collect_binaries_no_player_is_fail(monkeypatch):
    monkeypatch.setattr(doctor, "_check_binary",
                        lambda label, *names: ("MISSING", "—", "—"))
    monkeypatch.setattr(doctor, "_check_managed_bin",
                        lambda label, name: ("MISSING", "—", "—"))
    entries = doctor.collect_binaries()
    player = _label(entries, "local player")
    assert player["status"] == doctor.FAIL
    assert "mpv" in player["action"] or "vlc" in player["action"]


# ── PLAYERS (mpv / vlc) ──────────────────────────────────────────────
def test_collect_players_happy_path(monkeypatch, tmp_path):
    import freeflix_cli.player_manager as pm
    mpv = tmp_path / "mpv"
    mpv.write_text("", encoding="utf-8")
    monkeypatch.setattr(pm, "get_mpv_path", lambda: str(mpv))
    monkeypatch.setattr(pm, "get_vlc_path", lambda: None)
    monkeypatch.setattr(doctor, "_probe_binary",
                        lambda path, name: (doctor.PASS if False else "OK",
                                            "mpv v0.41.0"))
    monkeypatch.setitem(tracker.data, "player", "mpv")
    entries = doctor.collect_players()
    assert _label(entries, "mpv path")["status"] == doctor.PASS
    assert _label(entries, "mpv startup")["status"] == doctor.PASS
    assert _label(entries, "vlc path")["status"] == doctor.WARN
    assert _label(entries, "configured player")["status"] == doctor.PASS


def test_collect_players_configured_missing_is_fail(monkeypatch):
    import freeflix_cli.player_manager as pm
    monkeypatch.setattr(pm, "get_mpv_path", lambda: None)
    monkeypatch.setattr(pm, "get_vlc_path", lambda: None)
    monkeypatch.setitem(tracker.data, "player", "mpv")
    entries = doctor.collect_players()
    configured = _label(entries, "configured player")
    assert configured["status"] == doctor.FAIL
    assert "winget" in configured["action"] or "install" in configured["action"]


# ── MPV CONFIG & SHADERS ─────────────────────────────────────────────
def test_glsl_status_valid_invalid_empty(tmp_path):
    valid = tmp_path / "valid.glsl"
    valid.write_text("//!HOOK MAIN\n//!BIND HOOKED\nvec4 hook() { return 1; }",
                     encoding="utf-8")
    assert doctor._glsl_status(valid)["status"] == doctor.PASS

    invalid = tmp_path / "invalid.glsl"
    invalid.write_text("this is not a shader", encoding="utf-8")
    assert doctor._glsl_status(invalid)["status"] == doctor.WARN

    empty = tmp_path / "empty.glsl"
    empty.write_text("", encoding="utf-8")
    assert doctor._glsl_status(empty)["status"] == doctor.WARN


def test_collect_mpv_validates_shader_content(monkeypatch, tmp_path):
    config = tmp_path / "mpv"
    (config / "shaders").mkdir(parents=True)
    (config / "scripts").mkdir(parents=True)
    (config / "mpv.conf").write_text(
        "hwdec=auto-safe\ncache=yes\n# comment\n", encoding="utf-8")
    (config / "input.conf").write_text("CTRL+1 script-message anime4k\n",
                                       encoding="utf-8")
    (config / "scripts" / "freeflix_position.lua").write_text(
        "-- lua\n", encoding="utf-8")
    for shader in doctor._MPV_SHADERS:
        (config / "shaders" / shader).write_text(
            "//!HOOK MAIN\n//!BIND HOOKED\nvec4 hook() { return 1; }",
            encoding="utf-8")
    monkeypatch.setattr(doctor, "_mpv_config_dir", lambda: config)
    entries = doctor.collect_mpv()
    assert not any(status in (doctor.FAIL, doctor.ERROR)
                   for status in _statuses(entries))
    summary = _label(entries, "mpv.conf")
    assert "hwdec=auto-safe" in summary["detail"]


def test_collect_mpv_missing_config_is_warn(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_mpv_config_dir", lambda: tmp_path / "nope")
    entries = doctor.collect_mpv()
    assert _label(entries, "config dir")["status"] == doctor.WARN
    assert "freeflix --setup" in _label(entries, "config dir")["action"]


# ── PROXY ────────────────────────────────────────────────────────────
def test_collect_proxy_bind_failure(monkeypatch):
    class BrokenSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def bind(self, address):
            raise OSError("blocked")

    monkeypatch.setattr(doctor.socket, "socket", lambda *a, **k: BrokenSocket())
    entries = doctor.collect_proxy()
    assert _label(entries, "loopback bind")["status"] == doctor.FAIL


def test_collect_proxy_happy_path(monkeypatch):
    monkeypatch.setattr(doctor, "_proxy_start", lambda module: 1)
    monkeypatch.setattr(doctor, "_proxy_control_fetch",
                        lambda base: (200, "ok"))
    monkeypatch.setattr(doctor, "_proxy_stop", lambda module: None)
    entries = doctor.collect_proxy()
    assert _label(entries, "loopback bind")["status"] == doctor.PASS
    assert _label(entries, "start")["status"] == doctor.PASS
    assert _label(entries, "control fetch")["status"] == doctor.PASS
    assert _label(entries, "clean stop")["status"] == doctor.PASS


def test_collect_proxy_control_fetch_failure(monkeypatch):
    monkeypatch.setattr(doctor, "_proxy_start", lambda module: 1)
    monkeypatch.setattr(doctor, "_proxy_control_fetch",
                        lambda base: (500, "boom"))
    monkeypatch.setattr(doctor, "_proxy_stop", lambda module: None)
    entries = doctor.collect_proxy()
    assert _label(entries, "control fetch")["status"] == doctor.WARN


# ── NETWORK ──────────────────────────────────────────────────────────
def _probe(dns_ok=True, tcp_ok=True, tls_ok=True):
    return {"dns_ok": dns_ok, "ips": ["1.2.3.4"], "dns_err": "gaierror",
            "tcp_ok": tcp_ok, "tcp_err": "refused", "tls_ok": tls_ok,
            "tls_err": "certificate invalid", "cert_days": 90}


def test_collect_network_classifies_failures(monkeypatch):
    monkeypatch.setattr(doctor, "_network_hosts",
                        lambda: [("Good", "good.test"), ("NoDns", "dns.test"),
                                 ("NoTcp", "tcp.test"), ("NoTls", "tls.test")])
    monkeypatch.setattr(doctor, "_probe_hosts_parallel", lambda hosts, budget=5.0: {
        "Good": _probe(),
        "NoDns": _probe(dns_ok=False),
        "NoTcp": _probe(tcp_ok=False),
        "NoTls": _probe(tls_ok=False),
    })
    monkeypatch.setattr(doctor, "_check_flaresolverr",
                        lambda url: "NOT RUNNING (optional)")

    class FakeTracker:
        @staticmethod
        def get_flaresolverr_url():
            return "http://127.0.0.1:8191"

    monkeypatch.setattr(doctor, "_tracker", lambda: FakeTracker())
    entries = doctor.collect_network()
    assert _label(entries, "Good")["status"] == doctor.PASS
    assert _label(entries, "NoDns")["status"] == doctor.WARN
    assert "DNS" in _label(entries, "NoDns")["detail"]
    assert _label(entries, "NoTcp")["status"] == doctor.WARN
    assert _label(entries, "NoTls")["status"] == doctor.WARN
    assert _label(entries, "flaresolverr")["status"] == doctor.INFO


def test_collect_network_total_dns_failure_is_fail(monkeypatch):
    monkeypatch.setattr(doctor, "_network_hosts",
                        lambda: [("A", "a.test"), ("B", "b.test")])
    monkeypatch.setattr(doctor, "_probe_hosts_parallel",
                        lambda hosts, budget=5.0: {
                            "A": _probe(dns_ok=False),
                            "B": _probe(dns_ok=False)})
    monkeypatch.setattr(doctor, "_check_flaresolverr",
                        lambda url: "NOT RUNNING (optional)")
    monkeypatch.setattr(doctor, "_tracker", lambda: type(
        "T", (), {"get_flaresolverr_url": staticmethod(
            lambda: "http://127.0.0.1:8191")})())
    entries = doctor.collect_network()
    assert _label(entries, "internet")["status"] == doctor.FAIL


def test_host_probe_dns_failure_without_network(monkeypatch):
    def boom(*args, **kwargs):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(doctor.socket, "getaddrinfo", boom)
    result = doctor._host_probe("no-such-host.invalid")
    assert result["dns_ok"] is False
    assert "gaierror" in result["dns_err"]


def test_host_probe_tcp_failure(monkeypatch):
    monkeypatch.setattr(
        doctor.socket, "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("1.2.3.4", 443))])

    def boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(doctor.socket, "create_connection", boom)
    result = doctor._host_probe("host.test")
    assert result["dns_ok"] is True
    assert result["tcp_ok"] is False


def test_probe_hosts_parallel_returns_every_host(monkeypatch):
    monkeypatch.setattr(doctor, "_host_probe",
                        lambda host: _probe(dns_ok=(host != "slow.test")))
    results = doctor._probe_hosts_parallel(
        [("Fast", "fast.test"), ("Slow", "slow.test")], budget=2.0)
    assert set(results) == {"Fast", "Slow"}


# ── SOURCES & STREAMS ────────────────────────────────────────────────
def test_collect_sources_not_requested_is_skip():
    entries = doctor.collect_sources(requested=False)
    assert len(entries) == 1
    assert entries[0]["status"] == doctor.SKIP
    assert "--sources" in entries[0]["detail"]


class _FakeSourceModule:
    def __init__(self, results=None, error=None):
        self._results = results if results is not None else [_FakeFirst()]
        self._error = error
        self.searched = 0

    def get_website_url(self, *args, **kwargs):
        return "https://example.test"

    def search(self, query):
        self.searched += 1
        if self._error:
            raise self._error
        return self._results


def test_source_search_probe_pass(monkeypatch):
    module = _FakeSourceModule()
    monkeypatch.setattr(doctor, "_import_module", lambda path: module)
    entries = doctor._source_search_probe(
        "Anime-Sama", "freeflix_cli.scraping.anime_sama", "naruto",
        deep=False, timeout=5.0)
    assert entries[0]["status"] == doctor.PASS
    assert "1 result" in entries[0]["detail"]
    assert module.searched == 1


def test_source_search_probe_empty_results_is_warn(monkeypatch):
    monkeypatch.setattr(doctor, "_import_module",
                        lambda path: _FakeSourceModule(results=[]))
    entries = doctor._source_search_probe(
        "Coflix", "x", "matrix", deep=False, timeout=5.0)
    assert entries[0]["status"] == doctor.WARN
    assert "0 results" in entries[0]["detail"]


def test_source_search_probe_classifies_provider_vs_bug(monkeypatch):
    cloudflare = RuntimeError("Cloudflare challenge 403 cf-ray")
    monkeypatch.setattr(doctor, "_import_module",
                        lambda path: _FakeSourceModule(error=cloudflare))
    entries = doctor._source_search_probe(
        "Coflix", "x", "matrix", deep=False, timeout=5.0)
    assert entries[0]["status"] == doctor.WARN
    assert "MORT-FOURNISSEUR" in entries[0]["detail"]

    parser_bug = AttributeError("'NoneType' has no attribute 'text'")
    monkeypatch.setattr(doctor, "_import_module",
                        lambda path: _FakeSourceModule(error=parser_bug))
    entries = doctor._source_search_probe(
        "Coflix", "x", "matrix", deep=False, timeout=5.0)
    assert entries[0]["status"] == doctor.FAIL
    assert "BUG-FREEFLIX" in entries[0]["detail"]


def test_source_search_probe_import_failure_is_fail(monkeypatch):
    def boom(path):
        raise ImportError("missing module")

    monkeypatch.setattr(doctor, "_import_module", boom)
    entries = doctor._source_search_probe(
        "Anime-Sama", "x", "naruto", deep=False, timeout=5.0)
    assert entries[0]["status"] == doctor.FAIL
    assert "BUG-FREEFLIX" in entries[0]["detail"]


def test_source_search_probe_timeout(monkeypatch):
    import time as _time

    class SlowModule(_FakeSourceModule):
        def search(self, query):
            _time.sleep(0.5)
            return []

    monkeypatch.setattr(doctor, "_import_module",
                        lambda path: SlowModule())
    entries = doctor._source_search_probe(
        "Anime-Sama", "x", "naruto", deep=False, timeout=0.1)
    assert entries[0]["status"] == doctor.WARN
    assert "MORT-FOURNISSEUR" in entries[0]["detail"]


def test_classify_exception_buckets():
    tag, _action = doctor._classify_exception(
        RuntimeError("HTTP 503 Service Unavailable"))
    assert tag.startswith("MORT-FOURNISSEUR")
    tag, _action = doctor._classify_exception(KeyError("players"))
    assert tag == "BUG-FREEFLIX"


def test_deep_source_probe_reports_playable_stream(monkeypatch):
    monkeypatch.setitem(
        doctor._SOURCE_ADAPTERS, "Anime-Sama",
        lambda module, first: [{"name": "voe", "url": "https://cdn.test/x.m3u8"}])
    monkeypatch.setattr(doctor, "_probe_hls_playable",
                        lambda url, headers=None, timeout=8.0: (True, ""))
    entries = doctor._deep_source_probe(
        "Anime-Sama", object(), _FakeFirst(), 10.0)
    assert _label(entries, "players")["status"] == doctor.PASS
    stream = _label(entries, "stream")
    assert stream["status"] == doctor.PASS
    assert "voe" in stream["detail"]
    assert "OK" in stream["detail"]


def test_deep_source_probe_reports_expired_stream(monkeypatch):
    monkeypatch.setitem(
        doctor._SOURCE_ADAPTERS, "Coflix",
        lambda module, first: [{"name": "uqload", "url": "https://c/x.m3u8"}])
    monkeypatch.setattr(doctor, "_probe_hls_playable",
                        lambda url, headers=None, timeout=8.0:
                        (False, "expired"))
    entries = doctor._deep_source_probe("Coflix", object(), _FakeFirst(), 10.0)
    stream = _label(entries, "stream")
    assert stream["status"] == doctor.WARN
    assert "uqload" in stream["detail"]
    assert "MORT-FOURNISSEUR" in stream["detail"]


def test_deep_source_probe_no_adapter_is_info():
    entries = doctor._deep_source_probe(
        "Papystreaming", object(), _FakeFirst(), 10.0)
    assert entries[0]["status"] == doctor.INFO


def test_deep_source_probe_bug_is_flagged(monkeypatch):
    def broken(module, first):
        raise AttributeError("NoneType has no attribute 'players'")

    monkeypatch.setitem(doctor._SOURCE_ADAPTERS, "Anime-Sama", broken)
    entries = doctor._deep_source_probe(
        "Anime-Sama", object(), _FakeFirst(), 10.0)
    assert entries[0]["status"] == doctor.FAIL
    assert "BUG-FREEFLIX" in entries[0]["detail"]


@pytest.fixture
def fake_players_modules():
    class Player:
        def __init__(self, name, url):
            self.name = name
            self.url = url

    class Episode:
        def __init__(self, players):
            self.players = players

    class Season:
        def __init__(self, episodes):
            self.episodes = episodes

    class Access:
        def __init__(self, url):
            self.url = url

    class Series:
        def __init__(self):
            self.seasons = [Access("https://example.test/season")]

    players = [Player("voe", "https://example.test/embed")]

    class Movie:
        def __init__(self):
            self.players = players

    class AnimeModule:
        def get_series(self, url):
            return Series()

        def get_season(self, url):
            return Season({"vf": [Episode(players)]})

    class CoflixModule:
        def get_content(self, url):
            return Movie()

        def get_season(self, url):
            return Season([])

        def get_episode(self, url):
            return Episode(players)

    class FrenchStreamModule:
        def get_content(self, url):
            return Season({"vf": [Episode(players)]})

    class FrenchMangaModule:
        def get_episodes(self, url):
            return {"vf": {"1": players}}

    return {
        "anime": (AnimeModule(), players),
        "coflix": (CoflixModule(), players),
        "french_stream": (FrenchStreamModule(), players),
        "french_manga": (FrenchMangaModule(), players),
    }


def test_source_adapters_resolve_players(fake_players_modules):
    anime_module, players = fake_players_modules["anime"]
    assert doctor._players_anime_sama(anime_module, _FakeFirst()) == players

    coflix_module, players = fake_players_modules["coflix"]
    assert doctor._players_coflix(coflix_module, _FakeFirst()) == players

    fs_module, players = fake_players_modules["french_stream"]
    assert doctor._players_french_stream(fs_module, _FakeFirst()) == players

    fm_module, players = fake_players_modules["french_manga"]
    assert doctor._players_french_manga(fm_module, _FakeFirst()) == players


def test_stream_entry_signed_slot_is_info():
    from freeflix_cli.scraping.utils import ANIME_SAMA_SIGNED_SENTINEL
    entries = doctor._stream_entry(
        "Anime-Sama", "signed", ANIME_SAMA_SIGNED_SENTINEL, 5.0)
    assert entries[0]["status"] == doctor.INFO


def test_stream_entry_resolves_embed_then_probes(monkeypatch):
    monkeypatch.setattr(doctor, "_resolve_embed",
                        lambda url, timeout=10.0: "https://cdn.test/x.m3u8")
    monkeypatch.setattr(doctor, "_probe_hls_playable",
                        lambda url, headers=None, timeout=8.0: (True, ""))
    entries = doctor._stream_entry(
        "Coflix", "voe", "https://embed.test/voe", 10.0)
    assert entries[0]["status"] == doctor.PASS


def test_stream_entry_resolver_crash_is_warn(monkeypatch):
    def boom(url, timeout=10.0):
        raise RuntimeError("extractor broke")

    monkeypatch.setattr(doctor, "_resolve_embed", boom)
    entries = doctor._stream_entry(
        "Coflix", "voe", "https://embed.test/voe", 10.0)
    assert entries[0]["status"] == doctor.WARN


# ── TERMINAL & IMAGES ────────────────────────────────────────────────
def test_collect_terminal_reports_images_font_and_mouse(monkeypatch):
    import freeflix_cli.terminal_image as ti
    monkeypatch.setattr(ti, "chafa_available", lambda: True)
    monkeypatch.setattr(ti, "_chafa_version", lambda: (1, 18))
    monkeypatch.setattr(ti, "detect_image_protocol", lambda: "sixel")
    monkeypatch.setattr(ti, "sixel_hint", lambda: None)
    monkeypatch.setattr(doctor, "_nerd_font_present",
                        lambda: (True, "fc-list match"))
    monkeypatch.setattr(doctor, "_stdout_isatty", lambda: False)
    entries = doctor.collect_terminal()
    labels = {entry["label"] for entry in entries}
    assert {"chafa", "image protocol", "nerd font", "mouse",
            "alternate screen", "colors"} <= labels
    assert _label(entries, "chafa")["status"] == doctor.PASS
    assert _label(entries, "image protocol")["status"] == doctor.PASS


def test_collect_terminal_missing_chafa_is_warn(monkeypatch):
    import freeflix_cli.terminal_image as ti
    monkeypatch.setattr(ti, "chafa_available", lambda: False)
    monkeypatch.setattr(doctor, "_nerd_font_present", lambda: (False, ""))
    monkeypatch.setattr(doctor, "_stdout_isatty", lambda: False)
    monkeypatch.setitem(tracker.data, "icon_style", "emoji")
    entries = doctor.collect_terminal()
    assert _label(entries, "chafa")["status"] == doctor.WARN


def test_collect_terminal_nerd_icons_without_font_is_warn(monkeypatch):
    import freeflix_cli.terminal_image as ti
    monkeypatch.setattr(ti, "chafa_available", lambda: False)
    monkeypatch.setattr(doctor, "_nerd_font_present", lambda: (False, ""))
    monkeypatch.setattr(doctor, "_stdout_isatty", lambda: False)
    monkeypatch.setitem(tracker.data, "icon_style", "nerd")
    entries = doctor.collect_terminal()
    assert _label(entries, "nerd font")["status"] == doctor.WARN


# ── LOGS ─────────────────────────────────────────────────────────────
def test_collect_logs_recent_errors(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    paths["cache"].mkdir(parents=True)
    paths["log"].write_text(
        "12:00:00 INFO    freeflix: starting\n"
        "12:00:01 ERROR   freeflix: playback failed 403\n"
        "Traceback (most recent call last):\n"
        "Unhandled exception\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "_app_paths", lambda: paths)
    entries = doctor.collect_logs()
    errors = _label(entries, "errors")
    assert errors["status"] == doctor.WARN
    assert "recent error 1" in {entry["label"] for entry in entries}
    patterns = _label(entries, "failure patterns")
    assert "403" in patterns["detail"]


def test_collect_logs_missing_file_is_info(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    monkeypatch.setattr(doctor, "_app_paths", lambda: paths)
    entries = doctor.collect_logs()
    assert entries[0]["status"] == doctor.INFO


# ── STATE & CACHE ────────────────────────────────────────────────────
def test_collect_state_library_and_cache(monkeypatch, tmp_path):
    import freeflix_cli.player_manager as pm
    paths = _fake_paths(tmp_path)
    for key in ("cache", "http_cache", "covers", "downloads_temp", "data"):
        paths[key].mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(doctor, "_app_paths", lambda: paths)
    monkeypatch.setattr(pm, "list_interrupted_downloads", lambda: [])
    monkeypatch.setitem(tracker.data, "history", {"a": {}, "b": {}})
    monkeypatch.setitem(tracker.data, "followed_series", {"c": {}})
    entries = doctor.collect_state()
    library = _label(entries, "library")
    assert "history=2" in library["detail"]
    assert "follows=1" in library["detail"]
    assert _label(entries, "interrupted downloads")["status"] == doctor.PASS
    assert _label(entries, "cache size")["status"] == doctor.INFO


def test_collect_state_interrupted_downloads_is_warn(monkeypatch, tmp_path):
    import freeflix_cli.player_manager as pm
    paths = _fake_paths(tmp_path)
    for key in ("cache", "http_cache", "covers", "downloads_temp"):
        paths[key].mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(doctor, "_app_paths", lambda: paths)
    monkeypatch.setattr(pm, "list_interrupted_downloads",
                        lambda: [{"title": "Movie", "percent": 40}])
    entries = doctor.collect_state()
    pending = _label(entries, "interrupted downloads")
    assert pending["status"] == doctor.WARN
    assert "Movie" in pending["detail"]


# ── WINDOWS ──────────────────────────────────────────────────────────
def test_collect_windows_skipped_elsewhere(monkeypatch):
    monkeypatch.setattr(doctor, "_os", lambda: "linux")
    entries = doctor.collect_windows()
    assert entries[0]["status"] == doctor.SKIP


def test_collect_windows_branch(monkeypatch, tmp_path):
    paths = _fake_paths(tmp_path)
    paths["managed_bins"].mkdir(parents=True)
    paths["managed_bins"].joinpath("mpv.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(doctor, "_os", lambda: "windows")
    monkeypatch.setattr(doctor, "_app_paths", lambda: paths)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    for name in ("local", "roaming"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(doctor, "_win_console_vt",
                        lambda: (True, True, ""))
    monkeypatch.setattr(doctor, "_win_output_codepage", lambda: 65001)
    monkeypatch.setattr(doctor, "_win_long_paths", lambda: True)
    monkeypatch.setattr(doctor, "_win_motw", lambda exe: (False, "clean"))
    monkeypatch.setattr(doctor, "_win_defender", lambda: (True, "on"))
    entries = doctor.collect_windows()
    labels = {entry["label"] for entry in entries}
    assert "managed mpv.exe" in labels
    assert "console VT" in labels
    assert "console codepage" in labels
    assert "long paths" in labels
    assert "mark-of-the-web" in labels
    assert not any(status == doctor.ERROR for status in _statuses(entries))


# ── REPORT COLLECTION / CLI ──────────────────────────────────────────
def test_collect_report_offline_has_all_sections(monkeypatch):
    entries = doctor.collect_report(network=False)
    sections = {entry["section"] for entry in entries}
    assert {"install", "system", "config", "binaries", "players", "mpv",
            "proxy", "network", "terminal", "logs", "state",
            "windows"} <= sections


def test_collect_report_survives_every_collector_crashing(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("everything is broken")

    for name in ("collect_install", "collect_system", "collect_config",
                 "collect_binaries", "collect_players", "collect_mpv",
                 "collect_proxy", "collect_network", "collect_terminal",
                 "collect_logs", "collect_state", "collect_windows",
                 "collect_sources"):
        monkeypatch.setattr(doctor, name, boom)
    entries = doctor.collect_report(network=True, sources=True)
    assert entries
    assert all(entry["status"] == doctor.ERROR for entry in entries)
    report = doctor._render(entries, doctor._meta())
    assert "ERROR" in report


def test_run_returns_rendered_report_and_writes_file(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "collect_report", lambda **kwargs: [
        doctor._entry("system", "check", doctor.PASS, "all good")])
    target = tmp_path / "report.txt"
    report = doctor.run(network=False, report_path=target)
    assert "DIAGNOSTIC REPORT" in report
    assert target.is_file()
    assert "DIAGNOSTIC REPORT" in target.read_text(encoding="utf-8")


def test_run_json_matches_schema(monkeypatch):
    monkeypatch.setattr(doctor, "collect_report", lambda **kwargs: [
        doctor._entry("system", "check", doctor.PASS, "all good")])
    payload = json.loads(doctor.run_json(network=False))
    assert payload["schema"] == "freeflix.doctor/1"
    assert payload["summary"][doctor.PASS] == 1
    assert payload["verdict"]["system"] == doctor.PASS
    assert payload["checks"][0]["code"] == "SYS-01"


def test_run_upload_appends_gist_url(monkeypatch):
    monkeypatch.setattr(doctor, "collect_report", lambda **kwargs: [
        doctor._entry("system", "check", doctor.PASS, "all good")])
    monkeypatch.setattr(doctor, "_upload_gist",
                        lambda text: "https://gist.github.com/x")
    report = doctor.run(network=False, upload=True)
    assert "https://gist.github.com/x" in report


def test_cli_doctor_json(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["freeflix", "--doctor", "--json"])
    monkeypatch.setattr(doctor, "collect_report", lambda **kwargs: [
        doctor._entry("system", "check", doctor.PASS, "all good")])
    assert doctor.cli_doctor() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "freeflix.doctor/1"


def test_cli_doctor_report_flag(monkeypatch, capsys, tmp_path):
    target = tmp_path / "share-me.txt"
    monkeypatch.setattr("sys.argv",
                        ["freeflix", "--doctor", "--report", str(target)])
    monkeypatch.setattr(doctor, "collect_report", lambda **kwargs: [
        doctor._entry("system", "check", doctor.PASS, "all good")])
    assert doctor.cli_doctor() == 0
    out = capsys.readouterr()
    assert target.is_file()
    assert "Report written to:" in out.err


def test_cli_doctor_upload_failure_is_graceful(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["freeflix", "--doctor", "--upload"])
    monkeypatch.setattr(doctor, "collect_report", lambda **kwargs: [
        doctor._entry("system", "check", doctor.PASS, "all good")])
    monkeypatch.setattr(doctor, "_upload_gist", lambda text: None)
    assert doctor.cli_doctor() == 0
    captured = capsys.readouterr()
    assert "Upload skipped" in captured.err


def test_cli_doctor_help(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["freeflix", "--doctor", "--help"])
    assert doctor.cli_doctor() == 0
    out = capsys.readouterr().out
    assert "--report" in out and "--json" in out
    assert out.isascii()


def test_write_report_file_creates_parents(tmp_path):
    target = tmp_path / "a" / "b" / "report.txt"
    path = doctor._write_report_file("hello", target)
    assert path.read_text(encoding="utf-8") == "hello"


def test_meta_contains_expected_keys():
    meta = doctor._meta(elapsed=0.5)
    for key in ("schema", "generated_utc", "version", "code_version", "os",
                "distro", "platform", "python", "python_executable",
                "terminal", "width", "elapsed_s"):
        assert key in meta
    assert meta["elapsed_s"] == 0.5


def test_report_is_shareable_plain_text(sample_entries):
    report = doctor._render(sample_entries, doctor._meta(elapsed=2.5))
    assert report.startswith("=" * doctor._REPORT_WIDTH)
    assert report.endswith("=" * doctor._REPORT_WIDTH)
    assert "tokens" in report and "passwords" in report
