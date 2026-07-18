"""
Best-effort source health checks — powers the 'offline' badge in the sources
menu so a user sees at a glance that (say) French-Stream is unreachable right
now instead of picking it and hitting a wall.

Design goals :
  • NEVER block the UI — checks run in a background thread with a short per-host
    timeout, results cached for a few minutes ;
  • conservative — a source is badged offline ONLY when a check definitively
    fails (DNS / connect / timeout). Any HTTP response (even a 403 Cloudflare
    challenge or a 404) means the host is reachable, so it's counted UP ;
  • self-contained — the sources menu just calls badge_for(label).
"""

from __future__ import annotations

import threading
import time

# Portal key (in scraping.config.portals) -> substrings identifying the menu
# label of the provider that uses it. Only sources with a fixed, checkable base
# host are listed ; dynamically-resolved aggregators (GoldenMS/GoldenAnime,
# Papystreaming, Nyaa) are intentionally omitted — a green/red dot there would
# be misleading.
_PROVIDER_HOSTS: dict[str, list[str]] = {
    "anime-sama": ["anime-sama"],
    "french-manga": ["french-anime", "french-manga"],
    "coflix": ["coflix"],
    "french-stream": ["french-stream"],
}

_TTL = 300.0  # seconds a result stays fresh

_lock = threading.Lock()
_status: dict[str, tuple[float, bool]] = {}  # key -> (checked_at, is_up)
_checking = False
_last_run = 0.0


def _host_up(url: str) -> bool:
    """True if the host answers with ANY HTTP response (reachable)."""
    try:
        from curl_cffi import requests
        requests.get(url, impersonate="chrome", timeout=6, allow_redirects=True)
        return True
    except Exception:
        return False


def _check_one(key: str, url: str) -> None:
    up = _host_up(url)
    with _lock:
        _status[key] = (time.time(), up)


def refresh(portals: dict, force: bool = False) -> None:
    """Kick off (in the background) a health sweep of the known source hosts.

    No-op if a sweep is already running or the last one is still fresh (unless
    *force*). Returns immediately — results land in the cache as they arrive.
    """
    global _checking, _last_run
    now = time.time()
    with _lock:
        if _checking:
            return
        if not force and (now - _last_run) < _TTL:
            return
        _checking = True
        _last_run = now

    def _run():
        global _checking
        threads = []
        for key in _PROVIDER_HOSTS:
            url = portals.get(key)
            if not url:
                continue
            th = threading.Thread(target=_check_one, args=(key, url), daemon=True)
            th.start()
            threads.append(th)
        for th in threads:
            th.join(timeout=8)
        with _lock:
            _checking = False

    threading.Thread(target=_run, daemon=True).start()


def badge_for(label: str) -> str:
    """Return a trailing offline badge for a provider menu *label*, or ''.

    Only badges when we have a FRESH, definitive 'down' result — an unknown or
    stale source shows nothing (fail-quiet)."""
    low = label.lower()
    for key, needles in _PROVIDER_HOSTS.items():
        if any(n in low for n in needles):
            ent = _status.get(key)
            if ent and (time.time() - ent[0]) < _TTL and not ent[1]:
                from .icons import icon
                from .i18n import t
                return f"  {icon('offline')} {t('offline')}"
            return ""
    return ""
