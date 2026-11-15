"""Fluidity regressions for the poster-preview screens (search / planning).

The user report: "in the search or the planning, when the images load ... the
navigation with the cursor bugs; I want it smooth on every OS like the main
menu". Two root causes are pinned here:

1. ``_read_menu_key_raw`` (POSIX) decoded ONE raw read chunk against a 3-byte
   arrow table. A burst such as ``\\x1b[B\\x1b[B\\x1b[B`` (a held arrow, or keys
   piling up while a poster renders) matched nothing, so every press but the
   first was silently DROPPED — the cursor appeared stuck then jumped. Extra
   events must now be replayed by the next call.
2. The preview picker painted a ~0.5 MB chafa SIXEL synchronously on every
   cursor move. The poster repaint must wait for the navigation to settle
   (``_poster_paint_due``), so input stays instant like in ``select_from_list``.

These tests fake the tty layer, so they run on any OS/CI runner.
"""

import select as _select_mod
import sys
import types

import readchar

import freeflix_cli.cli_utils as cu
import freeflix_cli.preview_picker as pp


# ─── helpers ─────────────────────────────────────────────────────────
class _FakeTty:
    """Minimal stdin replacement backed by a byte buffer."""

    def __init__(self, data: bytes):
        self.buf = bytearray(data)

    def isatty(self):
        return True

    def fileno(self):
        return 99


def _install_fake_tty(monkeypatch, data: bytes):
    tty = _FakeTty(data)

    def fake_read(fd, n):
        out = bytes(tty.buf[:n])
        del tty.buf[:n]
        return out

    def fake_select(rlist, wlist, xlist, timeout=None):
        return ([rlist[0]], [], []) if tty.buf else ([], [], [])

    monkeypatch.setattr(sys, "stdin", tty)
    monkeypatch.setattr(cu.os, "read", fake_read)
    monkeypatch.setattr(_select_mod, "select", fake_select)
    # POSIX code path on every runner.
    monkeypatch.setattr(cu.os, "name", "posix")
    fake_termios = types.ModuleType("termios")
    fake_termios.tcgetattr = lambda fd: ["saved"]
    fake_termios.tcsetattr = lambda fd, when, attrs: None
    fake_termios.TCSADRAIN = 0
    fake_tty_mod = types.ModuleType("tty")
    fake_tty_mod.setcbreak = lambda fd: None
    monkeypatch.setitem(sys.modules, "termios", fake_termios)
    monkeypatch.setitem(sys.modules, "tty", fake_tty_mod)
    return tty


def _reset_carry():
    cu._esc_carry = False
    cu._raw_carry = b""


# Every test starts from a clean key-carry state (module-level buffers).
def setup_function(_fn):
    _reset_carry()


def teardown_function(_fn):
    _reset_carry()


# ─── 1. burst decoding: no keypress may be dropped ───────────────────
def test_decode_menu_seq_replays_every_arrow_of_a_burst():
    """One read chunk holding 3 arrows must yield 3 events, not 1."""
    chunk = b"\x1b[B\x1b[B\x1b[A"
    assert cu._decode_menu_seq(chunk) == readchar.key.DOWN
    assert cu._decode_menu_seq(cu._take_raw_carry()) == readchar.key.DOWN
    assert cu._decode_menu_seq(cu._take_raw_carry()) == readchar.key.UP
    assert cu._take_raw_carry() == b""


def test_read_menu_key_replays_queued_arrows(monkeypatch):
    _install_fake_tty(monkeypatch, b"\x1b[B\x1b[B\x1b[A\x1b[A\x1b[B")
    got = [cu._read_menu_key() for _ in range(5)]
    assert got == [readchar.key.DOWN, readchar.key.DOWN, readchar.key.UP,
                   readchar.key.UP, readchar.key.DOWN]


def test_read_menu_key_keeps_arrow_after_mouse_report(monkeypatch):
    """A mouse report + key in ONE read: the key must survive (it used to be
    stashed as a raw tail and then leaked/decoded as filter text)."""
    _install_fake_tty(monkeypatch, b"\x1b[<35;20;5M\x1b[B")
    first = cu._read_menu_key()
    assert isinstance(first, cu.MouseEvent)
    assert first.x == 20 and first.y == 5 and first.motion
    assert cu._read_menu_key() == readchar.key.DOWN


def test_read_menu_key_double_esc_then_arrow(monkeypatch):
    """Fast double-Esc in one read: Esc first, then the following arrow."""
    _install_fake_tty(monkeypatch, b"\x1b\x1b[B")
    assert cu._read_menu_key() == readchar.key.ESC
    assert cu._read_menu_key() == readchar.key.DOWN


def test_read_menu_key_focus_event_then_arrow(monkeypatch):
    """Alt-Tab focus reports stay ignored, and don't eat the next arrow."""
    _install_fake_tty(monkeypatch, b"\x1b[I\x1b[O\x1b[B")
    assert cu._read_menu_key() == ""
    assert cu._read_menu_key() == ""
    assert cu._read_menu_key() == readchar.key.DOWN


def test_read_menu_key_lone_esc_still_goes_back(monkeypatch):
    """Exactly one Esc byte (200 ms of silence) is still a real Esc."""
    _install_fake_tty(monkeypatch, b"\x1b")
    assert cu._read_menu_key() == readchar.key.ESC


def test_read_menu_key_paste_blob_kept_whole(monkeypatch):
    """Bracketed paste is still returned as one text blob (search inserts it)."""
    _install_fake_tty(monkeypatch, b"\x1b[200~naruto\x1b[201~")
    assert cu._read_menu_key() == "naruto"


def test_decode_menu_seq_terminal_reply_keeps_following_arrow():
    """An OSC reply (color query…) must be swallowed whole, never typed into
    the filter, and must not eat the key that follows it."""
    seq = b"\x1b]11;rgb:0000/0000/0000\x1b\\\x1b[B"
    assert cu._decode_menu_seq(seq) == ""
    assert cu._decode_menu_seq(cu._take_raw_carry()) == readchar.key.DOWN


def test_decode_menu_seq_unknown_csi_keeps_following_arrow():
    """An unknown escape (e.g. Shift-Tab) is dropped without swallowing the
    arrow queued right behind it."""
    assert cu._decode_menu_seq(b"\x1b[Z\x1b[A") == ""
    assert cu._decode_menu_seq(cu._take_raw_carry()) == readchar.key.UP


def test_decode_menu_seq_unknown_escape_alone_is_dropped():
    assert cu._decode_menu_seq(b"\x1b[Z") == ""
    assert cu._take_raw_carry() == b""


# ─── 2. stale input must not leak into the next screen ───────────────
def test_drain_stdin_purges_decoded_carry(monkeypatch):
    """Keys decoded into the carry buffers at a screen switch are stale."""
    class _NoTty:
        def isatty(self):
            return False

    monkeypatch.setattr(sys, "stdin", _NoTty())
    cu._stash_raw_carry(b"\x1b[B")
    cu._stash_esc_carry()
    cu.drain_stdin()
    assert cu._take_raw_carry() == b""
    assert cu._take_esc_carry() is False


# ─── 3. poster repaint policy: only once navigation settles ──────────
def test_poster_paint_not_due_during_navigation():
    """Right after a key the expensive SIXEL paint must be skipped."""
    assert pp._poster_paint_due(0.0, None, ("cover", 60, 20), True) is False
    assert pp._poster_paint_due(pp._PAINT_SETTLE - 0.01, None,
                                ("cover", 60, 20), True) is False


def test_poster_paint_due_after_settle():
    assert pp._poster_paint_due(pp._PAINT_SETTLE + 0.01, None,
                                ("cover", 60, 20), True) is True


def test_poster_paint_skipped_when_already_painted():
    target = ("cover", 60, 20, 2, 40)
    assert pp._poster_paint_due(5.0, target, target, True) is False


def test_poster_paint_waits_for_download():
    assert pp._poster_paint_due(5.0, None, ("cover", 60, 20), False) is False


def test_paint_settle_is_fraction_of_a_key_repeat():
    """Settle must be short (poster follows quickly) but >= typical repeat."""
    assert 0.05 <= pp._PAINT_SETTLE <= 0.25
