"""
Nyaa.si torrent provider for AutoFlix.

Searches nyaa.si, lets the user pick a result, then downloads it via
aria2c with BitTorrent options. The output directory is
~/Downloads/FreeFlix/Torrents/.
"""

import os
import shutil
import subprocess

from ..cli_utils import (
    select_from_list,
    print_header,
    print_info,
    print_warning,
    print_error,
    print_success,
    get_user_input,
    pause,
)
from ..scraping import nyaa
from ..player_manager import DOWNLOAD_DIR


TORRENT_DIR = os.path.join(DOWNLOAD_DIR, "Torrents")


def _aria2c_path():
    return shutil.which("aria2c")


def _format_row(r: dict) -> str:
    return f"[S:{r['seeders']:>4}] {r['size']:>8}  {r['title']}"


def _download_torrent(magnet: str, title: str) -> bool:
    aria = _aria2c_path()
    if not aria:
        print_error(
            "aria2c is not installed (required for torrent downloads). "
            "Install with: sudo dnf install aria2"
        )
        return False

    os.makedirs(TORRENT_DIR, exist_ok=True)

    cmd = [
        aria,
        "--enable-dht=true",
        "--enable-dht6=false",
        "--bt-enable-lpd=true",
        "--bt-max-peers=50",
        "--seed-time=0",          # stop seeding immediately when done
        "--summary-interval=2",
        "--console-log-level=warn",
        f"--dir={TORRENT_DIR}",
        magnet,
    ]

    print_info(f"Downloading torrent into [cyan]{TORRENT_DIR}[/cyan]")
    print_info("(BitTorrent — speed depends on seeders ; press Ctrl-C to abort)")

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print_error(f"aria2c exited with code {e.returncode}")
        return False
    except KeyboardInterrupt:
        print_info("\nDownload interrupted by user.")
        return False
    except Exception as e:
        print_error(f"Download error: {e}")
        return False

    print_success(f"Torrent download finished : {title}")
    return True


def handle_nyaa():
    """Provider handler — registered from main.py."""
    print_header("🌊 Nyaa.si Torrents")

    if not _aria2c_path():
        print_error(
            "aria2c is required for torrent downloads. "
            "Install with: sudo dnf install aria2"
        )
        pause()
        return

    query = get_user_input("Search nyaa.si (e.g. 'Naruto 1080p'), or 'exit'")
    if not query or query.lower() == "exit":
        return

    print_info(f"Searching nyaa.si for [cyan]{query}[/cyan] ...")
    results = nyaa.search(query, max_results=20)

    if not results:
        print_warning("No results.")
        pause()
        return

    labels = [_format_row(r) for r in results] + ["← Back"]
    idx = select_from_list(labels, "Pick a torrent:")
    if idx == len(results):
        return

    chosen = results[idx]
    _download_torrent(chosen["magnet"], chosen["title"])
    pause()
