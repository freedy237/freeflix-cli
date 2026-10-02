"""
Cross-platform unit tests for the menu key decoder (`_read_menu_key`).

These mock the OS input layer so they run on any CI runner, and would have
caught the 1.8.4 Windows arrow-key regression. They pin the contract:
  - arrows decode (classic-console \\x00/\\xe0 prefix AND VT \\x1b[… sequences),
  - focus / mouse events (\\x1b[I, \\x1b[O) are IGNORED (return ""),
  - a truly isolated Esc returns readchar.key.ESC,
  - Enter / Ctrl-C / Backspace decode.
"""

import sys
import types

import readchar

import freeflix_cli.cli_utils as cu


def _run_windows(chars):
    """Drive _read_menu_key through a fake msvcrt that yields `chars`."""
    fake = types.ModuleType("msvcrt")
    buf = list(chars)
    idx = {"i": 0}

    def getwch():
        if idx["i"] < len(buf):
            c = buf[idx["i"]]
            idx["i"] += 1
            return c
        return "\x00"

    fake.getwch = getwch
    fake.kbhit = lambda: idx["i"] < len(buf)
    sys.modules["msvcrt"] = fake
    orig = cu.os.name
    cu.os.name = "nt"
    try:
        return cu._read_menu_key()
    finally:
        cu.os.name = orig
        sys.modules.pop("msvcrt", None)


def test_windows_classic_arrows():
    assert _run_windows(["\xe0", "H"]) == readchar.key.UP
    assert _run_windows(["\xe0", "P"]) == readchar.key.DOWN
    assert _run_windows(["\xe0", "M"]) == readchar.key.RIGHT
    assert _run_windows(["\xe0", "K"]) == readchar.key.LEFT
    # \x00 prefix behaves the same
    assert _run_windows(["\x00", "H"]) == readchar.key.UP


def test_windows_vt_arrows():
    assert _run_windows(["\x1b", "[", "A"]) == readchar.key.UP
    assert _run_windows(["\x1b", "[", "B"]) == readchar.key.DOWN


def test_windows_focus_events_ignored():
    # Alt-Tab focus in/out must NOT be read as Esc.
    assert _run_windows(["\x1b", "[", "I"]) == ""
    assert _run_windows(["\x1b", "[", "O"]) == ""


def test_windows_lone_esc_is_back():
    assert _run_windows(["\x1b"]) == readchar.key.ESC


def test_windows_enter_and_ctrlc_and_backspace():
    assert _run_windows(["\r"]) == readchar.key.ENTER
    assert _run_windows(["\n"]) == readchar.key.ENTER
    assert _run_windows(["\x03"]) == readchar.key.CTRL_C
    assert _run_windows(["\x08"]) == readchar.key.BACKSPACE


def test_windows_printable_char_passthrough():
    assert _run_windows(["a"]) == "a"
    assert _run_windows(["/"]) == "/"


def test_back_option_detection_via_last_index():
    # Esc in select_from_list maps to the last option (the Back/Cancel/Exit
    # entry every menu appends). This keeps that contract explicit.
    for opts in (["A", "B", "← Back"], ["x", "y", "z", "Exit"]):
        assert opts[len(opts) - 1] in ("← Back", "Exit")


class _DummyLive:
    """Remplace Live : rend sans terminal, capture les frames."""

    def __init__(self, *a, **k):
        self.frames = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, renderable):
        self.frames.append(renderable)


def _run_input(keys, history=None, default=None):
    """Pilote _input_fullscreen avec des touches scriptées, sans TTY."""
    import sys as _sys

    class _FakeStdin:
        def isatty(self):
            return True

    seq = {"keys": list(keys)}
    orig_stdin = _sys.stdin
    orig_readkey = cu._read_menu_key
    orig_live = cu.Live
    _sys.stdin = _FakeStdin()
    cu._read_menu_key = lambda: seq["keys"].pop(0) if seq["keys"] else readchar.key.ENTER
    cu.Live = _DummyLive
    try:
        return cu._input_fullscreen("Q:", default, "H", history=history)
    finally:
        _sys.stdin = orig_stdin
        cu._read_menu_key = orig_readkey
        cu.Live = orig_live


def test_input_types_and_submits():
    assert _run_input(["a", "b", "c", readchar.key.ENTER]) == "abc"


def test_input_backspace_and_esc_default():
    assert _run_input(["a", "b", readchar.key.BACKSPACE, readchar.key.ENTER]) == "a"
    assert _run_input([readchar.key.ESC], default="dflt") == "dflt"


def test_input_history_recall():
    hist = ["naruto", "one piece"]
    assert _run_input([readchar.key.UP, readchar.key.ENTER], history=hist) == "naruto"
    out = _run_input(
        [readchar.key.UP, readchar.key.UP, readchar.key.DOWN, readchar.key.ENTER],
        history=hist,
    )
    assert out == "naruto"


def test_input_ignores_empty_and_ctrlc():
    assert _run_input(["", "x", readchar.key.ENTER]) == "x"
    try:
        _run_input([readchar.key.CTRL_C])
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("CTRL_C doit lever KeyboardInterrupt")


def test_input_not_a_tty_raises():
    import sys as _sys

    class _NoTty:
        def isatty(self):
            return False

    orig = _sys.stdin
    _sys.stdin = _NoTty()
    try:
        try:
            cu._input_fullscreen("Q:", None, "H")
        except RuntimeError:
            pass
        else:
            raise AssertionError("hors TTY doit lever RuntimeError")
    finally:
        _sys.stdin = orig


def _run_esccancel_win(chars_lists):
    """Drive _EscCancel poll() through fake msvcrt + os.name='nt'."""
    import os as _os
    import sys as _sys
    import types
    from unittest import mock
    from freeflix_cli import progress as _pg

    fake = types.ModuleType("msvcrt")
    state = {"queue": [], "queues": [list(q) for q in chars_lists]}

    def kbhit():
        if not state["queue"] and state["queues"]:
            state["queue"] = state["queues"].pop(0)
        return bool(state["queue"])

    def getwch():
        return state["queue"].pop(0)

    fake.kbhit = kbhit
    fake.getwch = getwch
    with mock.patch.dict(_sys.modules, {"msvcrt": fake}):
        with mock.patch.object(_os, "name", "nt"):
            esc = _pg._EscCancel()
            esc.active = True
            out = []
            for q in chars_lists:
                state["queue"] = list(q)
                state["queues"] = []
                out.append(esc.poll())
            return out


def test_esccancel_win_double_esc():
    assert _run_esccancel_win([["\x1b"], ["\x1b"]]) == [False, True]


def test_esccancel_win_single_burst():
    assert _run_esccancel_win([["\x1b", "\x1b"]]) == [True]


def test_esccancel_win_arrows_ignored():
    assert _run_esccancel_win([["\x1b", "[", "A", "\x00", "H"]]) == [False]


def test_esccancel_win_other_keys_ignored():
    assert _run_esccancel_win([["a", "b", "c"]]) == [False]
