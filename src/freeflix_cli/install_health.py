"""Install health: detect split installs and duplicates.

``freeflix --version`` reads the package METADATA while behaviour comes from
the ``.py`` files on disk. On Windows an upgrade can update one without the
other (second install shadowing PATH, locked files during upgrade, .exe run
instead of the tool). This module exposes that split so startup and --doctor
can warn with the exact fix.
"""

from __future__ import annotations

import os
import sys

# Version BAKED INTO THE CODE — bump together with pyproject.toml.
CODE_VERSION = "2.7.0"


def metadata_version() -> str | None:
    """Version from the installed dist-info (what --version prints)."""
    try:
        import importlib.metadata as _im
        return _im.version("freeflix-cli")
    except Exception:
        return None


def module_file() -> str:
    """Where the running freeflix_cli package is imported from."""
    try:
        import freeflix_cli
        return os.path.realpath(getattr(freeflix_cli, "__file__", "") or "")
    except Exception:
        return ""


def is_frozen() -> bool:
    """True when running as a PyInstaller onefile binary."""
    return bool(getattr(sys, "frozen", False))


# ── bundled reference data (Match clubs / channel logos) ──────────────
# These JSON indexes live INSIDE the package (src/freeflix_cli/data/). A
# PyInstaller build produced with --collect-submodules only (no
# --collect-data) still starts, but silently loses Match's curated team names
# and channel logos — a functional downgrade users cannot diagnose. The
# helpers below let --doctor / startup report it instead of hiding it.
# SINGLE SOURCE OF TRUTH for the reference data the app reads from the
# package. Any file added to src/freeflix_cli/data/ must be listed here; a CI
# test compares this manifest with the directory so a forgotten entry fails
# the build instead of silently degrading a release. The value is the minimal
# plausible size in bytes (an HTML error page must never be accepted as data).
BUNDLED_DATA_FILES = {
    "clubs.json": 5_000,           # real: ~22 KB, 441 clubs
    "channel_logos.json": 200_000,  # real: ~2.3 MB, ~30k logos
}


def package_dir() -> str:
    """Directory of the RUNNING freeflix_cli package (or of the frozen bundle).

    In a PyInstaller onefile build this resolves inside ``_MEIPASS`` because
    PyInstaller sets ``freeflix_cli.__file__`` there — the same anchor the
    scraper uses to read its data files.
    """
    try:
        import freeflix_cli
        return os.path.dirname(getattr(freeflix_cli, "__file__", "") or "")
    except Exception:
        return ""


def match_data_cache_dir() -> str:
    """Persistent cache where an affected build self-heals the Match data.

    Older standalone exes (built without --collect-data) repair themselves at
    launch by downloading the two JSON indexes here; the loader is pointed at
    that directory, so users never have to re-download the application.
    """
    try:
        from platformdirs import user_data_dir
        return os.path.join(
            user_data_dir("freeflix-cli", "PaulExplorer"), "match-data")
    except Exception:
        return ""


def _file_status(data_dir: str, name: str) -> tuple:
    path = os.path.join(data_dir, name) if data_dir else ""
    size = 0
    try:
        if path and os.path.isfile(path):
            size = os.path.getsize(path)
    except OSError:
        size = 0
    return path, size


def bundled_data_status(package_dir_override: str | None = None) -> dict:
    """Per-file presence/size/source of the Match reference data.

    Checks the package/bundle first, then the self-heal cache (an affected
    build patches its loader to read from there). Passing *package_dir_override*
    restricts the check to that directory (used by tests).
    """
    if package_dir_override is not None:
        dirs = ((os.path.join(package_dir_override, "data")
                 if package_dir_override else ""),)
    else:
        base = package_dir()
        dirs = (
            os.path.join(base, "data") if base else "",
            match_data_cache_dir(),
        )
    out: dict = {}
    for name in BUNDLED_DATA_FILES:
        path, size = "", 0
        for data_dir in dirs:
            cand_path, cand_size = _file_status(data_dir, name)
            if cand_size:
                path, size = cand_path, cand_size
                break
            if not path:
                path = cand_path
        source = "package"
        if size and path and package_dir_override is None:
            base = package_dir()
            in_package = bool(
                base
                and os.path.normcase(os.path.abspath(path)).startswith(
                    os.path.normcase(os.path.abspath(
                        os.path.join(base, "data"))))
            )
            source = "package" if in_package else "cache"
        out[name] = {
            "path": path,
            "present": bool(size),
            "size": size,
            "min_bytes": BUNDLED_DATA_FILES[name],
            "source": source,
        }
    return out


def bundled_data_ok(package_dir_override: str | None = None) -> bool:
    """True when this install/bundle carries Match's clubs + logos data."""
    return all(
        entry["present"]
        for entry in bundled_data_status(package_dir_override).values()
    )


def bundled_data_missing(package_dir_override: str | None = None) -> list:
    """Names of the reference-data files missing from this build ([] = OK)."""
    return [
        name
        for name, entry in bundled_data_status(package_dir_override).items()
        if not entry["present"]
    ]



def find_shims() -> list[str]:
    """Every `freeflix*` launcher found on PATH (shadowing suspects)."""
    names = ("freeflix", "freeflix.exe", "freeflix.cmd")
    found: list[str] = []
    try:
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    except Exception:
        return found
    for d in path_dirs:
        if not d:
            continue
        for n in names:
            try:
                cand = os.path.join(d, n)
            except Exception:
                continue
            try:
                if os.path.isfile(cand):
                    real = os.path.realpath(cand)
                    if real not in found:
                        found.append(real)
            except Exception:
                pass
    return found


def installer_kind() -> str:
    """Which manager owns the running copy: uv, pipx, pip, frozen or unknown.

    The clean-reinstall hint must name the *right* manager: telling a pipx
    user to run ``uv tool uninstall`` (the old hard-coded advice) fails and
    leaves the split install in place.
    """
    if is_frozen():
        return "frozen"
    path = module_file().replace("\\", "/").lower()
    if "/uv/tools/" in path:
        return "uv"
    if "/pipx/venvs/" in path:
        return "pipx"
    if "site-packages" in path or "dist-packages" in path:
        return "pip"
    return "unknown"


def install_state() -> dict:
    """Snapshot: frozen, exe, module file, both versions, dupes, mismatch."""
    meta = metadata_version()
    state = {
        "frozen": is_frozen(),
        "executable": sys.executable,
        "module_file": module_file(),
        "metadata_version": meta,
        "code_version": CODE_VERSION,
        "mismatch": bool(meta) and meta != CODE_VERSION,
        "shims": find_shims(),
        "installer": installer_kind(),
        # A frozen build can be missing its bundled Match data; the report
        # should show that instead of leaving users with silent bad names.
        "bundle_data_ok": bundled_data_ok(),
        "bundle_data_missing": bundled_data_missing(),
    }
    return state


def cleanup_hint() -> str:
    """Per-OS clean-reinstall commands for a split install.

    The commands match the manager that actually owns the running copy, so
    they work on pipx/pip installs too (a wrong uninstall command was a dead
    end after an upgrade went wrong).
    """
    kind = installer_kind()
    if kind == "frozen":
        # The release workflow builds one target per OS/arch. Naming the
        # Windows .exe unconditionally sent frozen-Linux/macOS users looking
        # for an artifact that does not exist (the .exe is a Windows file).
        asset = {
            "win32": "freeflix-windows-x86_64.exe",
            "cygwin": "freeflix-windows-x86_64.exe",
            "darwin": "freeflix-macos-arm64",
            "linux": "freeflix-linux-x86_64",
        }.get(sys.platform, "standalone binary")
        return (
            f"Download the latest {asset} from GitHub Releases and replace "
            "the old one (close FreeFlix first)."
        )
    if kind == "pipx":
        cmd = "pipx uninstall freeflix-cli && pipx install freeflix-cli"
    elif kind == "pip":
        cmd = "pip uninstall -y freeflix-cli && pip install freeflix-cli"
    else:
        cmd = "uv tool uninstall freeflix-cli && uv tool install freeflix-cli"
    if os.name == "nt":
        return (
            "Close FreeFlix, then run in PowerShell:\n"
            "  where.exe freeflix\n"
            f"  {cmd}"
        )
    return f"Close FreeFlix, then run:\n  {cmd}"
