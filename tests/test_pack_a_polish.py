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
