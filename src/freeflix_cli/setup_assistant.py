"""
Cross-platform setup assistant for FreeFlix.

Triggered on first launch (or via `freeflix --setup`). Detects OS + GPU,
downloads & installs the tuned mpv.conf / input.conf / lua hook /
Anime4K Mode A_S shaders to the user's mpv config dir. On Linux, also
installs PRIME render-offload wrappers when a discrete Nvidia/AMD GPU
is detected so standalone mpv calls also use the dGPU.

No package-data bundling : we fetch the configs straight from this
repo's main branch, which keeps the wheel small.
"""

from __future__ import annotations

import os
import re
import sys
import time
import shutil
import platform
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict

from .cli_utils import print_info, print_success, print_warning
from .tracker import tracker
from .i18n import t


REPO_RAW = "https://raw.githubusercontent.com/freedy237/freeflix-cli/main"
ANIME4K_RAW = "https://raw.githubusercontent.com/bloc97/Anime4K/master/glsl"


# ─── OS detection ─────────────────────────────────────────────────────
def detect_os() -> str:
    """Return 'linux', 'macos', 'windows', or 'unknown'."""
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform in ("win32", "cygwin"):
        return "windows"
    return "unknown"


def detect_arch() -> str:
    """Return a normalised CPU arch : 'x86_64' or 'arm64' (else the raw name).

    Used to pick arch-appropriate managed binaries (an x86_64 ffmpeg won't run
    on an aarch64 box). platform.machine() reports the CPU, not the Python build.
    """
    m = (platform.machine() or "").lower()
    if m in ("x86_64", "amd64", "x64", "i386", "i686"):
        return "x86_64"
    if m in ("aarch64", "arm64", "armv8", "armv8l", "armv8b"):
        return "arm64"
    return m or "x86_64"


# ─── GPU detection ────────────────────────────────────────────────────
def detect_gpus() -> Dict[str, bool]:
    """Return flags : nvidia, amd_discrete, intel_integrated, apple_silicon."""
    flags = {
        "nvidia": False,
        "amd_discrete": False,
        "intel_integrated": False,
        "apple_silicon": False,
    }
    os_name = detect_os()

    # Nvidia : universal — `nvidia-smi` returns 0 only if drivers are installed
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0 and "GPU" in r.stdout:
                flags["nvidia"] = True
        except Exception:
            pass

    if os_name == "linux":
        if shutil.which("lspci"):
            try:
                r = subprocess.run(
                    ["lspci", "-nn"], capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0:
                    lines = r.stdout.lower().splitlines()
                    for line in lines:
                        if " amd " in f" {line} " or "ati " in line or "radeon" in line:
                            if "vga" in line or "3d controller" in line or "display" in line:
                                flags["amd_discrete"] = True
                        if "intel" in line and ("graphics" in line or "vga" in line):
                            flags["intel_integrated"] = True
            except Exception:
                pass

    elif os_name == "macos":
        try:
            r = subprocess.run(["uname", "-m"], capture_output=True, text=True, timeout=2)
            if "arm64" in r.stdout:
                flags["apple_silicon"] = True
        except Exception:
            pass

    elif os_name == "windows":
        # Use PowerShell instead of wmic (deprecated on Win11)
        try:
            r = subprocess.run(
                ["powershell", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=8,
            )
            out = (r.stdout or "").lower()
            if "nvidia" in out or "geforce" in out or "quadro" in out:
                flags["nvidia"] = True
            if "amd" in out or "radeon" in out:
                flags["amd_discrete"] = True
            if "intel" in out and ("graphics" in out or "hd " in out or "iris" in out):
                flags["intel_integrated"] = True
        except Exception:
            pass

    return flags


# ─── Paths ────────────────────────────────────────────────────────────
def get_mpv_config_dir() -> Path:
    """
    Return FreeFlix's DEDICATED mpv config dir (not the global one).
    mpv is launched by FreeFlix with --config-dir pointing here, so our
    tuned config (Anime4K, big cache, position hook) applies ONLY to
    FreeFlix playback — the user's normal `mpv file.mkv` stays vanilla.

    Linux/macOS : ~/.config/freeflix/mpv
    Windows     : %APPDATA%/freeflix/mpv
    """
    if detect_os() == "windows":
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return Path(appdata) / "freeflix" / "mpv"
    return Path.home() / ".config" / "freeflix" / "mpv"


def get_local_bin_dir() -> Path:
    """Where to drop PRIME wrappers — Linux only."""
    return Path.home() / ".local" / "bin"


# ─── State checks ─────────────────────────────────────────────────────
def is_setup_complete() -> bool:
    """True if mpv.conf + at least one Anime4K shader are installed."""
    cfg = get_mpv_config_dir()
    if not (cfg / "mpv.conf").exists():
        return False
    shaders = cfg / "shaders"
    if not shaders.exists() or not any(shaders.glob("Anime4K_*.glsl")):
        return False
    return True


# ─── Self-managed binary directory ────────────────────────────────────
def _bin_dir() -> Path:
    """Return FreeFlix's managed binary directory (created on demand)."""
    from platformdirs import user_data_dir
    return Path(user_data_dir("freeflix-cli", "PaulExplorer")) / "bin"


def _ensure_bin_dir() -> Path:
    d = _bin_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _managed_bin(bin_name: str) -> Path:
    """Path to a managed binary inside our bin dir."""
    return _bin_dir() / bin_name


def _have_managed(bins: tuple[str, ...]) -> bool:
    """Check if any of the given binary names exist in our managed dir."""
    bd = _bin_dir()
    if not bd.is_dir():
        return False
    is_win = sys.platform in ("win32", "cygwin")
    for b in bins:
        if is_win and not b.endswith(".exe"):
            b += ".exe"
        if (bd / b).is_file():
            return True
    return False


# ─── Self-managed binary sources (per-OS download URLs) ─────────────
# Each entry: label -> {url, type, binary, extras}
#   url     : download URL of the archive
#   type    : "tar.xz" | "tar.gz" | "zip"
#   binary  : name of the executable inside the archive
#   extras  : additional executables to also extract (e.g. ffprobe)
#
# Only ffmpeg + aria2c + mpv are self-managed.
# Entries below are the x86_64 defaults ; _binary_sources_for() swaps in the
# arm64 ffmpeg build on aarch64 (see detect_arch / _FFMPEG_ARM64_URL).
_BINARY_SOURCES: dict[str, dict[str, dict]] = {
    "linux": {
        "ffmpeg": {
            "url": "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl.tar.xz",  # noqa: E501
            "type": "tar.xz", "binary": "ffmpeg", "extras": ["ffprobe"],
        },
        # NOTE: mpv AND aria2 are NOT self-managed on Linux — the static builds
        # we used vanished (coletrammer/mpv-static and q3aql/aria2-static-builds
        # both 404 now). Both ship in every distro's repos, so they're installed
        # via the package manager instead (see _linux_install_missing).
        # Only ffmpeg (BtbN, still maintained) stays self-managed.
    },
    "macos": {
        "ffmpeg": {
            "url": "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v6.1/ffmpeg-6.1-macos-64.zip",
            "type": "zip", "binary": "ffmpeg", "extras": [],
        },
        # aria2c: no reliable static macOS build available
        "mpv": {
            "url": "https://github.com/mpv-player/mpv/releases/download/v0.41.0/mpv-v0.41.0-macos-15-intel.zip",
            "type": "zip", "binary": "mpv", "extras": [],
        },
    },
    "windows": {
        "ffmpeg": {
            "url": "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip",
            "type": "zip", "binary": "ffmpeg.exe", "extras": ["ffprobe.exe"],
        },
        "aria2c": {
            "url": "https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip",
            "type": "zip", "binary": "aria2c.exe", "extras": [],
        },
        # chafa: no Windows binary in official releases (source-only)
        "mpv": {
            "url": "https://github.com/mpv-player/mpv/releases/download/v0.41.0/mpv-v0.41.0-x86_64-w64-mingw32.zip",
            "type": "zip", "binary": "mpv.exe", "extras": [],
        },
    },
}


# ─── Archive extraction helpers ──────────────────────────────────────
def _find_in_tar(archive: Path, target: str) -> Path | None:
    """Find *target* (exact basename) inside a tar.xz/tar.gz and extract to a temp dir right next to it.  Returns the extracted path or None."""  # noqa: E501
    import tarfile
    parent = archive.parent
    try:
        with tarfile.open(archive, "r:*") as tar:
            for m in tar.getmembers():
                if m.name.endswith(f"/{target}") or m.name == target:
                    tar.extract(m, parent, filter="data")
                    return parent / m.name
    except Exception:
        return None
    return None


def _find_in_zip(archive: Path, target: str) -> Path | None:
    """Same as _find_in_tar but for zip archives."""
    import zipfile
    parent = archive.parent
    try:
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                if name.endswith(f"/{target}") or name == target:
                    zf.extract(name, parent)
                    return parent / name
    except Exception:
        return None
    return None


def _download_and_install_binary(label: str, info: dict) -> bool:
    """Download a managed binary from *info["url"]*, extract, place in our bin dir.

    Returns True on success.
    """
    import tempfile

    url = info["url"]
    bin_target = info["binary"]
    extras = info.get("extras", [])
    arc_type = info["type"]

    with tempfile.TemporaryDirectory(prefix="freeflix-") as _td:
        tmp = Path(_td)
        arc_path = tmp / f"archive.{arc_type}"

        _download(url, arc_path)
        if not arc_path.is_file():
            return False

        if arc_type in ("tar.xz", "tar.gz"):
            extracted = _find_in_tar(arc_path, bin_target)
        elif arc_type == "zip":
            extracted = _find_in_zip(arc_path, bin_target)
        else:
            return False

        if extracted is None or not extracted.is_file():
            return False

        _ensure_bin_dir()
        shutil.copy2(extracted, _managed_bin(bin_target))
        _managed_bin(bin_target).chmod(0o755)

        for extra in extras:
            ex = _find_in_tar(arc_path, extra) if arc_type in ("tar.xz", "tar.gz") else _find_in_zip(arc_path, extra)
            if ex and ex.is_file():
                shutil.copy2(ex, _managed_bin(extra))
                _managed_bin(extra).chmod(0o755)

        return _managed_bin(bin_target).is_file()


_LABEL_TO_SOURCE = {
    "player": "mpv",
    "ffmpeg": "ffmpeg",
    "aria2": "aria2c",
}

# ffmpeg (BtbN) ships arch-specific builds ; swap the URL on arm64 so aarch64
# machines get a runnable binary instead of an x86_64 one.
_FFMPEG_ARM64_URL = {
    "linux": "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linuxarm64-gpl.tar.xz",  # noqa: E501
    "windows": "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-winarm64-gpl.zip",  # noqa: E501
}


def _binary_sources_for(os_name: str) -> dict:
    """Managed-binary sources for *os_name*, adjusted for the CPU arch.

    On arm64 we swap in the aarch64 ffmpeg build. mpv/aria2 have no official
    arm64 archive : on Linux they come from the package manager (arch-agnostic),
    and on Windows-on-ARM the x64 builds run under the OS's built-in emulation,
    so the x86_64 entries are kept as-is.
    """
    import copy
    sources = copy.deepcopy(_BINARY_SOURCES.get(os_name, {}))
    if detect_arch() == "arm64":
        arm_ffmpeg = _FFMPEG_ARM64_URL.get(os_name)
        if arm_ffmpeg and "ffmpeg" in sources:
            sources["ffmpeg"]["url"] = arm_ffmpeg
    return sources


def _auto_install_managed(os_name: str) -> None:
    """Install every missing tool that has a self-managed source for *os_name*."""
    sources = _binary_sources_for(os_name)

    # Ensure the bin dir exists early so tools can be placed there
    _ensure_bin_dir()

    if not sources:
        return

    for label, _id, bins in missing_tools():
        src_key = _LABEL_TO_SOURCE.get(label)
        if not src_key or src_key not in sources:
            continue
        info = sources[src_key]
        if _have_managed(bins):
            continue
        print_info(f"  Installing {label} …")
        ok = _download_and_install_binary(src_key, info)
        if ok:
            print_success(f"  ✓ {label}")
        else:
            print_warning(f"  ✗ {label} (download failed)")


# ─── Version helper for cache invalidation ────────────────────────────
def _get_installed_version() -> str:
    """Return the installed freeflix-cli version, or 'dev' if unknown."""
    try:
        import importlib.metadata as _im
        return _im.version("freeflix-cli")
    except Exception:
        return "dev"


# ─── Runtime dependency gate (idempotent / resumable) ─────────────────
# label -> (winget id for Windows, acceptable binary names, essential?)
# Essential tools gate playback ; the rest are quality-of-life (posters,
# faster downloads) and never block.
_TOOLS = [
    ("player",  "mpv.net",         ("mpvnet", "mpv", "vlc"), True),
    ("yt-dlp",  "yt-dlp.yt-dlp",   ("yt-dlp",),              True),
    ("ffmpeg",  "Gyan.FFmpeg",     ("ffmpeg",),              True),
    ("aria2",   "aria2.aria2",     ("aria2c",),              False),
    ("chafa",   "hpjansson.Chafa", ("chafa",),               False),
]


def _have(bins) -> bool:
    if any(shutil.which(b) for b in bins) or _have_managed(bins):
        return True
    # Windows: mpv.net / VLC are often installed OUTSIDE PATH (winget links dir,
    # Program Files…). Resolve them via their known locations so a real install
    # isn't reported missing (which kept re-triggering the player install).
    if sys.platform in ("win32", "cygwin") and any(
        b in ("mpvnet", "mpv", "vlc") for b in bins
    ):
        try:
            from .player_manager import get_mpv_path, get_vlc_path
            if get_mpv_path() or get_vlc_path():
                return True
        except Exception:
            pass
    return False


def missing_essential_tools() -> list:
    """Essential tools that aren't on PATH (empty list == ready to play)."""
    return [label for (label, _id, bins, ess) in _TOOLS if ess and not _have(bins)]


def missing_tools() -> list:
    """All tools (essential + optional) that aren't installed yet."""
    return [(label, _id, bins) for (label, _id, bins, _e) in _TOOLS if not _have(bins)]


def runtime_ready() -> bool:
    return not missing_essential_tools()


def _winget_install(pkg_id: str) -> None:
    try:
        # capture_output so winget's own logs don't fight the loading screen.
        subprocess.run(
            ["winget", "install", "--silent",
             "--accept-source-agreements", "--accept-package-agreements",
             "--id", pkg_id],
            check=False, capture_output=True, text=True,
        )
    except Exception:
        pass


def ensure_runtime_deps(auto_install: bool = True) -> bool:
    """
    Resumable dependency gate, run on every launch until it succeeds ONCE.

    Behaviour the user asked for : as long as the "all good" flag isn't cached,
    each launch re-checks what's already installed and installs ONLY what's
    still missing (it never restarts a finished install, and it never jumps
    ahead while essential tools are absent). Once everything essential is
    present, ``system_deps_ok`` is cached so future launches short-circuit
    instantly.

    Returns True when the essential tools (a player + yt-dlp + ffmpeg) exist.
    """
    _version = _get_installed_version()
    _cached_version = tracker.data.get("system_deps_ok_version")

    # Invalidate cache on version change — new version may have added
    # or removed dependencies in _TOOLS.
    if _cached_version is not None and _cached_version != _version:
        tracker.data.pop("system_deps_ok", None)
        tracker.data.pop("system_deps_ok_version", None)
        tracker._save_data()

    if tracker.data.get("system_deps_ok"):
        return True
    if runtime_ready():
        tracker.data["system_deps_ok"] = True
        tracker.data["system_deps_ok_version"] = _version
        tracker._save_data()
        return True

    os_name = detect_os()

    # ── Self-managed binaries (primary) ────────────────────────────
    # Download static builds from GitHub Releases into our own bin dir.
    # Works on all OS, no sudo required.
    if auto_install:
        _auto_install_managed(os_name)

    # ── Windows winget fallback ────────────────────────────────────
    if auto_install and os_name == "windows" and shutil.which("winget"):
        todo = missing_tools()
        if todo:
            from . import progress as _progress
            with _progress.LoadingScreen(status="Installing dependencies…") as _ls:
                total = len(todo)
                for i, (label, pkg_id, bins) in enumerate(todo):
                    # Target the NEXT milestone so the bar keeps CLIMBING
                    # smoothly toward it while this tool installs (winget gives
                    # no real %), instead of sitting then jumping.
                    _ls.status(f"Installing {label}… ({i + 1}/{total})",
                               frac=(i + 1) / total)
                    if not _have(bins):
                        _winget_install(pkg_id)
                _ls.status("Finishing up…", frac=1.0)
                time.sleep(0.5)

    if runtime_ready():
        tracker.data["system_deps_ok"] = True
        tracker.data["system_deps_ok_version"] = _version
        tracker._save_data()
        print_success(t("All required tools are installed."))
        return True

    # Still missing essentials → guide, and DON'T cache, so the next launch
    # picks up where this one left off.
    missing_ess = missing_essential_tools()
    print_warning(t("Some required tools are still missing:") + " "
                  + ", ".join(missing_ess))
    if os_name == "windows":
        print_info(t("Run this (re-runnable — installs only what's missing):"))
        print_info("  powershell -ExecutionPolicy Bypass -File scripts\\install.ps1")
        print_info(t("then open a NEW Windows Terminal and run:  freeflix"))
    elif os_name == "linux":
        # Try to auto-install via the package manager (mpv etc.), then re-check.
        if _linux_install_missing(missing_ess) and runtime_ready():
            tracker.data["system_deps_ok"] = True
            tracker.data["system_deps_ok_version"] = _version
            tracker._save_data()
            print_success(t("All required tools are installed."))
            return True
        _show_linux_commands(missing_ess)
    elif os_name == "macos":
        print_info(t("Run the installer:  ./scripts/install-mac.sh"))
    return False


# ─── Downloads ────────────────────────────────────────────────────────
def _download(url: str, dest: Path) -> bool:
    """Download `url` into `dest`. Returns True on success."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=30) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return True
    except Exception as e:
        print_warning(f"Could not download {url} ({type(e).__name__}: {e})")
        return False


def install_config_files() -> bool:
    """Pull mpv.conf, input.conf and the lua hook from the repo."""
    cfg = get_mpv_config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "scripts").mkdir(parents=True, exist_ok=True)

    ok = True
    files = [
        (f"{REPO_RAW}/config/mpv.conf",                  cfg / "mpv.conf"),
        (f"{REPO_RAW}/config/input.conf",                cfg / "input.conf"),
        (f"{REPO_RAW}/config/freeflix_position.lua",     cfg / "scripts" / "freeflix_position.lua"),
    ]
    for url, dest in files:
        if _download(url, dest):
            print_success(f"  ✓ {dest}")
        else:
            ok = False
    return ok


def install_anime4k_shaders() -> bool:
    """Download Mode A_S shaders (lighter) from bloc97's repo."""
    cfg = get_mpv_config_dir()
    sh_dir = cfg / "shaders"
    sh_dir.mkdir(parents=True, exist_ok=True)

    ok = True
    shaders = [
        (f"{ANIME4K_RAW}/Restore/Anime4K_Clamp_Highlights.glsl",  sh_dir / "Anime4K_Clamp_Highlights.glsl"),
        (f"{ANIME4K_RAW}/Restore/Anime4K_Restore_CNN_S.glsl",     sh_dir / "Anime4K_Restore_CNN_S.glsl"),
        (f"{ANIME4K_RAW}/Restore/Anime4K_Restore_CNN_VL.glsl",    sh_dir / "Anime4K_Restore_CNN_VL.glsl"),
        (f"{ANIME4K_RAW}/Upscale/Anime4K_Upscale_CNN_x2_S.glsl",  sh_dir / "Anime4K_Upscale_CNN_x2_S.glsl"),
        (f"{ANIME4K_RAW}/Upscale/Anime4K_Upscale_CNN_x2_VL.glsl", sh_dir / "Anime4K_Upscale_CNN_x2_VL.glsl"),
    ]
    for url, dest in shaders:
        if _download(url, dest):
            print_success(f"  ✓ {dest.name}")
        else:
            ok = False
    return ok


def _linux_pkg_cmd(pkg: str):
    """Return the install command for `pkg` for the detected package manager."""
    candidates = [
        ("dnf", ["sudo", "dnf", "install", "-y", pkg]),
        ("apt-get", ["sudo", "apt-get", "install", "-y", pkg]),
        ("pacman", ["sudo", "pacman", "-S", "--needed", "--noconfirm", pkg]),
        ("zypper", ["sudo", "zypper", "install", "-y", pkg]),
        ("apk", ["sudo", "apk", "add", pkg]),
    ]
    for binname, cmd in candidates:
        if shutil.which(binname):
            return cmd
    return None


def _linux_chafa_cmd():
    """Return the install command for chafa for the detected package manager."""
    return _linux_pkg_cmd("chafa")


def _linux_install_missing(missing_ess: list) -> bool:
    """
    Auto-install missing essentials (mpv, ffmpeg…) via the distro package
    manager. Asks once, then runs `sudo <pm> install …` (sudo prompts for the
    password). Returns True only if an install command actually ran to success.
    Falls back to False (caller then prints the manual command).
    """
    pkg_map = {"player": "mpv", "ffmpeg": "ffmpeg", "aria2": "aria2"}
    pkgs = [pkg_map.get(t, t) for t in missing_ess]
    # aria2 isn't "essential" (HLS uses yt-dlp natively) but it's the fast path
    # for direct .mp4 — grab it too while the package manager is open.
    if not _have(("aria2c",)) and "aria2" not in pkgs:
        pkgs.append("aria2")
    # VLC is the fallback player (install.sh / install-mac.sh / Windows players
    # already pull it) — add it here too so the uv-based install has parity.
    if not _have(("vlc",)) and "vlc" not in pkgs:
        pkgs.append("vlc")
    if not pkgs:
        return False

    managers = [
        ("apt-get", ["sudo", "apt-get", "install", "-y", *pkgs]),
        ("dnf",     ["sudo", "dnf", "install", "-y", *pkgs]),
        ("pacman",  ["sudo", "pacman", "-S", "--needed", "--noconfirm", *pkgs]),
        ("zypper",  ["sudo", "zypper", "install", "-y", *pkgs]),
        ("apk",     ["sudo", "apk", "add", *pkgs]),
    ]
    chosen = next(((b, c) for b, c in managers if shutil.which(b)), None)
    if not chosen:
        return False

    if not sys.stdin.isatty():
        return False
    try:
        ans = input(
            f"Install missing tools ({', '.join(pkgs)}) now via "
            f"{chosen[0]}? [Y/n] "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if ans in ("n", "no"):
        return False

    print_info(f"Installing {', '.join(pkgs)} (sudo may ask your password)…")
    try:
        return subprocess.run(chosen[1]).returncode == 0
    except Exception as e:
        print_warning(f"Auto-install failed: {e}")
        return False


def _show_linux_commands(missing_ess: list[str]):
    """Print distro-specific install commands for missing essential tools."""
    pkg_map = {"player": "mpv", "ffmpeg": "ffmpeg"}
    pkg_names = [pkg_map.get(tool, tool) for tool in missing_ess]
    # Try each package manager until one works
    candidates = [
        ("apt-get", "sudo apt-get install -y " + " ".join(pkg_names)),
        ("dnf",     "sudo dnf install -y " + " ".join(pkg_names)),
        ("pacman",  "sudo pacman -S --needed --noconfirm " + " ".join(pkg_names)),
        ("zypper",  "sudo zypper install -y " + " ".join(pkg_names)),
        ("apk",     "sudo apk add " + " ".join(pkg_names)),
    ]
    pm_found = False
    for binname, cmd_str in candidates:
        if shutil.which(binname):
            print_info(f"Install via {binname}:")
            print_info(f"  {cmd_str}")
            pm_found = True
            break
    if not pm_found:
        print_info(t("Run the installer:  ./scripts/install.sh"))


# Per-OS install command for the media players FreeFlix can launch.
_PLAYER_PACKAGES = {
    "mpv": {"linux": "mpv", "macos": "mpv", "winget": "mpv.net"},
    "vlc": {"linux": "vlc", "macos": "vlc", "winget": "VideoLAN.VLC"},
}


def install_media_player(name: str) -> bool:
    """
    Install a media player (mpv / vlc) via the OS package manager. Interactive
    (asks first). Returns True if the player ends up available afterwards.

    Used both by the first-run wizard and on-demand at playback time when the
    chosen player turns out to be missing.
    """
    spec = _PLAYER_PACKAGES.get(name)
    if not spec:
        return False

    os_name = detect_os()
    if os_name == "linux":
        cmd = _linux_pkg_cmd(spec["linux"])
    elif os_name == "macos":
        cmd = ["brew", "install", spec["macos"]] if shutil.which("brew") else None
    elif os_name == "windows":
        cmd = (
            ["winget", "install", "--silent", "--accept-source-agreements",
             "--accept-package-agreements", "--id", spec["winget"]]
            if shutil.which("winget") else None
        )
    else:
        cmd = None

    if not cmd:
        print_warning(
            f"No package manager found to install {name}. Install it manually, "
            "then try again."
        )
        return False

    try:
        ans = input(f"Install {name} now? ({' '.join(cmd)}) [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if ans in ("n", "no"):
        return False

    print_info(f"Installing {name}…")
    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        print_warning(f"{name} install failed ({type(e).__name__}: {e})")
        return False

    # Windows winget often needs a fresh shell for PATH ; mpv.net is mpvnet.exe.
    ok = bool(shutil.which(name) or (name == "mpv" and shutil.which("mpvnet")))
    if ok:
        print_success(f"  ✓ {name} installed")
    else:
        print_warning(
            f"  ! {name} installed but not yet on PATH — open a NEW terminal "
            "and relaunch freeflix."
        )
    return ok


def install_chafa() -> bool:
    """
    Install chafa (anime posters in the terminal) using the OS package
    manager. Interactive : asks before touching the system. Returns True
    if chafa ends up available.
    """
    if shutil.which("chafa"):
        print_success(t("chafa already installed — anime posters enabled"))
        return True

    os_name = detect_os()
    if os_name == "linux":
        cmd = _linux_chafa_cmd()
    elif os_name == "macos":
        cmd = ["brew", "install", "chafa"] if shutil.which("brew") else None
    elif os_name == "windows":
        cmd = (
            ["winget", "install", "--silent", "--accept-source-agreements",
             "--accept-package-agreements", "--id", "hpjansson.Chafa"]
            if shutil.which("winget") else None
        )
    else:
        cmd = None

    if not cmd:
        print_warning(
            "Could not find a package manager for chafa. Install it manually "
            "to enable anime posters (https://hpjansson.org/chafa/)."
        )
        return False

    print_info(t("chafa draws anime cover art inside the terminal (optional)."))
    try:
        ans = input(f"Install chafa now? ({' '.join(cmd)}) [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if ans in ("n", "no"):
        return False

    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        print_warning(f"chafa install failed ({type(e).__name__}: {e})")
        return False

    if shutil.which("chafa"):
        print_success("  ✓ chafa installed — anime posters enabled")
        return True
    print_warning("  ! chafa still not found — posters will stay off for now")
    return False


NERD_FONT_URL = (
    "https://github.com/ryanoasis/nerd-fonts/releases/latest/download/CascadiaCode.zip"
)
NERD_FONT_NAME = "CaskaydiaCove Nerd Font"
NERD_FONT_DIR = "CaskaydiaCoveNF"  # inside the zip


def detect_nerd_font() -> bool:
    """
    Check whether a Nerd Font (CaskaydiaCove) is already installed.
    Returns True/False.
    """
    os_name = detect_os()
    if os_name in ("linux", "macos"):
        try:
            out = subprocess.run(
                ["fc-list"], capture_output=True, text=True, timeout=10
            ).stdout
            import re
            return bool(re.search(r"(?i)CaskaydiaCove|Nerd Font", out))
        except Exception:
            return False
    if os_name == "windows":
        user_fonts = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Microsoft", "Windows", "Fonts",
        )
        if not user_fonts or not os.path.isdir(user_fonts):
            return False
        try:
            for f in os.listdir(user_fonts):
                if "CaskaydiaCove" in f and f.lower().endswith(".ttf"):
                    return True
        except Exception:
            pass
        sys_fonts = os.path.join(os.environ.get("WINDIR", ""), "Fonts")
        if sys_fonts and os.path.isdir(sys_fonts):
            try:
                for f in os.listdir(sys_fonts):
                    if "CaskaydiaCove" in f and f.lower().endswith(".ttf"):
                        return True
            except Exception:
                pass
        return False
    return False


def _set_windows_terminal_font(face: str) -> bool:
    """
    Point Windows Terminal at `face` so the Nerd glyphs actually render —
    installing/registering the font isn't enough, the terminal must USE it.
    Edits ``profiles.defaults.font.face`` in settings.json (backs it up first,
    strips JSONC comments). All settings are preserved; only comments/format
    are lost. Best-effort — returns True if at least one settings.json updated.
    """
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return False
    import glob as _glob
    import json
    from .config_loader import strip_json_comments, strip_trailing_commas

    candidates = _glob.glob(os.path.join(
        local, "Packages", "Microsoft.WindowsTerminal_*", "LocalState", "settings.json"
    )) + [os.path.join(local, "Microsoft", "Windows Terminal", "settings.json")]

    done = False
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            raw = open(path, "r", encoding="utf-8").read()
            data = json.loads(strip_trailing_commas(strip_json_comments(raw)))
            profiles = data.setdefault("profiles", {})
            if isinstance(profiles, list):  # very old schema
                profiles = {"defaults": {}, "list": profiles}
                data["profiles"] = profiles
            defaults = profiles.setdefault("defaults", {})
            font = defaults.get("font")
            if not isinstance(font, dict):
                font = {}
            font["face"] = face
            defaults["font"] = font
            try:
                if not os.path.exists(path + ".freeflix.bak"):
                    shutil.copy2(path, path + ".freeflix.bak")
            except Exception:
                pass
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            done = True
        except Exception:
            pass
    return done


def maybe_default_nerd_icons() -> None:
    """
    One-time, on first launch only : if a Nerd Font is already installed,
    default the icon style to 'nerd' (crisp glyphs). Skipped once the user (or
    this) has set ``icon_style`` — so a manual choice is always respected.
    """
    if "icon_style" in tracker.data:
        return
    try:
        if detect_nerd_font():
            tracker.data["icon_style"] = "nerd"
            tracker._save_data()
    except Exception:
        pass


def ensure_nerd_terminal_font() -> None:
    """
    Windows only, runs once : if icons are set to 'nerd' and a Nerd Font is
    installed but Windows Terminal isn't using it yet (older installs registered
    the font without setting the terminal's font), set it now so the glyphs
    render. Guarded by a flag so it never rewrites settings.json twice.
    """
    if detect_os() != "windows":
        return
    if tracker.data.get("wt_nerd_font_set"):
        return
    try:
        if tracker.get_icon_style() == "nerd" and detect_nerd_font():
            if _set_windows_terminal_font(NERD_FONT_NAME):
                tracker.data["wt_nerd_font_set"] = True
                tracker._save_data()
                print_info(
                    "Windows Terminal font set to the Nerd Font — reopen the "
                    "terminal to see the icons."
                )
    except Exception:
        pass


def install_nerd_font() -> bool:
    """
    Download and install CaskaydiaCove Nerd Font if missing.
    Interactive (Y/n). Returns True if font ends up available.
    """
    if detect_nerd_font():
        print_success(f"{NERD_FONT_NAME} already installed")
        # Already installed, but the terminal may still not USE it (older
        # installs registered the font without setting Windows Terminal's font).
        if detect_os() == "windows":
            if _set_windows_terminal_font(NERD_FONT_NAME):
                print_success("  ✓ Windows Terminal font set to the Nerd Font")
                print_warning(t("Close ALL Windows Terminal windows and reopen one."))
            else:
                print_info(
                    f"Set your terminal font to '{NERD_FONT_NAME}' manually."
                )
        return True

    os_name = detect_os()

    if os_name == "linux":
        dest = os.path.join(os.path.expanduser("~"), ".local", "share", "fonts")
        os.makedirs(dest, exist_ok=True)
        tmp = "/tmp/freeflix-nerdfont"
        zip_path = f"{tmp}.zip"
        print_info(t("Downloading CaskaydiaCove Nerd Font…"))
        try:
            urllib.request.urlretrieve(NERD_FONT_URL, zip_path)
            import zipfile
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(tmp)
            for f in os.listdir(tmp):
                if f.endswith(".ttf"):
                    shutil.copy2(os.path.join(tmp, f), os.path.join(dest, f))
            subprocess.run(["fc-cache", "-f", dest], capture_output=True, timeout=30)
            shutil.rmtree(tmp, ignore_errors=True)
            os.unlink(zip_path)
        except Exception as e:
            print_warning(f"Nerd Font install failed: {e}")
            shutil.rmtree(tmp, ignore_errors=True)
            return False

    elif os_name == "macos":
        if not shutil.which("brew"):
            print_warning(t("Homebrew not found — install it first: https://brew.sh"))
            return False
        cmd = ["brew", "install", "--quiet", "--cask", "font-caskaydia-cove-nerd-font"]
        print_info(t("Installing CaskaydiaCove Nerd Font via Homebrew…"))
        try:
            subprocess.run(cmd, check=False, timeout=120)
        except Exception as e:
            print_warning(f"Nerd Font install via brew failed: {e}")
            return False

    elif os_name == "windows":
        user_fonts = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Microsoft", "Windows", "Fonts",
        )
        if not user_fonts:
            print_warning(t("Could not find Windows fonts directory"))
            return False
        os.makedirs(user_fonts, exist_ok=True)
        zip_path = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "CascadiaCodeNF.zip")
        extract_dir = zip_path.replace(".zip", "")
        print_info(t("Downloading CaskaydiaCove Nerd Font…"))
        try:
            urllib.request.urlretrieve(NERD_FONT_URL, zip_path)
            import zipfile
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(extract_dir)
            import glob
            for ttf in glob.glob(os.path.join(extract_dir, "*.ttf")):
                shutil.copy2(ttf, os.path.join(user_fonts, os.path.basename(ttf)))
            import winreg
            reg_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE) as key:
                for ttf in glob.glob(os.path.join(user_fonts, "CaskaydiaCove*.ttf")):
                    name = os.path.basename(ttf).replace(".ttf", "") + " (TrueType)"
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, ttf)
            shutil.rmtree(extract_dir, ignore_errors=True)
            os.unlink(zip_path)
        except Exception as e:
            print_warning(f"Nerd Font install failed: {e}")
            return False

    else:
        print_warning(f"Unsupported OS ({os_name}) — install Nerd Font manually")
        return False

    if detect_nerd_font():
        print_success(f"  ✓ {NERD_FONT_NAME} installed")
        if os_name == "windows":
            # Installing the font isn't enough — Windows Terminal must USE it.
            if _set_windows_terminal_font(NERD_FONT_NAME):
                print_success("  ✓ Windows Terminal font set to the Nerd Font")
                print_warning(
                    "Close ALL Windows Terminal windows and reopen one for the "
                    "new font to take effect, then the icons will render."
                )
            else:
                print_info(
                    f"Set your terminal font to '{NERD_FONT_NAME}' manually "
                    "(Windows Terminal > Settings > Defaults > Appearance > "
                    "Font face), then reopen the terminal."
                )
        else:
            print_info(f"Select '{NERD_FONT_NAME}' in your terminal settings")
        return True
    print_warning(f"  ! {NERD_FONT_NAME} still not found — install manually")
    return False


def install_prime_wrappers(gpus: Dict[str, bool]) -> bool:
    """
    Linux only : if a discrete GPU is detected (Nvidia OR AMD), drop
    a ~/.local/bin/mpv wrapper that sets the PRIME render-offload env
    vars before exec-ing the system binary.
    """
    if detect_os() != "linux":
        return True
    if not (gpus.get("nvidia") or gpus.get("amd_discrete")):
        return True

    bindir = get_local_bin_dir()
    bindir.mkdir(parents=True, exist_ok=True)

    if gpus.get("nvidia"):
        offload_block = (
            'export __NV_PRIME_RENDER_OFFLOAD=1\n'
            'export __GLX_VENDOR_LIBRARY_NAME=nvidia\n'
            'export __VK_LAYER_NV_optimus=NVIDIA_only\n'
        )
        gpu_label = "Nvidia"
    else:
        # AMD discrete : `DRI_PRIME=1` routes the GL/Vulkan context to it
        offload_block = 'export DRI_PRIME=1\n'
        gpu_label = "AMD"

    target = bindir / "mpv"
    target.write_text(
        "#!/usr/bin/env bash\n"
        f"# FreeFlix PRIME wrapper — routes mpv to the {gpu_label} dGPU.\n"
        "# Delete this file (rm ~/.local/bin/mpv) to disable.\n"
        "\n"
        + offload_block
        + "\nexec /usr/bin/mpv \"$@\"\n"
    )
    target.chmod(0o755)

    # Warn if ~/.local/bin isn't in PATH
    if str(bindir) not in os.environ.get("PATH", "").split(":"):
        print_warning(
            f"  ! {bindir} is not in your PATH — add this to ~/.bashrc / ~/.zshrc :\n"
            f'      export PATH="$HOME/.local/bin:$PATH"'
        )
    return True


# ─── FlareSolverr : optional Cloudflare auto-solver ───────────────────
def _flaresolverr_running(url: str = "http://127.0.0.1:8191/") -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _container_runtime():
    """
    Return a usable container runtime : 'podman' (rootless, preferred — no
    sudo, no daemon, Fedora default) then 'docker'. None if neither works.
    """
    for cmd in ("podman", "docker"):
        if not shutil.which(cmd):
            continue
        try:
            r = subprocess.run([cmd, "info"], capture_output=True, timeout=12)
            if r.returncode == 0:
                return cmd
        except Exception:
            continue
    return None


FS_IMAGE = "ghcr.io/flaresolverr/flaresolverr:latest"


def _flaresolverr_make_persistent(runtime: str):
    """
    Linux + podman : make the container auto-start on boot via a systemd
    user service + lingering. (Docker uses --restart unless-stopped + its
    daemon, so nothing extra needed there.)
    """
    if detect_os() != "linux" or runtime != "podman":
        return
    try:
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        if user:
            subprocess.run(["loginctl", "enable-linger", user],
                           capture_output=True, timeout=10)
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        gen = subprocess.run(
            ["podman", "generate", "systemd", "--new", "--name", "flaresolverr",
             "--restart-policy=always"],
            capture_output=True, text=True, timeout=25,
        )
        if gen.returncode == 0 and gen.stdout.strip():
            (unit_dir / "flaresolverr.service").write_text(gen.stdout)
            # Hand the container over to systemd.
            subprocess.run(["podman", "stop", "flaresolverr"], capture_output=True)
            subprocess.run(["podman", "rm", "flaresolverr"], capture_output=True)
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
            subprocess.run(["systemctl", "--user", "enable", "--now",
                            "flaresolverr.service"], capture_output=True, timeout=30)
            print_success("  ✓ FlareSolverr set to auto-start on boot")
    except Exception:
        pass


def install_flaresolverr() -> bool:
    """
    Optional, fully automated : set up FlareSolverr (auto-solves Cloudflare
    JS challenges) so FreeFlix keeps working without pasting a token.

    Cross-platform, A-to-Z :
      * Linux  : Podman rootless (preferred) or Docker ; installs Podman via
                 the distro package manager if neither is present ; makes it
                 persistent (systemd user service + lingering).
      * macOS  : Podman/Docker if present, else guidance.
      * Windows: Docker Desktop if present, else guidance.
    """
    if _flaresolverr_running():
        print_success(t("FlareSolverr already running on :8191"))
        return True

    os_name = detect_os()
    print_info(t("FlareSolverr auto-solves Cloudflare challenges (optional, ~1 GB image)."))

    runtime = _container_runtime()

    # No runtime → try to provide one.
    if not runtime:
        if os_name == "linux":
            cmd = _linux_pkg_cmd("podman")
            if cmd:
                print_info(t("No Docker/Podman found. Podman is the easiest (rootless)."))
                try:
                    ans = input(f"Install Podman now? ({' '.join(cmd)}) [Y/n] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    return False
                if ans not in ("n", "no"):
                    subprocess.run(cmd, check=False)
                    runtime = _container_runtime()
        elif os_name == "macos":
            print_warning(
                "Install a container runtime to enable FlareSolverr, e.g.:\n"
                "  brew install podman && podman machine init && podman machine start\n"
                "  (or Docker Desktop), then re-run `freeflix --setup`."
            )
            return False
        elif os_name == "windows":
            print_warning(
                "Install Docker Desktop to enable FlareSolverr:\n"
                "  winget install Docker.DockerDesktop\n"
                "  then re-run `freeflix --setup`."
            )
            return False

    if not runtime:
        print_warning(t("No container runtime available — FlareSolverr skipped."))
        return False

    try:
        ans = input(f"Set up FlareSolverr via {runtime} now? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if ans in ("n", "no"):
        return False

    # Reuse an existing container, else pull & create it.
    subprocess.run([runtime, "start", "flaresolverr"], capture_output=True)
    if not _flaresolverr_running():
        print_info(f"Pulling & starting FlareSolverr via {runtime} (first run "
                   "downloads ~Chromium)…")
        try:
            subprocess.run(
                [runtime, "run", "-d", "--name", "flaresolverr",
                 "--restart", "unless-stopped", "-p", "8191:8191", FS_IMAGE],
                check=False,
            )
        except Exception as e:
            print_warning(f"Could not start FlareSolverr ({type(e).__name__}: {e})")
            return False

    # Make it survive reboots (Linux + podman).
    _flaresolverr_make_persistent(runtime)

    import time as _time
    for _ in range(10):
        if _flaresolverr_running():
            print_success(t("FlareSolverr is up on http://127.0.0.1:8191"))
            return True
        _time.sleep(2)
    print_info(t("FlareSolverr started — it may need a moment to be ready."))
    return True


# ─── Windows : install the media players ──────────────────────────────
def install_windows_players() -> bool:
    """
    Windows : install mpv (mpv.net) and VLC via winget so FreeFlix can
    actually launch them. Users who installed FreeFlix with `uv` never ran
    install.ps1, so the players may be missing. The tuned mpv config is
    applied separately by install_config_files() into %APPDATA%/freeflix/mpv.

    mpv.net's binary is mpvnet.exe ; player_manager.get_mpv_path() resolves
    both that and the winget shim, so FreeFlix can call it.
    """
    if detect_os() != "windows":
        return True
    if not shutil.which("winget"):
        print_warning(
            "winget not found. Install 'App Installer' from the Microsoft "
            "Store, or install mpv.net and VLC manually, so FreeFlix can "
            "launch them."
        )
        return False

    wanted = [
        ("mpv.net", "mpv.net (mpv for Windows)", ("mpv", "mpvnet")),
        ("VideoLAN.VLC", "VLC media player", ("vlc",)),
    ]
    for pkg_id, label, bins in wanted:
        if any(shutil.which(b) for b in bins):
            print_success(f"  ✓ {label} already installed")
            continue
        print_info(f"Installing {label} via winget…")
        try:
            subprocess.run(
                ["winget", "install", "--silent",
                 "--accept-source-agreements", "--accept-package-agreements",
                 "--id", pkg_id],
                check=False,
            )
        except Exception as e:
            print_warning(f"  ! {label} install failed ({type(e).__name__}: {e})")

    print_info(
        "If mpv/VLC aren't found immediately, open a NEW terminal so the "
        "PATH refreshes, then run `freeflix` again."
    )
    return True


# ─── Platform-specific guidance ───────────────────────────────────────
def print_platform_guidance_windows(gpus: Dict[str, bool]):
    """
    Windows 10/11 picks the GPU per-app via Settings → Display → Graphics.
    We can't set this programmatically (it's a UWP setting tied to the
    user shell). Best we can do is point the user there.
    """
    # Icons : the #1 Windows gotcha is running in the legacy cmd.exe console,
    # which can't render the TUI glyphs. Always show this.
    print_info("─" * 60)
    print_info(t("Icons not showing as crisp glyphs on Windows?"))
    print_info("─" * 60)
    print_info("  1. Use 'Windows Terminal' (Store / winget), NOT the old")
    print_info("     cmd.exe window — legacy console can't draw the glyphs.")
    print_info("  2. scripts/install.ps1 installs 'CaskaydiaCove Nerd Font'.")
    print_info("     In Windows Terminal: Settings > Defaults > Appearance >")
    print_info("     Font face -> CaskaydiaCove Nerd Font.")
    print_info("  3. Then in FreeFlix: Settings > Icon Style -> nerd.")
    print_info("     (Emoji icons are the default and work out of the box.)")
    print_info("")

    if not (gpus.get("nvidia") or gpus.get("amd_discrete")):
        return
    gpu = "Nvidia" if gpus.get("nvidia") else "AMD"
    print_info("─" * 60)
    print_info(f"Windows GPU offload : {gpu} dGPU detected")
    print_info("─" * 60)
    print_info(t("Windows handles GPU selection natively — no PRIME wrappers"))
    print_info(t("needed. To force mpv to use the dGPU, do this ONCE :"))
    print_info("")
    print_info("  Option A — Windows Graphics Settings (easiest)")
    print_info("    Settings → System → Display → Graphics")
    print_info("    Browse → C:\\Program Files\\mpv\\mpv.exe (or mpv.net)")
    print_info("    Options → High performance → Save")
    print_info("")
    if gpus.get("nvidia"):
        print_info("  Option B — Nvidia Control Panel (per-app profile)")
        print_info("    Nvidia Control Panel → Manage 3D settings")
        print_info("    Program Settings tab → Add → pick mpv.exe")
        print_info("    'Preferred graphics processor' → High-performance Nvidia")
        print_info("")


def print_platform_guidance_macos(gpus: Dict[str, bool]):
    """macOS picks the GPU automatically per-app based on energy needs."""
    print_info("─" * 60)
    if gpus.get("apple_silicon"):
        print_info(t("macOS Apple Silicon detected"))
        print_info("─" * 60)
        print_info(t("Apple Silicon has a single unified GPU — no offload needed."))
    else:
        print_info(t("macOS Intel detected"))
        print_info("─" * 60)
        print_info(t("macOS auto-selects between iGPU and dGPU based on app"))
        print_info(t("activity (Energy Saver). No manual action required."))


# ─── Top-level wizard ─────────────────────────────────────────────────
def run_setup(force: bool = False) -> bool:
    """
    Main entry point. Interactive wizard (uses input()) ; suppresses
    itself if setup is already complete and `force` is False.
    """
    if is_setup_complete() and not force:
        return False

    os_name = detect_os()
    gpus = detect_gpus()

    print_info("─" * 60)
    print_info(f"FreeFlix CLI — first-run setup ({os_name})")
    print_info("─" * 60)
    print_info(f"GPUs detected : {[k for k,v in gpus.items() if v] or ['none']}")
    print_info("")
    print_info(t("This will :"))
    print_info("  1. Install tuned mpv.conf + input.conf + position-resume hook")
    print_info("  2. Download Anime4K shaders (Mode A_S + A_VL, ~290 KB)")
    print_info("  3. Install the Nerd Font + chafa (crisp icons & posters)")
    print_info("  4. Offer to set up FlareSolverr (auto-solve Cloudflare, optional)")
    if os_name == "linux" and (gpus["nvidia"] or gpus["amd_discrete"]):
        gpu = "Nvidia" if gpus["nvidia"] else "AMD"
        print_info(f"  5. Install a PRIME wrapper so standalone mpv uses the {gpu} dGPU")
    print_info("")

    try:
        ans = input("Proceed? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print_info(t("Aborted."))
        return False
    if ans in ("n", "no"):
        # Remember the decline so we don't re-prompt every launch
        tracker.data["setup_declined"] = True
        tracker._save_data()
        return False

    print_info("\n• Installing mpv configuration…")
    install_config_files()
    print_info("\n• Downloading Anime4K shaders…")
    install_anime4k_shaders()
    print_info("\n• Anime posters (chafa)…")
    install_chafa()
    # Nerd Font is a required dependency for crisp icons — install it on every
    # OS and make 'nerd' the default icon style once it's present.
    print_info("\n• Installing Nerd Font (crisp icons)…")
    if install_nerd_font():
        tracker.set_icon_style("nerd")
    print_info("\n• Cloudflare auto-solver (FlareSolverr, optional)…")
    install_flaresolverr()
    if os_name == "linux":
        print_info("\n• Installing PRIME wrapper…")
        install_prime_wrappers(gpus)
    elif os_name == "windows":
        print_info("\n• Installing media players (mpv + VLC)…")
        install_windows_players()
        print_platform_guidance_windows(gpus)
    elif os_name == "macos":
        print_platform_guidance_macos(gpus)

    tracker.data["setup_done"] = True
    tracker.data.pop("setup_declined", None)
    tracker._save_data()

    print_success("\n✓ Setup complete. Launching FreeFlix…\n")
    return True


# ─── Post-upgrade migrations ──────────────────────────────────────────
def _ver_tuple(v):
    out = []
    for part in str(v or "0").split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


# Each entry : (version_that_introduced_it, description, action).
# `action` MUST be idempotent (check presence first) — it runs once, on the
# first launch after upgrading PAST that version. Use it to install a newly
# required tool, refresh configs, or clean up a removed feature.
#   e.g. ("1.6.0", "Feature X removed — cleaning up", _cleanup_x)
def _fix_anime4k_input_conf():
    """
    Make the bundled mpv configs render Anime4K on Windows. Two separate issues,
    both from mpv's path-list separator being ';' on Windows but ':' on Unix:

      1. input.conf  : the CTRL+1/2 toggle joined shaders with ':' in a single
         `set` → rewrite to per-shader `append` (cross-platform, no separator).
      2. mpv.conf    : the STARTUP `glsl-shaders="A:B:C"` line (loads on every
         video) — on Windows rewrite ':' to ';' between shader paths. This is
         the one that printed "Cannot open file …A.glsl:/shaders/B.glsl" when a
         video started.

    In-place, offline, idempotent — safe to run on every launch.
    """
    cfg = get_mpv_config_dir()
    is_win = sys.platform in ("win32", "cygwin")

    # 1) input.conf toggle → append form
    inp = cfg / "input.conf"
    if inp.is_file():
        try:
            txt = inp.read_text(encoding="utf-8")
            if 'glsl-shaders set "' in txt:
                def _conv(m):
                    paths = [p for p in m.group(1).split(":") if p]
                    parts = ['change-list glsl-shaders clr ""']
                    parts += [f'change-list glsl-shaders append "{p}"' for p in paths]
                    return "; ".join(parts)

                fixed = re.sub(r'change-list glsl-shaders set "([^"]+)"', _conv, txt)
                if fixed != txt:
                    inp.write_text(fixed, encoding="utf-8")
        except Exception:
            pass

    # 2) mpv.conf startup line → ';' separator on Windows
    if is_win:
        mpv = cfg / "mpv.conf"
        if mpv.is_file():
            try:
                txt = mpv.read_text(encoding="utf-8")
                fixed = txt.replace(".glsl:~~/", ".glsl;~~/")
                if fixed != txt:
                    mpv.write_text(fixed, encoding="utf-8")
            except Exception:
                pass


def _migrate_install_nerd_font():
    """
    Nerd Font became a standard dependency in 1.7.8 (first-run setup installs
    it). Existing users' run_setup won't re-run, so install it for them on
    upgrade and default to nerd icons if they never picked a style. Idempotent.
    """
    try:
        if not detect_nerd_font():
            install_nerd_font()
        if detect_nerd_font() and "icon_style" not in tracker.data:
            tracker.set_icon_style("nerd")
    except Exception:
        pass


def _migrations():
    return [
        ("1.5.7", "Anime posters need chafa", install_chafa),
        ("1.7.4", "Fix Anime4K shader toggle on Windows", _fix_anime4k_input_conf),
        ("1.7.8", "Install Nerd Font for crisp icons", _migrate_install_nerd_font),
    ]


def run_pending_migrations(current_version: str) -> None:
    """
    Run the migration steps for every version newer than the last one we
    set up, then record the current version. Called on launch so an
    upgrade (uv/pipx/pip) self-finishes on first run.
    """
    if not current_version or current_version == "dev":
        return

    last = tracker.get_last_setup_version()
    if last is None:
        # First launch with the migration system : adopt the current version
        # without replaying history (a fresh install already ran setup, and
        # in-app features still offer any missing tool on demand).
        tracker.set_last_setup_version(current_version)
        return

    if _ver_tuple(last) >= _ver_tuple(current_version):
        return  # same version or a downgrade — nothing to do

    pending = [
        (ver, desc, action)
        for ver, desc, action in _migrations()
        if _ver_tuple(last) < _ver_tuple(ver) <= _ver_tuple(current_version)
    ]
    if pending:
        print_info(f"Finalizing upgrade {last} → {current_version}…")
        for _ver, desc, action in pending:
            print_info(f"  • {desc}")
            try:
                action()
            except Exception as e:
                print_warning(f"    (skipped: {type(e).__name__})")

    tracker.set_last_setup_version(current_version)


def should_prompt_setup() -> bool:
    """True if we should ask the user to run setup."""
    # Already ran setup once → never re-prompt the FULL wizard (a silently
    # failed shader download would otherwise re-trigger "install the players…"
    # on every launch). Missing tools are handled by ensure_runtime_deps.
    if tracker.data.get("setup_done"):
        return False
    if is_setup_complete():
        return False
    if tracker.data.get("setup_declined"):
        return False  # user said no, don't pester
    return True
