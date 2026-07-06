"""
Background "new releases" feed, personalised to what you watch.

At launch we spawn a daemon thread that, for the Anime-Sama series in your
history, re-checks the source and keeps only the shows whose LATEST season/part
differs from the one you last watched — i.e. there's newer content for a show
you follow. It's fully non-blocking: the home screen never waits on it, and a
network failure just leaves the feed empty.
"""

from __future__ import annotations

import threading

_state = {"items": [], "ready": False, "started": False}
_lock = threading.Lock()


def start_background_fetch():
    """Kick off the fetch once per process (no-op if already started)."""
    with _lock:
        if _state["started"]:
            return
        _state["started"] = True
    threading.Thread(target=_fetch, name="freeflix-recent", daemon=True).start()


def get_items() -> list:
    """New-release items found so far : [{title, url, poster, latest_season}]."""
    return list(_state["items"])


def is_ready() -> bool:
    return _state["ready"]


def _fetch():
    items = []
    try:
        from .tracker import tracker
        from .scraping import anime_sama

        history = tracker.get_history()
        if history:
            anime_sama.get_website_url()

        seen = set()
        for e in history:
            if len(seen) >= 6:
                break
            if e.get("provider") != "Anime-Sama":
                continue
            title = e.get("series_title")
            url = e.get("series_url")
            if not title or not url or title in seen:
                continue
            seen.add(title)
            try:
                series = anime_sama.get_series(url)
            except Exception:
                continue
            if not series.seasons:
                continue
            latest = series.seasons[-1]
            watched_season = (e.get("season_title") or "").strip().lower()
            # "New" = the latest season/part isn't the one you last watched.
            if latest.title.strip().lower() != watched_season:
                items.append({
                    "title": title,
                    "url": series.url,
                    "poster": getattr(series, "img", ""),
                    "latest_season": latest.title,
                    "season_url": latest.url,
                })
    except Exception:
        pass
    finally:
        _state["items"] = items
        _state["ready"] = True
