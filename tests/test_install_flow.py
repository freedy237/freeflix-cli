"""Install / update flow regression tests (task: install idempotence).

The user-visible bugs these guard against:

* "the installer re-downloads the players / shaders even when everything is
  already installed" — every step must skip what exists and is valid.
* "freeflix asks again about mpv/setup at every launch" — a partial or
  interrupted setup must finish silently (fetching only the missing files)
  instead of re-opening the wizard (and its chafa / Nerd Font / FlareSolverr
  questions) on every start.
* "errors when a tool is already installed" — detection must use the same
  locations the app uses (PATH + managed bin dir + Windows install dirs).

All tests run offline: HTTP helpers are monkeypatched and failures are
counted, never performed.
"""

import os
import shutil
import re
import subprocess
import sys
from pathlib import Path

import pytest

from freeflix_cli import doctor, install_health
from freeflix_cli import setup_assistant as sa
from freeflix_cli.tracker import tracker

# The shell installers are POSIX-only: their tests execute bash scripts and
# shebang wrappers, which Windows cannot run (and its runner has no Linux
# distro). Pure-Python setup tests still run everywhere.
POSIX_ONLY = pytest.mark.skipif(
    os.name == "nt", reason="POSIX shell installers / shebang wrappers")
# Flatpak only exists on Linux; macOS runs the POSIX suite and used to fail
# these two tests because `detect_os()` correctly returned "macos".
LINUX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Flatpak is Linux-only")

ROOT = Path(__file__).resolve().parents[1]


# ─── Fixtures / helpers ───────────────────────────────────────────────
@pytest.fixture(autouse=True)
def isolated_tracker(monkeypatch):
    """Never touch the developer's real progress.json during these tests."""
    snapshot = dict(tracker.data)
    tracker.data.clear()
    monkeypatch.setattr(tracker, "_save_data", lambda: None)
    yield
    tracker.data.clear()
    tracker.data.update(snapshot)


def _fail(*_a, **_k):
    raise AssertionError("unexpected network call / prompt")


def _shader_bytes(name: str) -> bytes:
    """A file that passes ``_shader_ok`` (size floor + GLSL markers)."""
    min_bytes = int(sa._FILE_PINS[name]["min_bytes"])
    head = f"//!DESC Anime4K-test {name}\n//!HOOK MAIN\n".encode()
    return head + b"// filler\n" * max(1, min_bytes // 9 + 1)


def _write_complete_mpv_config(cfg: Path, shaders=sa._ALL_SHADERS) -> None:
    (cfg / "scripts").mkdir(parents=True, exist_ok=True)
    (cfg / "shaders").mkdir(parents=True, exist_ok=True)
    for name in ("mpv.conf", "input.conf"):
        shutil.copy(ROOT / "config" / name, cfg / name)
    shutil.copy(
        ROOT / "config" / "freeflix_position.lua",
        cfg / "scripts" / "freeflix_position.lua",
    )
    for name in shaders:
        (cfg / "shaders" / name).write_bytes(_shader_bytes(name))


def _fake_downloader(monkeypatch, written: list):
    """``_download_verified`` that writes platform-correct content offline."""
    def fake(url, dest, label=None):
        written.append(dest.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.name in sa._ALL_SHADERS:
            dest.write_bytes(_shader_bytes(dest.name))
        else:
            src = ROOT / "config" / dest.name
            dest.write_bytes(src.read_bytes())
        return True
    monkeypatch.setattr(sa, "_download_verified", fake)


# ─── 1. A complete install is never downloaded / asked again ─────────
def test_second_launch_downloads_nothing_and_asks_nothing(monkeypatch, tmp_path):
    cfg = tmp_path / "mpv"
    _write_complete_mpv_config(cfg)
    monkeypatch.setattr(sa, "get_mpv_config_dir", lambda: cfg)
    monkeypatch.setattr(sa, "_download_verified", _fail)
    monkeypatch.setattr(sa, "_download", _fail)
    monkeypatch.setattr(sa, "ask_yes_no", _fail)

    assert sa.is_setup_complete() is True
    assert sa.should_prompt_setup() is False

    # Two consecutive launches: neither may download, prompt or run the wizard.
    assert sa.run_setup(force=False) is False
    assert sa.run_setup(force=False) is False
    assert tracker.data.get("setup_done") is None  # wizard never ran
    assert tracker.data.get("setup_attempted") is None


def test_install_config_files_keeps_existing_and_counts_downloads(monkeypatch, tmp_path):
    cfg = tmp_path / "mpv"
    (cfg / "scripts").mkdir(parents=True)
    (cfg / "mpv.conf").write_text("hwdec=vaapi-copy\n", encoding="utf-8")
    monkeypatch.setattr(sa, "get_mpv_config_dir", lambda: cfg)
    written = []
    _fake_downloader(monkeypatch, written)

    assert sa.install_config_files(quiet=True) is True
    assert written == ["input.conf", "freeflix_position.lua"]
    # A user-tuned mpv.conf is never overwritten.
    assert (cfg / "mpv.conf").read_text(encoding="utf-8") == "hwdec=vaapi-copy\n"


def test_install_anime4k_shaders_keeps_valid_and_repairs_corrupt(monkeypatch, tmp_path):
    cfg = tmp_path / "mpv"
    _write_complete_mpv_config(cfg)
    victim = cfg / "shaders" / "Anime4K_Restore_CNN_S.glsl"
    victim.write_bytes(b"<html>404 Not Found</html>" * 1000)  # big but not GLSL
    monkeypatch.setattr(sa, "get_mpv_config_dir", lambda: cfg)
    written = []
    _fake_downloader(monkeypatch, written)

    assert sa.install_anime4k_shaders(quiet=True) is True
    assert written == ["Anime4K_Restore_CNN_S.glsl"]
    assert sa._shader_ok(victim)


# ─── 2. Partial / interrupted setup: silent repair, no wizard loop ───
def test_partial_setup_repairs_silently_without_prompting(monkeypatch, tmp_path):
    cfg = tmp_path / "mpv"
    (cfg / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "config" / "mpv.conf", cfg / "mpv.conf")
    monkeypatch.setattr(sa, "get_mpv_config_dir", lambda: cfg)
    written = []
    _fake_downloader(monkeypatch, written)
    monkeypatch.setattr(sa, "ask_yes_no", _fail)

    assert sa.is_setup_complete() is False
    assert sa.run_setup(force=False) is True  # silent repair, no question

    assert "mpv.conf" not in written  # already present → never re-downloaded
    assert tracker.data.get("setup_done") is True
    assert sa.is_setup_complete() is True

    # Following launches are complete no-ops.
    written.clear()
    assert sa.run_setup(force=False) is False
    assert written == []


def test_wizard_failure_marks_attempted_then_repairs_silently(monkeypatch, tmp_path):
    cfg = tmp_path / "mpv"
    monkeypatch.setattr(sa, "get_mpv_config_dir", lambda: cfg)
    monkeypatch.setattr(sa, "detect_gpus", lambda: {
        "nvidia": False, "amd_discrete": False,
        "intel_integrated": False, "apple_silicon": False,
    })
    monkeypatch.setattr(sa, "_download_verified", lambda *a, **k: False)
    monkeypatch.setattr(sa, "_download", lambda *a, **k: False)
    monkeypatch.setattr(sa, "ask_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(sa, "install_chafa", lambda: True)
    monkeypatch.setattr(sa, "install_nerd_font", lambda: False)
    monkeypatch.setattr(sa, "install_flaresolverr", lambda: False)
    monkeypatch.setattr(sa, "install_prime_wrappers", lambda gpus: True)
    monkeypatch.setattr(sa, "_get_installed_version", lambda: "9.9.9")

    # First run: the wizard runs (user consents), the network fails.
    assert sa.run_setup(force=False) is False
    assert tracker.data.get("setup_attempted") is True
    assert tracker.data.get("setup_done") is False
    assert tracker.data.get("setup_failure_version") == "9.9.9"

    # Second run: NO prompt, NO wizard — only a silent retry.
    monkeypatch.setattr(sa, "ask_yes_no", _fail)
    assert sa.run_setup(force=False) is False

    # Network back: the silent pass finishes and never asks anything again.
    written = []
    _fake_downloader(monkeypatch, written)
    assert sa.run_setup(force=False) is True
    assert sa.is_setup_complete() is True
    assert tracker.data.get("setup_done") is True
    assert tracker.data.get("setup_attempted") is None
    assert written and "mpv.conf" in written

    written.clear()
    assert sa.run_setup(force=False) is False
    assert written == []


def test_setup_done_when_required_files_are_valid_despite_optional_failure(
        monkeypatch, tmp_path):
    """A failed *optional* (VL) shader must not keep setup_done False forever."""
    cfg = tmp_path / "mpv"
    monkeypatch.setattr(sa, "get_mpv_config_dir", lambda: cfg)
    monkeypatch.setattr(sa, "detect_gpus", lambda: {
        "nvidia": False, "amd_discrete": False,
        "intel_integrated": False, "apple_silicon": False,
    })
    monkeypatch.setattr(sa, "ask_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(sa, "install_chafa", lambda: True)
    monkeypatch.setattr(sa, "install_nerd_font", lambda: False)
    monkeypatch.setattr(sa, "install_flaresolverr", lambda: False)
    monkeypatch.setattr(sa, "install_prime_wrappers", lambda gpus: True)

    def downloads(url, dest, label=None):
        # Everything succeeds except the optional VL pair (e.g. a flaky CDN).
        if dest.name in sa._OPTIONAL_SHADERS:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.name in sa._ALL_SHADERS:
            dest.write_bytes(_shader_bytes(dest.name))
        else:
            dest.write_bytes((ROOT / "config" / dest.name).read_bytes())
        return True

    monkeypatch.setattr(sa, "_download_verified", downloads)

    # The wizard still reports success: the player is fully usable.
    assert sa.run_setup(force=True) is True
    assert tracker.data.get("setup_done") is True
    assert sa.is_setup_complete() is True
    # Next launch: complete → instant no-op (no download, no prompt).
    monkeypatch.setattr(sa, "ask_yes_no", _fail)
    monkeypatch.setattr(sa, "_download_verified", _fail)
    assert sa.run_setup(force=False) is False


# ─── 3. "Installed but asked to install again" ───────────────────────
def test_media_player_present_is_not_reinstalled_nor_asked(monkeypatch):
    monkeypatch.setattr(sa, "_player_available", lambda name: True)
    monkeypatch.setattr(sa, "ask_yes_no", _fail)
    monkeypatch.setattr(sa.subprocess, "run", _fail)
    assert sa.install_media_player("mpv") is True
    assert sa.install_media_player("vlc") is True


def test_windows_players_present_are_not_reinstalled(monkeypatch):
    monkeypatch.setattr(sa, "detect_os", lambda: "windows")
    monkeypatch.setattr(
        sa.shutil, "which", lambda n: "winget" if n == "winget" else None)
    monkeypatch.setattr(sa, "_player_available", lambda name: True)
    monkeypatch.setattr(sa.subprocess, "run", _fail)
    assert sa.install_windows_players() is True


def test_nerd_font_marker_prevents_redownload(monkeypatch):
    tracker.data["nerd_font_installed"] = True
    monkeypatch.setattr(sa, "detect_nerd_font", lambda: False)
    monkeypatch.setattr(sa, "_nerd_font_files_present", lambda: False)
    monkeypatch.setattr(sa, "_download", _fail)
    assert sa.install_nerd_font() is True


@POSIX_ONLY
def test_nerd_font_detected_from_disk_when_fc_list_fails(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("fc-list missing")

    monkeypatch.setattr(sa.subprocess, "run", boom)
    monkeypatch.setattr(sa, "_nerd_font_files_present", lambda: True)
    assert sa.detect_nerd_font() is True


def test_declined_dependency_install_is_not_asked_every_launch(monkeypatch):
    monkeypatch.setattr(sa, "_get_installed_version", lambda: "2.4.4")
    monkeypatch.setattr(sa.shutil, "which",
                        lambda n: "/usr/bin/dnf" if n == "dnf" else None)

    class _TTY:
        def isatty(self):
            return True

    monkeypatch.setattr(sa.sys, "stdin", _TTY())

    # First launch: asked once, user says no → remembered for this version.
    monkeypatch.setattr(sa, "ask_yes_no", lambda *a, **k: False)
    assert sa._linux_install_missing(["player"]) is False
    assert tracker.data.get("deps_declined_version") == "2.4.4"

    # Second launch: no question at all.
    monkeypatch.setattr(sa, "ask_yes_no", _fail)
    assert sa._linux_install_missing(["player"]) is False


@POSIX_ONLY
def test_prime_wrapper_never_clobbers_foreign_mpv(monkeypatch, tmp_path):
    bindir = tmp_path / ".local" / "bin"
    bindir.mkdir(parents=True)
    foreign = bindir / "mpv"
    foreign.write_text("#!/bin/sh\n# my own wrapper\n", encoding="utf-8")

    # The wrapper resolves the real mpv by walking PATH: give it one (the CI
    # runner has no mpv, which is not what this test is about).
    sysbin = tmp_path / "sysbin"
    sysbin.mkdir()
    real = sysbin / "mpv"
    real.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    real.chmod(0o755)
    monkeypatch.setenv("PATH", f"{sysbin}{os.pathsep}{bindir}{os.pathsep}"
                                + os.environ.get("PATH", ""))

    monkeypatch.setattr(sa, "get_local_bin_dir", lambda: bindir)
    monkeypatch.setattr(sa.shutil, "which",
                        lambda n: str(sysbin / n) if n in ("sudo", "mpv") else None)
    monkeypatch.setattr(sa, "ask_yes_no", _fail)

    assert sa.install_prime_wrappers({"nvidia": True, "amd_discrete": False}) is True
    assert foreign.read_text(encoding="utf-8") == "#!/bin/sh\n# my own wrapper\n"


def test_two_full_launches_with_everything_installed_are_silent(monkeypatch, tmp_path):
    """End-to-end launch gate: launch #2 must not download, ask or install."""
    cfg = tmp_path / "mpv"
    _write_complete_mpv_config(cfg)
    monkeypatch.setattr(sa, "get_mpv_config_dir", lambda: cfg)
    monkeypatch.setattr(sa, "_download_verified", _fail)
    monkeypatch.setattr(sa, "_download", _fail)
    monkeypatch.setattr(sa, "ask_yes_no", _fail)
    monkeypatch.setattr(sa, "runtime_ready", lambda: True)
    monkeypatch.setattr(sa, "_get_installed_version", lambda: "2.4.4")
    # Nothing was ever attempted / declined: a complete config dir is enough.
    monkeypatch.setattr(sa, "_nerd_font_files_present", lambda: True)
    monkeypatch.setattr(sa, "detect_nerd_font", lambda: True)

    for _launch in range(2):
        assert sa.ensure_runtime_deps() is True
        sa.maybe_default_nerd_icons()
        if sa.should_prompt_setup():
            sa.run_setup(force=False)
        sa.run_pending_migrations("2.4.4")

    assert tracker.data.get("setup_done") is None  # wizard never opened
    assert tracker.data.get("system_deps_ok") is True
    assert tracker.data.get("system_deps_ok_version") == "2.4.4"


def test_managed_mpv_counts_as_installed(monkeypatch):
    """A player FreeFlix downloaded itself must not be reported missing."""
    bdir = sa._bin_dir()
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "mpv").write_text("", encoding="utf-8")
    monkeypatch.setattr(sa.shutil, "which", lambda name: None)
    monkeypatch.setattr(sa, "ask_yes_no", _fail)
    monkeypatch.setattr(sa.subprocess, "run", _fail)

    assert sa._player_available("mpv") is True
    assert sa.install_media_player("mpv") is True


@POSIX_ONLY
def test_prime_wrapper_execs_the_real_mpv_from_path(tmp_path):
    """The wrapper must not hard-code /usr/bin/mpv (breaks Nix/snap/usr-local)."""
    source = ROOT / "scripts" / "wrappers" / "mpv"
    assert '/usr/bin/mpv "$@"' not in source.read_text(encoding="utf-8")

    wrapper_dir = tmp_path / "bin"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "mpv"
    shutil.copy(source, wrapper)
    wrapper.chmod(0o755)
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = real_dir / "mpv"
    real.write_text("#!/bin/sh\necho REAL_MPV_USED\n", encoding="utf-8")
    real.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{wrapper_dir}:{real_dir}:/usr/bin:/bin"
    result = subprocess.run([str(wrapper)], env=env, capture_output=True,
                            text=True, timeout=30)
    assert "REAL_MPV_USED" in result.stdout


@LINUX_ONLY
def test_flatpak_player_counts_as_installed(monkeypatch):
    """Flatpak installs have no PATH binary: they must not look "missing"."""
    monkeypatch.setattr(
        sa.shutil, "which",
        lambda n: "/usr/bin/flatpak" if n == "flatpak" else None)
    monkeypatch.setattr(
        sa, "_flatpak_app_present", lambda app_id: app_id == "org.videolan.VLC")
    monkeypatch.setattr(sa, "ask_yes_no", _fail)
    monkeypatch.setattr(sa.subprocess, "run", _fail)

    assert sa._have(("mpv", "vlc")) is True
    assert sa.install_media_player("vlc") is True


@LINUX_ONLY
def test_flatpak_player_gets_a_managed_launcher(monkeypatch):
    monkeypatch.setattr(sa, "detect_os", lambda: "linux")
    monkeypatch.setattr(
        sa.shutil, "which",
        lambda n: "/usr/bin/flatpak" if n == "flatpak" else None)
    monkeypatch.setattr(
        sa, "_flatpak_app_present", lambda app_id: app_id == "io.mpv.Mpv")

    assert sa.install_flatpak_shims() is True
    shim = sa._managed_bin("mpv")
    assert shim.is_file()
    assert "flatpak run io.mpv.Mpv" in shim.read_text(encoding="utf-8")
    # Second pass is a no-op (idempotent).
    assert sa.install_flatpak_shims() is False
    # And the player now resolves through the managed dir — no false prompt.
    assert sa._player_available("mpv") is True


# ─── 4. Post-upgrade migrations run once (no replay) ─────────────────
def test_pending_migrations_run_once_and_record_version(monkeypatch):
    tracker.data["last_setup_version"] = "1.0.0"
    calls = []

    def action():
        calls.append("ran")

    monkeypatch.setattr(sa, "_migrations", lambda: [("1.5.7", "desc", action)])
    monkeypatch.setattr(sa, "print_info", lambda *a, **k: None)

    sa.run_pending_migrations("2.4.4")
    assert calls == ["ran"]
    assert tracker.data.get("last_setup_version") == "2.4.4"

    sa.run_pending_migrations("2.4.4")
    assert calls == ["ran"]  # not replayed


def test_interrupted_migration_does_not_replay_every_launch(monkeypatch):
    tracker.data["last_setup_version"] = "1.0.0"

    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(sa, "_migrations",
                        lambda: [("1.5.7", "desc", interrupted)])
    monkeypatch.setattr(sa, "print_info", lambda *a, **k: None)

    sa.run_pending_migrations("2.4.4")  # must not raise / not lose the version
    assert tracker.data.get("last_setup_version") == "2.4.4"


# ─── 5. --doctor: managed/system binaries + optional services ────────
def test_doctor_managed_binary_falls_back_to_system(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_managed_bin_dir", lambda: tmp_path / "bin")
    monkeypatch.setattr(
        doctor.shutil, "which",
        lambda n: "/usr/bin/ffmpeg" if n == "ffmpeg" else None)

    status, _info, path = doctor._check_managed_bin("ffmpeg", "ffmpeg")
    assert status == "SYSTEM"
    assert path == "/usr/bin/ffmpeg"


@POSIX_ONLY
def test_doctor_binary_finds_managed_copy_not_on_path(monkeypatch, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "ffmpeg"
    exe.write_text("#!/bin/sh\necho 'ffmpeg version 7.1.1'\n", encoding="utf-8")
    exe.chmod(0o755)

    monkeypatch.setattr(sa, "_managed_bin", lambda n: bindir / n)
    monkeypatch.setattr(doctor.shutil, "which", lambda n: None)

    status, info, path = doctor._check_binary("ffmpeg", "ffmpeg")
    assert status == "OK"
    assert "managed" in info
    assert path == str(exe)


def test_doctor_mpv_config_covers_every_installed_file(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_mpv_config_dir", lambda: tmp_path)
    names = {entry["name"] for entry in doctor._check_mpv_config()}
    for name in doctor._MPV_SHADERS + ("mpv.conf", "input.conf"):
        assert name in names
    assert "freeflix_position.lua" in names


def test_doctor_flaresolverr_absent_is_not_an_error(monkeypatch):
    def refused(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", refused)
    status = doctor._check_flaresolverr("http://127.0.0.1:8191")
    assert status == "NOT RUNNING (optional)"


def test_doctor_version_comparison_flags_old_tools():
    assert doctor._version_status("ffmpeg", "ffmpeg version 4.4.2") == "OLD"
    assert doctor._version_status("ffmpeg", "ffmpeg version 7.1.1") is None
    assert doctor._version_status("mpv", "mpv v0.41.0") is None
    assert doctor._version_status("inconnu", "v1") is None


def test_install_health_hint_matches_the_installer(monkeypatch):
    monkeypatch.setattr(
        install_health, "module_file",
        lambda: "/home/u/.local/share/uv/tools/freeflix-cli/lib/site-packages/"
                "freeflix_cli/__init__.py")
    assert install_health.installer_kind() == "uv"
    assert "uv tool uninstall" in install_health.cleanup_hint()

    monkeypatch.setattr(
        install_health, "module_file",
        lambda: "/home/u/.local/pipx/venvs/freeflix-cli/lib/python3.12/"
                "site-packages/freeflix_cli/__init__.py")
    assert install_health.installer_kind() == "pipx"
    assert "pipx uninstall" in install_health.cleanup_hint()

    monkeypatch.setattr(install_health, "installer_kind", lambda: "frozen")
    assert "GitHub Releases" in install_health.cleanup_hint()


# ─── 6. Shell installers: syntax + real double-run harness ───────────
@POSIX_ONLY
def test_shell_installers_are_syntactically_valid():
    for script in ("scripts/install.sh", "scripts/install-mac.sh"):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / script)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script}: {result.stderr}"


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _fake_install_env(tmp_path: Path):
    """Fake distro tools so scripts/install.sh can be run twice, offline."""
    fake = tmp_path / "fakebin"
    fake.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    calls = tmp_path / "calls.log"
    calls.write_text("", encoding="utf-8")
    try:
        project_version = re.search(
            r'^version = "([^"]+)"',
            (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
            re.M).group(1)
    except Exception:
        project_version = "0"
    env = {
        "HOME": str(tmp_path / "home"),
        "SHELL": "/bin/bash",
        "PATH": f"{fake}:/usr/bin:/bin",
        "FAKE_STATE": str(state),
        "FAKE_CALLS": str(calls),
        # The installer skips a reinstall when `uv tool list` reports the
        # pyproject version: keep the fake in sync so a version bump in the
        # repo does not look like "needs reinstall".
        "FAKE_VERSION": project_version,
        # Pin a distro so the dnf fake is valid on every runner (the test used
        # to assume Fedora and failed on Ubuntu CI).
        "FREEFLIX_DISTRO_OVERRIDE": "fedora",
    }
    (tmp_path / "home").mkdir()

    # sudo → run the command directly (the fake dnf/apt never needs root).
    _write_executable(fake / "sudo", 'exec "$@"\n')
    # rpm -q <pkg> → succeeded iff the fake dnf "installed" it before.
    _write_executable(fake / "rpm", """
state="$FAKE_STATE"
for a in "$@"; do
  case "$a" in -*) continue;; esac
  [ -e "$state/$a" ] || exit 1
done
exit 0
""")
    # dnf install -y <pkg> → remember the package (so run #2 skips it).
    _write_executable(fake / "dnf", """
printf 'dnf %s\\n' "$*" >> "$FAKE_CALLS"
eval last=\\${$#}
touch "$FAKE_STATE/$last"
exit 0
""")
    # curl: log every call; `-o file` writes a plausible payload, else fails
    # (the FlareSolverr health probe).
    _write_executable(fake / "curl", """
printf 'curl %s\\n' "$*" >> "$FAKE_CALLS"
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) shift ;;
  esac
done
if [ -n "$out" ]; then
  mkdir -p "$(dirname "$out")"
  printf '//!DESC fake shader\\nxxxxxxxx\\n' > "$out"
  exit 0
fi
exit 1
""")
    # uv: `tool list` reports what `tool install` marked as installed.
    _write_executable(fake / "uv", """
printf 'uv %s\\n' "$*" >> "$FAKE_CALLS"
case "$*" in
  "tool list")
    if [ -e "$FAKE_STATE/uv-tool-freeflix" ]; then
      echo "freeflix-cli v${FAKE_VERSION:?}"
      echo "- freeflix"
    fi
    ;;
  tool\\ install*) touch "$FAKE_STATE/uv-tool-freeflix" ;;
esac
exit 0
""")
    _write_executable(fake / "fc-list", "exit 0\n")
    _write_executable(fake / "fc-cache", "exit 0\n")
    _write_executable(fake / "unzip", """
printf 'unzip %s\\n' "$*" >> "$FAKE_CALLS"
dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    -d) dir="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[ -n "$dir" ] && mkdir -p "$dir" && touch "$dir/CaskaydiaCoveNerdFont-Regular.ttf"
exit 0
""")
    return env, fake, state, calls


@POSIX_ONLY
def test_install_sh_is_idempotent_and_never_redownloads(tmp_path):
    env, _fake, _state, calls = _fake_install_env(tmp_path)
    script = str(ROOT / "scripts" / "install.sh")

    first = subprocess.run(
        ["bash", script], env=env, capture_output=True, text=True,
        timeout=180, stdin=subprocess.DEVNULL)
    assert first.returncode == 0, first.stdout + first.stderr
    first_calls = calls.read_text(encoding="utf-8").splitlines()

    # Tune the config to prove a second run must not overwrite it.
    mpv_conf = tmp_path / "home" / ".config" / "freeflix" / "mpv" / "mpv.conf"
    assert mpv_conf.is_file()
    mpv_conf.write_text("hwdec=vaapi-copy  # USER TUNED\n", encoding="utf-8")
    calls.write_text("", encoding="utf-8")

    second = subprocess.run(
        ["bash", script], env=env, capture_output=True, text=True,
        timeout=180, stdin=subprocess.DEVNULL)
    assert second.returncode == 0, second.stdout + second.stderr
    second_calls = calls.read_text(encoding="utf-8").splitlines()

    # 1. No package manager install on the second run.
    assert not [c for c in second_calls if c.startswith("dnf ")]
    assert len([c for c in first_calls if c.startswith("dnf ")]) > 0
    # 2. No shader re-download on the second run.
    assert not [c for c in second_calls
                if c.startswith("curl ") and "Anime4K" in c]
    # 3. No freeflix reinstall on the second run.
    assert not [c for c in second_calls if "tool install" in c]
    # 4. The user's tuned config survives.
    assert "USER TUNED" in mpv_conf.read_text(encoding="utf-8")


@POSIX_ONLY
def test_install_py_reuses_installed_tools(tmp_path):
    """A second install.py run must upgrade (no-op) instead of re-downloading."""
    fake = tmp_path / "fakebin"
    fake.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    calls = tmp_path / "calls.log"
    calls.write_text("", encoding="utf-8")
    _write_executable(fake / "uv", """
printf 'uv %s\\n' "$*" >> "$FAKE_CALLS"
case "$*" in
  "tool list")
    [ -e "$FAKE_STATE/freeflix-cli" ] && echo "freeflix-cli v2.4.4"
    [ -e "$FAKE_STATE/yt-dlp" ] && echo "yt-dlp v2025.9.5"
    ;;
  "tool upgrade "*) exit 0 ;;
  tool\\ install*)
    for a in "$@"; do case "$a" in freeflix-cli|yt-dlp) touch "$FAKE_STATE/$a";; esac; done
    ;;
esac
exit 0
""")
    _write_executable(fake / "freeflix", "exit 0\n")
    try:
        project_version = re.search(
            r'^version = "([^"]+)"',
            (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
            re.M).group(1)
    except Exception:
        project_version = "0"
    env = {
        "HOME": str(tmp_path / "home"),
        "SHELL": "/bin/bash",
        "PATH": f"{fake}:/usr/bin:/bin",
        "FAKE_STATE": str(state),
        "FAKE_CALLS": str(calls),
        # The installer skips a reinstall when `uv tool list` reports the
        # pyproject version: keep the fake in sync so a version bump in the
        # repo does not look like "needs reinstall".
        "FAKE_VERSION": project_version,
        # Pin a distro so the dnf fake is valid on every runner (the test used
        # to assume Fedora and failed on Ubuntu CI).
        "FREEFLIX_DISTRO_OVERRIDE": "fedora",
    }
    (tmp_path / "home").mkdir()
    installer = str(ROOT / "scripts" / "install.py")

    first = subprocess.run(
        [sys.executable, installer], env=env, capture_output=True, text=True,
        timeout=120)
    assert first.returncode == 0, first.stdout + first.stderr
    assert len([c for c in calls.read_text().splitlines() if "tool install" in c]) == 2
    assert "--force" not in first.stdout and "--force" not in first.stderr

    calls.write_text("", encoding="utf-8")
    second = subprocess.run(
        [sys.executable, installer], env=env, capture_output=True, text=True,
        timeout=120)
    second_calls = calls.read_text(encoding="utf-8").splitlines()
    assert second.returncode == 0, second.stdout + second.stderr
    assert not [c for c in second_calls if "tool install" in c]
    assert len([c for c in second_calls if "tool upgrade" in c]) == 2
    assert "already installed" in second.stdout


def test_windows_installer_avoids_forced_reinstalls_and_stderr_traps():
    ps = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    # Native stderr must not terminate the script under $ErrorActionPreference Stop.
    assert "Invoke-Native" in ps
    assert "PSNativeCommandUseErrorActionPreference" in ps
    assert "2>$null" not in ps
    # Already-installed tools are upgraded (no-op) instead of force-reinstalled.
    assert "uv tool upgrade" in ps
    assert "uv tool install freeflix-cli --force" not in ps
    assert "uv tool install yt-dlp --force" not in ps
    # Every winget candidate is probed for presence before being installed.
    assert "Test-Tool" in ps
