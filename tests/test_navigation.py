"""Navigation coherence: one Back = one level, state kept.

Simulates the Anime-Sama stack with fake inputs and asserts the screen
sequence: results → season → episode → Back → season → Back → results →
Back → search prompt → exit. The results list must be shown again WITHOUT
re-running the search.
"""

from freeflix_cli.handlers import anime_sama as H
from freeflix_cli.scraping import anime_sama as S


class _Result:
    title = "Frieren"
    url = "https://x/catalogue/frieren"
    img = ""
    genres = []


class _SeasonAccess:
    title = "Saison 1"
    url = "https://x/catalogue/frieren/saison1/vostfr"


class _Series:
    title = "Frieren"
    url = "https://x/catalogue/frieren"
    img = ""
    genres = []
    seasons = [_SeasonAccess()]


class _Episode:
    title = "Épisode 1"


class _Season:
    title = "Saison 1"
    episodes = {"vostfr": [_Episode()]}


def test_anime_sama_back_stack(monkeypatch):
    events = []

    monkeypatch.setattr(S, "get_website_url", lambda: None)
    search_calls = {"n": 0}

    def _search(query):
        search_calls["n"] += 1
        events.append(("search", query))
        return [_Result()]

    monkeypatch.setattr(S, "search", _search)
    monkeypatch.setattr(S, "get_series", lambda url: _Series())
    monkeypatch.setattr(S, "get_season", lambda url: _Season())
    monkeypatch.setattr(H, "play_episode_flow", lambda **kw: None)

    from freeflix_cli import terminal_image
    monkeypatch.setattr(terminal_image, "show_poster", lambda *a, **k: False)

    inputs = iter(["frieren", "exit"])
    monkeypatch.setattr(H, "get_user_input", lambda *a, **k: next(inputs))

    # Results menu: 1st → select the show, 2nd (after the series flow) → Back.
    results_choices = iter([0, 1])

    def _swp(labels, prompt, previews):
        events.append(("results", len(labels)))
        return next(results_choices)

    monkeypatch.setattr(H, "select_with_preview", _swp)

    # Seasons: select 0; Episodes: index len(eps)+1 = Back; Seasons: len = Back.
    menu_choices = iter([0, 2, 1])

    def _sfl(labels, prompt, **kw):
        events.append(("menu", prompt, len(labels)))
        return next(menu_choices)

    monkeypatch.setattr(H, "select_from_list", _sfl)

    # The provider now opens on Planning / Search: pick "Search an anime".
    H._search_flow()

    # The search ran ONCE; results were re-displayed after backing out of the
    # season picker (no refetch).
    assert search_calls["n"] == 1
    assert sum(1 for e in events if e[0] == "results") == 2
    # Sequence: results → season → episode → season → results → search prompt.
    kinds = [e[0] for e in events]
    assert kinds == ["search", "results", "menu", "menu", "menu", "results"]


def test_anime_sama_entry_shows_planning_menu(monkeypatch):
    """Entering the provider must offer Planning and Search first."""
    picked = []

    def _sfl(opts, prompt, **kw):
        picked.append(opts)
        return len(opts) - 1  # Back

    monkeypatch.setattr(H, "select_from_list", _sfl)
    H.handle_anime_sama()
    assert len(picked) == 1
    assert len(picked[0]) == 3
    assert "planning" in picked[0][0].lower()


def test_select_back_means_last_option():
    """Esc maps to the last option — every menu appends a Back entry."""
    # This is the invariant handlers rely on; documented here so a change to
    # select_from_list's Esc mapping is caught.
    import inspect
    from freeflix_cli import cli_utils

    src = inspect.getsource(cli_utils.select_from_list)
    assert "result = len(options) - 1" in src


def test_escape_cancels_instead_of_returning_default():
    """Esc at a pre-filled prompt must go BACK, not re-run the search with the
    default query (the 'Esc → results' trap)."""
    from freeflix_cli.cli_utils import _finish_input

    assert _finish_input("", "frieren", cancelled=True) == ""
    assert _finish_input("", "frieren", cancelled=False) == "frieren"
    assert _finish_input("  naruto ", "frieren", cancelled=False) == "naruto"
    # GoldenMS: blank means "latest", so Esc must return a DISTINCT sentinel.
    assert _finish_input("", "", cancelled=True, cancel_value=None) is None
    assert _finish_input("", "", cancelled=False, cancel_value=None) == ""


def test_leave_label_detection_is_multilingual_and_safe():
    """Back/Cancel/Exit are wiped on the LAST row only, in FR and EN, and a
    movie whose title contains 'Back' must NOT wipe the screen."""
    from freeflix_cli.cli_utils import _looks_like_leave

    # last row, FR and EN, with or without the arrow
    assert _looks_like_leave("← Back", 5, 6)
    assert _looks_like_leave("← Retour", 5, 6)
    assert _looks_like_leave("Annuler", 3, 4)
    assert _looks_like_leave("Quitter", 9, 10)
    assert _looks_like_leave("❌ Quitter", 9, 10)
    # a normal result, even if it contains 'Back', is not a leave row
    assert not _looks_like_leave("Back to the Future (1985)", 2, 20)
    assert not _looks_like_leave("Auto (best)", 4, 5)
    assert not _looks_like_leave("Exit", 0, 20)  # not the last row
