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
CODE_VERSION = "2.6.1"


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
        return (
            "Download the latest freeflix-windows-x86_64.exe from GitHub "
            "Releases and replace the old one (close FreeFlix first)."
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
