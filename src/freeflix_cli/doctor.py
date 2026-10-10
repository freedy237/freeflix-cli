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

    # ── Install health ─────────────────────────────────────────────
    # Catches split installs (metadata says new, code runs old) and
    # shadowing second installs — the classic "upgraded but still old".
    L("INSTALL")
    L()
    try:
        from . import install_health as _ih
        _st = _ih.install_state()
        _ok = "OK" if not _st["mismatch"] else "MIXED"
        L(f"  Mode    : {'frozen .exe' if _st['frozen'] else 'python tool'}")
        L(f"  Module  : {_st['module_file'] or '(unknown)'}")
        L(f"  Code    : {_st['code_version']}")
        L(f"  Metadata: {_st['metadata_version'] or '(none)'}  [{_ok}]")
        if _st["mismatch"]:
            L("  !! Metadata and code disagree — clean reinstall advised.")
        _shims = _st["shims"]
        L(f"  Launchers on PATH ({len(_shims)}):")
        for _s in _shims[:6]:
            L(f"    - {_s}")
        if not _shims:
            L("    (none found)")
    except Exception as _e:
        L(f"  (install check failed: {_e})")
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
    # Hosts lus depuis les portails EFFECTIFS (jamais de domaines périmés
    # en dur : coflix.cymru / french-stream.xyz ont déjà induit en erreur).
    L("NETWORK")
    L()
    hosts = [
        ("GitHub", "github.com", 443),
        ("api.anilist.co", "api.anilist.co", 443),
    ]
    try:
        from urllib.parse import urlparse as _up
        from .scraping.config import portals as _portals
        for _name in ("coflix", "anime-sama", "french-stream", "french-manga"):
            _u = _portals.get(_name, "")
            _h = (_up(_u).hostname or "").strip() if _u else ""
            if _h:
                hosts.append((_name, _h, 443))
    except Exception:
        pass
    for label, host, port in hosts:
        status = _check_connectivity(host, port)
        L(f"  {label:20s}  {status:<12s}  {host}:{port}")
    L(sep)

    # ── Posters ──────────────────────────────────────────────────
    L("POSTERS")
    L()
    try:
        from . import terminal_image as _ti
        from .tracker import tracker as _trk
        _pmode = (_trk.get_poster_mode() or "auto")
        _has_chafa = _ti.chafa_available()
        _proto = _ti.detect_image_protocol()
        _chafa_v = ".".join(map(str, _ti._chafa_version())) if _has_chafa else "(missing)"
        L(f"  Mode     : {_pmode}")
        L(f"  Protocol : {_proto}  (chafa {_chafa_v})")
        _hint = _ti.sixel_hint()
        if _hint:
            L(f"  Hint     : {_hint}")
    except Exception as _e:
        L(f"  (poster check failed: {_e})")
    L(sep)

    # ── Config paths ───────────────────────────────────────────────
    L("CONFIG")
    L()
    from .tracker import tracker

    L(f"  Tracker data : {tracker.data_dir}")
    try:
        from .scraping.config import portals as _portals
        from .scraping.config import portal_origins as _origins
        from .scraping import config as _cfg
        L("  Portals (effective URL + source):")
        for _name in ("anime-sama", "french-manga", "coflix", "french-stream"):
            _u = _portals.get(_name, "") or "(missing)"
            _o = _origins.get(_name, "?")
            L(f"    {_name:14s} {_u}  [{_o}]")
        L(f"  Local file : {getattr(_cfg, '_local_portal_path', '') or '(none found)'}")
    except Exception as _e:
        L(f"  Portals : (unavailable: {_e})")
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


# ── Live source self-test (freeflix --doctor --sources) ───────────────
# Each entry : (label, scraper module path, a search query). We call the
# scraper's get_website_url() + search() exactly like the app does and report
# reachable / results / Cloudflare / broken — so a site migration (Coflix went
# WordPress, French-Stream's decoy) is caught in seconds instead of "it just
# doesn't work".
_SOURCE_TESTS = [
    ("Anime-Sama", "freeflix_cli.scraping.anime_sama", "naruto"),
    ("French-Manga", "freeflix_cli.scraping.french_manga", "naruto"),
    ("Coflix", "freeflix_cli.scraping.coflix", "matrix"),
    ("French-Stream", "freeflix_cli.scraping.french_stream", "matrix"),
    ("Papystreaming", "freeflix_cli.scraping.papystreaming", "matrix"),
]


def check_sources() -> str:
    """Live-test every source (get_website_url + search) and return a report."""
    import importlib
    import time as _t

    lines = ["FreeFlix — source self-test", "=" * 34, ""]
    for label, modpath, query in _SOURCE_TESTS:
        t0 = _t.time()
        try:
            mod = importlib.import_module(modpath)
        except Exception as e:
            lines.append(f"✗ {label:<14} import error: {e}")
            continue
        try:
            if hasattr(mod, "get_website_url"):
                mod.get_website_url()
            try:
                _origin = getattr(mod, "website_origin", "") or ""
            except Exception:
                _origin = ""
            n = len(mod.search(query))
            dt = int((_t.time() - t0) * 1000)
            _via = f" via {_origin}" if _origin else ""
            if n > 0:
                lines.append(f"✓ {label:<14} OK — {n} results  ({dt} ms){_via}")
            else:
                lines.append(f"⚠ {label:<14} reachable but 0 results for '{query}'  ({dt} ms){_via}")
        except Exception as e:
            msg = str(e)
            low = msg.lower()
            tag = "Cloudflare" if ("cloudflare" in low or "cf-ray" in low) else \
                  "unreachable" if any(k in low for k in ("resolve", "connection", "timed out", "dns")) else \
                  "broken"
            lines.append(f"✗ {label:<14} {tag}: {msg[:70]}")
    lines.append("")
    from .logsetup import LOG_FILE
    lines.append(f"(details logged to {LOG_FILE})")
    return "\n".join(lines)


def cli_doctor():
    """Entry point for ``freeflix --doctor``."""
    if "--sources" in sys.argv:
        print(check_sources())
        return 0
    upload = "--upload" in sys.argv
    report = run(upload=upload)
    print(report)
    return 0
