"""
Lightweight update notifier : check PyPI for a newer freeflix-cli once
a day (cached via the tracker), and print a big yellow banner at the
top of the home screen when one exists.
"""

import json
import urllib.request
import importlib.metadata
from datetime import datetime, timedelta
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .tracker import tracker
from .i18n import t
from .icons import icon

console = Console()

PYPI_URL = "https://pypi.org/pypi/{pkg}/json"
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


def check_update(package_name: str = "freeflix-cli") -> bool:
    """
    If a newer version is on PyPI, print a banner and return True.
    Otherwise return False. Safe in dev (uninstalled) mode : no-op.
    """
    try:
        current = importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return False

    latest = _cached_latest(package_name)
    if not latest:
        return False

    if _parse_version(latest) <= _parse_version(current):
        return False

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
