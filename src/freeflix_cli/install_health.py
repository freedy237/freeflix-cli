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
CODE_VERSION = "1.11.3"


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
    }
    return state


def cleanup_hint() -> str:
    """Per-OS clean-reinstall commands for a split install."""
    if os.name == "nt":
        return (
            "Close FreeFlix, then run in PowerShell:\n"
            "  where.exe freeflix\n"
            "  uv tool uninstall freeflix-cli\n"
            "  uv tool install freeflix-cli\n"
            "Or re-download freeflix-windows-x86_64.exe from GitHub Releases."
        )
    return (
        "Close FreeFlix, then run:\n"
        "  uv tool uninstall freeflix-cli\n"
        "  uv tool install freeflix-cli"
    )
