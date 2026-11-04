"""Nouveautés must follow the episodes the user actually watches."""

from types import SimpleNamespace

from freeflix_cli import recent
from freeflix_cli.scraping import anime_sama
from freeflix_cli.scraping import anime_sama_planning
from freeflix_cli.tracker import tracker


def _ep(n):
    return SimpleNamespace(title=f"Episode {n}", url=f"https://x/ep{n}")


def _season(title, episodes, url="https://x/saison1"):
    return SimpleNamespace(title=title, url=url,
                           episodes={"vostfr": [_ep(n) for n in episodes]})


def _setup(monkeypatch, watched_episode="Episode 5", watched_season="Saison 1",
           latest_season="Saison 1", latest_eps=None,
           seen=None, planning=None):
    if latest_eps is None:
        latest_eps = range(1, 13)
    hist = [{
        "provider": "Anime-Sama",
        "series_title": "Frieren",
        "season_title": watched_season,
        "episode_title": watched_episode,
        "series_url": "https://anime-sama.to/catalogue/frieren",
        "season_url": "https://anime-sama.to/catalogue/frieren/saison1/vostfr",
    }]
    series = SimpleNamespace(
        title="Frieren",
        url="https://anime-sama.to/catalogue/frieren",
        img="https://img/frieren.jpg",
        seasons=[SimpleNamespace(title=latest_season,
                                 url="https://x/latest")],
    )
    season = _season(latest_season, latest_eps)
    monkeypatch.setattr(tracker, "get_history", lambda: hist)
    monkeypatch.setattr(tracker, "get_seen_releases", lambda: set(seen or ()))
    monkeypatch.setattr(anime_sama, "get_website_url", lambda: None)
    monkeypatch.setattr(anime_sama, "get_series", lambda url: series)
    monkeypatch.setattr(anime_sama, "get_season", lambda url: season)
    monkeypatch.setattr(anime_sama_planning, "get_planning",
                        lambda: (planning if planning is not None else []))
    recent._state["items"] = []
    recent._state["ready"] = False
    recent._fetch()
    return recent.get_items()


def test_new_episode_in_same_season_is_a_new_release(monkeypatch):
    items = _setup(monkeypatch)
    assert len(items) == 1
    assert items[0]["latest_episode"] == "Episode 12"
    assert items[0]["latest_season"] == "Saison 1"
    assert items[0]["key"].endswith("|Saison 1|Episode 12")


def test_latest_episode_already_watched_is_not_listed(monkeypatch):
    assert _setup(monkeypatch, watched_episode="Episode 12") == []


def test_new_season_is_a_new_release(monkeypatch):
    items = _setup(monkeypatch, watched_season="Saison 1",
                   latest_season="Saison 2", latest_eps=[1, 2])
    assert len(items) == 1
    assert items[0]["latest_season"] == "Saison 2"
    assert items[0]["latest_episode"] == "Episode 2"


def test_other_providers_are_ignored(monkeypatch):
    hist = [{"provider": "Coflix", "series_title": "X",
             "season_title": "S1", "episode_title": "E1",
             "series_url": "https://x", "season_url": "https://x"}]
    monkeypatch.setattr(tracker, "get_history", lambda: hist)
    monkeypatch.setattr(tracker, "get_seen_releases", lambda: set())
    recent._state["items"] = []
    recent._state["ready"] = False
    recent._fetch()
    assert recent.get_items() == []


def test_dismiss_removes_item_and_persists_key(monkeypatch):
    marked = []
    monkeypatch.setattr(tracker, "mark_release_seen", lambda key: marked.append(key))
    item = {"key": "Anime-Sama|X|Saison 1|Episode 9", "title": "X"}
    recent._state["items"] = [item, {"key": "other", "title": "Y"}]
    recent.dismiss(item)
    assert recent.get_items() == [{"key": "other", "title": "Y"}]
    assert marked == [item["key"]]


def test_seen_key_is_filtered(monkeypatch):
    key = "Anime-Sama|Frieren|Saison 1|Episode 12"
    assert _setup(monkeypatch, seen={key}) == []


def test_unreleased_planning_episode_is_not_announced(monkeypatch):
    """Anime-Sama pre-creates the upcoming episode page; the planning's
    released flag must keep it out of Nouveautés until it actually airs."""
    entry = SimpleNamespace(
        url="https://anime-sama.to/catalogue/frieren",
        released=False,
    )
    items = _setup(monkeypatch, watched_episode="Episode 11",
                   latest_eps=range(1, 13), planning=[entry])
    # Latest listed is 12 but not out → last released is 11, already watched.
    assert items == []


def test_previous_released_episode_is_announced(monkeypatch):
    entry = SimpleNamespace(
        url="https://anime-sama.to/catalogue/frieren",
        released=False,
    )
    items = _setup(monkeypatch, watched_episode="Episode 10",
                   latest_eps=range(1, 13), planning=[entry])
    assert len(items) == 1
    assert items[0]["latest_episode"] == "Episode 11"


def test_released_planning_episode_is_announced(monkeypatch):
    entry = SimpleNamespace(
        url="https://anime-sama.to/catalogue/frieren",
        released=True,
    )
    items = _setup(monkeypatch, watched_episode="Episode 11",
                   latest_eps=range(1, 13), planning=[entry])
    assert len(items) == 1
    assert items[0]["latest_episode"] == "Episode 12"
