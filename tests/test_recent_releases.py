"""New-releases feed: it must be visible at launch, not after a detour.

The feed is personalised (history + followed shows) and costs ~30 s of network
on a cold cache: a planning read plus one season probe per show. The screen
used to wait only 8 s, so on a fresh launch it said "no new releases" and only
worked after the user wandered through Planning — which merely bought the
fetch enough time. It now persists its result, seeds the list from that
snapshot at startup, and refreshes in parallel in the background.
"""

import json
import time

import pytest

from freeflix_cli import recent


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(recent, "_state",
                        {"items": [], "ready": False, "started": False})
    monkeypatch.setattr(recent, "_ready", recent.threading.Event())
    monkeypatch.setattr(recent, "_cache_path",
                        lambda: str(tmp_path / "recent.json"))
    yield


def _item(title="Frieren"):
    return {"provider": "Anime-Sama", "title": title,
            "latest_season": "Saison 1", "latest_episode": "Épisode 5",
            "key": f"Anime-Sama|{title}|Saison 1|Épisode 5"}


def test_cache_roundtrip(tmp_path):
    recent._save_cache([_item()])
    loaded = recent._load_cache()
    assert len(loaded) == 1 and loaded[0]["title"] == "Frieren"


def test_stale_cache_is_ignored(tmp_path):
    path = tmp_path / "recent.json"
    path.write_text(json.dumps({"ts": time.time() - 3 * 86400,
                                "items": [_item()]}), encoding="utf-8")
    assert recent._load_cache() == []


def test_corrupt_cache_is_ignored(tmp_path):
    (tmp_path / "recent.json").write_text("{not json", encoding="utf-8")
    assert recent._load_cache() == []


def test_start_seeds_items_from_cache_without_waiting(monkeypatch):
    """Second launch: the list is there immediately, network refreshes after."""
    recent._save_cache([_item()])
    started = []
    monkeypatch.setattr(recent.threading, "Thread",
                        lambda **kw: type("T", (), {
                            "start": lambda self: started.append(True),
                            "name": kw.get("name"),
                        })())

    recent.start_background_fetch()

    assert len(recent.get_items()) == 1
    assert recent._state["ready"] is True
    # The refresh still runs in the background.
    assert started == [True]


def test_wait_ready_returns_immediately_with_a_snapshot():
    recent._state["items"] = [_item()]
    recent._state["ready"] = True
    t0 = time.time()
    assert len(recent.wait_ready(timeout=30)) == 1
    assert time.time() - t0 < 0.2


def test_wait_ready_is_bounded_without_a_snapshot():
    t0 = time.time()
    assert recent.wait_ready(timeout=0.2) == []
    assert time.time() - t0 < 2.0


def test_start_is_idempotent(monkeypatch):
    threads = []
    monkeypatch.setattr(recent.threading, "Thread",
                        lambda **kw: type("T", (), {
                            "start": lambda self: threads.append(True)})())
    recent.start_background_fetch()
    recent.start_background_fetch()
    assert len(threads) == 1


def test_fetch_checks_shows_in_parallel(monkeypatch):
    """Ten shows used to take 90 s sequentially; the pool bounds the wall time."""
    from freeflix_cli.tracker import tracker

    history = [{"provider": "Anime-Sama", "series_title": f"Show {i}",
                "series_url": f"https://anime-sama.to/catalogue/show-{i}",
                "season_title": "Saison 1", "episode_title": "Épisode 1",
                "logo_url": ""} for i in range(8)]
    from freeflix_cli.scraping import anime_sama

    monkeypatch.setattr(anime_sama, "get_website_url", lambda *a, **k: None)
    monkeypatch.setattr(tracker, "get_history", lambda: history)
    monkeypatch.setattr(tracker, "get_followed_series", lambda: [])
    monkeypatch.setattr(tracker, "get_seen_releases", lambda: set())
    monkeypatch.setattr(recent, "_planning_index", lambda: {})

    active = {"now": 0, "max": 0}
    def fake_item(cand, planning, seen):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        time.sleep(0.05)
        active["now"] -= 1
        return None

    monkeypatch.setattr(recent, "_candidate_item", fake_item)
    recent._fetch()
    assert active["max"] >= 2, "candidates must be checked concurrently"
    assert recent._state["ready"] is True


def test_fetch_failure_still_marks_ready(monkeypatch):
    from freeflix_cli.tracker import tracker

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(tracker, "get_history", boom)
    recent._fetch()
    assert recent._state["ready"] is True
    assert recent.get_items() == []
