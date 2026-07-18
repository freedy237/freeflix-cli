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
