"""FreeFlix 2.0 — Cinema Noir design system guards."""

from rich.console import Console

from freeflix_cli import themes, ui


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lum(hex_color):
    r, g, b = _rgb(hex_color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_noir_is_dark_first_and_readable():
    theme = themes.preview_theme("noir")
    assert theme["label"] == "Cinema Noir"
    assert _lum(theme["surface"]) < 40
    assert _lum(theme["text"]) > 180
    # The accent is warm amber, not cyan/red.
    r, g, b = _rgb(theme["accent"])
    assert r > b and g > b


def test_no_light_themes_are_offered():
    # 2.0 is dark-first: the paper/light palettes were removed on purpose.
    assert "criterion" not in themes.THEMES
    assert "latte" not in themes.THEMES
    assert themes.DEFAULT_THEME == "noir"


def test_legacy_themes_get_2_roles_without_crashing():
    for key in themes.THEMES:
        for role in ("surface", "text", "muted", "border_soft", "selection"):
            assert isinstance(themes.preview_theme(key).get(role), (str, type(None)))
    # color() uses fallbacks for old packs; it must never raise.
    old = themes.THEMES["dracula"]
    assert old["accent"]


def test_ui_words_and_rules():
    assert ui.wordmark().plain == "FreeFlix"
    # Cinema Noir (default) keeps the signature amber + ivory wordmark.
    from rich.console import Console as _Console
    wm = ui.wordmark()
    con = _Console(color_system="truecolor")
    assert str(wm.get_style_at_offset(con, 0)) == "bold #e6b45e"
    assert str(wm.get_style_at_offset(con, 4)) == "bold #f4eee2"
    assert ui.section("Continuer").plain.strip().startswith("Continuer")
    assert "─" in ui.rule("").plain


def test_home_dashboard_renders_on_80x24_black_terminal():
    from freeflix_cli.main import _home_dashboard
    panel = _home_dashboard()
    con = Console(width=80, height=24, color_system="truecolor", record=True)
    con.print(panel)
    out = con.export_text()
    assert "FreeFlix" in out
    # No white background block is forced (the terminal's black stays black).
    assert "on #ffffff" not in out.lower()


def test_home_frame_is_black_and_only_the_light_travels(monkeypatch):
    from freeflix_cli import motion
    from freeflix_cli.main import _home_dashboard
    monkeypatch.setattr(themes, "active_theme",
                        lambda: themes.preview_theme("noir"))
    monkeypatch.setattr(motion, "reduced", lambda: False)
    panel = _home_dashboard()
    assert panel._border_style == "#1A1A21"        # deep panel interior
    assert panel._static_edge_style == "#2C2C36"   # same frame as the top banner
    assert panel._light_style == "#E6B45E"         # amber comet only
    assert panel._cell_speed == 30.0          # one border cell per frame
    assert panel.animation_fps == 30


def test_neon_panel_accepts_a_two_tone_rich_title():
    from rich import box
    from freeflix_cli.neon import NeonPanel
    panel = NeonPanel("inside", title=ui.wordmark(), border_style="#E6B45E",
                      animate=True, box_style=box.ROUNDED)
    con = Console(width=80, color_system="truecolor", record=True)
    con.print(panel)
    out = con.export_text()
    assert "FreeFlix" in out
    assert "╭" in out and "╮" in out


def test_header_is_hairline_panel():
    from freeflix_cli.main import _theme_preview_panel
    from freeflix_cli.cli_utils import _header_panel
    p = _header_panel("Anime-Sama")
    con = Console(width=80, record=True, color_system="truecolor")
    con.print(p)
    assert "Anime-Sama" in con.export_text()
    preview = _theme_preview_panel(themes.THEMES["noir"], "Noir")
    assert "▰" in preview.renderable.plain
