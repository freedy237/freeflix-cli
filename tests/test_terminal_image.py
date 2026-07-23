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
    for k in ("KITTY_WINDOW_ID", "TERM", "TERM_PROGRAM", "ITERM_SESSION_ID", "WEZTERM_PANE"):
        monkeypatch.delenv(k, raising=False)
    yield


def _ver(monkeypatch, v):
    monkeypatch.setattr(ti, "_chafa_version", lambda: v)


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
