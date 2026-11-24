"""freeflix doctor — system diagnostic."""

from __future__ import annotations

import json
import locale
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _os() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform in ("win32", "cygwin"):
        return "windows"
    return sys.platform


def _version() -> str:
    try:
        import importlib.metadata as _im

        return _im.version("freeflix-cli")
    except Exception:
        return "dev"


def _fmt_size(path: Path) -> str:
    try:
        b = path.stat().st_size
        if b < 1024:
            return f"{b} B"
        if b < 1024**2:
            return f"{b / 1024:.1f} KB"
        return f"{b / 1024**2:.1f} MB"
    except OSError:
        return "?"


# Most tools print their version with `--version`; ffmpeg only accepts
# `-version` (it exits 8 on the double-dash form, which used to be reported
# as BROKEN even on a perfectly healthy install).
_VERSION_FLAGS = {
    "ffmpeg": "-version",
    "ffprobe": "-version",
}


def _managed_bin_dir() -> Path:
    """FreeFlix's self-managed binary dir (same one setup_assistant uses)."""
    from platformdirs import user_data_dir

    return Path(user_data_dir("freeflix-cli", "PaulExplorer")) / "bin"


def _probe_binary(path: str, name: str) -> tuple[str, str]:
    """Run ``<path> --version`` and return (status, first output line)."""
    try:
        flag = _VERSION_FLAGS.get(Path(name).name.lower(), "--version")
        out = subprocess.run(
            [path, flag], capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        ver = (out.stdout or out.stderr or "").splitlines()[0].strip()
        # An existing shim can still be broken (stale uv/pip env).
        return ("OK" if out.returncode == 0 and ver else "BROKEN", ver)
    except Exception:
        return ("BROKEN", "—")


# FreeFlix minimums : below these, playback/Anime4K/posters degrade (or fail
# outright). --doctor compares the parsed version so "installed but ancient"
# is reported as OLD instead of a misleading OK.
_MIN_VERSIONS = {
    "mpv": (0, 37),
    "ffmpeg": (5, 0),
    "yt-dlp": (2023, 1, 1),
    "aria2c": (1, 36),
    "chafa": (1, 10),
    "vlc": (3, 0),
}


def _parse_version(text: str) -> tuple:
    m = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", text or "")
    if not m:
        return ()
    return tuple(int(g) for g in m.groups() if g is not None)


def _version_status(name: str, ver: str) -> str | None:
    """'OLD' when the reported version is below the FreeFlix minimum."""
    minimum = _MIN_VERSIONS.get(Path(name).name.lower())
    got = _parse_version(ver)
    if not minimum or not got:
        return None
    return "OLD" if got < minimum else None


def _check_binary(label: str, *names: str) -> tuple[str, str, str]:
    """PATH first, then FreeFlix's managed dir — what the app actually uses.

    Reporting MISSING for a tool that is installed in the managed bin dir was
    misleading: the app resolves those binaries and playback works fine.
    """
    for n in names:
        path = shutil.which(n)
        if path:
            status, ver = _probe_binary(path, n)
            return (status, ver, path)
    if _os() == "windows":
        # winget installs shims here but only refreshes PATH for future
        # processes; a doctor run from a shell started before the install
        # otherwise reports MISSING for a working tool.
        links = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Microsoft", "WinGet", "Links")
        for n in names:
            cand = Path(links) / (n if n.lower().endswith(".exe") else n + ".exe")
            if cand.is_file():
                status, ver = _probe_binary(str(cand), n)
                return (status, ver, str(cand))
    try:
        from .setup_assistant import _managed_bin
        for n in names:
            cand = _managed_bin(n)
            for c in (cand, Path(str(cand) + ".exe")):
                if c.is_file():
                    status, ver = _probe_binary(str(c), n)
                    return (status, ver + " (managed)", str(c))
    except Exception:
        pass
    return ("MISSING", "—", "—")


def _check_managed_bin(label: str, name: str) -> tuple[str, str, str]:
    """Status of the managed copy, with the SYSTEM binary as a fallback.

    "MISSING" is only reported when neither the managed copy nor a system
    install exists — otherwise it read as "ffmpeg missing" on a working box.
    """
    bdir = _managed_bin_dir()
    exe = f"{name}.exe" if _os() == "windows" else name
    path = bdir / exe
    if path.is_file():
        status, ver = _probe_binary(str(path), name)
        return (status, ver or _fmt_size(path), str(path))
    system = shutil.which(name)
    if system:
        return ("SYSTEM", "—", system)
    return ("MISSING", "—", "—")


_MPV_CONFIG_FILES = (
    "mpv.conf",
    "input.conf",
    "scripts/freeflix_position.lua",
)
_MPV_SHADERS = (
    "Anime4K_Clamp_Highlights.glsl",
    "Anime4K_Restore_CNN_S.glsl",
    "Anime4K_Upscale_CNN_x2_S.glsl",
    "Anime4K_Restore_CNN_VL.glsl",
    "Anime4K_Upscale_CNN_x2_VL.glsl",
)


def _check_mpv_config() -> list[dict]:
    """Every file the setup installs — not a subset.

    The old list skipped the two VL shaders, so the report claimed the config
    was fine while CTRL+1 ("max" Anime4K) silently had nothing to load.
    """
    results = []
    cfg_dir = _mpv_config_dir()
    expected = [(Path(n).name, cfg_dir / n) for n in _MPV_CONFIG_FILES]
    expected += [(n, cfg_dir / "shaders" / n) for n in _MPV_SHADERS]
    for name, path in expected:
        if path.is_file() and path.stat().st_size > 0:
            status = "OK"
        elif path.is_file():
            status = "EMPTY"
        else:
            status = "MISSING"
        size = _fmt_size(path) if path.is_file() else "—"
        results.append(
            {"name": name, "status": status, "size": size, "path": str(path)}
        )
    return results


def _mpv_config_dir() -> Path:
    """FreeFlix's dedicated mpv config dir (what the player actually reads).

    Imported lazily: setup_assistant is heavy and doctor must stay fast, but
    duplicating the path here is how the report ended up inspecting the
    user's *global* ~/.config/mpv and calling it MISSING/OK by mistake.
    """
    try:
        from .setup_assistant import get_mpv_config_dir
        return Path(get_mpv_config_dir())
    except Exception:
        if _os() == "windows":
            return Path(os.environ.get("APPDATA", "")) / "freeflix" / "mpv"
        return Path.home() / ".config" / "freeflix" / "mpv"


def _check_connectivity(host: str, port: int = 443, timeout: int = 5) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "REACHABLE"
    except OSError:
        return "UNREACHABLE"


def _check_flaresolverr(url: str | None = None) -> str:
    if not url:
        return "DISABLED"
    import urllib.error
    import urllib.request

    base = url.rstrip("/")
    for path in (base + "/health", base + "/"):
        try:
            req = urllib.request.Request(path, method="GET")
            with urllib.request.urlopen(req, timeout=5) as r:
                return f"HEALTHY ({r.status})" if r.status < 500 else f"UNHEALTHY ({r.status})"
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return f"HEALTHY ({exc.code})"
        except Exception:
            continue
    # Optional service: "not running" is normal, not an error to scare the user.
    return "NOT RUNNING (optional)"


def _detect_distro() -> str:
    os_rel = Path("/etc/os-release")
    if os_rel.is_file():
        data = os_rel.read_text()
        m = re.search(r'^PRETTY_NAME="?(.+?)"?$', data, re.MULTILINE)
        if m:
            return m.group(1)
        m = re.search(r'^ID="?(.+?)"?$', data, re.MULTILINE)
        if m:
            return m.group(1)
    if _os() == "macos":
        try:
            out = subprocess.run(
                ["sw_vers", "-productVersion"],
                capture_output=True,
                text=True,
                timeout=5,
                encoding="utf-8", errors="replace",
            )
            return f"macOS {out.stdout.strip()}"
        except Exception:
            return "macOS"
    if _os() == "windows":
        try:
            out = subprocess.run(
                ["cmd", "/c", "ver"], capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            return out.stdout.strip()
        except Exception:
            return "Windows"
    return "unknown"


def _python_info() -> str:
    return f"{sys.version.split()[0]} ({sys.executable})"

# ═════════════════════════════════════════════════════════════════════
# SHAREABLE DIAGNOSTIC ENGINE
#
# Design rules (the report is now the ONE thing we ask a user for):
#   * every check is isolated: one failure never kills the report ;
#   * every network/subprocess probe is bounded by a timeout ;
#   * nothing is interactive, nothing writes to the user's app data ;
#   * no token/password value is ever printed (presence only) ;
#   * output is plain ASCII at <= 78 columns (cp1252-safe on Windows).
# ═════════════════════════════════════════════════════════════════════

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
INFO = "INFO"
SKIP = "SKIP"
ERROR = "ERROR"

_BAD = (FAIL, ERROR)

_REPORT_WIDTH = 78

_ISSUES_URL = "https://github.com/freedy237/freeflix-cli/issues"

# Section order shown in the report (and used by the VERDICT block).
_SECTIONS = (
    ("install", "INSTALL"),
    ("system", "SYSTEM"),
    ("config", "CONFIG & DISK"),
    ("binaries", "BINARIES"),
    ("players", "PLAYERS (mpv / vlc)"),
    ("mpv", "MPV CONFIG & SHADERS"),
    ("proxy", "LOCAL PROXY"),
    ("network", "NETWORK"),
    ("sources", "SOURCES & STREAMS"),
    ("terminal", "TERMINAL & IMAGES"),
    ("logs", "LOGS"),
    ("state", "STATE & CACHE"),
    ("windows", "WINDOWS"),
)

_PREFIX = {
    "install": "INS",
    "system": "SYS",
    "config": "CFG",
    "binaries": "BIN",
    "players": "PLY",
    "mpv": "MPV",
    "proxy": "PXY",
    "network": "NET",
    "sources": "SRC",
    "terminal": "TRM",
    "logs": "LOG",
    "state": "STA",
    "windows": "WIN",
}


# ── tiny helpers ─────────────────────────────────────────────────────
def _one_line(value) -> str:
    """Collapse any value to a single sanitised line (never raises)."""
    try:
        text = str(value)
    except Exception:
        return "?"
    text = text.replace("\r", " ").replace("\n", " / ").replace("\t", " ")
    return re.sub(r"\s{2,}", " ", text).strip()


def _pretty(text: str) -> str:
    """Collapse to one line and shorten the home dir to ``~``.

    Long absolute paths were the main reason report lines wrapped mid-word;
    ``~/...`` keeps them readable at 80 columns without hiding the location.
    """
    value = _one_line(text)
    try:
        home = str(Path.home())
        if home and home != "/" and len(home) > 1:
            value = value.replace(home, "~")
    except Exception:
        pass
    return value


def _entry(section: str, label: str, status: str, detail: str = "",
           action: str = "") -> dict:
    return {
        "section": section,
        "label": _one_line(label),
        "status": str(status).upper(),
        "detail": _pretty(detail),
        "action": _pretty(action),
    }


def _timed(fn, timeout: float):
    """Run ``fn()`` in a daemon thread; raise TimeoutError after *timeout* s.

    Plain ``ThreadPoolExecutor`` is deliberately NOT used: its atexit hook
    joins worker threads, so a DNS call stuck in the OS resolver would hang
    the whole ``--doctor`` process even after the timeout "fired".
    """
    import threading as _th

    box: dict = {}

    def _worker():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - reported as a failed check
            box["error"] = exc

    th = _th.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f"no answer within {timeout:g}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _stdout_isatty() -> bool:
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def _human_bytes(n) -> str:
    try:
        value = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return "?"


def _code_version() -> str:
    try:
        from .install_health import CODE_VERSION
        return str(CODE_VERSION)
    except Exception:
        return "?"


def _tracker():
    from .tracker import tracker
    return tracker


def _config_dir() -> Path:
    if _os() == "windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / "freeflix"
    return Path.home() / ".config" / "freeflix"


def _app_paths() -> dict:
    """Every path FreeFlix reads/writes, resolved exactly like the app does."""
    from platformdirs import user_cache_dir, user_data_dir

    root_data = Path(user_data_dir("AutoFlixCLI", "PaulExplorer"))
    root_cache = Path(user_cache_dir("freeflix-cli", "PaulExplorer"))
    covers_cache = Path(user_cache_dir("AutoFlixCLI", "PaulExplorer"))
    paths = {
        "data": root_data,
        "progress": root_data / "progress.json",
        "cache": root_cache,
        "http_cache": root_cache / "http",
        "recent": root_cache / "recent_releases.json",
        "covers": covers_cache / "covers",
        "config": _config_dir(),
        "mpv": _mpv_config_dir(),
        "managed_bins": _managed_bin_dir(),
        "portal_override": _config_dir() / "source_portal.jsonc",
    }
    try:
        from .logsetup import LOG_FILE
        paths["log"] = Path(LOG_FILE)
    except Exception:
        paths["log"] = root_cache / "freeflix.log"
    paths["log_dir"] = paths["log"].parent
    try:
        from .player_manager import DOWNLOAD_DIR, TEMP_DIR
        paths["downloads"] = Path(DOWNLOAD_DIR)
        paths["downloads_temp"] = Path(TEMP_DIR)
    except Exception:
        try:
            from platformdirs import user_downloads_dir
            base = user_downloads_dir()
        except Exception:
            base = os.path.expanduser("~/Downloads")
        paths["downloads"] = Path(base) / "FreeFlix"
        paths["downloads_temp"] = paths["downloads"] / ".temp"
    return paths


def _nearest_existing(path: Path):
    """Closest existing ancestor of *path* (or None), without creating it."""
    try:
        current = Path(path)
        for _ in range(64):
            if current.exists():
                return current
            parent = current.parent
            if parent == current:
                return None
            current = parent
    except Exception:
        return None
    return None


def _dir_entry(section: str, label: str, path) -> dict:
    """Writable? Exists? Both answered without writing a single byte."""
    try:
        target = Path(path)
        if target.is_dir():
            if os.access(str(target), os.W_OK):
                return _entry(section, label, PASS, str(target))
            return _entry(
                section, label, FAIL, f"{target} (read-only)",
                _chmod_hint(target))
        parent = _nearest_existing(target)
        if parent is None:
            return _entry(
                section, label, WARN, f"{target} (no parent found)",
                f"create it manually: mkdir -p {target}")
        if os.access(str(parent), os.W_OK):
            return _entry(
                section, label, WARN,
                f"{target} (missing - created on first run)")
        return _entry(
            section, label, FAIL,
            f"{target} (cannot create: {parent} is read-only)",
            _chmod_hint(parent))
    except Exception as exc:  # noqa: BLE001 - a broken path cannot break doctor
        return _entry(section, label, ERROR,
                      f"{type(exc).__name__}: {exc}")


def _chmod_hint(path: Path) -> str:
    if _os() == "windows":
        escaped = str(path).replace("'", "''")
        return (f"icacls '{escaped}' /grant \"$env:USERNAME:(OI)(CI)F\" "
                "/T  (PowerShell)")
    escaped = str(path).replace('"', '\\"')
    return f'chown -R "$USER" "{escaped}" && chmod -R u+rwX "{escaped}"'


def _disk_entry(section: str, label: str, path) -> dict:
    """Free space on the filesystem that actually backs *path*."""
    try:
        target = _nearest_existing(Path(path))
        if target is None:
            return _entry(section, label, WARN, f"{path} (unknown volume)")
        usage = shutil.disk_usage(str(target))
        percent = (usage.used / usage.total * 100.0) if usage.total else 0.0
        detail = (f"{_human_bytes(usage.free)} free of "
                  f"{_human_bytes(usage.total)} ({percent:.0f}% used) on {target}")
        if usage.free < 300 * 1024 ** 2:
            return _entry(
                section, label, FAIL, detail,
                "free at least 2 GB: delete old downloads in "
                f"{_app_paths()['downloads']}")
        if usage.free < 2 * 1024 ** 3 or percent > 95:
            return _entry(
                section, label, WARN, detail,
                "downloads need room: free some space or move "
                f"{_app_paths()['downloads']}")
        return _entry(section, label, PASS, detail)
    except Exception as exc:  # noqa: BLE001
        return _entry(section, label, ERROR, f"{type(exc).__name__}: {exc}")


# ── OS / installer helpers ───────────────────────────────────────────
_WINGET_IDS = {
    "ffmpeg": "Gyan.FFmpeg",
    "ffprobe": "Gyan.FFmpeg",
    "mpv": "shinchiro.mpv",
    "vlc": "VideoLAN.VLC",
    "yt-dlp": "yt-dlp.yt-dlp",
    "aria2c": "aria2.aria2",
    "chafa": "hpjansson.Chafa",
    "uv": "astral-sh.uv",
    "gh": "GitHub.cli",
}

_LINUX_PKG = {
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffmpeg",
    "mpv": "mpv",
    "vlc": "vlc",
    "yt-dlp": "yt-dlp",
    "aria2c": "aria2",
    "chafa": "chafa",
    "uv": "uv",
    "gh": "gh",
}

_MAC_PKG = {
    "aria2c": "aria2",
    "aria2": "aria2",
}


def _linux_family() -> str:
    """Package manager family: apt | dnf | pacman | zypper | apk | unknown."""
    ident = ""
    try:
        for line in Path("/etc/os-release").read_text(
                encoding="utf-8", errors="replace").splitlines():
            if line.startswith("ID=") or line.startswith("ID_LIKE="):
                ident += " " + line.split("=", 1)[1].strip('"').lower()
    except Exception:
        pass
    if any(k in ident for k in ("debian", "ubuntu", "mint", "pop", "raspbian")):
        return "apt"
    if any(k in ident for k in ("fedora", "rhel", "centos", "rocky", "alma")):
        return "dnf"
    if "arch" in ident or "manjaro" in ident:
        return "pacman"
    if any(k in ident for k in ("suse", "opensuse")):
        return "zypper"
    if "alpine" in ident:
        return "apk"
    for binary, family in (("apt-get", "apt"), ("dnf", "dnf"),
                           ("pacman", "pacman"), ("zypper", "zypper"),
                           ("apk", "apk")):
        try:
            if shutil.which(binary):
                return family
        except Exception:
            continue
    return "unknown"


def _install_command(name: str) -> str:
    """The EXACT command this machine needs to install *name*."""
    key = Path(str(name)).name.lower()
    if _os() == "windows":
        package = _WINGET_IDS.get(key, key)
        return f"winget install --id {package} -e --accept-source-agreements"
    if _os() == "macos":
        package = _MAC_PKG.get(key, key)
        return f"brew install {package}"
    family = _linux_family()
    package = _LINUX_PKG.get(key, key)
    if family == "apt":
        return f"sudo apt install -y {package}"
    if family == "dnf":
        return f"sudo dnf install -y {package}"
    if family == "pacman":
        return f"sudo pacman -S --needed {package}"
    if family == "zypper":
        return f"sudo zypper install -y {package}"
    if family == "apk":
        return f"sudo apk add {package}"
    return f"install '{package}' with your package manager"


def _dns_hint() -> str:
    if _os() == "windows":
        return ("set DNS to 1.1.1.1 or 8.8.8.8 "
                "(Settings > Network > DNS), then: nslookup github.com")
    if _os() == "macos":
        return ("switch DNS or enable a VPN, then test: "
                "dscacheutil -q host -a name github.com")
    return ("switch DNS to 1.1.1.1 or enable a VPN, then test: "
            "getent hosts github.com")


def _setup_hint() -> str:
    return "freeflix --setup   (re-runs dependency setup)"


# ── log / directory helpers ──────────────────────────────────────────
def _tail_lines(path: Path, max_lines: int = 400,
                max_bytes: int = 256 * 1024) -> list:
    try:
        with open(str(path), "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            start = max(0, size - max_bytes)
            handle.seek(start)
            data = handle.read()
        lines = data.decode("utf-8", errors="replace").splitlines()
        if start > 0 and lines:
            lines = lines[1:]  # first line is very likely truncated
        return lines[-max_lines:]
    except OSError:
        return []
    except Exception:
        return []


def _dir_stats(path, max_entries: int = 4000) -> dict:
    """Recursive size/count, capped so a huge cache cannot stall the report."""
    total = 0
    count = 0
    truncated = False
    try:
        for root, _dirs, files in os.walk(str(path)):
            for name in files:
                count += 1
                if count > max_entries:
                    truncated = True
                    return {"bytes": total, "files": count, "truncated": truncated}
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    except OSError:
        pass
    except Exception:
        pass
    return {"bytes": total, "files": count, "truncated": truncated}


# ── INSTALL ──────────────────────────────────────────────────────────
def _install_mode_label() -> str:
    """Human label for HOW this FreeFlix runs (uv/pipx/pip/frozen/source)."""
    kind = "unknown"
    try:
        from .install_health import installer_kind
        kind = installer_kind()
    except Exception:
        pass
    if kind in ("uv", "pipx", "pip", "frozen"):
        return kind
    try:
        from .install_health import module_file
        path = (module_file() or "").replace("\\", "/").lower()
    except Exception:
        path = ""
    if "/src/freeflix_cli/" in path or path.endswith("/src/freeflix_cli/__init__.py"):
        return "source checkout (editable)"
    if "site-packages" in path or "dist-packages" in path:
        return "pip (site-packages)"
    return kind


def _bundle_data_entry(state: dict):
    """Match reference data (clubs + logos) bundled, or missing from the build.

    win-parity-2's install_health exposes ``bundle_data_ok`` /
    ``bundle_data_missing``: a standalone binary built without --collect-data
    silently loses translated club names and logos, so that must be visible.
    Older install_health versions lack the keys: then no line is added.
    """
    ok = state.get("bundle_data_ok")
    if ok is None:
        return None
    if ok:
        source = ""
        try:
            from .install_health import bundled_data_status
            statuses = bundled_data_status()
            sources = {entry.get("source") for entry in statuses.values()}
            if sources == {"cache"}:
                source = " - restored from cache by the auto-repair"
            elif "cache" in sources:
                source = " - partly restored from cache by the auto-repair"
        except Exception:
            pass
        return _entry("install", "match data", PASS,
                      f"OK (clubs + logos){source}")
    missing = list(state.get("bundle_data_missing") or [])
    names = ", ".join(str(name) for name in missing) or "unknown files"
    if state.get("frozen"):
        action = ("incomplete standalone build: download the latest release "
                  "(rebuilt with the data) - the auto-repair retries on next "
                  "launch")
    else:
        action = ("relaunch FreeFlix (the auto-repair fetches the data into "
                  "the user cache) or run: freeflix --setup")
    return _entry("install", "match data", WARN, f"MISSING: {names}", action)


def collect_install() -> list:
    out: list = []
    try:
        from . import install_health as ih

        state = ih.install_state()
    except Exception as exc:  # noqa: BLE001 - doctor must survive this
        return [_entry("install", "install health", ERROR,
                       f"{type(exc).__name__}: {exc}",
                       "report this issue with the full --doctor output")]

    mode = "frozen binary" if state.get("frozen") else "python package"
    out.append(_entry("install", "mode", PASS,
                      f"{mode}: {_install_mode_label()}"))
    out.append(_entry("install", "module", INFO,
                      state.get("module_file") or "(unknown)"))
    out.append(_entry("install", "code version", INFO,
                      str(state.get("code_version") or "?")))
    metadata = state.get("metadata_version")
    if state.get("mismatch"):
        out.append(_entry(
            "install", "metadata version", FAIL,
            f"{metadata} != code {state.get('code_version')}",
            _one_line(ih.cleanup_hint())))
    else:
        out.append(_entry("install", "metadata version", PASS,
                          str(metadata or "(none - source checkout)")))

    shims = list(state.get("shims") or [])
    if not shims:
        if state.get("frozen"):
            out.append(_entry("install", "launchers", INFO,
                              "not needed for a frozen binary"))
        else:
            out.append(_entry(
                "install", "launchers", WARN,
                "no 'freeflix' launcher found on PATH",
                'export PATH="$HOME/.local/bin:$PATH"  '
                "(then reopen the terminal)"))
    elif len(shims) > 1:
        out.append(_entry(
            "install", "launchers", WARN,
            f"{len(shims)} launchers shadow each other: {', '.join(shims[:4])}",
            "which -a freeflix ; remove the stale install ("
            + _one_line(ih.cleanup_hint()) + ")"))
    else:
        out.append(_entry("install", "launchers", PASS, shims[0]))

    bundle_entry = _bundle_data_entry(state)
    if bundle_entry is not None:
        out.append(bundle_entry)
    return out


# ── SYSTEM ───────────────────────────────────────────────────────────
def _encoding_entry() -> dict:
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    try:
        "é─→".encode(getattr(sys.stdout, "encoding", None) or "ascii")
        can_non_ascii = True
    except Exception:
        can_non_ascii = False
    label = f"{encoding or '?'}"
    if can_non_ascii and encoding.replace("-", "") in ("utf8", "utf8mb4"):
        return _entry("system", "encoding", PASS, f"{label} (UTF-8)")
    if _os() == "windows":
        action = "chcp 65001   (or run freeflix from Windows Terminal)"
    else:
        action = 'export LANG=C.UTF-8 LC_ALL=C.UTF-8  (add it to your shell rc)'
    if can_non_ascii:
        return _entry("system", "encoding", WARN,
                      f"{label} (not UTF-8; some glyphs may break)", action)
    return _entry("system", "encoding", WARN,
                  f"{label} (cannot encode non-ASCII characters)", action)


def _locale_entry() -> dict:
    env_locale = (os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE")
                  or os.environ.get("LANG") or "")
    try:
        current = ".".join(part for part in locale.getlocale() if part)
    except Exception:
        current = ""
    value = current or env_locale or "(unset)"
    if "utf-8" in value.lower() or "utf8" in value.lower():
        return _entry("system", "locale", PASS, value)
    if _os() == "windows":
        action = "set the console codepage: chcp 65001"
    else:
        action = 'export LANG=C.UTF-8 LC_ALL=C.UTF-8  (add it to your shell rc)'
    return _entry("system", "locale", WARN, value, action)


def _path_entry() -> dict:
    raw = os.environ.get("PATH") or ""
    parts = [part for part in raw.split(os.pathsep) if part]
    seen: set = set()
    duplicates: list = []
    missing = 0
    for part in parts:
        key = os.path.normcase(os.path.normpath(part))
        if key in seen:
            duplicates.append(part)
        seen.add(key)
        try:
            if not os.path.isdir(part):
                missing += 1
        except Exception:
            missing += 1
    if duplicates or missing:
        return _entry(
            "system", "PATH", WARN,
            f"{len(parts)} entries, {len(duplicates)} duplicate(s), "
            f"{missing} missing folder(s)",
            "clean PATH duplicates / stale entries in your shell rc")
    entry = _entry("system", "PATH", PASS,
                   f"{len(parts)} entries, no duplicates")
    entry["action"] = ""
    return entry


def _path_order_entry() -> dict:
    raw = os.environ.get("PATH") or "(unset)"
    return _entry("system", "PATH order", INFO, raw)


def collect_system() -> list:
    out: list = []
    try:
        out.append(_entry("system", "os", PASS,
                          f"{_detect_distro()} [{_os()}] "
                          f"{platform.machine()}"))
        out.append(_entry("system", "kernel", INFO, platform.release()))
        out.append(_entry("system", "cpu", INFO,
                          f"{os.cpu_count() or '?'} logical core(s)"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("system", "os", WARN,
                          f"{type(exc).__name__}: {exc}"))

    try:
        columns, rows = shutil.get_terminal_size(fallback=(0, 0))
        term = os.environ.get("TERM") or "(unset)"
        program = os.environ.get("TERM_PROGRAM") or ""
        tty = _stdout_isatty()
        detail = f"{term}"
        if program:
            detail += f" ({program})"
        detail += f" {columns}x{rows}"
        if not tty:
            detail += " [stdout is not a TTY]"
        out.append(_entry("system", "terminal", PASS if tty else INFO, detail))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("system", "terminal", INFO,
                          f"{type(exc).__name__}: {exc}"))

    try:
        out.append(_encoding_entry())
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("system", "encoding", WARN,
                          f"{type(exc).__name__}: {exc}"))
    try:
        out.append(_locale_entry())
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("system", "locale", WARN,
                          f"{type(exc).__name__}: {exc}"))

    version = sys.version_info
    python_detail = (f"{sys.version.split()[0]} ({sys.executable})")
    if version < (3, 9):
        out.append(_entry(
            "system", "python", FAIL, python_detail,
            "install Python 3.9+ then reinstall FreeFlix "
            "(see https://github.com/freedy237/freeflix-cli#install)"))
    else:
        out.append(_entry("system", "python", PASS, python_detail))
    frozen = bool(getattr(sys, "frozen", False))
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    out.append(_entry(
        "system", "python env", INFO,
        "frozen PyInstaller binary" if frozen
        else ("virtual environment" if in_venv else "system interpreter")))
    try:
        out.append(_entry("system", "install mode", INFO, _install_mode_label()))
    except Exception:
        pass

    try:
        out.append(_path_entry())
        out.append(_path_order_entry())
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("system", "PATH", WARN,
                          f"{type(exc).__name__}: {exc}"))

    try:
        out.append(_dir_entry("system", "home", Path.home()))
    except Exception:
        pass
    try:
        import tempfile
        out.append(_dir_entry("system", "temp dir",
                              os.environ.get("TMPDIR") or tempfile.gettempdir()))
    except Exception:
        pass
    try:
        paths = _app_paths()
        for label, key in (
            ("data dir", "data"),
            ("cache dir", "cache"),
            ("config dir", "config"),
            ("download dir", "downloads"),
            ("managed bins", "managed_bins"),
            ("log dir", "log_dir"),
        ):
            out.append(_dir_entry("system", label, paths[key]))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("system", "app dirs", WARN,
                          f"{type(exc).__name__}: {exc}"))
    return out


# ── CONFIG & DISK ────────────────────────────────────────────────────
def _progress_entry() -> list:
    out: list = []
    path = _app_paths()["progress"]
    try:
        if not path.is_file():
            return [_entry("config", "progress file", INFO,
                           f"{path} (not created yet - first run does it)")]
        from datetime import datetime as _dt
        stamp = _dt.fromtimestamp(path.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M")
        size = _fmt_size(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            return [_entry(
                "config", "progress file", FAIL,
                f"{path} is corrupt ({type(exc).__name__})",
                f'mv "{path}" "{path}.bak"   (FreeFlix then starts fresh)')]
        if not isinstance(data, dict):
            return [_entry(
                "config", "progress file", FAIL,
                f"{path} has the wrong format (not an object)",
                f'mv "{path}" "{path}.bak"')]
        out.append(_entry("config", "progress file", PASS,
                          f"{size}, modified {stamp}"))
        try:
            from .tracker import ProgressTracker
            containers = ProgressTracker._CONTAINERS
        except Exception:
            containers = {}
        bad = [key for key, kind in containers.items()
               if key in data and not isinstance(data[key], kind)]
        if bad:
            out.append(_entry(
                "config", "progress schema", WARN,
                f"unexpected types for: {', '.join(bad)}",
                "FreeFlix ignores these keys; move progress.json aside "
                "if something looks wrong"))
        else:
            out.append(_entry("config", "progress schema", PASS, "valid"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("config", "progress file", ERROR,
                          f"{type(exc).__name__}: {exc}"))
    return out


def _settings_entries() -> list:
    out: list = []
    try:
        track = _tracker()
        data = track.data if isinstance(track.data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        return [_entry("config", "settings", ERROR,
                       f"{type(exc).__name__}: {exc}")]

    player = data.get("player")
    if not player:
        out.append(_entry(
            "config", "player", WARN, "not chosen yet",
            "freeflix --setup   (or pick a player in Settings)"))
    else:
        known = set()
        try:
            from .player_manager import get_all_players
            known = {code for code, _display in get_all_players()}
        except Exception:
            pass
        if known and player not in known:
            out.append(_entry(
                "config", "player", WARN,
                f"{player!r} is not a known player code",
                "freeflix --setup"))
        else:
            out.append(_entry("config", "player", PASS, str(player)))

    languages = (f"interface={data.get('language') or '(not set)'}, "
                 f"anime={data.get('anime_language') or '(not set)'}")
    if not data.get("language") or not data.get("anime_language"):
        out.append(_entry("config", "languages", WARN, languages,
                          "freeflix --setup   (choose interface + anime language)"))
    else:
        out.append(_entry("config", "languages", PASS, languages))

    out.append(_entry(
        "config", "download quality", PASS,
        str(data.get("download_quality") or "auto")))
    playback = (
        f"analyze_players={data.get('analyze_players', True)}, "
        f"disk_cache={data.get('disk_cache', True)}, "
        f"subtitle_search={data.get('subtitle_search', False)}, "
        f"nvidia_offload={data.get('nvidia_offload', 'auto')}, "
        f"parallel_downloads={data.get('parallel_downloads', 1)}")
    out.append(_entry("config", "playback", INFO, playback))
    display = (
        f"poster_mode={data.get('poster_mode', 'auto')}, "
        f"theme={data.get('theme', 'noir')}, "
        f"icon_style={data.get('icon_style', 'emoji')}, "
        f"last_server={data.get('last_server') or '(none)'}")
    out.append(_entry("config", "display", INFO, display))

    secrets = (
        f"anilist_token={'set' if data.get('anilist_token') else 'unset'}, "
        f"opensubtitles_key="
        f"{'set' if data.get('opensubtitles_api_key') else 'unset'}, "
        f"cf_clearance_hosts={len(data.get('cf_clearance') or {})}")
    out.append(_entry("config", "credentials", INFO, secrets))

    out.append(_entry(
        "config", "flaresolverr", INFO,
        str(data.get("flaresolverr_url") or "http://127.0.0.1:8191")))

    last_setup = data.get("last_setup_version")
    code = _code_version()
    if last_setup and code not in ("?", "dev") and last_setup != code:
        out.append(_entry(
            "config", "setup version", WARN,
            f"completed for {last_setup}, code is {code}",
            "freeflix --setup   (apply post-upgrade migrations)"))
    else:
        out.append(_entry("config", "setup version", PASS,
                          str(last_setup or "unknown")))
    return out


def _portals_entries() -> list:
    """Effective source portals + where each URL came from (default/remote/local)."""
    out: list = []
    try:
        from .scraping.config import portal_origins, portals
        for name in ("anime-sama", "french-manga", "coflix", "french-stream",
                     "papystreaming"):
            url = portals.get(name) or "(missing)"
            origin = portal_origins.get(name, "?")
            out.append(_entry("config", f"portal {name}", INFO,
                              f"{url} [{origin}]"))
        try:
            from .scraping import config as scraping_config
            local = getattr(scraping_config, "_local_portal_path", "") or ""
        except Exception:
            local = ""
        out.append(_entry("config", "portal override", INFO,
                          local or "(bundled defaults)"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("config", "portals", WARN,
                          f"{type(exc).__name__}: {exc}"))
    return out


def collect_config() -> list:
    out: list = []
    try:
        paths = _app_paths()
    except Exception as exc:  # noqa: BLE001
        return [_entry("config", "paths", ERROR,
                       f"{type(exc).__name__}: {exc}")]
    for key, value in paths.items():
        if key == "log":
            continue  # shown as "log_dir" + in LOGS
        out.append(_entry("config", key, INFO, str(value)))
    try:
        out.extend(_progress_entry())
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("config", "progress file", ERROR,
                          f"{type(exc).__name__}: {exc}"))
    try:
        out.extend(_settings_entries())
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("config", "settings", ERROR,
                          f"{type(exc).__name__}: {exc}"))
    try:
        out.extend(_portals_entries())
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("config", "portals", WARN,
                          f"{type(exc).__name__}: {exc}"))
    try:
        out.append(_disk_entry("config", "disk (downloads)",
                               paths["downloads"]))
        out.append(_disk_entry("config", "disk (cache)", paths["cache"]))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("config", "disk", ERROR,
                          f"{type(exc).__name__}: {exc}"))
    return out


# ── BINARIES ─────────────────────────────────────────────────────────
# (binary, role, status-when-missing, why it matters / fallback)
_BINARY_SPECS = (
    ("mpv", "player", FAIL, "main playback engine"),
    ("vlc", "player", WARN, "alternative player"),
    ("ffmpeg", "media", FAIL, "download + stream remux"),
    ("ffprobe", "media", WARN, "stream analysis"),
    ("yt-dlp", "downloader", WARN, "downloads / some hosts"),
    ("aria2c", "downloader", WARN, "fast downloads, torrents"),
    ("chafa", "posters", WARN, "terminal poster rendering"),
    ("uv", "installer", INFO, "installer / updates"),
    ("gh", "upload", INFO, "used by --doctor --upload"),
)


def _binary_entry(name: str, role: str, missing_status: str,
                  why: str) -> list:
    out: list = []
    try:
        status, info, path = _check_binary(name, name)
    except Exception as exc:  # noqa: BLE001
        return [_entry("binaries", name, ERROR,
                       f"{type(exc).__name__}: {exc}")]
    if status in ("OK", "BROKEN"):
        old = _version_status(name, info) if status == "OK" else None
        if old:
            status = old
        if status == "OK":
            out.append(_entry("binaries", name, PASS,
                              f"{info} | {path}"))
        elif status == "OLD":
            out.append(_entry(
                "binaries", name, WARN,
                f"{info} (below FreeFlix minimum) | {path}",
                _install_command(name)))
        else:
            out.append(_entry(
                "binaries", name, FAIL,
                f"present but does not run | {path}",
                f"reinstall: {_install_command(name)}"))
        return out
    if status == "MISSING":
        detail = f"not found ({why})"
        action = _install_command(name)
        if missing_status == FAIL:
            entry = _entry("binaries", name, FAIL, detail, action)
        elif missing_status == WARN:
            entry = _entry("binaries", name, WARN, detail, action)
        else:
            entry = _entry("binaries", name, INFO, detail, action)
        out.append(entry)
        return out
    out.append(_entry("binaries", name, WARN, f"{status}: {info}", path))
    return out


def collect_binaries() -> list:
    out: list = []
    for name, role, missing_status, why in _BINARY_SPECS:
        try:
            out.extend(_binary_entry(name, role, missing_status, why))
        except Exception as exc:  # noqa: BLE001
            out.append(_entry("binaries", name, ERROR,
                              f"{type(exc).__name__}: {exc}"))

    # Managed copies (auto-downloaded on first run, not always on PATH).
    try:
        for label, name in (
            ("ffmpeg (managed)", "ffmpeg"),
            ("mpv (managed)", "mpv"),
            ("aria2c (managed)", "aria2c"),
            ("chafa (managed)", "chafa"),
        ):
            status, info, path = _check_managed_bin(label, name)
            if status == "MISSING":
                out.append(_entry("binaries", label, INFO,
                                  "not downloaded (system copy used if any)"))
            elif status == "SYSTEM":
                out.append(_entry("binaries", label, INFO,
                                  f"system copy: {path}"))
            elif status == "OK":
                out.append(_entry("binaries", label, PASS,
                                  f"{info} | {path}"))
            else:
                out.append(_entry("binaries", label, WARN,
                                  f"{status} | {path}",
                                  f"re-download: {_setup_hint()}"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("binaries", "managed", ERROR,
                          f"{type(exc).__name__}: {exc}"))

    # At least one player must exist, regardless of the binaries table.
    try:
        have_mpv = _check_binary("mpv", "mpv")[0] in ("OK", "OLD")
        have_vlc = _check_binary("vlc", "vlc")[0] in ("OK", "OLD")
        if not have_mpv and not have_vlc:
            out.append(_entry(
                "binaries", "local player", FAIL,
                "neither mpv nor vlc is usable - nothing can play",
                f"{_install_command('mpv')}   (or {_install_command('vlc')})"))
    except Exception:
        pass
    return out


# ── PLAYERS (mpv / vlc) ──────────────────────────────────────────────
def _player_startup(name: str, path) -> list:
    out: list = []
    try:
        status, version = _probe_binary(str(path), name)
    except Exception as exc:  # noqa: BLE001
        return [_entry("players", f"{name} startup", ERROR,
                       f"{type(exc).__name__}: {exc}")]
    if status == "OK":
        old = _version_status(name, version)
        if old:
            out.append(_entry(
                "players", f"{name} startup", WARN,
                f"{version} (below minimum) | {path}",
                _install_command(name)))
        else:
            out.append(_entry("players", f"{name} startup", PASS,
                              f"{version} | {path}"))
    else:
        out.append(_entry(
            "players", f"{name} startup", FAIL,
            f"'{path} --version' failed - the binary is broken",
            f"reinstall: {_install_command(name)}"))
    return out


def collect_players() -> list:
    out: list = []
    try:
        from .player_manager import get_mpv_path, get_vlc_path
    except Exception as exc:  # noqa: BLE001
        return [_entry("players", "resolve", ERROR,
                       f"{type(exc).__name__}: {exc}")]

    resolved: dict = {}
    for name, getter in (("mpv", get_mpv_path), ("vlc", get_vlc_path)):
        try:
            path = getter()
        except Exception as exc:  # noqa: BLE001
            out.append(_entry("players", f"{name} path", WARN,
                              f"resolution failed: {type(exc).__name__}: {exc}"))
            path = None
        resolved[name] = path
        if not path:
            out.append(_entry(
                "players", f"{name} path", WARN,
                "not found (PATH, managed bin dir, Windows registry)",
                _install_command(name)))
            continue
        out.append(_entry("players", f"{name} path", PASS, str(path)))
        out.extend(_player_startup(name, path))

    try:
        track = _tracker()
        chosen = (track.get_player() or "").strip().lower()
    except Exception:
        chosen = ""
    if chosen in ("mpv", "vlc"):
        if resolved.get(chosen):
            out.append(_entry("players", "configured player", PASS,
                              f"{chosen} -> {resolved[chosen]}"))
        else:
            out.append(_entry(
                "players", "configured player", FAIL,
                f"{chosen} is selected but cannot be found",
                f"{_install_command(chosen)}   (or {_setup_hint()})"))
    elif chosen in ("android", "browser", "download", "manual"):
        out.append(_entry("players", "configured player", INFO,
                          f"player mode: {chosen}"))
    elif not chosen:
        out.append(_entry("players", "configured player", WARN,
                          "no player chosen yet", _setup_hint()))
    else:
        out.append(_entry("players", "configured player", WARN,
                          f"unknown code {chosen!r}", _setup_hint()))
    return out


# ── MPV CONFIG & SHADERS ─────────────────────────────────────────────
def _glsl_status(path: Path) -> dict:
    """Content check for an Anime4K shader - existence alone is not enough."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:8192]
    except OSError as exc:
        return {"status": ERROR, "detail": f"unreadable: {exc}"}
    if not text.strip():
        return {"status": WARN, "detail": "empty file"}
    # mpv user shaders use the //!HOOK directive and a hook() entry point
    # (Anime4K v4 has no `void main`), so both are valid markers.
    has_hook = "//!HOOK" in text
    has_entry = ("vec4 hook(" in text) or ("vec4 hook (" in text) \
        or ("void main" in text)
    if has_hook and has_entry:
        return {"status": PASS, "detail": "valid GLSL"}
    if not has_hook:
        return {"status": WARN,
                "detail": "not a shader (no //!HOOK directive)"}
    return {"status": WARN,
            "detail": "damaged shader (no hook()/main() entry point)"}


def _mpv_conf_summary(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    settings: dict = {}
    invalid = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _sep, value = line.partition("=")
            settings[key.strip()] = value.strip()
        else:
            invalid += 1
    interesting = []
    for key in ("hwdec", "vo", "cache", "cache-dir", "profile", "ytdl-format"):
        if key in settings:
            interesting.append(f"{key}={settings[key]}")
    summary = ", ".join(interesting[:4]) or f"{len(settings)} settings"
    if invalid:
        summary += f", {invalid} unparsed line(s)"
    return summary


def collect_mpv() -> list:
    out: list = []
    try:
        config_dir = _mpv_config_dir()
    except Exception as exc:  # noqa: BLE001
        return [_entry("mpv", "config dir", ERROR,
                       f"{type(exc).__name__}: {exc}")]
    if config_dir.is_dir():
        out.append(_entry("mpv", "config dir", PASS, str(config_dir)))
    else:
        out.append(_entry("mpv", "config dir", WARN,
                          f"{config_dir} (missing)", _setup_hint()))

    for name in _MPV_CONFIG_FILES:
        path = config_dir / name
        try:
            if not path.is_file():
                out.append(_entry("mpv", name, WARN, "missing", _setup_hint()))
                continue
            if path.stat().st_size == 0:
                out.append(_entry("mpv", name, WARN, "empty file", _setup_hint()))
                continue
            detail = _fmt_size(path)
            if name == "mpv.conf":
                summary = _mpv_conf_summary(path)
                if summary:
                    detail += f" | {summary}"
            out.append(_entry("mpv", name, PASS, detail))
        except Exception as exc:  # noqa: BLE001
            out.append(_entry("mpv", name, ERROR,
                              f"{type(exc).__name__}: {exc}"))

    for shader in _MPV_SHADERS:
        path = config_dir / "shaders" / shader
        try:
            short_name = shader.replace("Anime4K_", "").replace(".glsl", "")
            if not path.is_file():
                out.append(_entry(
                    "mpv", "shader", WARN,
                    f"{short_name}: MISSING (Anime4K profile will fail to "
                    f"load it)", _setup_hint()))
                continue
            result = _glsl_status(path)
            if result["status"] == PASS:
                out.append(_entry("mpv", "shader", PASS,
                                  f"{short_name}: {_fmt_size(path)} | "
                                  f"{result['detail']}"))
            else:
                out.append(_entry(
                    "mpv", "shader", result["status"],
                    f"{short_name}: {_fmt_size(path)} | {result['detail']}",
                    f"delete it and re-run {_setup_hint()}"))
        except Exception as exc:  # noqa: BLE001
            out.append(_entry("mpv", "shader", ERROR,
                              f"{type(exc).__name__}: {exc}"))
    return out


# ── LOCAL PROXY ──────────────────────────────────────────────────────
def _proxy_start(proxy_module):
    """Start the app's local proxy; indirection keeps this testable."""
    return _timed(
        lambda: proxy_module.ensure_started(port=0, wait=5.0), 8.0)


def _proxy_control_fetch(base: str) -> tuple:
    import urllib.request

    with urllib.request.urlopen(base + "/player/heartbeat", timeout=3) as response:
        body = (response.read() or b"").decode("utf-8", errors="replace").strip()
        return response.status, body


def _proxy_stop(proxy_module) -> None:
    _timed(proxy_module.stop_proxy_server, 5.0)


def collect_proxy() -> list:
    out: list = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = sock.getsockname()[1]
        out.append(_entry("proxy", "loopback bind", PASS,
                          f"127.0.0.1:{port} bindable"))
    except OSError as exc:
        return [_entry(
            "proxy", "loopback bind", FAIL,
            f"cannot bind 127.0.0.1: {type(exc).__name__}: {exc}",
            "allow loopback in your firewall/antivirus, then retry")]

    try:
        from . import proxy as proxy_module
    except Exception as exc:  # noqa: BLE001
        return out + [_entry("proxy", "import", ERROR,
                             f"{type(exc).__name__}: {exc}")]

    port = 0
    started = False
    base = ""
    try:
        port = _proxy_start(proxy_module) or 0
        base = f"http://127.0.0.1:{port}"
        if not port:
            out.append(_entry(
                "proxy", "start", FAIL, "server did not report a port",
                "another app may occupy the port range; retry or reboot"))
        else:
            started = True
            out.append(_entry("proxy", "start", PASS, f"listening on {base}"))

        if started:
            try:
                status, body = _timed(
                    lambda: _proxy_control_fetch(base), 5.0)
                if 200 <= int(status) < 300 and body == "ok":
                    out.append(_entry("proxy", "control fetch", PASS,
                                      f"GET /player/heartbeat -> {status} {body}"))
                else:
                    out.append(_entry(
                        "proxy", "control fetch", WARN,
                        f"GET /player/heartbeat -> HTTP {status} {body[:30]}",
                        "local proxy answers but not as expected; report this"))
            except TimeoutError:
                out.append(_entry(
                    "proxy", "control fetch", FAIL,
                    "local request timed out",
                    "antivirus may intercept loopback; allow freeflix"))
            except Exception as exc:  # noqa: BLE001
                out.append(_entry(
                    "proxy", "control fetch", FAIL,
                    f"local request failed: {type(exc).__name__}: {exc}",
                    "antivirus/firewall may block 127.0.0.1; allow freeflix"))
    except TimeoutError:
        out.append(_entry("proxy", "start", FAIL,
                          "server start timed out", _ISSUES_URL))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("proxy", "start", FAIL,
                          f"{type(exc).__name__}: {exc}", _ISSUES_URL))
    finally:
        try:
            _proxy_stop(proxy_module)
        except Exception:
            pass

    if started:
        still_open = False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                still_open = True
        except OSError:
            still_open = False
        except Exception:
            still_open = False
        if still_open:
            out.append(_entry("proxy", "clean stop", WARN,
                              "port still accepting connections after stop",
                              _ISSUES_URL))
        else:
            out.append(_entry("proxy", "clean stop", PASS,
                              "port closed after stop"))
    return out


# ── NETWORK ──────────────────────────────────────────────────────────
def _cert_days_left(cert: dict) -> int:
    try:
        not_after = cert.get("notAfter") or ""
        seconds = ssl.cert_time_to_seconds(not_after)
        return int((seconds - time.time()) // 86400)
    except Exception:
        return -1


def _host_probe(host: str) -> dict:
    """DNS -> TCP -> TLS for one host, each phase bounded."""
    result: dict = {
        "dns_ok": False, "ips": [], "dns_err": "",
        "tcp_ok": False, "tcp_err": "",
        "tls_ok": False, "tls_err": "", "cert_days": -1,
    }
    try:
        infos = _timed(
            lambda: socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM),
            2.0)
        result["ips"] = sorted({info[4][0] for info in infos})[:3]
        result["dns_ok"] = True
    except TimeoutError:
        result["dns_err"] = "DNS timeout"
        return result
    except OSError as exc:
        result["dns_err"] = f"{type(exc).__name__}: {exc}"
        return result
    except Exception as exc:  # noqa: BLE001
        result["dns_err"] = f"{type(exc).__name__}: {exc}"
        return result

    try:
        with socket.create_connection((host, 443), timeout=1.5):
            result["tcp_ok"] = True
    except OSError as exc:
        result["tcp_err"] = f"{type(exc).__name__}: {exc}"
        return result
    except Exception as exc:  # noqa: BLE001
        result["tcp_err"] = f"{type(exc).__name__}: {exc}"
        return result

    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=2.0) as sock:
            with context.wrap_socket(sock, server_hostname=host) as secure:
                cert = secure.getpeercert() or {}
        result["tls_ok"] = True
        result["cert_days"] = _cert_days_left(cert)
    except ssl.SSLCertVerificationError as exc:
        result["tls_err"] = f"certificate invalid: {exc.reason or exc}"
    except Exception as exc:  # noqa: BLE001
        result["tls_err"] = f"{type(exc).__name__}: {exc}"
    return result


def _network_hosts() -> list:
    hosts = [
        ("GitHub", "github.com"),
        ("GitHub raw (config)", "raw.githubusercontent.com"),
        ("AniList", "api.anilist.co"),
    ]
    try:
        from urllib.parse import urlparse as _urlparse
        from .scraping.config import portals
        for name in ("anime-sama", "french-manga", "coflix", "french-stream"):
            url = portals.get(name, "")
            host = (_urlparse(url).hostname or "").strip() if url else ""
            if host:
                hosts.append((name, host))
    except Exception:
        pass
    seen: set = set()
    unique: list = []
    for label, host in hosts:
        if host in seen:
            continue
        seen.add(host)
        unique.append((label, host))
    return unique


def _probe_hosts_parallel(hosts: list, budget: float = 5.0) -> dict:
    """Probe all hosts concurrently with a global deadline."""
    import threading as _threading

    results: dict = {}

    def _worker(label, host):
        try:
            results[label] = _host_probe(host)
        except Exception as exc:  # noqa: BLE001
            results[label] = {"fatal": f"{type(exc).__name__}: {exc}"}

    threads = []
    for label, host in hosts:
        thread = _threading.Thread(target=_worker, args=(label, host), daemon=True)
        thread.start()
        threads.append(thread)
    deadline = time.monotonic() + budget
    for thread in threads:
        thread.join(max(0.05, deadline - time.monotonic()))
    return results


def _proxies_entry() -> dict:
    proxies: dict = {}
    try:
        import urllib.request as _ur
        proxies = {str(k): str(v) for k, v in (_ur.getproxies() or {}).items()}
    except Exception:
        proxies = {}

    def _redact(value: str) -> str:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(value)
            if parsed.username or parsed.password:
                host = parsed.hostname or ""
                port = f":{parsed.port}" if parsed.port else ""
                return f"{parsed.scheme}://***@{host}{port}"
        except Exception:
            pass
        return value

    if not proxies:
        return _entry("network", "system proxy", INFO, "none configured")
    detail = ", ".join(f"{key}={_redact(value)}"
                       for key, value in sorted(proxies.items()))
    return _entry("network", "system proxy", INFO, detail)


def _dns_servers_entry() -> dict:
    try:
        if _os() == "windows":
            return _entry("network", "dns servers", INFO,
                          "read by the OS (see ipconfig /all)")
        servers: list = []
        for line in Path("/etc/resolv.conf").read_text(
                encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("nameserver"):
                parts = line.split()
                if len(parts) > 1:
                    servers.append(parts[1])
        return _entry("network", "dns servers", INFO,
                      ", ".join(servers) if servers else "(none in resolv.conf)")
    except Exception:
        return _entry("network", "dns servers", INFO, "(unreadable)")


def collect_network() -> list:
    out: list = []
    hosts = _network_hosts()
    results = _probe_hosts_parallel(hosts, budget=5.0)
    all_dns_failed = True
    for label, host in hosts:
        probe = results.get(label)
        if not probe:
            out.append(_entry("network", label, WARN,
                              f"{host}: no answer within budget",
                              _dns_hint()))
            continue
        if probe.get("fatal"):
            out.append(_entry("network", label, WARN,
                              f"{host}: {probe['fatal']}", _ISSUES_URL))
            continue
        if not probe.get("dns_ok"):
            out.append(_entry(
                "network", label, WARN,
                f"{host}: DNS FAIL - {probe.get('dns_err') or 'unknown'}",
                _dns_hint()))
            continue
        all_dns_failed = False
        ips = ", ".join(probe.get("ips") or []) or "?"
        if not probe.get("tcp_ok"):
            out.append(_entry(
                "network", label, WARN,
                f"{host} -> {ips} but TCP 443 FAIL - "
                f"{probe.get('tcp_err') or 'unknown'}",
                "check firewall / antivirus / VPN; test: "
                f"curl -v https://{host}"))
            continue
        if not probe.get("tls_ok"):
            out.append(_entry(
                "network", label, WARN,
                f"{host}: DNS+TCP ok but TLS FAIL - "
                f"{probe.get('tls_err') or 'unknown'}",
                "captive portal or antivirus TLS interception? "
                "try another network / disable HTTPS scanning"))
            continue
        days = probe.get("cert_days", -1)
        cert = f", cert {days}d" if isinstance(days, int) and days >= 0 else ""
        if isinstance(days, int) and 0 <= days < 15:
            out.append(_entry(
                "network", label, WARN,
                f"{host}: reachable, certificate expires in {days}d",
                "update your system certificates (ca-certificates)"))
        else:
            out.append(_entry("network", label, PASS,
                              f"{host}: DNS {ips}, TCP+TLS ok{cert}"))

    if all_dns_failed and hosts:
        out.append(_entry(
            "network", "internet", FAIL,
            "no host resolved - DNS is blocked or the machine is offline",
            _dns_hint()))

    out.append(_proxies_entry())
    out.append(_dns_servers_entry())

    # FlareSolverr (optional Cloudflare solver).
    try:
        url = _tracker().get_flaresolverr_url()
        status = _timed(lambda: _check_flaresolverr(url), 8.0)
        if status.startswith("HEALTHY"):
            out.append(_entry("network", "flaresolverr", PASS,
                              f"{status} | {url}"))
        elif status.startswith("UNHEALTHY"):
            out.append(_entry(
                "network", "flaresolverr", WARN, f"{status} | {url}",
                "restart it: podman start flaresolverr   (or freeflix --setup)"))
        else:
            out.append(_entry(
                "network", "flaresolverr", INFO,
                f"{status} - optional, only needed for Cloudflare sources"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("network", "flaresolverr", WARN,
                          f"{type(exc).__name__}: {exc}"))
    return out


# ── SOURCES & STREAMS ────────────────────────────────────────────────
_SOURCE_TESTS = [
    ("Anime-Sama", "freeflix_cli.scraping.anime_sama", "naruto"),
    ("French-Manga", "freeflix_cli.scraping.french_manga", "naruto"),
    ("Coflix", "freeflix_cli.scraping.coflix", "matrix"),
    ("French-Stream", "freeflix_cli.scraping.french_stream", "matrix"),
    ("Papystreaming", "freeflix_cli.scraping.papystreaming", "matrix"),
]


def _import_module(name: str):
    """Indirection so tests can mock module imports without network."""
    import importlib
    return importlib.import_module(name)


def _classify_exception(exc: BaseException) -> tuple:
    """(tag, action) - separates provider outages from real FreeFlix bugs."""
    name = type(exc).__name__
    message = str(exc)
    low = message.lower()
    provider_markers = (
        "cloudflare", "cf-ray", "cf_ray", "403", "429", "timed out",
        "timeout", "connection", "resolve", "dns", "unreachable", "502",
        "503", "504", "404", "410", "certificate", "ssl", "no such host",
        "temporary failure", "name or service not known", "max retries",
    )
    bug_types = (AttributeError, KeyError, TypeError, IndexError,
                 ImportError, ValueError)
    if isinstance(exc, bug_types) and not any(
            marker in low for marker in provider_markers):
        return ("BUG-FREEFLIX",
                "this is a FreeFlix bug: report it at " + _ISSUES_URL
                + " with this report")
    if "cloudflare" in low or "cf-ray" in low or "403" in low:
        return ("MORT-FOURNISSEUR (Cloudflare)",
                "provider-side: retry later, or upgrade FreeFlix "
                "(`uv tool upgrade freeflix-cli`)")
    if any(marker in low for marker in provider_markers):
        return ("MORT-FOURNISSEUR (unreachable)",
                "provider-side/network: retry later; if every source fails, "
                "see NETWORK")
    if name in ("HTTPError",):
        return ("MORT-FOURNISSEUR (HTTP error)",
                "provider-side: retry later")
    return ("BUG-FREEFLIX",
            "report this at " + _ISSUES_URL + " with this report")


def _player_name_url(player) -> tuple:
    if isinstance(player, dict):
        name = (player.get("name") or player.get("host")
                or player.get("label") or "player")
        url = (player.get("url") or player.get("embed")
               or player.get("link") or "")
        return str(name), str(url)
    name = getattr(player, "name", None) or getattr(player, "host", None) \
        or "player"
    url = getattr(player, "url", None) or getattr(player, "embed", None) or ""
    return str(name), str(url)


def _players_anime_sama(module, first) -> list:
    series = module.get_series(getattr(first, "url", ""))
    seasons = getattr(series, "seasons", None) or []
    if not seasons:
        return []
    season = module.get_season(seasons[0].url)
    episodes_map = getattr(season, "episodes", None) or {}
    first_episodes = []
    if isinstance(episodes_map, dict):
        for episodes in episodes_map.values():
            if episodes:
                first_episodes = list(episodes)
                break
    if not first_episodes:
        return []
    return list(getattr(first_episodes[0], "players", None) or [])


def _players_coflix(module, first) -> list:
    content = module.get_content(getattr(first, "url", ""))
    players = getattr(content, "players", None)
    if players:
        return list(players)
    seasons = getattr(content, "seasons", None) or []
    if not seasons:
        return []
    season = module.get_season(seasons[0].url)
    episodes = getattr(season, "episodes", None) or []
    if not episodes:
        return []
    episode = module.get_episode(episodes[0].url)
    return list(getattr(episode, "players", None) or [])


def _players_french_stream(module, first) -> list:
    content = module.get_content(getattr(first, "url", ""))
    players = getattr(content, "players", None)
    if players:
        return list(players)
    episodes_map = getattr(content, "episodes", None) or {}
    if isinstance(episodes_map, dict):
        for episodes in episodes_map.values():
            if episodes:
                return list(getattr(episodes[0], "players", None) or [])
    return []


def _players_french_manga(module, first) -> list:
    data = module.get_episodes(getattr(first, "url", ""))
    if not isinstance(data, dict):
        return []
    for lang in ("vf", "vostfr"):
        episodes = data.get(lang) or {}
        if not isinstance(episodes, dict):
            continue
        for _number, players in episodes.items():
            if players:
                return list(players)
    return []


_SOURCE_ADAPTERS = {
    "Anime-Sama": _players_anime_sama,
    "French-Manga": _players_french_manga,
    "Coflix": _players_coflix,
    "French-Stream": _players_french_stream,
}


def _probe_hls_playable(url: str, headers: dict = None,
                       timeout: float = 8.0) -> tuple:
    """Indirection over player_manager.probe_hls_playable (mockable in tests)."""
    from .player_manager import probe_hls_playable
    return probe_hls_playable(url, headers or {}, timeout=timeout)


def _resolve_embed(embed_url: str, timeout: float = 10.0):
    """Resolve an embed page to a playable media URL (HLS preferred)."""
    from .scraping import player as scraping_player
    return _timed(lambda: scraping_player.get_hls_link(embed_url, {}), timeout)


def _stream_entry(label: str, player_name: str, embed_url: str,
                  timeout: float) -> list:
    """One stream probe, labelled "<source> stream" + "<player>: ..." detail.

    Keeping the player name in the detail (instead of a long label) keeps the
    report readable at 80 columns without truncating which server was tested.
    """
    from .scraping.utils import ANIME_SAMA_SIGNED_SENTINEL

    entry_label = f"{label} stream"
    prefix = f"{player_name}: "
    out: list = []
    if not embed_url or embed_url == ANIME_SAMA_SIGNED_SENTINEL \
            or not embed_url.lower().startswith(("http://", "https://")):
        out.append(_entry(
            "sources", entry_label, INFO,
            prefix + "signed or indirect player - resolved at play time"))
        return out
    media_url = embed_url
    if ".m3u8" not in embed_url.lower():
        try:
            media_url = _resolve_embed(embed_url, timeout=min(timeout, 10.0)) or ""
        except TimeoutError:
            return [_entry(
                "sources", entry_label, WARN,
                prefix + "MORT-FOURNISSEUR - extractor timed out",
                "provider-side: retry or pick another server")]
        except Exception as exc:  # noqa: BLE001
            tag, action = _classify_exception(exc)
            return [_entry("sources", entry_label, WARN,
                           prefix + f"{tag} - extractor failed: "
                           f"{type(exc).__name__}: {exc}"[:150], action)]
    if not media_url:
        return [_entry(
            "sources", entry_label, WARN,
            prefix + "MORT-FOURNISSEUR - no stream URL found (dead embed "
            "or outdated extractor)",
            "provider-side: retry later, or report with this report")]
    try:
        playable, reason = _probe_hls_playable(
            media_url, {}, timeout=min(timeout, 8.0))
    except TimeoutError:
        return [_entry("sources", entry_label, WARN,
                       prefix + "stream probe timed out",
                       "retry with --doctor --players")]
    except Exception as exc:  # noqa: BLE001
        return [_entry("sources", entry_label, WARN,
                       prefix + f"stream probe error: "
                       f"{type(exc).__name__}: {exc}"[:120], _ISSUES_URL)]
    if playable:
        return [_entry("sources", entry_label, PASS,
                       prefix + "OK - manifest + first segment playable")]
    return [_entry(
        "sources", entry_label, WARN,
        prefix + f"MORT-FOURNISSEUR - stream refused ({reason or 'unknown'})",
        "provider-side: expired token or removed stream; pick another "
        "server or retry later")]

def _deep_source_probe(label: str, module, first, timeout: float) -> list:
    """Resolve the first item's real players and probe their first segment."""
    adapter = _SOURCE_ADAPTERS.get(label)
    if adapter is None:
        return [_entry(
            "sources", f"{label} players", INFO,
            "streams resolved through the GoldenMS/GoldenAnime extractors - "
            "not probed here")]
    try:
        players = _timed(lambda: adapter(module, first), timeout) or []
    except TimeoutError:
        return [_entry("sources", f"{label} players", WARN,
                       "MORT-FOURNISSEUR - player list timed out",
                       "provider-side or slow network: retry")]
    except Exception as exc:  # noqa: BLE001
        tag, action = _classify_exception(exc)
        return [_entry("sources", f"{label} players", FAIL if tag.startswith("BUG")
                       else WARN,
                       f"{tag} - {type(exc).__name__}: {exc}"[:160], action)]
    if not players:
        return [_entry("sources", f"{label} players", WARN,
                       "MORT-FOURNISSEUR - no player found for the first item",
                       "provider-side: page layout may have changed; if it "
                       "persists, report with this report")]
    names = ", ".join(_player_name_url(item)[0] for item in players[:6])
    out = [_entry("sources", f"{label} players", PASS,
                  f"{len(players)}: {names}" if names else str(len(players)))]
    for player in players[:3]:
        name, url = _player_name_url(player)
        out.extend(_stream_entry(label, name, url, timeout))
    return out


def _source_search_probe(label: str, module_path: str, query: str,
                         deep: bool, timeout: float) -> list:
    started = time.monotonic()
    try:
        module = _timed(lambda: _import_module(module_path), min(5.0, timeout))
    except Exception as exc:  # noqa: BLE001
        return [_entry("sources", label, FAIL,
                       f"BUG-FREEFLIX - import failed: "
                       f"{type(exc).__name__}: {exc}",
                       "this is a packaging bug: report it at " + _ISSUES_URL)]

    try:
        website_url = getattr(module, "get_website_url", None)
        if callable(website_url):
            _timed(website_url, min(8.0, timeout))
    except TimeoutError:
        return [_entry("sources", label, WARN,
                       "MORT-FOURNISSEUR - website URL probe timed out",
                       "retry later")]
    except Exception as exc:  # noqa: BLE001
        tag, action = _classify_exception(exc)
        return [_entry("sources", label, WARN,
                       f"{tag} - {type(exc).__name__}: {exc}"[:160], action)]

    try:
        results = _timed(lambda: module.search(query), timeout) or []
    except TimeoutError:
        return [_entry("sources", label, WARN,
                       f"MORT-FOURNISSEUR - search timed out ({timeout:.0f}s)",
                       "provider-side or slow network: retry")]
    except Exception as exc:  # noqa: BLE001
        tag, action = _classify_exception(exc)
        status = FAIL if tag.startswith("BUG") else WARN
        return [_entry("sources", label, status,
                       f"{tag} - search failed: "
                       f"{type(exc).__name__}: {exc}"[:160], action)]

    elapsed_ms = int((time.monotonic() - started) * 1000)
    try:
        count = len(results)
    except Exception:
        count = 0
    if count == 0:
        return [_entry(
            "sources", label, WARN,
            f"reachable but 0 results for '{query}' ({elapsed_ms} ms)",
            "the site may have changed layout: retry; if it persists "
            "report it (possible BUG-FREEFLIX)")]

    first = results[0]
    title = getattr(first, "title", None) or (
        first.get("title") if isinstance(first, dict) else "") or "?"
    out = [_entry("sources", label, PASS,
                  f"{count} result(s) in {elapsed_ms} ms | first: {title}")]
    if deep:
        remaining = max(4.0, timeout - (time.monotonic() - started))
        out.extend(_deep_source_probe(label, module, first, remaining))
    return out


def collect_sources(requested: bool = False, deep: bool = False,
                    budget: float = 60.0) -> list:
    if not requested:
        return [_entry(
            "sources", "live probe", SKIP,
            "not run (pass --sources for a short live search; "
            "add --players for player/stream resolution)")]
    out: list = []
    started = time.monotonic()
    for label, module_path, query in _SOURCE_TESTS:
        remaining = budget - (time.monotonic() - started)
        if remaining <= 3.0:
            out.append(_entry("sources", label, SKIP,
                              "budget exhausted, skipped",
                              "re-run with --doctor --sources"))
            continue
        per_source = min(12.0 if deep else 8.0, remaining - 1.0)
        try:
            out.extend(_source_search_probe(
                label, module_path, query, deep, per_source))
        except Exception as exc:  # noqa: BLE001 - never lose the report
            out.append(_entry("sources", label, ERROR,
                              f"{type(exc).__name__}: {exc}",
                              "report this at " + _ISSUES_URL))
    return out


# ── TERMINAL & IMAGES ────────────────────────────────────────────────
def _nerd_font_present() -> tuple:
    """Fast Nerd Font detection (files first; fc-list only as a fallback)."""
    try:
        from .setup_assistant import _nerd_font_files_present
        if _nerd_font_files_present():
            return True, "font files found"
    except Exception:
        pass
    if _os() in ("linux", "macos"):
        try:
            out = subprocess.run(
                ["fc-list"], capture_output=True, text=True, timeout=3,
                encoding="utf-8", errors="replace").stdout or ""
            if re.search(r"(?i)caskaydia|nerd font", out):
                return True, "fc-list match"
        except Exception:
            pass
    return False, ""


def collect_terminal() -> list:
    out: list = []
    try:
        columns, rows = shutil.get_terminal_size(fallback=(0, 0))
        if not columns:
            out.append(_entry("terminal", "size", INFO,
                              "unknown (stdout is not a TTY)"))
        elif columns < 60:
            out.append(_entry("terminal", "size", WARN,
                              f"{columns}x{rows} - too narrow for the TUI",
                              "resize the terminal to at least 80 columns"))
        else:
            out.append(_entry("terminal", "size", PASS, f"{columns}x{rows}"))
    except Exception:
        pass

    try:
        from . import terminal_image
        available = terminal_image.chafa_available()
        if not available:
            out.append(_entry(
                "terminal", "chafa", WARN,
                "not installed - posters disabled (list view still works)",
                _install_command("chafa")))
        else:
            version = terminal_image._chafa_version()
            minimum = (1, 10)
            status = PASS if tuple(version) >= minimum else WARN
            action = "" if status == PASS else _install_command("chafa")
            out.append(_entry(
                "terminal", "chafa", status,
                f"{'.'.join(map(str, version)) or '?'} "
                f"(minimum {'.'.join(map(str, minimum))})",
                action))
        try:
            protocol = _timed(terminal_image.detect_image_protocol, 2.5)
            if protocol in ("kitty", "iterm", "sixel"):
                out.append(_entry("terminal", "image protocol", PASS,
                                  f"{protocol} (real pixels)"))
            else:
                out.append(_entry("terminal", "image protocol", INFO,
                                  f"{protocol} - Unicode blocks "
                                  "(install chafa/use a pixel terminal "
                                  "for sharper posters)"))
            hint = terminal_image.sixel_hint()
            if hint:
                out.append(_entry("terminal", "image hint", INFO, hint))
        except Exception as exc:  # noqa: BLE001
            out.append(_entry("terminal", "image protocol", WARN,
                              f"{type(exc).__name__}: {exc}"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("terminal", "images", WARN,
                          f"{type(exc).__name__}: {exc}"))

    try:
        present, how = _nerd_font_present()
        try:
            icon_style = _tracker().get_icon_style()
        except Exception:
            icon_style = "emoji"
        if present:
            out.append(_entry("terminal", "nerd font", PASS, how))
        elif icon_style == "nerd":
            out.append(_entry(
                "terminal", "nerd font", WARN,
                "icons are set to 'nerd' but no Nerd Font is installed",
                "install CaskaydiaCove Nerd Font or switch icons to 'emoji' "
                "in Settings"))
        else:
            out.append(_entry("terminal", "nerd font", INFO,
                              "not installed (emoji icons in use)"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("terminal", "nerd font", WARN,
                          f"{type(exc).__name__}: {exc}"))

    try:
        disabled = os.environ.get("FREEFLIX_NO_MOUSE", "").lower() in (
            "1", "true", "yes", "on")
        if disabled:
            out.append(_entry("terminal", "mouse", INFO,
                              "disabled via FREEFLIX_NO_MOUSE"))
        else:
            try:
                from .cli_utils import _mouse_available
                supported = _timed(_mouse_available, 2.0)
            except Exception:
                supported = False
            if supported:
                out.append(_entry("terminal", "mouse", PASS,
                                  "SGR mouse reporting available"))
            else:
                out.append(_entry(
                    "terminal", "mouse", INFO,
                    "unavailable (keyboard works everywhere)"))
    except Exception:
        pass

    try:
        term = (os.environ.get("TERM") or "").lower()
        if not _stdout_isatty():
            out.append(_entry("terminal", "alternate screen", INFO,
                              "not a TTY - full-screen UI disabled"))
        elif term == "dumb":
            out.append(_entry("terminal", "alternate screen", WARN,
                              "TERM=dumb - the full-screen UI cannot run",
                              "use a real terminal emulator "
                              "(Windows Terminal, Konsole, iTerm...)"))
        else:
            out.append(_entry("terminal", "alternate screen", PASS,
                              "supported"))
    except Exception:
        pass

    try:
        color = (os.environ.get("COLORTERM") or "").lower()
        term = (os.environ.get("TERM") or "").lower()
        if "truecolor" in color or "24bit" in color:
            detail = "truecolor (24-bit)"
        elif "256" in term or "256" in color:
            detail = "256 colors"
        else:
            detail = color or term or "unknown"
        out.append(_entry("terminal", "colors", INFO, detail))
    except Exception:
        pass
    return out


# ── LOGS ─────────────────────────────────────────────────────────────
_LOG_ERROR_MARKERS = (" ERROR ", " CRITICAL ", "Traceback (most recent call last)")
_LOG_KEYWORDS = ("403", "429", "cloudflare", "timed out", "timeout",
                 "connection", "dns", "502", "503", "504")


def collect_logs(limit: int = 8) -> list:
    out: list = []
    try:
        path = _app_paths()["log"]
    except Exception as exc:  # noqa: BLE001
        return [_entry("logs", "log file", WARN,
                       f"{type(exc).__name__}: {exc}")]
    if not path.is_file():
        return [_entry("logs", "log file", INFO,
                       f"{path} (not created yet - run freeflix once)")]
    try:
        size = path.stat().st_size
        from datetime import datetime as _dt
        stamp = _dt.fromtimestamp(path.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S")
        out.append(_entry("logs", "log file", PASS,
                          f"{path} ({_human_bytes(size)}, last write {stamp})"))
    except OSError as exc:
        return [_entry("logs", "log file", WARN, f"unreadable: {exc}")]

    try:
        backups = sorted(path.parent.glob(path.name + ".*"))
        if backups:
            total = 0
            for backup in backups:
                try:
                    total += backup.stat().st_size
                except OSError:
                    pass
            out.append(_entry("logs", "rotated logs", INFO,
                              f"{len(backups)}, {_human_bytes(total)} total"))
    except Exception:
        pass

    lines = _tail_lines(path, max_lines=500)
    errors = [line for line in lines
              if any(marker in line for marker in _LOG_ERROR_MARKERS)]
    unhandled = sum(1 for line in lines if "Unhandled exception" in line)
    if errors or unhandled:
        out.append(_entry(
            "logs", "errors", WARN,
            f"{len(errors)} error line(s) in the last {len(lines)} "
            f"(unhandled exceptions: {unhandled})",
            f"freeflix --verbose   (then reproduce and paste the new log: "
            f"{path})"))
        for index, line in enumerate(errors[-limit:][::-1], 1):
            out.append(_entry("logs", f"recent error {index}", INFO,
                              str(line)[:240]))
    else:
        out.append(_entry("logs", "errors", PASS,
                          f"none in the last {len(lines)} line(s)"))

    try:
        joined = "\n".join(lines).lower()
        counts = {keyword: joined.count(keyword)
                  for keyword in _LOG_KEYWORDS if joined.count(keyword)}
        if counts:
            summary = ", ".join(f"{key}={value}"
                                for key, value in sorted(counts.items()))
            out.append(_entry("logs", "failure patterns", INFO, summary))
    except Exception:
        pass
    return out


# ── STATE & CACHE ────────────────────────────────────────────────────
def collect_state() -> list:
    out: list = []
    try:
        track = _tracker()
        data = track.data if isinstance(track.data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        return [_entry("state", "tracker", ERROR,
                       f"{type(exc).__name__}: {exc}")]

    try:
        history = data.get("history")
        follows = data.get("followed_series")
        out.append(_entry(
            "state", "library", INFO,
            f"history={len(history) if isinstance(history, dict) else 0}, "
            f"follows={len(follows) if isinstance(follows, dict) else 0}, "
            f"watched={len(data.get('watched_episodes') or [])}, "
            f"searches={len(data.get('search_history') or [])}"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("state", "library", WARN,
                          f"{type(exc).__name__}: {exc}"))

    try:
        from .player_manager import list_interrupted_downloads
        pending = _timed(list_interrupted_downloads, 3.0) or []
        if pending:
            titles = ", ".join(str(item.get("title") or "?")[:40]
                               for item in pending[:4])
            out.append(_entry(
                "state", "interrupted downloads", WARN,
                f"{len(pending)}: {titles}",
                "relaunch FreeFlix and resume them, or delete "
                f"{_app_paths()['downloads_temp']} to reclaim the space"))
        else:
            out.append(_entry("state", "interrupted downloads", PASS, "none"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("state", "interrupted downloads", WARN,
                          f"{type(exc).__name__}: {exc}"))

    try:
        paths = _app_paths()
        for label, key in (("cache size", "cache"),
                           ("http cache", "http_cache"),
                           ("poster covers", "covers"),
                           ("download temp", "downloads_temp")):
            stats = _dir_stats(paths[key])
            suffix = " (capped)" if stats["truncated"] else ""
            out.append(_entry(
                "state", label, INFO,
                f"{_human_bytes(stats['bytes'])} in {stats['files']} "
                f"file(s){suffix}"))
        recent = paths["recent"]
        if recent.is_file():
            from datetime import datetime as _dt
            stamp = _dt.fromtimestamp(recent.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M")
            out.append(_entry("state", "release cache", INFO,
                              f"{_fmt_size(recent)}, {stamp}"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("state", "cache", WARN,
                          f"{type(exc).__name__}: {exc}"))
    return out


# ── WINDOWS-SPECIFIC ─────────────────────────────────────────────────
def _win_console_vt() -> tuple:
    """(supported, vt_enabled) for the current Windows console."""
    if os.name != "nt":
        return (False, False, "not Windows")
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return (False, False, "no console attached")
        return (True, bool(mode.value & 0x4), "")
    except Exception as exc:  # noqa: BLE001
        return (False, False, f"{type(exc).__name__}: {exc}")


def _win_output_codepage():
    if os.name != "nt":
        return None
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetConsoleOutputCP())
    except Exception:
        return None


def _win_long_paths():
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return bool(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
    except Exception:
        return None


def _powershell(query: str, timeout: float = 5.0):
    if os.name != "nt":
        return None
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace")
        return (completed.stdout or "").strip()
    except Exception:
        return None


def _win_motw(executable) -> tuple:
    """(blocked, detail): Mark-of-the-Web on the installed executable."""
    if os.name != "nt" or not executable:
        return (None, "not checked")
    escaped = str(executable).replace("'", "''")
    output = _powershell(
        f"(Get-Item -LiteralPath '{escaped}' -Stream Zone.Identifier "
        "-ErrorAction SilentlyContinue).Stream", timeout=5.0)
    if output is None:
        return (None, "PowerShell unavailable")
    return (bool(output.strip()), output.strip() or "no zone stream")


def _win_defender() -> tuple:
    """(enabled, detail) for Windows Defender real-time protection."""
    if os.name != "nt":
        return (None, "not checked")
    output = _powershell(
        "(Get-MpComputerStatus -ErrorAction SilentlyContinue)"
        ".RealTimeProtectionEnabled", timeout=6.0)
    if output is None:
        return (None, "PowerShell unavailable")
    low = output.strip().lower()
    if low in ("true", "1"):
        return (True, "real-time protection ON")
    if low in ("false", "0"):
        return (False, "real-time protection OFF")
    return (None, output[:80] or "unknown")


def collect_windows() -> list:
    if _os() != "windows":
        return [_entry("windows", "platform", SKIP,
                       "not running Windows - section skipped")]
    out: list = []
    try:
        paths = _app_paths()
        managed_dir = paths["managed_bins"]
        for name in ("mpv.exe", "ffmpeg.exe", "chafa.exe", "aria2c.exe"):
            target = managed_dir / name
            if target.is_file():
                out.append(_entry("windows", f"managed {name}", PASS,
                                  f"{_fmt_size(target)} | {target}"))
            else:
                out.append(_entry("windows", f"managed {name}", INFO,
                                  "not downloaded"))
        for label, value in (("LOCALAPPDATA", os.environ.get("LOCALAPPDATA")),
                             ("APPDATA", os.environ.get("APPDATA"))):
            if value:
                out.append(_dir_entry("windows", label, Path(value)))
            else:
                out.append(_entry("windows", label, FAIL, "not set",
                                  "weird Windows environment: report this"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("windows", "app paths", WARN,
                          f"{type(exc).__name__}: {exc}"))

    try:
        supported, vt, detail = _win_console_vt()
        if not supported:
            out.append(_entry("windows", "console VT", WARN,
                              f"unavailable: {detail}",
                              "run freeflix from Windows Terminal"))
        elif vt:
            out.append(_entry("windows", "console VT", PASS,
                              "virtual-terminal processing enabled"))
        else:
            out.append(_entry(
                "windows", "console VT", WARN,
                "virtual-terminal processing disabled",
                "use Windows Terminal, or enable VT in the console "
                "properties (freeflix tries to enable it at startup)"))
        codepage = _win_output_codepage()
        if codepage is None:
            out.append(_entry("windows", "console codepage", INFO,
                              "unknown"))
        elif codepage == 65001:
            out.append(_entry("windows", "console codepage", PASS,
                              "65001 (UTF-8)"))
        else:
            out.append(_entry(
                "windows", "console codepage", WARN,
                f"{codepage} (not UTF-8)",
                "chcp 65001   (freeflix sets it at startup when possible)"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("windows", "console", WARN,
                          f"{type(exc).__name__}: {exc}"))

    try:
        long_paths = _win_long_paths()
        if long_paths is True:
            out.append(_entry("windows", "long paths", PASS, "enabled"))
        elif long_paths is False:
            out.append(_entry(
                "windows", "long paths", WARN,
                "disabled - deep folder names can break downloads",
                "enable LongPathsEnabled in the registry (or move "
                f"{_app_paths()['downloads']} closer to C:)"))
        else:
            out.append(_entry("windows", "long paths", INFO, "unknown"))
    except Exception:
        pass

    try:
        try:
            from .player_manager import get_mpv_path
            exe = get_mpv_path()
        except Exception:
            exe = None
        blocked, detail = _win_motw(exe)
        if blocked is None:
            out.append(_entry("windows", "mark-of-the-web", INFO, detail))
        elif blocked:
            out.append(_entry(
                "windows", "mark-of-the-web", WARN,
                f"mpv.exe is marked as downloaded: {detail}",
                f'Unblock-File -LiteralPath "{exe}"   (PowerShell)'))
        else:
            out.append(_entry("windows", "mark-of-the-web", PASS,
                              "no blocked zone on mpv.exe"))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("windows", "mark-of-the-web", INFO,
                          f"{type(exc).__name__}: {exc}"))

    try:
        enabled, detail = _win_defender()
        if enabled is None:
            out.append(_entry("windows", "defender", INFO, detail))
        elif enabled:
            out.append(_entry(
                "windows", "defender", PASS, detail))
        else:
            out.append(_entry("windows", "defender", INFO,
                              "real-time protection seems OFF: " + detail))
    except Exception as exc:  # noqa: BLE001
        out.append(_entry("windows", "defender", INFO,
                          f"{type(exc).__name__}: {exc}"))

    try:
        if os.environ.get("WT_SESSION"):
            out.append(_entry("windows", "terminal host", PASS,
                              "Windows Terminal"))
        elif os.environ.get("ConEmuANSI"):
            out.append(_entry("windows", "terminal host", INFO, "ConEmu"))
        else:
            out.append(_entry("windows", "terminal host", INFO,
                              "classic conhost - Windows Terminal is nicer"))
        executable = (sys.executable or "").lower()
        if executable.endswith("pythonw.exe"):
            out.append(_entry(
                "windows", "interpreter", WARN,
                "running under pythonw.exe (no console)",
                "run freeflix from a terminal, not a GUI launcher"))
    except Exception:
        pass
    return out


# ── REPORT COLLECTION / RENDERING ────────────────────────────────────
def _meta(elapsed: float = None) -> dict:
    """Report header metadata - every field resolved defensively."""
    try:
        columns, rows = shutil.get_terminal_size(fallback=(0, 0))
    except Exception:
        columns, rows = 0, 0
    try:
        local_stamp = datetime.now().astimezone().strftime(
            "%Y-%m-%d %H:%M:%S %z")
    except Exception:
        local_stamp = "(unknown)"
    try:
        utc_stamp = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        utc_stamp = "(unknown)"
    try:
        distro = _detect_distro()
    except Exception:
        distro = "(unknown)"
    meta = {
        "schema": "freeflix.doctor/1",
        "generated_utc": utc_stamp,
        "generated_local": local_stamp,
        "version": _version(),
        "code_version": _code_version(),
        "os": _os(),
        "distro": distro,
        "platform": f"{platform.system()} {platform.release()} "
                    f"({platform.machine()})",
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "terminal": f"{os.environ.get('TERM') or '?'} {columns}x{rows}",
        "width": _REPORT_WIDTH,
    }
    if elapsed is not None:
        try:
            meta["elapsed_s"] = round(float(elapsed), 2)
        except Exception:
            pass
    return meta


def _counts(entries: list) -> dict:
    counts = {PASS: 0, WARN: 0, FAIL: 0, ERROR: 0, INFO: 0, SKIP: 0}
    for entry in entries:
        status = entry.get("status", INFO)
        if status not in counts:
            counts[status] = 0
        counts[status] += 1
    return counts


def _section_status(entries: list) -> str:
    statuses = {entry.get("status") for entry in entries}
    if statuses & set(_BAD):
        return FAIL
    if WARN in statuses:
        return WARN
    if statuses and statuses <= {SKIP}:
        return SKIP
    return PASS


def _assign_codes(entries: list) -> list:
    counters: dict = {}
    coded: list = []
    for entry in entries:
        copied = dict(entry)
        section = copied.get("section") or "misc"
        copied["section"] = section
        prefix = _PREFIX.get(section, section[:3].upper() or "GEN")
        counters[prefix] = counters.get(prefix, 0) + 1
        copied["code"] = f"{prefix}-{counters[prefix]:02d}"
        coded.append(copied)
    return coded


def _wrap_text(text, width: int) -> list:
    import textwrap

    value = _one_line(text)
    if not value:
        return [""]
    width = max(12, int(width))
    try:
        chunks = textwrap.wrap(
            value, width=width, break_long_words=True,
            break_on_hyphens=False, replace_whitespace=True)
    except Exception:
        chunks = [value[:width]]
    return chunks or [""]


def _append_row(lines: list, label: str, value, width: int) -> None:
    prefix = f"{label:<11}: "
    for index, chunk in enumerate(_wrap_text(value, width - len(prefix))):
        lines.append((prefix if index == 0 else " " * len(prefix)) + chunk)


def _entry_lines(entry: dict, width: int) -> list:
    status = str(entry.get("status") or INFO)
    code = str(entry.get("code") or "---")
    label = str(entry.get("label") or "")
    if len(label) > 24:
        label = label[:23] + "~"
    head = f"  {status:<5} {code:<7} {label:<24} "
    body = entry.get("detail") or ""
    chunks = _wrap_text(body, width - len(head))
    lines = [head + chunks[0]]
    indent = " " * len(head)
    for chunk in chunks[1:]:
        lines.append(indent + chunk)
    action = entry.get("action") or ""
    if action:
        action_prefix = " " * 8 + "fix: "
        for index, chunk in enumerate(
                _wrap_text(action, width - len(action_prefix))):
            lines.append((action_prefix if index == 0
                          else " " * len(action_prefix)) + chunk)
    return [line[:width] for line in lines]


def _entry_title(entry: dict) -> str:
    label = str(entry.get("label") or "")
    detail = str(entry.get("detail") or "")
    if detail:
        return f"{label}: {detail}"
    return label


def _render(entries: list, meta: dict = None) -> str:
    """Human report: ASCII only, wrapped to ``_REPORT_WIDTH`` columns."""
    meta = dict(meta or _meta())
    width = int(meta.get("width") or _REPORT_WIDTH)
    coded = _assign_codes(entries)
    lines: list = []

    banner = "=" * width
    lines.append(banner)
    lines.append("  FreeFlix CLI - DIAGNOSTIC REPORT".center(width).rstrip())
    lines.append(banner)
    _append_row(lines, "Generated", f"{meta.get('generated_utc')} "
                 f"(local {meta.get('generated_local')})", width)
    _append_row(lines, "Version", f"{meta.get('version')} "
                 f"(code {meta.get('code_version')})", width)
    _append_row(lines, "OS", f"{meta.get('distro')} [{meta.get('os')}] "
                 f"{meta.get('platform')}", width)
    _append_row(lines, "Python", f"{meta.get('python')} "
                 f"({meta.get('python_executable')})", width)
    _append_row(lines, "Terminal", meta.get("terminal"), width)
    if meta.get("elapsed_s") is not None:
        _append_row(lines, "Duration", f"{meta['elapsed_s']} s", width)
    counts = _counts(coded)
    _append_row(lines, "Summary",
                f"{counts.get(PASS, 0)} PASS / {counts.get(WARN, 0)} WARN / "
                f"{counts.get(FAIL, 0) + counts.get(ERROR, 0)} FAIL / "
                f"{counts.get(SKIP, 0)} SKIP", width)
    lines.append(banner)
    lines.append("")

    for key, title in _SECTIONS:
        section_entries = [entry for entry in coded
                           if entry.get("section") == key]
        if not section_entries:
            continue
        aggregate = _section_status(section_entries)
        head = f"[{title}]"
        fill = width - len(head) - len(aggregate) - 2
        lines.append(head + " " + "-" * max(3, fill) + " " + aggregate)
        for entry in section_entries:
            lines.extend(_entry_lines(entry, width))
        lines.append("")

    # ── VERDICT ──
    lines.append(banner)
    lines.append("VERDICT")
    lines.append("")
    for key, title in _SECTIONS:
        section_entries = [entry for entry in coded
                           if entry.get("section") == key]
        if not section_entries:
            continue
        aggregate = _section_status(section_entries)
        failures = sum(1 for entry in section_entries
                       if entry.get("status") in _BAD)
        warnings = sum(1 for entry in section_entries
                       if entry.get("status") == WARN)
        if failures:
            detail = f"{failures} failure(s), {warnings} warning(s)"
        elif warnings:
            detail = f"{warnings} warning(s)"
        else:
            detail = "ok"
        lines.append(f"  {title:<24}{aggregate:<6}{detail}"[:width])
    lines.append("")
    fixes = [entry for entry in coded
             if entry.get("status") in _BAD or entry.get("status") == WARN]
    fixes = [entry for entry in fixes if entry.get("action")]
    # Failures first: the user fixes what blocks playback before cosmetics.
    fixes.sort(key=lambda entry: (0 if entry.get("status") in _BAD else 1))
    if fixes:
        lines.append("  FIXES (run these in order):")
        for entry in fixes[:20]:
            text = f"[{entry.get('code')}] {_entry_title(entry)}"
            chunks = _wrap_text(text, width - 6)
            lines.append("   - " + chunks[0])
            for chunk in chunks[1:]:
                lines.append("     " + chunk)
            action_prefix = "       -> "
            for index, chunk in enumerate(
                    _wrap_text(entry.get("action"), width
                               - len(action_prefix))):
                lines.append((action_prefix if index == 0
                              else " " * len(action_prefix)) + chunk)
        if len(fixes) > 20:
            lines.append(f"   ... and {len(fixes) - 20} more fix(es) above.")
    else:
        lines.append("  FIXES: none - no action required.")
    lines.append("")
    lines.append(banner)
    lines.append("HOW TO REPORT A BUG")
    for chunk in _wrap_text(
            "Open an issue and paste this whole report (plain text, no "
            "tokens or passwords are included): " + _ISSUES_URL, width - 2):
        lines.append("  " + chunk)
    for chunk in _wrap_text(
            "Commands: freeflix --doctor --report [file]  |  "
            "freeflix --doctor --json  |  freeflix --doctor --sources  |  "
            "freeflix --doctor --players", width - 2):
        lines.append("  " + chunk)
    try:
        log_path = _app_paths()["log"]
        for chunk in _wrap_text(f"Log file: {log_path}", width - 2):
            lines.append("  " + chunk)
    except Exception:
        pass
    lines.append(banner)
    return "\n".join(line[:width] for line in lines)


def collect_report(network: bool = True, sources: bool = False,
                   players: bool = False, budget: float = 60.0) -> list:
    """Run every collector; a broken collector becomes one ERROR entry."""
    collectors = (
        ("install", collect_install),
        ("system", collect_system),
        ("config", collect_config),
        ("binaries", collect_binaries),
        ("players", collect_players),
        ("mpv", collect_mpv),
        ("proxy", collect_proxy),
        ("network", collect_network if network else None),
        ("terminal", collect_terminal),
        ("logs", collect_logs),
        ("state", collect_state),
        ("windows", collect_windows),
    )
    entries: list = []
    for key, collector in collectors:
        if collector is None:
            entries.append(_entry(key, "network", SKIP,
                                  "skipped (--no-network)"))
            continue
        try:
            entries.extend(collector() or [])
        except Exception as exc:  # noqa: BLE001 - never lose the report
            entries.append(_entry(key, "collector", ERROR,
                                  f"{type(exc).__name__}: {exc}",
                                  "report this at " + _ISSUES_URL))
    try:
        entries.extend(collect_sources(
            requested=sources, deep=players or sources, budget=budget))
    except Exception as exc:  # noqa: BLE001
        entries.append(_entry("sources", "collector", ERROR,
                              f"{type(exc).__name__}: {exc}",
                              "report this at " + _ISSUES_URL))
    return entries


def _as_json(entries: list, meta: dict) -> dict:
    coded = _assign_codes(entries)
    counts = _counts(coded)
    verdict = {}
    for key, _title in _SECTIONS:
        section_entries = [entry for entry in coded
                           if entry.get("section") == key]
        if section_entries:
            verdict[key] = _section_status(section_entries)
    report = dict(meta)
    report["summary"] = counts
    report["verdict"] = verdict
    report["checks"] = [
        {
            "code": entry.get("code"),
            "section": entry.get("section"),
            "label": entry.get("label"),
            "status": entry.get("status"),
            "detail": entry.get("detail"),
            "action": entry.get("action"),
        }
        for entry in coded
    ]
    return report


def _default_report_name() -> str:
    try:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    except Exception:
        stamp = "report"
    return f"freeflix-doctor-{stamp}.txt"


def _write_report_file(text: str, target) -> Path:
    path = Path(os.path.expanduser(str(target)))
    if path.is_dir():
        path = path / _default_report_name()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    path.write_text(text, encoding="utf-8", errors="replace")
    return path


def _safe_print(text: str, stream=None) -> None:
    """print() that can never crash on a cp1252/ASCII console."""
    stream = stream or sys.stdout
    payload = str(text)
    if not payload.endswith("\n"):
        payload += "\n"
    try:
        stream.write(payload)
        stream.flush()
    except UnicodeEncodeError:
        try:
            encoding = getattr(stream, "encoding", None) or "ascii"
            fallback = payload.encode(encoding, "replace").decode(
                encoding, "replace")
            stream.write(fallback)
            stream.flush()
        except Exception:
            pass
    except Exception:
        pass


def run(upload: bool = False, sources: bool = False,
        players: bool = False, network: bool = True,
        report_path=None) -> str:
    """Run diagnostics and return the report as a string."""
    import time as _time

    started = _time.monotonic()
    entries = collect_report(network=network, sources=sources,
                             players=players)
    meta = _meta(elapsed=_time.monotonic() - started)
    report = _render(entries, meta)
    if report_path:
        try:
            _write_report_file(report, report_path)
        except Exception:
            pass
    if upload:
        gist_url = _upload_gist(report)
        if gist_url:
            report += f"\nUploaded to: {gist_url}\n"
    return report


def run_json(sources: bool = False, players: bool = False,
             network: bool = True) -> str:
    """Machine-readable report (stable schema 'freeflix.doctor/1')."""
    import time as _time

    started = _time.monotonic()
    entries = collect_report(network=network, sources=sources,
                             players=players)
    meta = _meta(elapsed=_time.monotonic() - started)
    return json.dumps(_as_json(entries, meta), ensure_ascii=True,
                      indent=2, default=str)


def _upload_gist(content: str) -> str | None:
    """Upload report as a secret GitHub Gist (needs ``gh`` CLI)."""
    gist = shutil.which("gh")
    if not gist:
        return None
    try:
        result = subprocess.run(
            [
                "gh",
                "gist",
                "create",
                "--filename",
                f"freeflix-doctor-{datetime.now():%Y%m%d}.txt",
            ],
            input=content,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8", errors="replace",
        )
        url = (result.stdout or "").strip()
        if url.startswith("https://"):
            return url
    except Exception:
        pass
    return None


def check_sources(deep: bool = True) -> str:
    """Live source self-test as a shareable report (legacy entry point)."""
    entries = collect_sources(requested=True, deep=deep)
    return _render(entries, _meta())


# ── CLI ──────────────────────────────────────────────────────────────
def _usage_text() -> str:
    return "\n".join((
        "freeflix --doctor                 full diagnostic report "
        "(the shareable one)",
        "freeflix --doctor --sources       + live source search probes",
        "freeflix --doctor --players       + player/stream resolution per "
        "source (implies --sources)",
        "freeflix --doctor --report [file] write the report to a .txt file "
        "ready to paste",
        "freeflix --doctor --json          machine-readable JSON on stdout",
        "freeflix --doctor --upload        also upload it as a secret Gist "
        "(needs gh)",
        "freeflix --doctor --no-network    skip network probes (fast/offline)",
        "",
        "Examples:",
        "  freeflix --doctor --report",
        "  freeflix --doctor --report ~/Desktop/freeflix.txt",
        "  freeflix --doctor --sources --upload",
    ))


def _parse_doctor_args(argv) -> dict:
    options = {
        "sources": False,
        "players": False,
        "upload": False,
        "json": False,
        "report": False,
        "report_path": None,
        "no_network": False,
        "help": False,
    }
    index = 0
    while index < len(argv):
        argument = str(argv[index])
        if argument in ("--sources", "-s"):
            options["sources"] = True
        elif argument in ("--players", "--streams"):
            options["players"] = True
            options["sources"] = True
        elif argument == "--upload":
            options["upload"] = True
        elif argument == "--json":
            options["json"] = True
        elif argument == "--no-network":
            options["no_network"] = True
        elif argument in ("--help", "-h"):
            options["help"] = True
        elif argument == "--report":
            options["report"] = True
            if index + 1 < len(argv) and not str(argv[index + 1]).startswith("-"):
                options["report_path"] = str(argv[index + 1])
                index += 1
        elif argument.startswith("--report="):
            options["report"] = True
            value = argument.split("=", 1)[1].strip()
            options["report_path"] = value or None
        index += 1
    return options


def _silence_mouse_atexit() -> None:
    """Drop cli_utils' mouse-off atexit hook.

    Doctor never enables mouse tracking, but importing any app module pulls
    cli_utils in, whose exit hook writes raw escape sequences to stdout. When
    the report is redirected to a file (`freeflix --doctor > report.txt`) those
    bytes would end up pasted into support tickets.
    """
    try:
        import atexit
        from . import cli_utils
        atexit.unregister(cli_utils._mouse_off)
    except Exception:
        pass


def cli_doctor():
    """Entry point for ``freeflix --doctor``."""
    import time as _time

    _silence_mouse_atexit()
    options = _parse_doctor_args(sys.argv[1:])
    if options["help"]:
        _safe_print(_usage_text())
        return 0

    started = _time.monotonic()
    try:
        entries = collect_report(
            network=not options["no_network"],
            sources=options["sources"],
            players=options["players"],
        )
    except Exception as exc:  # noqa: BLE001 - doctor must always report
        entries = [_entry("install", "doctor", ERROR,
                          f"{type(exc).__name__}: {exc}",
                          "report this at " + _ISSUES_URL)]
    meta = _meta(elapsed=_time.monotonic() - started)

    saved_path = None
    if options["report"]:
        try:
            saved_path = _write_report_file(
                _render(entries, meta),
                options["report_path"] or _default_report_name())
        except Exception as exc:  # noqa: BLE001
            _safe_print(f"Could not write report file: "
                        f"{type(exc).__name__}: {exc}", sys.stderr)

    upload_url = None
    if options["upload"]:
        try:
            upload_url = _timed(
                lambda: _upload_gist(_render(entries, meta)), 40.0)
        except Exception:
            upload_url = None

    if options["json"]:
        _safe_print(json.dumps(_as_json(entries, meta), ensure_ascii=True,
                               indent=2, default=str))
    else:
        report = _render(entries, meta)
        if upload_url:
            report += f"\nUploaded to: {upload_url}\n"
        _safe_print(report)
    if saved_path:
        _safe_print(f"Report written to: {saved_path}", sys.stderr)
    if options["upload"] and not upload_url:
        _safe_print("Upload skipped: 'gh' CLI not found or not "
                    "authenticated (run: gh auth login)", sys.stderr)
    return 0
