"""
Daily scanner that re-scrapes each Anime-Sama series in the user's history
and notifies via libnotify (notify-send) when new episodes are available.

Runnable as a module : `python -m freeflix_cli.notifications`
A systemd user timer at ~/.config/systemd/user/freeflix-notify.timer
invokes it once a day. See `install_systemd_timer()` for setup.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Dict


def _extract_max_episode_number(episodes_dict: dict) -> int:
    """Given {lang: [Episode]}, return the highest detected episode number."""
    best = 0
    for eps in episodes_dict.values():
        n = len(eps)
        if n > best:
            best = n
    return best


def scan_for_new_episodes() -> List[Dict]:
    """
    For each Anime-Sama entry in tracker history, re-scrape the matching
    season and report any series where the latest available episode is
    higher than the user's recorded progress.

    Returns the list of new-episode reports.
    """
    from .tracker import tracker
    from .scraping import anime_sama

    try:
        anime_sama.get_website_url()
    except Exception:
        return []

    history = tracker.get_history()
    findings: List[Dict] = []
    seen_keys = set()

    for entry in history:
        if entry.get("provider") != "Anime-Sama":
            continue

        series_title = entry.get("series_title")
        season_title = entry.get("season_title")
        series_url = entry.get("series_url") or ""

        key = (series_title, season_title)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        if not series_url.startswith("http"):
            series_url = anime_sama.website_origin.rstrip("/") + series_url

        # Best-effort scrape; never crash the daemon on a single bad entry
        try:
            series = anime_sama.get_series(series_url)
        except Exception:
            continue

        last_match = re.search(r"(\d+)", entry.get("episode_title", ""))
        if not last_match:
            continue
        last_ep_num = int(last_match.group(1))

        for season_access in series.seasons:
            if season_access.title != season_title:
                continue
            try:
                season = anime_sama.get_season(season_access.url)
            except Exception:
                break
            max_avail = _extract_max_episode_number(season.episodes)
            if max_avail > last_ep_num:
                findings.append(
                    {
                        "series": series_title,
                        "season": season_title,
                        "current": last_ep_num,
                        "available": max_avail,
                    }
                )
            break

    return findings


def _notify(title: str, body: str):
    """Best-effort libnotify wrapper. Silent if notify-send is missing."""
    notify = shutil.which("notify-send")
    if not notify:
        return
    try:
        subprocess.run(
            [notify, "-a", "AutoFlix", "-i", "video-x-generic", title, body],
            check=False,
            timeout=5,
        )
    except Exception:
        pass


def main():
    findings = scan_for_new_episodes()
    if not findings:
        return 0

    lines = []
    for f in findings:
        lines.append(
            f"• {f['series']} — {f['season']} : ep {f['current']} → {f['available']}"
        )
    _notify("New AutoFlix episodes available", "\n".join(lines))
    return 0


# ──────────────────────────────────────────────────────────────────
# systemd user-timer setup helpers (called from the Settings menu)
# ──────────────────────────────────────────────────────────────────

SYSTEMD_DIR = Path.home() / ".config" / "systemd" / "user"
SERVICE_NAME = "freeflix-notify.service"
TIMER_NAME = "freeflix-notify.timer"


def _python_path() -> str:
    """Path to the Python inside this uv tool's venv (stable across runs)."""
    return sys.executable


def install_systemd_timer() -> bool:
    """
    Write the .service and .timer files, reload daemon, enable + start
    the timer. Returns True on success.
    """
    SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)

    service_path = SYSTEMD_DIR / SERVICE_NAME
    timer_path = SYSTEMD_DIR / TIMER_NAME

    service_path.write_text(
        f"""[Unit]
Description=AutoFlix: scan history for new anime episodes
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={_python_path()} -m freeflix_cli.notifications
"""
    )

    timer_path.write_text(
        """[Unit]
Description=Run AutoFlix episode scan once a day

[Timer]
OnBootSec=15min
OnUnitActiveSec=24h
Persistent=true

[Install]
WantedBy=timers.target
"""
    )

    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False

    for args in (
        [systemctl, "--user", "daemon-reload"],
        [systemctl, "--user", "enable", "--now", TIMER_NAME],
    ):
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            return False

    return True


def uninstall_systemd_timer() -> bool:
    systemctl = shutil.which("systemctl")
    if systemctl:
        subprocess.run(
            [systemctl, "--user", "disable", "--now", TIMER_NAME],
            capture_output=True,
        )

    for fname in (SERVICE_NAME, TIMER_NAME):
        p = SYSTEMD_DIR / fname
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass

    if systemctl:
        subprocess.run(
            [systemctl, "--user", "daemon-reload"], capture_output=True
        )
    return True


def is_systemd_timer_installed() -> bool:
    return (SYSTEMD_DIR / TIMER_NAME).exists()


if __name__ == "__main__":
    sys.exit(main())
