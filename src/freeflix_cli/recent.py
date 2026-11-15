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

import json
import os
import re
import threading

_state = {"items": [], "ready": False, "started": False}
_lock = threading.Lock()
_ready = threading.Event()

_MAX_SHOWS = 10  # history entries checked per refresh

# The feed costs ~30 s of network on a cold cache (planning + one season probe
# per show), so it is persisted: the next launch shows the last result
# instantly and refreshes in the background. Without it, opening the entry
# before the fetch landed said "no new releases" until the user wandered into
# Planning, which merely bought the fetch enough time.
_CACHE_MAX_AGE = 24 * 3600


def _cache_path():
    try:
        from platformdirs import user_cache_dir
        base = user_cache_dir("freeflix-cli", "PaulExplorer")
    except Exception:
        return None
    return os.path.join(base, "recent_releases.json")


def _load_cache() -> list:
    path = _cache_path()
    if not path:
        return []
    try:
        import time
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
        if time.time() - float(blob.get("ts") or 0) > _CACHE_MAX_AGE:
            return []
        items = blob.get("items")
        return items if isinstance(items, list) else []
    except Exception:
        return []


def _save_cache(items: list) -> None:
    path = _cache_path()
    if not path:
        return
    try:
        import time
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"ts": time.time(), "items": items}, fh,
                      ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def start_background_fetch():
    """Kick off the fetch once per process (no-op if already started).

    Seeds the in-memory list from the last snapshot first, so a second launch
    shows New releases immediately instead of waiting on the network.
    """
    with _lock:
        if _state["started"]:
            return
        _state["started"] = True
        if not _state["items"]:
            cached = _load_cache()
            if cached:
                _state["items"] = cached
                _state["ready"] = True
                _ready.set()
    threading.Thread(target=_fetch, name="freeflix-recent", daemon=True).start()


def get_items() -> list:
    """New-release items found so far : [{title, url, poster, latest_season}]."""
    with _lock:
        return list(_state["items"])


def wait_ready(timeout: float = 45.0) -> list:
    """Block (bounded) until the background feed has finished, then return it.

    The budget used to be 8 s while the fetch needs ~30 s cold, which is
    exactly why the screen said "no new releases" on a fresh launch. A cached
    snapshot returns immediately.
    """
    if not _state["ready"]:
        _ready.wait(timeout=max(0.0, timeout))
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
        if item.get("provider") and item.get("title"):
            tracker.update_followed_progress(
                item["provider"], item["title"],
                item.get("latest_season", ""),
                item.get("latest_episode", ""),
            )
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


def _candidate_item(cand, planning, seen_keys):
    """Check ONE show and return its new-release item, or None.

    Pure network work on a copy of the candidate: safe to run in a pool. The
    old sequential loop took ~9 s per show (nine language probes for the
    season), so ten shows needed 90 s+, while the UI only waited 8 s — that is
    why "New releases" looked empty on a fresh launch and only appeared after
    wandering through Planning (which bought the fetch enough time).
    """
    from .scraping import anime_sama

    title = cand["title"]
    series_url = cand["series_url"]
    if not series_url:
        return None
    try:
        series = anime_sama.get_series(series_url)
    except Exception:
        return None
    seasons = getattr(series, "seasons", None) or []
    if not seasons:
        return None

    latest = seasons[-1]
    try:
        season = anime_sama.get_season(_abs_url(latest.url))
    except Exception:
        return None
    if not (getattr(season, "episodes", None) or {}):
        return None
    latest_episode, latest_num = _latest_episode(season)
    if not latest_episode:
        return None

    # If the current week's planning says the episode is not out yet, step
    # back to the last really-released one (the source pre-creates the page).
    week = planning.get(_norm_url(series_url), [])
    if week and not any(getattr(p, "released", False) for p in week):
        if latest_num > 0:
            latest_num -= 1
            latest_episode = _episode_title_at(season, latest_num) or latest_episode
        if latest_num <= 0:
            return None

    watched_season = cand["season"]
    watched_num = cand["ep_num"]

    new_season = latest.title.strip().lower() != watched_season.lower()
    new_episode = latest_num > watched_num
    if not (new_season or new_episode):
        return None

    key = f"Anime-Sama|{title}|{latest.title}|{latest_episode}"
    if key in seen_keys:
        return None

    return {
        "provider": "Anime-Sama",
        "title": title,
        "url": getattr(series, "url", series_url),
        "poster": getattr(series, "img", "") or cand["logo"] or "",
        "latest_season": latest.title,
        "season_url": _abs_url(latest.url),
        "latest_episode": latest_episode,
        "episode_number": latest_num,
        "key": key,
    }


def _fetch():
    items = []
    try:
        from .tracker import tracker
        from .scraping import anime_sama

        history = tracker.get_history()
        followed = tracker.get_followed_series()
        # Resolve the Anime-Sama mirror only when there is actually an
        # Anime-Sama show to follow: a Coflix-only history used to trigger a
        # network request (and a ~3 s stall) for nothing.
        has_anime = any(
            (e.get("provider") == "Anime-Sama") for e in history
        ) or any(
            isinstance(f, dict) and f.get("provider") == "Anime-Sama"
            for f in followed
        )
        if has_anime:
            anime_sama.get_website_url()
        seen_keys = tracker.get_seen_releases()

        # Candidate shows: history first (most recent), then planning follows
        # that have never been played.
        candidates = []
        seen_titles = set()
        for e in history:
            if e.get("provider") != "Anime-Sama":
                continue
            title = (e.get("series_title") or "").strip()
            if not title or title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())
            candidates.append({
                "title": title,
                "series_url": _abs_url(e.get("series_url")),
                "logo": e.get("logo_url") or "",
                "season": (e.get("season_title") or "").strip(),
                "ep_num": _ep_num(e.get("episode_title")),
                "source": "history",
            })
        for f in followed:
            if not isinstance(f, dict) or f.get("provider") != "Anime-Sama":
                continue
            title = (f.get("title") or "").strip()
            if not title or title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())
            candidates.append({
                "title": title,
                "series_url": _abs_url(f.get("series_url")),
                "logo": f.get("logo_url") or "",
                "season": (f.get("last_season") or "").strip(),
                "ep_num": int(f.get("last_episode_num") or 0),
                "source": "follow",
            })

        candidates = [c for c in candidates[:_MAX_SHOWS] if c["series_url"]]
        # Planning is a 6-7 s network read on a cold cache: only pay for it
        # when there is a show to check, and do it in parallel with nothing
        # else that depends on it.
        planning = _planning_index() if candidates else {}
        if candidates:
            from concurrent.futures import ThreadPoolExecutor
            workers = min(4, len(candidates))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                found = list(pool.map(
                    lambda c: _candidate_item(c, planning, seen_keys),
                    candidates,
                ))
            items = [i for i in found if i]
    except Exception:
        pass
    finally:
        with _lock:
            _state["items"] = items
            _state["ready"] = True
        _ready.set()
        _save_cache(items)
