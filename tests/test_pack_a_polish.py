"""Pack A polish: badges, unified bars, batch table, theme preview."""

from freeflix_cli.cli_utils import _styled_option
from freeflix_cli import main


def test_styled_option_plain_untouched():
    t = _styled_option("[1/6] Episode 2")
    assert t.plain == "[1/6] Episode 2"
    assert len(t.spans) == 0


def test_styled_option_badges():
    label = "premium : sibnet  —  1080p  [VF]"
    t = _styled_option(label)
    assert t.plain == label
    covered = [(s.start, s.end) for s in t.spans]
    assert (label.index("1080p"), label.index("1080p") + 5) in covered
    assert (label.index("[VF]"), label.index("[VF]") + 4) in covered


def test_styled_option_status_glyphs():
    assert _styled_option("srv ✗").plain == "srv ✗"
    assert len(_styled_option("srv ✗").spans) == 1
    assert len(_styled_option("ok ✓").spans) == 1


def test_styled_option_theme_dot():
    t = _styled_option("[bright_cyan]●[/] Default (cyan)")
    assert t.plain == "● Default (cyan)"
    assert len(t.spans) >= 1


def test_dashboard_bar_uses_house_style():
    t = main._progress_bar_text(62, width=10)
    assert "62%" in t.plain
    assert "▰" in t.plain and "▱" in t.plain
    assert "█" not in t.plain


def test_batch_summary_renders(capsys):
    from freeflix_cli.handlers.playback import _print_batch_summary
    _print_batch_summary({"[1/2] Ep 1": True, "[2/2] Ep 2": False}, 1, 2)
    out = capsys.readouterr().out
    assert "1/2" in out and "Ep 1" in out and "Ep 2" in out


def test_theme_preview_has_samples():
    from freeflix_cli import themes
    p = main._theme_preview_panel(themes.THEMES["dracula"], "Dracula")
    plain = p.renderable.plain
    assert "▰" in plain and "[VF]" in plain and "1080p" in plain


def test_logo_shine_stays_on_letters_and_loops():
    """The splash shine must only touch letter glyphs (never background
    spaces) and must travel with ticks, looping seamlessly."""
    from freeflix_cli.splash import _LOGO, _shine_line, logo_renderable

    lines = _LOGO.strip("\n").split("\n")

    def bright_cols(line, center):
        t = _shine_line(line, center, "bold cyan")
        return {s.start for s in t.spans if "white" in str(s.style)}

    # Letters get the shine, spaces never do.
    t = _shine_line(lines[0], 5.0, "bold cyan")
    for s in t.spans:
        if "white" in str(s.style):
            assert lines[0][s.start:s.end].strip(), "shine on background!"

    # The band travels with ticks and wraps around (seamless loop).
    span = max(len(ln) for ln in lines)
    cols_a = bright_cols(lines[0], 10.0)
    cols_b = bright_cols(lines[0], 30.0)
    assert cols_a and cols_b and cols_a != cols_b
    far = _shine_line(lines[0], span + 50.0, "bold cyan")
    assert not [s for s in far.spans if "white" in str(s.style)]

    # Animated renderable still centers like the plain one.
    assert type(logo_renderable(80, 24, animate=True, tick=7)).__name__ == "Align"


def test_neon_panel_light_travels_and_falls_back():
    """NeonPanel: the comet moves with the clock, lights title/subtitle,
    keeps the rounded box, and falls back to a plain panel when narrow."""
    from rich.console import Console

    from freeflix_cli.neon import NeonPanel
    from freeflix_cli.main import _home_dashboard

    p = NeonPanel("hi", title="FreeFlix", subtitle="anime · films",
                  loop_seconds=6.0, clock=lambda: 0.0)
    c = Console(width=60, force_terminal=True, record=True, color_system="truecolor")
    c.print(p)
    f0 = c.export_text(styles=True)
    p._clock = lambda: 2.0
    c2 = Console(width=60, force_terminal=True, record=True, color_system="truecolor")
    c2.print(p)
    f1 = c2.export_text(styles=True)
    assert f0 != f1  # the light moved
    assert "\x1b[1;97m" in f0  # bright core somewhere
    assert "38;2;" in f0  # truecolor gradient tail melting to the accent
    for corner in ("╭", "╮", "╰", "╯"):
        assert corner in f0
    import re as _re
    plain = _re.sub(r"\x1b\[[0-9;]*m", "", f0)
    assert "FreeFlix" in plain and "anime · films" in plain

    narrow = Console(width=30, force_terminal=True, record=True)
    narrow.print(NeonPanel("hi", title="T", clock=lambda: 0.0))
    # Narrow terminals fall back to a plain bordered panel (Rich may swap
    # rounded corners for square ones on legacy Windows consoles).
    _narrow_out = narrow.export_text()
    assert "─" in _narrow_out and "│" in _narrow_out and "T" in _narrow_out

    # The real home dashboard returns a NeonPanel.
    assert isinstance(_home_dashboard(), NeonPanel)


def test_toast_hub_shows_then_expires():
    from freeflix_cli import cli_utils as cu

    cu._toasts.clear()
    assert cu._current_toast() is None
    cu.push_toast("hello", ttl=60)
    msg, _style = cu._current_toast()
    assert msg == "hello"
    cu._toasts[0] = (0.0, "hello", "red")  # force-expire
    assert cu._current_toast() is None
    cu._toasts.clear()


def test_pulse_is_bool_and_bar_plain_stable():
    from freeflix_cli import cli_utils as cu
    from freeflix_cli.progress import bar

    assert isinstance(cu._pulse(), bool)
    assert bar(0.5, 10).plain == "▰" * 5 + "▱" * 5


def test_reveal_typewriter():
    import time

    from freeflix_cli.progress import _reveal

    assert _reveal("hello", None) == "hello"
    assert _reveal("hello", time.monotonic() + 100) == "h"
    assert _reveal("hi", time.monotonic() - 10) == "hi"


def test_skeleton_context_exits_cleanly():
    from freeflix_cli.cli_utils import skeleton

    with skeleton("Loading…", lines=2):
        pass


def test_title_updater_chains_and_restores():
    from freeflix_cli import player_manager as pm

    seen = []
    mon = type("M", (), {})()
    mon.on_position = lambda pos, dur: seen.append((pos, dur))
    pm._chain_title_updater(mon, "Some Title That Is Way Too Long For A Tab Bar Really")
    mon.on_position(65.0, 600.0)
    assert seen == [(65.0, 600.0)]
    pm._set_term_title("FreeFlix CLI")  # no crash when piped


def test_live_stats_line_ticks_clock():
    import re

    from rich.console import Console

    from freeflix_cli.main import _LiveStatsLine

    stats = {"this_week": 3, "streak": 2, "by_day": {}}
    line = _LiveStatsLine(stats, 1, 0, False)
    c = Console(width=100, force_terminal=True, record=True)
    c.print(line)
    out = c.export_text()
    assert re.search(r"\d{2}:\d{2}", out)


