"""
Nyaa.si torrent provider for FreeFlix.

Searches nyaa.si (anime-first), lets the user pick a result, then either
downloads it via aria2c (BitTorrent) or downloads it *while watching*
(sequential pieces + mpv on the growing file). Output directory is
~/Downloads/FreeFlix/Torrents/ (scanned by the Local Downloads browser).
"""

import os
import shutil
import subprocess
import time

from ..cli_utils import (
    select_from_list,
    select_multiple,
    print_header,
    print_info,
    print_warning,
    print_error,
    print_success,
    get_user_input,
    pause,
    skeleton,
    push_toast,
)
from ..scraping import nyaa
from ..player_manager import DOWNLOAD_DIR, get_mpv_path
from ..tracker import tracker
from ..icons import icon
from ..i18n import t


TORRENT_DIR = os.path.join(DOWNLOAD_DIR, "Torrents")
VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".webm", ".m4v", ".mov", ".ts"}

# Public trackers appended to every download so metadata/peers resolve fast
# even when DHT is slow. aria2 tries them in order; dead ones are skipped.
TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.tracker.cl:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.dutchtracking.com:6969/announce",
    "udp://open.stealth.si:80/announce",
    "udp://ipv4.tracker.harry.lu:80/announce",
]

# (menu label, category, trusted_only). Labels go through icon()/t() at
# display time (see scope_labels below) so nerd mode + FR both apply.
SCOPES = [
    ("anime", "anime", False),
    ("english", "english", False),
    ("raw", "raw", False),
    ("manga", "manga", False),
    ("trusted", "anime", True),
    ("all", "all", False),
]

_SCOPE_LABELS = {
    # (icon-name, FR-ready label key)
    "anime": ("anime", "Anime (all)"),
    "english": ("globe", "Anime — English-translated"),
    "raw": ("globe", "Anime — Raw"),
    "manga": ("book", "Manga"),
    "trusted": ("verified", "Trusted uploads only"),
    "all": ("package", "Everything (all categories)"),
}


def _scope_labels():
    from ..icons import icon
    from ..i18n import t
    return [f"{icon(ic)} {t(label)}" for _k, (ic, label) in
            ((k, _SCOPE_LABELS[k]) for k, _, _ in SCOPES)]


def _aria2c_path():
    return shutil.which("aria2c")


def _format_row(r: dict) -> str:
    trust = "✓" if r.get("trusted") else " "
    dead = f" [{t('dead')}]" if not r.get("seeders") else ""
    return (f"[S:{r['seeders']:>4}] [{r.get('quality', '?'):>5}]"
            f"[{trust}] {r['size']:>10}  {r['title']}{dead}")


def _base_aria_cmd(magnet: str, sequential: bool = False) -> list:
    aria = _aria2c_path()
    cmd = [
        aria,
        "--enable-dht=true",
        "--enable-dht6=false",
        # DHT bootstrap routers : without these, a stale/missing dht.dat
        # leaves magnet metadata resolution stuck at 0B forever.
        "--dht-entry-point=router.bittorrent.com:6881",
        "--dht-entry-point6=router.bittorrent.com:6881",
        "--bt-enable-lpd=true",
        "--bt-max-peers=60",
        "--bt-tracker=" + ",".join(TRACKERS),
        "--bt-tracker-connect-timeout=10",
        # Give up a dead torrent instead of hanging at 0B forever : the
        # caller reports failure and the user can try another release.
        "--bt-stop-timeout=300",
        "--seed-ratio=0.0",
        "--seed-time=0",          # stop seeding immediately when done
        "--summary-interval=2",
        "--console-log-level=warn",
        f"--dir={TORRENT_DIR}",
    ]
    if sequential:
        # Sequential pieces + head priority => playable before completion.
        cmd += [
            "--bt-sequential-download=true",
            "--bt-prioritize-piece=head=32M,tail=32M",
            "--file-allocation=none",
        ]
    cmd.append(magnet)
    return cmd


def _download_torrent(magnet: str, title: str, watch: bool = False) -> bool:
    os.makedirs(TORRENT_DIR, exist_ok=True)

    if not watch:
        from ..progress import run_download_with_bar
        cmd = _base_aria_cmd(magnet) + ["--continue=true"]
        print_info(f"{t('Downloading torrent into')} [cyan]{TORRENT_DIR}[/cyan]")
        print_info(t("(Re-select the same torrent later to resume an interrupted download)"))
        rc = run_download_with_bar(cmd, title)
        if rc != 0:
            print_error(f"aria2c {t('exited with code')} {rc}")
            return False
        print_success(f"{t('Torrent download finished:')} {title}")
        push_toast(f"{t('Torrent download finished:')} {title}", bell=True)
        return True

    return _download_and_watch(magnet, title)


def _new_video_files(since: float):
    """Video files under TORRENT_DIR created after `since` (largest first)."""
    found = []
    for root, _dirs, names in os.walk(TORRENT_DIR):
        for n in names:
            if n.endswith(".aria2"):
                continue
            if os.path.splitext(n)[1].lower() not in VIDEO_EXTS:
                continue
            full = os.path.join(root, n)
            try:
                if os.path.getmtime(full) < since:
                    continue
                found.append((os.path.getsize(full), full))
            except OSError:
                continue
    found.sort(reverse=True)
    return [f for _s, f in found]


def _download_and_watch(magnet: str, title: str) -> bool:
    """Stream-while-downloading: sequential aria2 in background, mpv on the
    growing file. Stopping the player stops aria2 ; progress is kept in the
    .aria2 control files and resumes on re-download."""
    mpv = None
    try:
        mpv = get_mpv_path()
    except Exception:
        pass
    mpv = mpv or shutil.which("mpv")
    if not mpv:
        print_error(t("mpv is not installed (required to watch while downloading)."))
        return False

    t0 = time.time()
    print_info(t("Starting download (sequential pieces for early playback)..."))
    try:
        proc = subprocess.Popen(
            _base_aria_cmd(magnet, sequential=True),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
    except Exception as e:
        print_error(f"{t('Download error:')} {e}")
        return False

    target = None
    try:
        # Wait for a playable prefix: biggest fresh video file ≥ 25 MB.
        deadline = time.time() + 180
        while time.time() < deadline:
            if proc.poll() is not None:
                break  # tiny torrent already finished
            cands = _new_video_files(t0)
            if cands and os.path.getsize(cands[0]) >= 25 * 1024 * 1024:
                target = cands[0]
                if len(cands) > 1:
                    print_warning(t("Multi-file torrent: playing the largest file."))
                break
            time.sleep(2)

        if target is None:
            cands = _new_video_files(t0)
            if proc.poll() is not None and cands:
                target = cands[0]  # finished quickly, play the result
            else:
                print_warning(t("Not enough data yet — leaving the download running in the foreground."))
                proc.wait()
                print_success(f"{t('Torrent download finished:')} {title}")
                push_toast(f"{t('Torrent download finished:')} {title}", bell=True)
                return proc.returncode == 0

        print_info(f"{t('Playing (download continues in background):')} {os.path.basename(target)}")
        print_info(t("(Close the player to stop the download ; progress is kept and resumable)"))
        try:
            subprocess.run([mpv, f"--force-media-title={title}", target], check=False)
        except KeyboardInterrupt:
            pass
        return True
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


def handle_nyaa():
    """Provider handler — registered from main.py."""
    print_header(t("🌊 Nyaa.si Torrents"))

    if not _aria2c_path():
        print_error(
            f"{t('aria2c is not installed (required for torrent downloads).')} "
            f"{t('Install with:')} {t('sudo apt install aria2 / sudo dnf install aria2 / brew install aria2')}"
        )
        pause()
        return

    scope_labels = _scope_labels() + [t("← Back")]
    scope_idx = select_from_list(scope_labels, t("Search scope:"))
    if scope_idx >= len(SCOPES):
        return
    _label, category, trusted_only = SCOPES[scope_idx]

    mode = select_from_list(
        [f"{icon('new')} {t('Latest uploads')}",
         f"{icon('search')} {t('Search by title')}", t("← Back")],
        f"{icon('wave')} Nyaa",
    )
    if mode == 1:
        query = get_user_input(
            t("Search query (or 'exit' to back)"),
            header=f"{icon('wave')} Nyaa",
            history=tracker.get_search_history(),
        )
        if query and query.lower() != "exit":
            tracker.add_search_query(query)
        if not query or query.lower() == "exit":
            return
        print_info(f"{t('Searching nyaa.si for')} [cyan]{query}[/cyan] ...")
        results = nyaa.search(query, max_results=20, category=category,
                              trusted_only=trusted_only)
    elif mode == 0:
        with skeleton(f"{t('Loading latest torrents…')}"):
            results = nyaa.latest(category, max_results=20)
    else:
        return

    if not results:
        if nyaa.last_error:
            print_warning(f"{t('Search failed:')} {nyaa.last_error}")
        else:
            print_warning(t("No results."))
        pause()
        return

    labels = [_format_row(r) for r in results] + [t("← Back")]
    idx = select_from_list(labels, t("Pick a torrent:"))
    if idx >= len(results):
        return

    chosen = results[idx]
    if not chosen.get("seeders"):
        print_warning(t("Warning: 0 seeders — this torrent may never complete."))
    actions = [f"{icon('play')} {t('Stream')}", f"{icon('download')} {t('Download')}", f"{icon('play')} {t('Download + Watch')}",
               f"{icon('list')} {t('Batch download (multi-select)')}", t("← Back")]
    act = select_from_list(actions, chosen["title"][:60])
    if act == 0:
        from .yts import _stream_via_goldenanime
        _stream_via_goldenanime(chosen["title"])
    elif act == 1:
        _download_torrent(chosen["magnet"], chosen["title"], watch=False)
    elif act == 2:
        _download_and_watch(chosen["magnet"], chosen["title"])
    elif act == 3:
        _batch_download(results)
    else:
        return
    pause()


def _batch_download(results: list) -> None:
    """Multi-select torrents (Space/a, like season batch) then download them
    one by one with the themed progress bar. Esc cancels the picker."""
    from ..cli_utils import icon
    labels = [_format_row(r) for r in results]
    picked = select_multiple(
        labels,
        f"{icon('download')} {t('Select torrents to download:')}",
    )
    if not picked:
        return
    ok, fail = 0, 0
    for i in picked:
        r = results[i]
        print_info(f"\n[{i + 1}/{len(picked)}] {r['title'][:70]}")
        if _download_torrent(r["magnet"], r["title"], watch=False):
            ok += 1
        else:
            fail += 1
    if fail:
        print_warning(f"{t('Batch finished:')} {ok} ✓, {fail} ✗")
    else:
        print_success(f"{t('Batch finished:')} {ok} ✓")
    push_toast(f"{t('Batch finished:')} {ok} ✓")
