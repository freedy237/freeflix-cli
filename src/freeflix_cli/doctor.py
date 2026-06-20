"""freeflix doctor — system diagnostic."""

from __future__ import annotations

import os
import re
import sys
import shutil
import socket
import subprocess
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


def _check_binary(label: str, *names: str) -> tuple[str, str, str]:
    for n in names:
        path = shutil.which(n)
        if path:
            try:
                out = subprocess.run(
                    [n, "--version"], capture_output=True, text=True, timeout=10
                )
                ver = (out.stdout or out.stderr or "").splitlines()[0].strip()
            except Exception:
                ver = "✓"
            return ("OK", ver, path)
    return ("MISSING", "—", "—")


def _check_managed_bin(label: str, name: str) -> tuple[str, str, str]:
    from platformdirs import user_data_dir

    bdir = Path(user_data_dir("freeflix-cli", "PaulExplorer")) / "bin"
    exe = f"{name}.exe" if _os() == "windows" else name
    path = bdir / exe
    if path.is_file():
        return ("OK", _fmt_size(path), str(path))
    return ("MISSING", "—", "—")


def _check_mpv_config() -> list[dict]:
    results = []
    cfg_dir = _mpv_config_dir()
    expected = [
        ("mpv.conf", cfg_dir / "mpv.conf"),
        ("input.conf", cfg_dir / "input.conf"),
        ("freeflix_position.lua", cfg_dir / "scripts" / "freeflix_position.lua"),
        (
            "Anime4K_Clamp_Highlights.glsl",
            cfg_dir / "shaders" / "Anime4K_Clamp_Highlights.glsl",
        ),
        (
            "Anime4K_Restore_CNN_VL.glsl",
            cfg_dir / "shaders" / "Anime4K_Restore_CNN_VL.glsl",
        ),
        (
            "Anime4K_Upscale_CNN_x2_VL.glsl",
            cfg_dir / "shaders" / "Anime4K_Upscale_CNN_x2_VL.glsl",
        ),
    ]
    for name, path in expected:
        status = "OK" if path.is_file() else "MISSING"
        size = _fmt_size(path) if path.is_file() else "—"
        results.append(
            {"name": name, "status": status, "size": size, "path": str(path)}
        )
    return results


def _mpv_config_dir() -> Path:
    if _os() == "windows":
        return Path(os.environ.get("APPDATA", "")) / "mpv"
    return Path.home() / ".config" / "mpv"


def _check_connectivity(host: str, port: int = 443, timeout: int = 5) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "REACHABLE"
    except OSError:
        return "UNREACHABLE"


def _check_flaresolverr(url: str | None = None) -> str:
    if not url:
        return "DISABLED"
    import urllib.request

    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            return (
                f"HEALTHY ({r.status})"
                if r.status == 200
                else f"UNHEALTHY ({r.status})"
            )
    except Exception as exc:
        return f"ERROR ({type(exc).__name__})"


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
            )
            return f"macOS {out.stdout.strip()}"
        except Exception:
            return "macOS"
    if _os() == "windows":
        try:
            out = subprocess.run(
                ["cmd", "/c", "ver"], capture_output=True, text=True, timeout=5
            )
            return out.stdout.strip()
        except Exception:
            return "Windows"
    return "unknown"


def _python_info() -> str:
    return f"{sys.version.split()[0]} ({sys.executable})"


def run(upload: bool = False) -> str:
    """Run diagnostics and return the report as a string."""
    lines: list[str] = []

    def L(msg: str = ""):
        lines.append(msg)

    sep = "─" * 60

    L("╭──────────────────────────────────────╮")
    L("│  FreeFlix CLI  —  Diagnostic Report  │")
    L("╰──────────────────────────────────────╯")
    L()

    L(f"Generated : {datetime.now(timezone.utc).isoformat()}")
    L(f"OS        : {_detect_distro()} ({_os()})")
    L(f"Python    : {_python_info()}")
    L(f"Version   : {_version()}")
    L(sep)

    # ── Binaries ───────────────────────────────────────────────────
    L("BINARIES")
    L()
    bins = [
        ("ffmpeg", "ffmpeg"),
        ("yt-dlp", "yt-dlp"),
        ("mpv", "mpv"),
        ("vlc", "vlc"),
        ("aria2c", "aria2c"),
        ("chafa", "chafa"),
        ("uv", "uv"),
    ]
    for label, name in bins:
        status, info, path = _check_binary(label, name)
        L(f"  {label:12s}  {status:<8s}  {info:<30s}  {path}")

    # Also check managed bin dir
    managed_pairs = [
        ("ffmpeg (managed)", "ffmpeg"),
        ("mpv (managed)", "mpv"),
        ("aria2c (managed)", "aria2c"),
    ]
    L()
    L("  Managed binaries (auto-downloaded):")
    for label, name in managed_pairs:
        status, info, path = _check_managed_bin(label, name)
        L(f"    {label:20s}  {status:<8s}  {info:<30s}  {path}")

    L(sep)

    # ── mpv config ─────────────────────────────────────────────────
    L("MPV CONFIG")
    L()
    for entry in _check_mpv_config():
        L(
            f"  {entry['name']:35s}  {entry['status']:<8s}  {entry['size']:<6s}  {entry['path']}"
        )
    L(sep)

    # ── FlareSolverr ───────────────────────────────────────────────
    L("FLARESOLVERR")
    L()
    from .tracker import tracker

    fs_url = tracker.get_flaresolverr_url()
    L(f"  URL  : {fs_url or '(not set)'}")
    L(f"  Health: {_check_flaresolverr(fs_url)}")
    L(sep)

    # ── Network ────────────────────────────────────────────────────
    L("NETWORK")
    L()
    hosts = [
        ("GitHub", "github.com", 443),
        ("coflix.cymru", "coflix.cymru", 443),
        ("anime-sama.to", "anime-sama.to", 443),
        ("french-stream.xyz", "french-stream.xyz", 443),
        ("api.anilist.co", "api.anilist.co", 443),
    ]
    for label, host, port in hosts:
        status = _check_connectivity(host, port)
        L(f"  {label:20s}  {status:<12s}  {host}:{port}")
    L(sep)

    # ── Config paths ───────────────────────────────────────────────
    L("CONFIG")
    L()
    from .tracker import tracker

    L(f"  Tracker data : {tracker.data_dir}")
    L(f"  mpv config   : {_mpv_config_dir()}")
    try:
        from platformdirs import user_data_dir

        managed = Path(user_data_dir("freeflix-cli", "PaulExplorer")) / "bin"
        L(f"  Managed bins : {managed}")
    except Exception:
        pass
    L(sep)

    report = "\n".join(lines)

    if upload:
        gist_url = _upload_gist(report)
        if gist_url:
            L()
            L(f"Report uploaded to: {gist_url}")

    return report


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
        )
        url = (result.stdout or "").strip()
        if url.startswith("https://"):
            return url
    except Exception:
        pass
    return None


def cli_doctor():
    """Entry point for ``freeflix --doctor``."""
    upload = "--upload" in sys.argv
    report = run(upload=upload)
    print(report)
    return 0
