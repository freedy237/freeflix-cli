"""
Tests for terminal image protocol selection (freeflix_cli.terminal_image).

Pins the conservative detection : we only override chafa's own autodetection
when the environment AND chafa version make a graphics protocol certain, and
we never emit kitty/iterm on a chafa too old to support it.
"""

import pytest

from freeflix_cli import terminal_image as ti


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("KITTY_WINDOW_ID", "TERM", "TERM_PROGRAM", "ITERM_SESSION_ID",
              "WEZTERM_PANE", "KONSOLE_VERSION", "WT_SESSION",
              "GHOSTTY_RESOURCES_DIR", "VTE_VERSION"):
        monkeypatch.delenv(k, raising=False)
    # Neutralise the real DA1 sixel probe by default so tests are deterministic
    # and never touch a tty. Individual tests opt into sixel via _sixel(True).
    monkeypatch.setattr(ti, "_terminal_supports_sixel", lambda: False)
    yield


def _ver(monkeypatch, v):
    monkeypatch.setattr(ti, "_chafa_version", lambda: v)


def _sixel(monkeypatch, ok):
    monkeypatch.setattr(ti, "_terminal_supports_sixel", lambda: ok)


def test_kitty_env_recent_chafa(monkeypatch):
    _ver(monkeypatch, (1, 14))
    monkeypatch.setenv("KITTY_WINDOW_ID", "3")
    assert ti.detect_image_protocol() == "kitty"
    assert ti._render_format("auto") == "kitty"


def test_kitty_env_old_chafa_falls_back(monkeypatch):
    # chafa too old for the kitty format → don't force it.
    _ver(monkeypatch, (1, 8))
    monkeypatch.setenv("KITTY_WINDOW_ID", "3")
    assert ti.detect_image_protocol() == "auto"
    assert ti._render_format("auto") is None


def test_iterm_env(monkeypatch):
    _ver(monkeypatch, (1, 14))
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    assert ti.detect_image_protocol() == "iterm"


def test_plain_terminal_defers_to_chafa(monkeypatch):
    _ver(monkeypatch, (1, 14))
    monkeypatch.setenv("TERM", "xterm-256color")
    assert ti.detect_image_protocol() == "auto"
    assert ti._render_format("auto") is None  # None → chafa autodetects


def test_sixel_mode_forces_sixels(monkeypatch):
    _ver(monkeypatch, (1, 14))
    assert ti._render_format("sixel") == "sixels"


def test_blocks_mode_forces_symbols(monkeypatch):
    _ver(monkeypatch, (1, 14))
    assert ti._render_format("blocks") == "symbols"


def test_konsole_is_always_sixel(monkeypatch):
    # Konsole (>= 22.12) has sixel ON by default and does NOT advertise it in
    # DA1 — so we must trust KONSOLE_VERSION, not the query (else the overlay
    # would never activate, which was the bug).
    _ver(monkeypatch, (1, 14))
    monkeypatch.setenv("KONSOLE_VERSION", "260403")
    monkeypatch.setenv("TERM", "xterm-256color")
    _sixel(monkeypatch, False)          # DA1 says "no" — must be ignored here
    assert ti.detect_image_protocol() == "sixel"
    assert ti._render_format("auto") == "sixels"


def test_old_konsole_without_sixel_defers(monkeypatch):
    # Pre-22.12 Konsole has no sixel engine → don't force it.
    _ver(monkeypatch, (1, 14))
    monkeypatch.setenv("KONSOLE_VERSION", "210800")   # 21.08
    _sixel(monkeypatch, False)
    assert ti.detect_image_protocol() == "auto"


def test_sixel_via_da1_when_confirmed(monkeypatch):
    # A non-Konsole terminal (e.g. Windows Terminal / xterm+sixel): trust DA1.
    _ver(monkeypatch, (1, 14))
    monkeypatch.setenv("TERM", "xterm-256color")
    _sixel(monkeypatch, True)
    assert ti.detect_image_protocol() == "sixel"
    assert ti._render_format("auto") == "sixels"


def test_sixel_off_falls_back_to_blocks(monkeypatch):
    # Non-Konsole terminal with sixel OFF (DA1 says no) → must NOT emit sixel
    # (would paint escape garbage); fall back to chafa autodetect/blocks.
    _ver(monkeypatch, (1, 14))
    monkeypatch.setenv("TERM", "xterm-256color")
    _sixel(monkeypatch, False)
    assert ti.detect_image_protocol() == "auto"
    assert ti._render_format("auto") is None


def test_sixel_needs_chafa_1_4(monkeypatch):
    _ver(monkeypatch, (1, 2))          # too old for sixel
    _sixel(monkeypatch, True)
    assert ti.detect_image_protocol() == "auto"


def test_kitty_wins_over_sixel(monkeypatch):
    # A terminal that could do both → prefer the sharper kitty protocol.
    _ver(monkeypatch, (1, 14))
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    _sixel(monkeypatch, True)
    assert ti.detect_image_protocol() == "kitty"


def test_sixel_hint_only_when_off(monkeypatch):
    # Windows Terminal relies on DA1 (opt-in sixel) → hint when OFF, gone when ON.
    _ver(monkeypatch, (1, 14))
    monkeypatch.setenv("WT_SESSION", "abc")
    _sixel(monkeypatch, False)
    assert ti.sixel_hint() and "Sixel" in ti.sixel_hint()
    _sixel(monkeypatch, True)          # sixel on → no hint
    assert ti.sixel_hint() is None


# Captured at import (before the autouse fixture mocks it) : the REAL DA1/nt
# probe, to pin the Windows behaviour without touching a tty.
_real_sixel_probe = ti._terminal_supports_sixel


def test_windows_never_trusts_wt_session_for_sixel(monkeypatch):
    """Windows Terminal sets WT_SESSION even when its opt-in Sixel flag is
    OFF — trusting it painted sixels that never render (blank preview).
    The nt branch must fail closed so posters fall back to blocks."""
    monkeypatch.setattr(ti.os, "name", "nt")
    monkeypatch.setenv("WT_SESSION", "abc")
    monkeypatch.setattr(ti, "_SIXEL_OK", None)
    assert _real_sixel_probe() is False
