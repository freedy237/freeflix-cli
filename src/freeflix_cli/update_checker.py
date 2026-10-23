"""
Lightweight update notifier : check PyPI for a newer freeflix-cli once
a day (cached via the tracker), and print a big yellow banner at the
top of the home screen when one exists.
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import importlib.metadata
from datetime import datetime, timedelta
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .tracker import tracker
from .i18n import t
from .icons import icon
from .cli_utils import print_info, print_warning, print_error, print_success

console = Console()

PYPI_URL = "https://pypi.org/pypi/{pkg}/json"
RELEASES_URL = "https://github.com/freedy237/freeflix-cli/releases/latest"
CACHE_TTL = timedelta(hours=24)


def _parse_version(s: str):
    """Light packaging.Version replacement (no extra dep)."""
    try:
        from packaging.version import Version
        return Version(s)
    except Exception:
        # Fallback : tuple-of-ints (handles "1.10.0" > "1.9.0" correctly)
        try:
            return tuple(int(p) for p in s.split(".") if p.isdigit())
        except Exception:
            return (0,)


def _fetch_latest(package_name: str):
    """Hit PyPI's JSON API once. Returns version string or None on error."""
    try:
        url = PYPI_URL.format(pkg=package_name)
        with urllib.request.urlopen(url, timeout=3) as response:
            data = json.loads(response.read().decode())
            return data["info"]["version"]
    except Exception:
        return None


def _cached_latest(package_name: str) -> str:
    """
    Return the latest PyPI version, refreshing from PyPI at most once
    every CACHE_TTL. The cache lives in tracker.data so it survives runs.
    """
    raw = tracker.data.get("update_check", {})
    cached_ts = raw.get("ts")
    cached_ver = raw.get("latest")

    if cached_ts and cached_ver:
        try:
            if datetime.now() - datetime.fromisoformat(cached_ts) < CACHE_TTL:
                return cached_ver
        except ValueError:
            pass  # stale/bad timestamp → ignore

    fresh = _fetch_latest(package_name)
    if fresh:
        tracker.data["update_check"] = {
            "ts": datetime.now().isoformat(),
            "latest": fresh,
        }
        tracker._save_data()
        return fresh

    return cached_ver  # fall back to whatever we have (may be None)


def _installed_version(package_name: str):
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _new_tools_missing() -> bool:
    """True when the upgraded release needs a system tool we don't have.

    Cheap `shutil.which` scan only: it never downloads anything and never
    re-runs the interactive setup wizard here — the launch-time dependency
    gate (ensure_runtime_deps) does the real install right after the reload.
    """
    try:
        from . import setup_assistant
        return bool(setup_assistant.missing_tools())
    except Exception:
        return False


def _dev_checkout() -> bool:
    """True when running from a source checkout (editable / .venv).

    `importlib.metadata` may then report an old version while the code on disk
    is newer; upgrading pip would clobber that checkout, so we never do it.
    """
    try:
        import freeflix_cli
        pkg_file = (freeflix_cli.__file__ or "").replace("\\", "/")
        root = pkg_file.rsplit("/src/", 1)[0] if "/src/" in pkg_file else ""
        if root and os.path.exists(os.path.join(root, "pyproject.toml")):
            return True
    except Exception:
        pass
    prefix = sys.prefix.replace("\\", "/").lower()
    return "/.venv" in prefix or "\\\\.venv" in prefix


def _running_version(package_name: str) -> str:
    """Version actually on disk (the code that runs), not just metadata."""
    try:
        from . import install_health
        code = install_health.CODE_VERSION
        if code:
            return code
    except Exception:
        pass
    return _installed_version(package_name) or "?"


def run_update(package_name: str = "freeflix-cli") -> bool:
    """Upgrade in place with the same installer that manages this copy."""
    # Only PIP would overwrite the sources of a checkout; uv/pipx installs are
    # separate environments and must still update.
    if installer_kind() == "pip" and _dev_checkout():
        current, latest = (_running_version(package_name),
                           update_plan(package_name) or (None, None))[1]
        if current == latest:
            print_success(f"{t('FreeFlix is up to date:')} {current}")
        else:
            print_info(f"{t('Running from a source checkout — nothing to install.')}"
                       f"  ({current})")
        return True

    cmd, label = _upgrade_command(package_name)
    if not cmd:
        print_warning(t("Could not find how FreeFlix was installed."))
        print_info(t("Download the latest version here:") + " "
                   + RELEASES_URL)
        return False
    # A release can add Python dependencies: upgrading pulls them in for uv/
    # pipx/pip alike. Then the post-upgrade migrations install any NEW system
    # tool (mpv/ffmpeg/ffprobe/aria2c/…).
    print_info(f"{t('Updating FreeFlix…')} ({label})")
    fresh = bool(update_plan(package_name))
    print_info(t("New dependencies, if any, are installed automatically."))
    try:
        rc = subprocess.run(cmd, check=False).returncode
    except Exception as e:  # noqa: BLE001
        print_error(f"{t('Update failed:')} {e}")
        return False
    if rc != 0:
        print_error(t("Update failed. You can retry manually:"))
        print_info("  " + " ".join(cmd))
        return False
    print_success(f"{t('Update installed:')} {package_name}")
    if fresh and _new_tools_missing():
        # The new release needs a tool this machine lacks: the launch-time
        # gate installs it (managed binary / winget / package manager) right
        # after the reload, without opening the full setup wizard here.
        print_info(t("New tools required by this version will be installed "
                     "after the restart."))
    return True


def _system_tools_needed() -> list:
    """System binaries the CURRENT release needs (for the tests/QA helper)."""
    try:
        from . import setup_assistant
        return list(setup_assistant.missing_tools())
    except Exception:
        return []


def update_plan(package_name: str = "freeflix-cli"):
    """(current, latest) when a newer release exists, else None.

    Pure check (no printing): used by the startup prompt and by --doctor.
    Safe in dev/uninstalled mode (no metadata) → None.
    """
    # Compare with the version actually RUNNING (code on disk), not just the
    # metadata: a source checkout can ship newer code than its dist-info.
    current = _running_version(package_name)
    if not current or current == "?":
        return None
    latest = _cached_latest(package_name)
    if not latest:
        return None
    try:
        if _parse_version(latest) <= _parse_version(current):
            return None
    except Exception:
        return None
    return (current, latest)


def installer_kind() -> str:
    """Which installer owns this copy: ``uv`` | ``pipx`` | ``pip`` | ``exe``.

    Detection is path-based (the running interpreter), so it matches the way
    FreeFlix was really installed — never a guess from what is on PATH.
    """
    exe = sys.executable.replace("\\", "/").lower()
    prefix = sys.prefix.replace("\\", "/").lower()
    if getattr(sys, "frozen", False):
        return "exe"
    if "/uv/tools/" in exe or "/uv/tools/" in prefix or "/tools/" in exe:
        return "uv"
    if "/pipx/venvs/" in exe or "/pipx/" in prefix:
        return "pipx"
    if "/pipx/" in exe:
        return "pipx"
    return "pip"


def _upgrade_command(package_name: str):
    """Upgrade with the SAME installer that installed FreeFlix.

    uv install → ``uv tool upgrade`` · pipx → ``pipx upgrade`` ·
    pip → ``python -m pip install --upgrade`` (same interpreter).
    """
    kind = installer_kind()
    if kind == "uv":
        uv = shutil.which("uv")
        if uv:
            return [uv, "tool", "upgrade", package_name], "uv tool upgrade"
        return [], "download"
    if kind == "pipx":
        pipx = shutil.which("pipx")
        if pipx:
            return [pipx, "upgrade", package_name], "pipx upgrade"
        return [], "download"
    if kind == "exe":
        return [], "download"
    return (
        [sys.executable, "-m", "pip", "install", "--upgrade", package_name],
        "pip install --upgrade",
    )


def ask_update(package_name: str = "freeflix-cli") -> bool:
    """Announce a new version and ask Y/n (also O/N in French).

    Returns True when the user wants to update."""
    plan = update_plan(package_name)
    if not plan:
        return False
    current, latest = plan

    body = Text()
    body.append(f"\n  {icon('up')}  {t('A new version of FreeFlix is available!')}\n\n",
                style="bold yellow")
    body.append(f"     {t('Installed')}:  ", style="white")
    body.append(f"{current}\n", style="bold red")
    body.append(f"     {t('Latest')}:     ", style="white")
    body.append(f"{latest}\n", style="bold green")
    body.append(f"\n  {t('Do you want to update now?')}  ", style="bold white")
    body.append(t("(y/n)"), style="dim")
    console.print(Panel(
        body,
        title=f"[bold yellow]{icon('party')} {t('Update available')}[/bold yellow]",
        subtitle=f"[dim]{current} → {latest}[/dim]",
        border_style="yellow",
        expand=False,
    ))
    try:
        answer = input(f"  {t('Your choice')} [y/n] : ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    # y / yes / o / oui → update ; anything else → later.
    return answer in ("y", "yes", "o", "oui")


def reload_process() -> None:  # pragma: no cover - replaces the process
    """Restart FreeFlix in place so the NEW code runs (same terminal)."""
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    argv = [sys.executable, "-m", "freeflix_cli"] + sys.argv[1:]
    os.execv(sys.executable, argv)


def prompt_and_update(package_name: str = "freeflix-cli") -> bool:
    """Startup flow: announce → ask y/n → install → wait Enter → reload.

    Returns True when the process was reloaded (it never returns then)."""
    from .cli_utils import pause

    if not ask_update(package_name):
        return False
    print()
    if not run_update(package_name):
        pause()
        return False
    print_info(t("Press Enter to restart FreeFlix with the new version."))
    try:
        pause()
    except Exception:
        pass
    reload_process()
    return True


def check_update(package_name: str = "freeflix-cli") -> bool:
    """
    If a newer version is on PyPI, print a banner and return True.
    Otherwise return False. Safe in dev (uninstalled) mode : no-op.

    Kept for callers that only need the banner (the startup flow now uses
    ask_update/run_update so it can install and reload).
    """
    plan = update_plan(package_name)
    if not plan:
        return False
    current, latest = plan

    body = Text()
    body.append(f"\n  {icon('up')}  {t('A new version of FreeFlix is available!')}\n\n",
                style="bold yellow")
    body.append(f"     {t('Installed')}:  ", style="white")
    body.append(f"{current}\n", style="bold red")
    body.append(f"     {t('Latest')}:     ", style="white")
    body.append(f"{latest}\n\n", style="bold green")
    body.append(f"  {t('Upgrade with')}:\n\n", style="bold white")
    body.append(f"     uv tool upgrade {package_name}\n", style="cyan")

    console.print(
        Panel(
            body,
            title=f"[bold yellow]{icon('party')} {t('Update available')}[/bold yellow]",
            subtitle=f"[dim]{current} → {latest}[/dim]",
            border_style="yellow",
            expand=False,
        )
    )
    return True
