"""Back/Esc must always go exactly ONE level up.

The user reported that leaving a player list jumped over the level it came
from ("from an episode, Back sends me to the main menu instead of the
season"). These tests pin the hierarchy of the flows that had that bug:

    players → episode → language → season → results → search/home

Each case scripts the menu answers and asserts which screen is shown next, so
a future change that skips or repeats a level fails here instead of in front of
the user.
"""

import types

from freeflix_cli import main as main_mod


# ── helpers ──────────────────────────────────────────────────────────
class _Season:
    def __init__(self, lanes):
        self.episodes = lanes
        self.title = "Saison 1"


class _Episode:
    def __init__(self, title):
        self.title = title
        self.players = []


def _ep(title):
    return _Episode(title)


# ── Match: players → quality → match list ────────────────────────────
def test_match_back_from_quality_returns_to_match_list(monkeypatch):
    from freeflix_cli.handlers import match as mh

    screens = []

    def fake_fetch_events():
        return [types.SimpleNamespace(
            id="1", championship="L", channel="beIN 1",
            start=0, end=2 ** 31 - 1, home="A", away="B",
            start_dt=None, status=lambda now: "live",
        )], False

    # The prompts are translated (FR/EN depending on the profile), so drive
    # the script by CALL ORDER instead of matching English text:
    #   1) match list → open the first match
    #   2) quality screen → ← Back
    #   3) match list → ← Back (leave)
    answers = iter([0, "back", "back"])

    def fake_select(options, prompt, **kw):
        screens.append(prompt)
        answer = next(answers, "back")
        if answer == "back":
            return len(options) - 1
        return answer

    monkeypatch.setattr(mh.ym, "fetch_events", fake_fetch_events)
    monkeypatch.setattr(mh, "select_from_list", fake_select)
    monkeypatch.setattr(mh, "_sort_events", lambda ev, now: ev)
    monkeypatch.setattr(mh, "_dedupe", lambda ev, now: ev)
    monkeypatch.setattr(mh, "_column_widths", lambda ordered, now: {})
    monkeypatch.setattr(mh, "_build_rows", lambda group, now, w: ["row"])
    monkeypatch.setattr(mh, "_group_label", lambda state, n: state)
    monkeypatch.setattr(mh.ym, "localize_events",
                        lambda evs, lang: evs)
    # Never touch the network: the quality screen only needs a couple of rows.
    monkeypatch.setattr(mh.ym, "fetch_streams",
                        lambda event_id, **kw: [
                            {"name": "HD", "url": "https://x/hd.m3u8",
                             "headers": {}},
                            {"name": "SD", "url": "https://x/sd.m3u8",
                             "headers": {}},
                        ])
    monkeypatch.setattr(mh, "_quality_label", lambda s: s["name"])
    monkeypatch.setattr(mh, "_choose_player",
                        lambda current, allow_cancel=False: None)
    monkeypatch.setattr(mh, "_play", lambda *a, **k: True)

    mh.handle_match()

    assert len(screens) >= 3, (
        "Back on the quality screen must re-show the match list, "
        f"got screens={screens!r}"
    )


# ── New releases: players → episodes → language → list ───────────────
def _stub_new_releases(monkeypatch, langs):
    from freeflix_cli import recent
    from freeflix_cli.handlers import playback
    from freeflix_cli.scraping import anime_sama

    season = _Season({lang: [_ep("Épisode 1"), _ep("Épisode 2")]
                      for lang in langs})
    monkeypatch.setattr(anime_sama, "get_season",
                        lambda url, **kw: season)
    monkeypatch.setattr(playback, "play_episode_flow",
                        lambda **kw: False)  # Back from the players
    monkeypatch.setattr(recent, "get_items",
                        lambda: [{"title": "X", "url": "u", "poster": "",
                                  "latest_season": "Saison 1",
                                  "season_url": "s",
                                  "latest_episode": "Épisode 1"}])
    monkeypatch.setattr(recent, "dismiss", lambda it: None)
    monkeypatch.setattr(recent, "_ep_num", lambda title: 1)

    from freeflix_cli import terminal_image
    monkeypatch.setattr(terminal_image, "show_poster",
                        lambda *a, **k: None, raising=False)

    calls = {"list": 0}

    def fake_select_with_preview(labels, prompt, previews):
        calls["list"] += 1
        if calls["list"] == 1:
            return 0            # open the first release
        return len(labels)      # then Back out of the list

    from freeflix_cli import cli_utils
    monkeypatch.setattr(cli_utils, "select_with_preview",
                        fake_select_with_preview)
    monkeypatch.setattr(main_mod, "select_with_preview",
                        fake_select_with_preview, raising=False)
    return calls


def test_new_releases_back_from_episode_returns_to_the_list(monkeypatch):
    calls = _stub_new_releases(monkeypatch, ["vostfr"])

    def fake_select(options, prompt, **kw):
        # Episode screen: choose ← Back immediately.
        return len(options) - 1

    monkeypatch.setattr(main_mod, "select_from_list", fake_select)

    main_mod._browse_new_releases([
        {"title": "X", "url": "u", "poster": "", "latest_season": "Saison 1",
         "season_url": "s", "latest_episode": "Épisode 1"}])

    assert calls["list"] >= 2, (
        "Back from an episode must return to the New-releases list, "
        "not to the home menu"
    )


def test_new_releases_back_from_language_returns_to_the_list(monkeypatch):
    calls = _stub_new_releases(monkeypatch, ["vostfr", "vf"])

    def fake_select(options, prompt, **kw):
        if "Language" in prompt or "langue" in prompt.lower():
            return len(options) - 1   # ← Back on the language screen
        return len(options) - 1

    monkeypatch.setattr(main_mod, "select_from_list", fake_select)

    main_mod._browse_new_releases([
        {"title": "X", "url": "u", "poster": "", "latest_season": "Saison 1",
         "season_url": "s", "latest_episode": "Épisode 1"}])

    assert calls["list"] >= 2, (
        "Back from the language screen must return to the New-releases list"
    )


# ── Papystreaming: season → results (not the search prompt) ──────────
def test_papystreaming_back_from_season_returns_to_results(monkeypatch):
    from freeflix_cli.handlers import papystreaming as ph

    results = [{"title": "Film", "year": "2020", "media_type": "series",
                "poster": "", "tmdb_id": "1"}]
    monkeypatch.setattr(ph.papystreaming, "search", lambda q: results)
    monkeypatch.setattr(ph.papystreaming, "blocked_by_cloudflare", False,
                        raising=False)
    monkeypatch.setattr(ph.tracker, "get_search_history", lambda: [],
                        raising=False)
    monkeypatch.setattr(ph.tracker, "add_search_query", lambda q: None,
                        raising=False)

    inputs = iter(["film", "exit"])   # then leave the search level
    monkeypatch.setattr(ph, "get_user_input", lambda *a, **k: next(inputs, "exit"))
    monkeypatch.setattr(ph, "clear_screen", lambda: None, raising=False)
    monkeypatch.setattr(ph, "skeleton", lambda *a, **k: _Ctx())

    shown = []

    def fake_select_with_preview(labels, prompt, previews):
        shown.append(prompt)
        return 0 if len(shown) == 1 else len(labels)  # open once, then Back

    monkeypatch.setattr(ph, "select_with_preview", fake_select_with_preview)
    monkeypatch.setattr(ph, "make_preview", lambda **kw: kw)

    # First season picker call → backed out; then let the results loop leave.
    monkeypatch.setattr(ph, "_pick_season_episode", lambda t, y: (None, None))
    monkeypatch.setattr(ph, "_flow_goldenms_stream", lambda **kw: None)

    ph.handle_papystreaming()

    assert len(shown) >= 2, (
        "Back from the season screen must re-show the results list, "
        "not jump to the search prompt"
    )


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ── Home: Esc must not quit silently ─────────────────────────────────
def test_home_escape_does_not_select_exit():
    """Esc on Home used to pick the LAST row (Exit) and close the app."""
    src = (main_mod.__file__ and open(main_mod.__file__, encoding="utf-8").read())
    call = src.split("choice_idx = select_from_list(", 1)[1][:1500]
    assert "esc_selects_last=False" in call, (
        "Home must not map Esc to the Exit row"
    )


def test_home_escape_redraws_instead_of_quitting():
    """Esc on Home now returns None: it must redraw, never hit the Exit path."""
    assert main_mod._home_choice_is_valid(3) is True
    assert main_mod._home_choice_is_valid(0) is True
    assert main_mod._home_choice_is_valid(None) is False
    assert main_mod._home_choice_is_valid(-1) is False
