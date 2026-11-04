"""
Background "new releases" feed, personalised to what you watch.

At launch we spawn a daemon thread that, for the Anime-Sama series in your
history, re-checks the source and keeps only the shows with content NEWER than
what you last watched:

* a new episode in the season you follow (Episode 12 while you stopped at 5),
* or a whole new season/part.

It is fully non-blocking: the home screen never waits on it, and a network
failure just leaves the feed empty. Items are dismissed once opened; because
the dismissal key includes the episode, a later episode makes the show come
back automatically.
"""

from __future__ import annotations

import re
import threading

_state = {"items": [], "ready": False, "started": False}
_lock = threading.Lock()

_MAX_SHOWS = 10  # history entries checked per refresh


def start_background_fetch():
    """Kick off the fetch once per process (no-op if already started)."""
    with _lock:
        if _state["started"]:
            return
        _state["started"] = True
    threading.Thread(target=_fetch, name="freeflix-recent", daemon=True).start()


def get_items() -> list:
    """New-release items found so far : [{title, url, poster, latest_season}]."""
    with _lock:
        return list(_state["items"])


def wait_ready(timeout: float = 8.0) -> list:
    """Block (bounded) until the background feed has finished, then return its
    items. Used only when the user explicitly opens 'New releases' before the
    silent fetch has landed — the home screen itself never waits."""
    import time as _t
    end = _t.time() + max(0.0, timeout)
    while not _state["ready"] and _t.time() < end:
        _t.sleep(0.1)
    return get_items()


def dismiss(item: dict) -> None:
    """Mark one release as seen and remove it from the home badge immediately.

    Called as soon as the user opens the item. The key contains the latest
    episode, so the next episode will create a new key and show up again.
    """
    key = (item or {}).get("key")
    if not key:
        return
    try:
        from .tracker import tracker
        tracker.mark_release_seen(key)
    except Exception:
        pass
    with _lock:
        _state["items"] = [i for i in _state["items"] if i.get("key") != key]


def _abs_url(url: str) -> str:
    """History stores same-origin URLs as relative paths."""
    if not url:
        return ""
    if str(url).startswith("http"):
        return str(url)
    try:
        from .scraping import anime_sama
        return anime_sama.website_origin.rstrip("/") + "/" + str(url).lstrip("/")
    except Exception:
        return str(url)


def _ep_num(title: str) -> int:
    """Episode number from a title ('Episode 12' → 12); 0 when absent."""
    nums = re.findall(r"\d+", str(title or ""))
    try:
        return int(nums[-1]) if nums else 0
    except (TypeError, ValueError):
        return 0


def _latest_episode(season) -> tuple[str, int]:
    """Latest episode title/number across every language track."""
    best_title, best_num = "", -1
    for episodes in (getattr(season, "episodes", {}) or {}).values():
        for ep in episodes or []:
            num = _ep_num(getattr(ep, "title", ""))
            if num > best_num:
                best_num, best_title = num, getattr(ep, "title", "")
    return best_title, max(0, best_num)


def _norm_url(url: str) -> str:
    return str(url or "").strip().rstrip("/").lower()


def _planning_index() -> dict:
    """Map catalogue URL → this week's planning entries (with release state).

    Anime-Sama pre-publishes the episode page: the season's LAST episode may
    not have aired yet. The planning's live ``released`` flag is what tells
    us whether that episode is really out.
    """
    try:
        from .scraping import anime_sama_planning as planning
        entries = planning.get_planning()
    except Exception:
        return {}
    index = {}
    for entry in entries or []:
        index.setdefault(_norm_url(getattr(entry, "url", "")), []).append(entry)
    return index


def _episode_title_at(season, number: int) -> str:
    for episodes in (getattr(season, "episodes", {}) or {}).values():
        for ep in episodes or []:
            if _ep_num(getattr(ep, "title", "")) == number:
                return getattr(ep, "title", "")
    return ""


def _fetch():
    items = []
    try:
        from .tracker import tracker
        from .scraping import anime_sama

        history = tracker.get_history()
        if history:
            anime_sama.get_website_url()
        seen_keys = tracker.get_seen_releases()
        planning = _planning_index()

        seen_titles = set()
        checked = 0
        for e in history:
            if checked >= _MAX_SHOWS:
                break
            if e.get("provider") != "Anime-Sama":
                continue
            title = (e.get("series_title") or "").strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            checked += 1

            series_url = _abs_url(e.get("series_url"))
            if not series_url:
                continue
            try:
                series = anime_sama.get_series(series_url)
            except Exception:
                continue
            seasons = getattr(series, "seasons", None) or []
            if not seasons:
                continue

            latest = seasons[-1]
            try:
                season = anime_sama.get_season(_abs_url(latest.url))
            except Exception:
                continue
            season_eps = getattr(season, "episodes", None) or {}
            if not season_eps:
                continue
            latest_episode, latest_num = _latest_episode(season)
            if not latest_episode:
                continue

            # If the current week's planning says the episode is not out yet,
            # step back to the last really-released episode (the source
            # pre-creates the upcoming episode page).
            week = planning.get(_norm_url(series_url), [])
            if week and not any(getattr(p, "released", False) for p in week):
                if latest_num > 0:
                    latest_num -= 1
                    latest_episode = (
                        _episode_title_at(season, latest_num) or latest_episode
                    )
                if latest_num <= 0:
                    continue

            watched_season = (e.get("season_title") or "").strip()
            watched_episode = (e.get("episode_title") or "").strip()
            watched_num = _ep_num(watched_episode)

            # New = a whole new season, or a later episode in the same one.
            new_season = latest.title.strip().lower() != watched_season.lower()
            new_episode = latest_num > watched_num
            if not (new_season or new_episode):
                continue

            key = f"Anime-Sama|{title}|{latest.title}|{latest_episode}"
            if key in seen_keys:
                continue

            items.append({
                "title": title,
                "url": getattr(series, "url", series_url),
                "poster": getattr(series, "img", "") or e.get("logo_url") or "",
                "latest_season": latest.title,
                "season_url": _abs_url(latest.url),
                "latest_episode": latest_episode,
                "episode_number": latest_num,
                "key": key,
            })
    except Exception:
        pass
    finally:
        with _lock:
            _state["items"] = items
            _state["ready"] = True
