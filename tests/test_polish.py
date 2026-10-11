"""
Tests for the visual polish round (menus, dashboard, badges, help).
All offline — no network, no tty.
"""

from freeflix_cli import cli_utils as cu


def test_highlight_match():
    t = cu._hl_match("Naruto Shippuden", "ship", base="")
    assert t.plain == "Naruto Shippuden"
    # matched slice carries the accent style
    spans = [(s.start, s.end, s.style) for s in t.spans]
    assert spans, "match should be styled"
    start, end, _style = spans[0]
    assert t.plain[start:end].lower() == "ship"


def test_highlight_no_match_falls_back():
    t = cu._hl_match("Naruto", "zzz", base="")
    assert t.plain == "Naruto"
    assert not t.spans


def test_highlight_empty_query():
    t = cu._hl_match("Naruto [VF]", "", base="")
    assert t.plain == "Naruto [VF]"


def test_scrollbar():
    b = cu._scrollbar(0, 20)
    assert b.plain == "▰▱▱▱▱"
    b = cu._scrollbar(19, 20)
    assert b.plain == "▰▰▰▰▰"
    b = cu._scrollbar(0, 1)
    assert set(b.plain) <= {"▰"}


def test_kbd_pill():
    p = cu._kbd("Enter: select")
    # nerd terminals: rounded E0B6/E0B4 ends ; others: ‹› — centred either way
    assert "Enter: select" in p.plain
    assert (p.plain.startswith("\ue0b6") and p.plain.endswith("\ue0b4")) or (
        p.plain.startswith("‹") and p.plain.endswith("›")
    )


def test_status_bar_pills_and_armed():
    from freeflix_cli.tracker import tracker
    _prev = tracker.get_language()
    tracker.set_language("en")
    try:
        bar = cu._status_bar()
        # pills carry the theme accent (rounded nerd ends or ‹› fallback)
        acc = cu.color("accent")
        styles = " ".join(str(s.style) for s in bar.spans)
        assert acc in styles, styles
        assert "Enter: select" in bar.plain
    finally:
        tracker.set_language(_prev or "en")


def test_help_overlay_two_columns():
    from rich.table import Table
    panel = cu._help_overlay()
    grid = panel.renderable
    assert isinstance(grid, Table)
    assert len(grid.columns) == 2


def test_episode_badges_duration(monkeypatch):
    from freeflix_cli import player_manager as pm
    from freeflix_cli.tracker import tracker
    monkeypatch.setattr(tracker, "get_episode_duration", lambda k: 1440)
    monkeypatch.setattr(tracker, "get_episode_position", lambda k: None)
    monkeypatch.setattr(tracker, "is_episode_watched", lambda k: False)
    monkeypatch.setattr(pm, "is_already_downloaded", lambda *a, **k: False)
    badges = pm.episode_badges("S", "Saison 1", "Épisode 1")
    assert "24min" in badges


def test_dashboard_sparkline_present():
    from freeflix_cli.main import _home_dashboard
    from rich.console import Console
    panel = _home_dashboard()
    con = Console(width=100)
    with con.capture() as cap:
        con.print(panel)
    out = cap.get()
    assert any(c in out for c in "▁▂▃▄▅▆▇")


def test_tip_of_the_day_translated():
    from freeflix_cli.progress import _tip_of_the_day
    from freeflix_cli.tracker import tracker
    tracker.set_language("fr")
    try:
        assert _tip_of_the_day().startswith("Astuce")
    finally:
        tracker.set_language("fr")


def test_resolution_colour_scale():
    from freeflix_cli.themes import color
    got = {}
    for h, role in ((480, "dim"), (720, "success"), (1080, "warning"),
                    (2160, "accent")):
        tx = cu._styled_option(f"Player {h}p", base="")
        styles = {s.style for s in tx.spans}
        assert f"bold {color(role)}" in styles, (h, styles)
        got[h] = styles
    # all four heights render differently
    assert len({tuple(sorted(s)) for s in got.values()}) == 4


def test_coflix_season_episode_counts(monkeypatch):
    from freeflix_cli.scraping import coflix
    html = (
        "<html><body><h1>S</h1>"
        '<button data-season="0">Saison 1</button>'
        '<div class="cf-episodes-panel" data-panel="0">'
        '<div class="cf-episode-item">E1</div>'
        '<div class="cf-episode-item">E2</div>'
        '<div class="cf-episode-item">E3</div>'
        "</div></body></html>"
    )

    class _R:
        text = html
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(coflix, "_get", lambda *a, **k: _R())
    monkeypatch.setattr(coflix, "website_origin", "https://coflix.ac")
    series = coflix.get_series("https://coflix.ac/serie/s/")
    assert len(series.seasons) == 1
    assert "· 3" in series.seasons[0].title, series.seasons[0].title
