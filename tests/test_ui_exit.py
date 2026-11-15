"""Exit-path regressions: closing FreeFlix must leave a CLEAN terminal.

User report: after quitting, the last home-menu line ("❯ Que veux-tu faire ?
Quitter") was re-drawn BELOW the shell prompt, sometimes with literal mouse
report fragments ("35;87;5M") in the prompt line.

Root cause (reproduced in a real Konsole window): Rich's
``Console.set_alt_screen()`` writes ``?1049h``/``?1049l`` on EVERY call, and
the exit path called it up to three times (Live.stop, the home menu Exit
branch, ``_clean_exit``). Each extra ``?1049l`` makes terminals such as
Konsole re-apply their saved primary screen + cursor, which re-displayed the
menu echo line after the prompt. The exit paths must:
  - stop mouse/focus reporting and DRAIN already-queued reports (they would be
    echoed by the shell as text in the prompt line),
  - leave the alternate screen EXACTLY ONCE,
  - show the cursor and flush,
  - and Ctrl-C/EOF must run that cleanup instead of printing a traceback.
"""

import io

import pytest

import freeflix_cli.cli_utils as cu
import freeflix_cli.main as app


class _FakeConsole:
    """Records the terminal-state calls instead of writing escape sequences."""

    def __init__(self, alt=False):
        self._alt = alt
        self.calls = []
        self.file = io.StringIO()

    @property
    def is_alt_screen(self):
        return self._alt

    def set_alt_screen(self, enable=True):
        self.calls.append(("set_alt_screen", enable))
        self._alt = bool(enable)
        return True

    def show_cursor(self, show=True):
        self.calls.append(("show_cursor", show))


@pytest.fixture
def fake_console(monkeypatch):
    fake = _FakeConsole(alt=True)
    monkeypatch.setattr(cu, "console", fake)
    return fake


def _count(fake, name):
    return sum(1 for call in fake.calls if call[0] == name)


# ── 1. alt screen: exactly one leave, no-op when already out ─────────
def test_leave_alt_screen_noop_when_not_in_alt(monkeypatch):
    fake = _FakeConsole(alt=False)
    monkeypatch.setattr(cu, "console", fake)
    assert cu.leave_alt_screen() is False
    assert fake.calls == []  # no duplicate ?1049l for the shell to replay


def test_leave_alt_screen_writes_once_then_noop(fake_console):
    assert cu.leave_alt_screen() is True
    assert fake_console.calls == [("set_alt_screen", False)]
    # The exit path calls it again from _clean_exit: must NOT write a 2nd one.
    assert cu.leave_alt_screen() is False
    assert _count(fake_console, "set_alt_screen") == 1


def test_exit_branch_plus_clean_exit_leaves_alt_screen_once(
        fake_console, monkeypatch):
    """Regression: Exit branch + _clean_exit both ran ?1049l (3x total)."""
    monkeypatch.setattr(app, "restore_terminal", app.restore_terminal)
    monkeypatch.setattr(app, "_stop_proxy_if_running", lambda: None)
    monkeypatch.setattr(cu, "drain_stdin", lambda: None)
    monkeypatch.setattr(cu, "_mouse_off", lambda: None)

    # Home menu's Exit branch does this, then main calls _clean_exit(0).
    cu.leave_alt_screen()
    with pytest.raises(SystemExit) as exc:
        app._clean_exit(0)
    assert exc.value.code == 0
    assert _count(fake_console, "set_alt_screen") == 1


# ── 2. terminal restore: order + best effort ────────────────────────
def test_restore_terminal_order_and_single_leave(fake_console, monkeypatch):
    events = []
    monkeypatch.setattr(cu, "_mouse_off", lambda: events.append("mouse_off"))
    monkeypatch.setattr(cu, "drain_stdin", lambda: events.append("drain"))

    cu.restore_terminal()

    # Mouse reports are stopped and the QUEUED ones dropped BEFORE leaving the
    # alt screen (otherwise the shell echoes them in the prompt line).
    assert events == ["mouse_off", "drain"]
    assert fake_console.calls == [
        ("set_alt_screen", False),
        ("show_cursor", True),
    ]
    assert _count(fake_console, "set_alt_screen") == 1


def test_restore_terminal_never_raises(monkeypatch):
    class _Boom:
        def __getattr__(self, name):
            raise RuntimeError("boom")

    monkeypatch.setattr(cu, "console", _Boom())

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(cu, "_mouse_off", _boom)
    monkeypatch.setattr(cu, "drain_stdin", _boom)
    monkeypatch.setattr(cu, "leave_alt_screen", _boom)
    cu.restore_terminal()  # must swallow everything


# ── 3. Ctrl-C / EOF: clean exit, no traceback ───────────────────────
def _system_exit(code=0):
    raise SystemExit(code)


def test_main_keyboard_interrupt_exits_cleanly(monkeypatch):
    events = []

    def _interrupted():
        raise KeyboardInterrupt()

    monkeypatch.setattr(app, "_main", _interrupted)
    monkeypatch.setattr(app, "leave_alt_screen",
                        lambda: events.append("leave"))
    monkeypatch.setattr(app, "print_success",
                        lambda msg: events.append(("goodbye", msg)))
    monkeypatch.setattr(app, "_clean_exit", _system_exit)

    with pytest.raises(SystemExit) as exc:
        app.main()
    assert exc.value.code == 0
    # Goodbye printed on the restored screen, alt screen left only once.
    assert events[0] == "leave"
    assert events[1] == ("goodbye", app.t("Goodbye!"))


def test_main_eof_exits_cleanly(monkeypatch):
    def _eof():
        raise EOFError()

    monkeypatch.setattr(app, "_main", _eof)
    monkeypatch.setattr(app, "leave_alt_screen", lambda: None)
    monkeypatch.setattr(app, "print_success", lambda msg: None)
    monkeypatch.setattr(app, "_clean_exit", _system_exit)
    with pytest.raises(SystemExit):
        app.main()
