"""Mouse support: SGR decoding + hit-testing every interactive screen.

The tests never touch a real tty. They feed the same MouseEvent objects the
terminal reader produces, so the coordinate → row mapping is exercised exactly
like a real click (including wheel, right-click, buttons and the preview pane).
"""

import contextlib
import sys
import types
from types import SimpleNamespace

import readchar

import freeflix_cli.cli_utils as cu


class _DummyLive:
    """Evaluate ``get_renderable`` like Rich does, without a terminal."""

    def __init__(self, renderable=None, get_renderable=None, **kw):
        self.get_renderable = get_renderable
        self.frames = []
        if renderable is not None:
            self.frames.append(renderable)

    def __enter__(self):
        if self.get_renderable is not None:
            self.frames.append(self.get_renderable())
        return self

    def __exit__(self, *exc):
        return False

    def update(self, renderable=None, **kw):
        if renderable is not None:
            self.frames.append(renderable)


class _FakeConsole:
    is_terminal = True
    size = SimpleNamespace(width=80, height=24)

    def __init__(self):
        self.printed = []

    def print(self, *a, **k):
        self.printed.append(a)

    def clear(self):
        pass


def _patch_ui(monkeypatch):
    monkeypatch.setattr(cu, "_crumbs", [])
    monkeypatch.setattr(cu, "Live", _DummyLive)
    monkeypatch.setattr(cu, "flush_input_settled", lambda: None)
    monkeypatch.setattr(cu, "clear_screen", lambda: None)
    monkeypatch.setattr(cu, "_mouse_available", lambda: True)
    monkeypatch.setattr(cu, "mouse_tracking", lambda: contextlib.nullcontext(True))
    # Simple one-row renderables keep the expected hit rows obvious.
    monkeypatch.setattr(cu, "_renderable_height", lambda *a, **k: 1)


def _mouse(x=1, y=1, button=0, pressed=True):
    return cu.MouseEvent(x, y, button, pressed)


# ── SGR decoding ─────────────────────────────────────────────────────

def test_sgr_mouse_events_decode():
    e = cu._mouse_from_match(
        cu._MOUSE_RE_B.match(b"\x1b[<0;12;5M"))
    assert (e.x, e.y, e.button, e.pressed, e.wheel) == (12, 5, 0, True, "")
    assert e.is_left and not e.is_right

    right = cu._mouse_from_match(
        cu._MOUSE_RE_B.match(b"\x1b[<2;1;3M"))
    assert right.is_right and not right.is_left

    wheel = cu._mouse_from_match(
        cu._MOUSE_RE_B.match(b"\x1b[<65;4;6M"))
    assert wheel.wheel == "down"

    release = cu._mouse_from_match(
        cu._MOUSE_RE_B.match(b"\x1b[<0;4;6m"))
    assert release.pressed is False and release.is_left is False


def test_windows_reader_returns_mouse_not_ignored(monkeypatch):
    chars = list("\x1b[<0;12;5M")

    fake = types.ModuleType("msvcrt")
    state = {"i": 0}

    def getwch():
        c = chars[state["i"]]
        state["i"] += 1
        return c

    fake.getwch = getwch
    fake.kbhit = lambda: state["i"] < len(chars)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(cu.os, "name", "nt")
    monkeypatch.setattr(cu, "_esc_carry", False)
    ev = cu._read_menu_key()
    assert isinstance(ev, cu.MouseEvent)
    assert (ev.x, ev.y, ev.button, ev.pressed) == (12, 5, 0, True)


# ── Tracking on/off ──────────────────────────────────────────────────

def test_mouse_tracking_enables_and_restores(monkeypatch):
    writes = []
    monkeypatch.setattr(cu, "_mouse_available", lambda: True)
    monkeypatch.setattr(cu, "_mouse_write", writes.append)
    monkeypatch.setattr(cu, "_mouse_active", False)

    with cu.mouse_tracking() as active:
        assert active is True
        assert writes == [cu._MOUSE_ON]
    assert writes[-1] == cu._MOUSE_OFF
    assert cu._mouse_active is False


def test_mouse_tracking_noop_without_tty(monkeypatch):
    writes = []
    monkeypatch.setattr(cu, "_mouse_available", lambda: False)
    monkeypatch.setattr(cu, "_mouse_write", writes.append)
    with cu.mouse_tracking() as active:
        assert active is False
    assert writes == []


# ── Menus ────────────────────────────────────────────────────────────

def test_select_from_list_clicks_a_row(monkeypatch):
    _patch_ui(monkeypatch)
    monkeypatch.setattr(cu, "_read_menu_key", lambda: _mouse(y=2))
    assert cu.select_from_list(["First", "Second", "← Back"],
                               "Choose") == 0


def test_select_from_list_wheel_then_enter(monkeypatch):
    _patch_ui(monkeypatch)
    keys = [_mouse(y=1, button=65), readchar.key.ENTER]
    monkeypatch.setattr(cu, "_read_menu_key",
                        lambda: keys.pop(0) if keys else readchar.key.ENTER)
    assert cu.select_from_list(["First", "Second", "Third"],
                               "Choose") == 1


def test_select_from_list_right_click_goes_back(monkeypatch):
    _patch_ui(monkeypatch)
    monkeypatch.setattr(cu, "_read_menu_key",
                        lambda: _mouse(y=1, button=2))
    assert cu.select_from_list(["First", "Second", "← Back"],
                               "Choose") == 2


def test_select_from_list_status_click_opens_help(monkeypatch):
    _patch_ui(monkeypatch)
    monkeypatch.setattr(cu, "_kbd", lambda label: label)
    from freeflix_cli.i18n import t
    plain = cu._status_bar(False).plain
    x = plain.find(t("?: help")) + 1
    # With one-row renderables: prompt, item0, item1, blank, status = row 5.
    keys = [_mouse(x=x, y=5), readchar.key.ENTER, readchar.key.ENTER]
    monkeypatch.setattr(cu, "_read_menu_key",
                        lambda: keys.pop(0) if keys else readchar.key.ENTER)
    # Help opens then closes (Enter twice) without leaving the menu.
    assert cu.select_from_list(["First", "Second", "← Back"],
                               "Choose") == 0


def test_select_multiple_click_toggles_row(monkeypatch):
    _patch_ui(monkeypatch)
    keys = [_mouse(y=3), readchar.key.ENTER]
    monkeypatch.setattr(cu, "_read_menu_key",
                        lambda: keys.pop(0) if keys else readchar.key.ENTER)
    assert cu.select_multiple(["Ep1", "Ep2"], "Pick", preselected=[]) == [0]


def test_select_multiple_confirm_button(monkeypatch):
    _patch_ui(monkeypatch)
    monkeypatch.setattr(cu, "_kbd", lambda label: label)
    from freeflix_cli.i18n import t
    # Rows: prompt, blank, item0, item1, blank, count, hint/buttons.
    hint = ("  ↑/↓ · " + t("Space: select") + " · " + t("a: all")
            + " · " + t("Enter: confirm") + " · " + t("Esc: back"))
    x = hint.find(t("Enter: confirm")) + 1
    keys = [_mouse(y=7, x=x)]
    monkeypatch.setattr(cu, "_read_menu_key",
                        lambda: keys.pop(0) if keys else readchar.key.ENTER)
    assert cu.select_multiple(["Ep1", "Ep2"], "Pick", preselected=[1]) == [1]


# ── Preview list ─────────────────────────────────────────────────────

def test_preview_click_selects_an_item(monkeypatch):
    _patch_ui(monkeypatch)
    fake = _FakeConsole()
    monkeypatch.setattr(cu, "console", fake)
    monkeypatch.setattr(cu, "_read_menu_key", lambda: _mouse(y=3))
    previews = [
        {"cover": "", "title": "A", "lines": [], "panel_title": ""},
        {"cover": "", "title": "B", "lines": [], "panel_title": ""},
    ]
    assert cu.select_with_preview(["A", "B"], "Pick", previews) == 0


def test_preview_right_click_goes_back(monkeypatch):
    _patch_ui(monkeypatch)
    fake = _FakeConsole()
    monkeypatch.setattr(cu, "console", fake)
    monkeypatch.setattr(cu, "_read_menu_key", lambda: _mouse(y=1, button=2))
    previews = [
        {"cover": "", "title": "A", "lines": [], "panel_title": ""},
        {"cover": "", "title": "B", "lines": [], "panel_title": ""},
    ]
    assert cu.select_with_preview(["A", "B"], "Pick", previews) == 2


# ── Text field buttons ───────────────────────────────────────────────

def test_input_click_ok_submits(monkeypatch):
    _patch_ui(monkeypatch)
    fake = _FakeConsole()
    monkeypatch.setattr(cu, "console", fake)

    class FakeStdin:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", FakeStdin())
    keys = ["a", "b", "c", _mouse(x=3, y=5)]
    monkeypatch.setattr(cu, "_read_menu_key",
                        lambda: keys.pop(0) if keys else readchar.key.ENTER)
    assert cu._input_fullscreen("Q:", None, "Header") == "abc"


def test_input_click_cancel(monkeypatch):
    _patch_ui(monkeypatch)
    fake = _FakeConsole()
    monkeypatch.setattr(cu, "console", fake)

    class FakeStdin:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", FakeStdin())
    # Rows: header, prompt, text, default hint, blank, buttons.
    keys = [_mouse(x=13, y=6)]
    monkeypatch.setattr(cu, "_read_menu_key",
                        lambda: keys.pop(0) if keys else readchar.key.ENTER)
    assert cu._input_fullscreen("Q:", "dflt", "Header") == ""


# ── Download cancel ──────────────────────────────────────────────────

def test_download_cancel_accepts_double_click(monkeypatch):
    from unittest import mock
    from freeflix_cli import progress as pg

    runs = [
        list("\x1b[<0;10;5M"),
        list("\x1b[<0;10;5M"),
    ]
    state = {"queue": list(runs[0])}
    fake = types.ModuleType("msvcrt")
    fake.kbhit = lambda: bool(state["queue"])
    fake.getwch = lambda: state["queue"].pop(0)
    with mock.patch.dict(sys.modules, {"msvcrt": fake}):
        with mock.patch.object(cu.os, "name", "nt"):
            esc = pg._EscCancel()
            esc.active = True
            assert esc.poll() is False
            state["queue"] = list(runs[1])
            assert esc.poll() is True
            assert esc.armed is True


# ── Clickable Yes / No ──────────────────────────────────────────────

def test_ask_yes_no_click_yes_and_no(monkeypatch):
    _patch_ui(monkeypatch)
    fake = _FakeConsole()
    monkeypatch.setattr(cu, "console", fake)
    monkeypatch.setattr(cu, "_kbd", lambda label: label)

    class FakeStdin:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", FakeStdin())
    from freeflix_cli.i18n import t
    line = f"  {cu.iconify('Update?')}   {t('Yes')}  {t('No')}"
    x_yes = line.find(t("Yes")) + 1
    x_no = line.find(t("No")) + 1

    monkeypatch.setattr(cu, "_read_menu_key",
                        lambda: _mouse(x=x_yes, y=1))
    assert cu.ask_yes_no("Update?") is True
    monkeypatch.setattr(cu, "_read_menu_key",
                        lambda: _mouse(x=x_no, y=1))
    assert cu.ask_yes_no("Update?") is False


def test_preview_hint_click_goes_back(monkeypatch):
    _patch_ui(monkeypatch)
    fake = _FakeConsole()
    monkeypatch.setattr(cu, "console", fake)
    from freeflix_cli.i18n import t
    hint = t("↑/↓ navigate · type to filter · Enter · Esc")
    x = hint.find(t("Esc")) + 1
    monkeypatch.setattr(cu, "_read_menu_key", lambda: _mouse(x=x, y=21))
    previews = [
        {"cover": "", "title": "A", "lines": [], "panel_title": ""},
        {"cover": "", "title": "B", "lines": [], "panel_title": ""},
    ]
    assert cu.select_with_preview(["A", "B"], "Pick", previews) == 2
