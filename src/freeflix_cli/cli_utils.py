import os
import readchar
import re
import threading
import time
from contextlib import contextmanager
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.cells import cell_len
from rich.table import Table
from .themes import color
from .icons import iconify, icon

console = Console()


def plural(n: int, one: str, many: str) -> str:
    """Translated singular/plural label for a count ("1 saison", "3 saisons")."""
    from .i18n import t as _t
    return _t(one) if int(n) == 1 else _t(many)


def _pulse(period: float = 2.4, duty: float = 0.6) -> bool:
    """Breathing phase for living UI (cursor, flames…) : True during the
    bright part of the cycle. Time-driven, so every Live repaint advances
    it with zero threads. Reduced motion keeps it steadily bright."""
    try:
        from . import motion
        if motion.reduced():
            return True
        return (time.monotonic() % period) < period * duty
    except Exception:
        return True


# ─── Toasts ──────────────────────────────────────────────────────────
# Tiny in-memory hub: long jobs (downloads…) post a toast, and the next
# menu repaint shows it in the status bar for a few seconds — no overlay,
# no threading, no scrollback spam.
_toasts: list = []  # (expires_at, text, style)


def push_toast(text: str, style: str = None, ttl: float = 6.0, bell: bool = False):
    """Post a transient status-bar toast (shown until ``ttl`` expires).
    Non-blocking: the next menu repaint picks it up (see _status_bar).
    Callers pass already-translated text."""
    try:
        _toasts.append((time.monotonic() + max(1.0, ttl),
                        str(text), style or color("success")))
        del _toasts[:-4]
        if bell:
            try:
                console.bell()
            except Exception:
                pass
    except Exception:
        pass


def _current_toast():
    """Newest unexpired toast as (text, style), else None."""
    try:
        now = time.monotonic()
        while _toasts and _toasts[0][0] <= now:
            _toasts.pop(0)
        return (_toasts[-1][1], _toasts[-1][2]) if _toasts else None
    except Exception:
        return None


def clear_screen():
    """Clear the terminal screen, including pixel posters.

    Uses Rich's console.clear() (an ANSI escape) instead of shelling out to
    `clear`/`cls` : no subprocess per clear, and it can't be hijacked by a
    `clear`/`cls` binary earlier on PATH. Konsole keeps sixel images in a
    separate layer that ED does not erase — terminal_image.clear_graphics()
    drops it first so the next menu never lands on top of an old poster.
    """
    try:
        from . import terminal_image
        terminal_image.clear_graphics()
    except Exception:
        pass
    console.clear()


def _finish_input(text: str, default: str, cancelled: bool,
                  cancel_value=""):
    """Resolve a text prompt: Esc CANCELS (returns ``cancel_value``) ; Enter on
    an empty field accepts the displayed default. This distinction matters —
    Esc used to return the pre-filled default, which re-ran the search instead
    of going back. A caller where an EMPTY string is a valid choice (GoldenMS:
    blank = latest) can pass a distinct ``cancel_value`` (e.g. None)."""
    if cancelled:
        return cancel_value
    return (text or "").strip() or (default or "")


def get_user_input(prompt: str, default: str = None, header: str = None,
                   history: list = None, cancel_value="") -> str:
    """
    Get user input with a styled prompt.

    Args:
        prompt: The prompt text to display
        default: The default value to display
        header: Optional banner. When set on a real terminal, the prompt is
            shown FULL-SCREEN with the header panel rendered inside a Live
            (alternate-screen) region and the text typed in raw mode.
        history: Optional recent-entries list (most-recent-first). When set, a
            helper is shown and ↑/↓ recalls previous entries into the field.

    Returns:
        The user's input as a string
    """
    # On a mouse-capable terminal every text field gets the same full-screen
    # editor (and its clickable OK/Cancel buttons). Without this, a bare
    # ``input()`` would swallow mouse reports as typed characters. Plain
    # terminals keep the lightweight prompt.
    if console.is_terminal and (header or _mouse_available()):
        try:
            return _input_fullscreen(prompt, default, header or "", history,
                                     cancel_value)
        except Exception:
            pass  # any raw-mode issue -> plain prompt below

    styled_prompt = Text(f"\n❯ {iconify(prompt)}: ", style=f"bold {color('accent')}")
    console.print(styled_prompt, end="")
    return input().strip() or default


def _input_fullscreen(prompt: str, default: str, header: str,
                       history: list = None, cancel_value="") -> str:
    """Full-screen, resize-safe single-line text prompt (cross-platform).

    Renders the header panel + prompt + live-typed text inside a screen=True
    Live, so resizing the window reflows the whole frame with no leftovers.
    Enter submits, Esc cancels, Ctrl-C raises.
    Keys come from _read_menu_key() (Windows msvcrt / POSIX with focus-event
    filtering), so history recall works on every OS. Esc CANCELS (returns an
    empty string); Enter on an empty field accepts the displayed default.
    """
    import sys

    if not sys.stdin.isatty():
        raise RuntimeError("not a tty")

    flush_input_settled()

    from .i18n import t as _t
    text = ""
    result = {"val": None}
    cancelled = {"v": False}
    history = history or []
    hist_idx = {"i": -1}   # -1 = live text, 0.. = into history
    mouse_on = _mouse_available()
    mouse_rows = []

    def _buttons_action(x, plain):
        for token, action in ((_t("OK"), "ok"), (_t("Cancel"), "cancel")):
            i = plain.find(token)
            if i >= 0 and i - 2 <= (x - 1) < i + len(token):
                return action
        return None

    def render():
        body = []
        mouse_rows.clear()

        def add(line, tag=None):
            body.append(line)
            h = _renderable_height(line) if mouse_on else 1
            mouse_rows.extend([tag] + [None] * (h - 1))

        if header:
            add(_header_panel(header))
        add(Text(f"\n ❯ {iconify(prompt)}", style=f"bold {color('accent')}"))
        add(Text(f"\n   {text}▏", style="white"))
        if default and not text:
            add(Text(f"\n   ({iconify('default')}: {default})",
                     style=color("dim")))
        if history:
            recent = "   ".join(f"↺ {h}" for h in history[:4])
            add(Text(f"\n\n   {_t('Recent searches')}",
                     style=f"bold {color('info')}"))
            add(Text(f"\n   {recent[:76]}", style=color("dim")))
            add(Text(f"\n   {_t('↑/↓ recall · type to search')}",
                     style=color("dim")))
        if mouse_on:
            # Mouse users can submit/cancel the field without knowing the
            # keyboard shortcuts. Typing itself still needs the keyboard (no
            # virtual keyboard in a terminal), but every action has a target.
            add(Text(""))
            buttons = Text.assemble(
                Text("  ", style=color("dim")),
                _kbd(_t("OK")), Text("  ", style=color("dim")),
                _kbd(_t("Cancel")),
            )
            add(buttons, ("buttons", buttons.plain))
        return Group(*body)

    with mouse_tracking():
        with Live(render(), console=console, refresh_per_second=20,
                  screen=True) as live:
            while result["val"] is None:
                key = _read_menu_key()
                if key == "":
                    continue  # event focus/souris ignoré
                if isinstance(key, MouseEvent):
                    if key.motion:
                        continue
                    if key.is_left:
                        rel = key.y - 1
                        tag = (mouse_rows[rel]
                               if 0 <= rel < len(mouse_rows) else None)
                        if tag and tag[0] == "buttons":
                            act = _buttons_action(key.x, tag[1])
                            if act == "ok":
                                result["val"] = text
                            elif act == "cancel":
                                cancelled["v"] = True
                                result["val"] = ""
                    live.update(render())
                    continue
                if key == readchar.key.ESC:
                    cancelled["v"] = True
                    result["val"] = ""  # Esc -> cancel (never the default)
                elif key == readchar.key.UP:
                    if history and hist_idx["i"] < len(history) - 1:
                        hist_idx["i"] += 1
                        text = history[hist_idx["i"]]
                elif key == readchar.key.DOWN:
                    if history:
                        if hist_idx["i"] > 0:
                            hist_idx["i"] -= 1
                            text = history[hist_idx["i"]]
                        else:
                            hist_idx["i"] = -1
                            text = ""
                elif key == readchar.key.ENTER:
                    result["val"] = text
                elif key == readchar.key.BACKSPACE:
                    text = text[:-1]
                elif key == readchar.key.CTRL_C:
                    raise KeyboardInterrupt("cancelled")
                elif isinstance(key, str):
                    for c in key:
                        if c.isprintable():
                            text += c
                            hist_idx["i"] = -1  # back to live editing
                live.update(render())

    return _finish_input(result["val"], default, cancelled["v"], cancel_value)


def pause():
    """Wait for Enter/Space/Esc or a mouse click before continuing."""
    import sys
    from .i18n import t as _t
    if not sys.stdin.isatty() or not console.is_terminal:
        console.input(f"\n[{color('dim')}]{_t('Press Enter to continue...')}[/{color('dim')}]")
        return
    flush_input_settled()
    console.print(f"\n[{color('dim')}]{_t('Press Enter or click to continue...')}[/{color('dim')}]")
    with mouse_tracking():
        while True:
            key = _read_menu_key()
            if isinstance(key, MouseEvent):
                if key.is_left:
                    return
                continue
            if key in (readchar.key.ENTER, readchar.key.ESC, " "):
                return
            if key == readchar.key.CTRL_C:
                raise KeyboardInterrupt("cancelled")


def ask_yes_no(message: str, default: bool = True,
               non_tty: bool = False) -> bool:
    """A small clickable Yes/No prompt (used by update/setup confirmations).

    Keyboard: Enter = default · y/o = yes · n = no · Esc = no.
    Mouse: click the visible Yes or No pill. On a non-tty ``non_tty`` is
    returned immediately (False by default) so scripts never block or
    silently install/update anything.
    """
    import sys
    from .i18n import t as _t

    if not console.is_terminal or not sys.stdin.isatty():
        return non_tty
    flush_input_settled()
    yes, no = _t("Yes"), _t("No")

    def render():
        line = Text.assemble(
            Text(f"  {iconify(message)}   ", style="bold white"),
            _kbd(yes), Text("  "), _kbd(no),
        )
        return line

    def _action(x, plain):
        for token, value in ((yes, True), (no, False)):
            i = plain.find(token)
            if i >= 0 and i - 2 <= (x - 1) < i + len(token):
                return value
        return None

    with mouse_tracking():
        with Live(render(), console=console, refresh_per_second=8,
                  transient=True) as live:
            while True:
                key = _read_menu_key()
                if isinstance(key, MouseEvent):
                    if key.motion:
                        continue
                    if key.is_left:
                        val = _action(key.x, render().plain)
                        if val is not None:
                            return val
                    live.update(render())
                    continue
                if key == readchar.key.ENTER:
                    return default
                if key in ("y", "Y", "o", "O"):
                    return True
                if key in ("n", "N", "q", "Q", readchar.key.ESC):
                    return False
                if key == " ":
                    return True
                if key == readchar.key.CTRL_C:
                    raise KeyboardInterrupt("cancelled")
                live.update(render())


def confirm_or_timeout(message: str, seconds: int = 6, default: bool = True) -> bool:
    """Show *message* with a live countdown and auto-return *default*.

    Enter/Space/y = accept, Esc/n = decline. A click on the visible yes/no
    pills does the same. On a non-interactive terminal it returns *default*
    immediately (never blocks a script). One portable loop drives the
    countdown; the platform-specific reader is only used to know *when* a
    key/click is available, then the shared menu decoder handles it.
    """
    import sys
    import time as _time
    from .i18n import t as _t

    if not console.is_terminal or not sys.stdin.isatty():
        return default

    flush_input_settled()
    accent, dim = color("accent"), color("dim")
    yes, no = _t("yes"), _t("no")

    def _render(remaining):
        return Text.from_markup(
            f"  [bold {accent}]{iconify(message)}[/]   "
            f"[{dim}]{_t('Enter')}: {yes} · {_t('Esc')}: {no} · "
            f"{_t('auto in')} {remaining}s[/]"
        )

    def _decide(key, remaining):
        if isinstance(key, MouseEvent):
            if not key.is_left:
                return None
            plain = _render(remaining).plain
            for token, value in ((_t("yes"), True), (_t("no"), False)):
                i = plain.rfind(token)  # labels live at the end
                if i >= 0 and i - 2 <= (key.x - 1) < i + len(token):
                    return value
            return None
        if key in (readchar.key.ENTER, " ", "y", "Y", "o", "O"):
            return True
        if key in ("n", "N", "q", "Q", readchar.key.ESC):
            return False
        if key == readchar.key.CTRL_C:
            raise KeyboardInterrupt("cancelled")
        return None

    end = _time.time() + seconds
    decided = None
    with mouse_tracking():
        with Live(_render(seconds), console=console, refresh_per_second=8,
                  transient=True) as live:
            while _time.time() < end and decided is None:
                key = None
                if os.name == "nt":
                    import msvcrt
                    if msvcrt.kbhit():
                        key = _read_menu_key()
                    else:
                        _time.sleep(0.05)
                else:
                    import select as _sel
                    r, _, _ = _sel.select([sys.stdin.fileno()], [], [], 0.15)
                    if r:
                        key = _read_menu_key()
                if key is not None:
                    decided = _decide(key, max(0, int(end - _time.time()) + 1))
                live.update(_render(max(0, int(end - _time.time()) + 1)))
    return default if decided is None else decided


def drain_stdin():
    """
    Discard anything already sitting in stdin. At launch a terminal often emits
    replies to init queries (device attributes, cursor position) or a focus
    event — those bytes start with ``\\x1b`` and, if read by the first menu, are
    mis-parsed as a lone Esc → the home menu maps Esc to its last option (Exit)
    → FreeFlix "closes by itself the moment you enter". Draining first fixes it.
    Best-effort ; never raises.
    """
    try:
        import sys
        if not sys.stdin.isatty():
            return
        if os.name == "nt":
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getwch()
        else:
            # tcflush discards the terminal driver's pending INPUT queue
            # regardless of canonical/raw mode — the escape bytes emitted at
            # startup have no newline, so they're NOT readable via os.read in
            # canonical mode ; tcflush drops them anyway. This is the fix.
            import termios
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except Exception:
        pass


def flush_input_settled(settle: float = 0.03):
    """Purge stale stdin before an interactive screen.

    Between two screens (spinner → menu, mpv → menu, menu → menu) any
    keystroke or terminal event (focus ``\\x1b[I``/``\\x1b[O``, mouse report,
    device-attribute reply) sitting in the input queue is *invalid* — the user
    can't aim at a screen that isn't shown yet. Without this purge the next
    menu misreads the leading ``\\x1b`` as a lone Esc → phantom "back".

    Waits ~30 ms first so an escape sequence still in flight can complete,
    then drains. Best-effort ; never raises.
    """
    try:
        import sys
        import time as _t
        if sys.stdin.isatty():
            _t.sleep(settle)
    except Exception:
        pass
    drain_stdin()


# ─── Mouse support (menus, lists, confirmations) ──────────────────────
# Terminals report clicks as SGR sequences:
#   ESC [ < button ; x ; y M   (press / wheel)
#   ESC [ < button ; x ; y m   (release)
# `button` is 0 left, 1 middle, 2 right, 64 wheel-up, 65 wheel-down (with
# modifier bits in the low byte). Bit 32 marks a motion report. We enable
# button + all-motion reporting with SGR encoding (?1000h ?1003h ?1006h) so
# the menu cursor follows the physical mouse (hover), not just clicks.
# Tracking is switched off as soon as the screen exits, so the user's shell
# keeps its normal mouse selection.
_MOUSE_RE_S = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
_MOUSE_RE_B = re.compile(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
_MOUSE_ON = "\x1b[?1000h\x1b[?1003h\x1b[?1006h"
_MOUSE_OFF = "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l"
_mouse_active = False
_raw_mode_active = False


def _escape_incomplete(data):
    """True while an escape sequence has not received its final byte.

    This is what stops a split mouse report (very common under all-motion
    tracking) from being decoded byte-by-byte, which used to append
    ``<35;...M`` fragments to the type-to-filter query and hide results.
    """
    if not data or not data.startswith(b"\x1b"):
        return False
    if _PASTE_START.startswith(data):
        return True
    if data == b"\x1b":
        return True
    if data.startswith(b"\x1b[<"):
        return _MOUSE_RE_B.match(data) is None
    if data.startswith(b"\x1b]"):
        return not any(end in data[2:] for end in _OSC_ENDS)
    if data[1:2] in (b"[", b"O"):
        return len(data) < 3
    return False


class MouseEvent:
    """A decoded terminal mouse event (1-based screen coordinates)."""

    __slots__ = ("x", "y", "button", "pressed", "wheel", "motion")

    def __init__(self, x: int, y: int, button: int, pressed: bool):
        raw = int(button)
        self.x = int(x)
        self.y = int(y)
        self.button = raw & 3
        self.pressed = bool(pressed)
        self.motion = bool(raw & 32 and not raw & 64)
        self.wheel = (raw & 64) and (
            "up" if (raw & 1) == 0 else "down") or ""

    @property
    def is_left(self) -> bool:
        return (self.pressed and not self.wheel and not self.motion
                and self.button == 0)

    @property
    def is_right(self) -> bool:
        return (self.pressed and not self.wheel and not self.motion
                and self.button == 2)

    def __repr__(self):
        return (f"MouseEvent(x={self.x}, y={self.y}, button={self.button}, "
                f"pressed={self.pressed}, wheel={self.wheel!r}, "
                f"motion={self.motion})")


def _mouse_from_match(m) -> MouseEvent:
    raw, x, y, final = m.group(1), m.group(2), m.group(3), m.group(4)
    if isinstance(raw, bytes):
        raw, x, y, final = (raw.decode(), x.decode(), y.decode(),
                            final.decode())
    return MouseEvent(int(x), int(y), int(raw), final == "M")


def _mouse_available() -> bool:
    """True when this process can both send mouse modes and read reports."""
    import sys
    if os.environ.get("FREEFLIX_NO_MOUSE", "").lower() in ("1", "true", "yes", "on"):
        return False
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _mouse_write(seq: str) -> None:
    import sys
    try:
        sys.stdout.write(seq)
        sys.stdout.flush()
    except Exception:
        pass


def _mouse_off() -> None:
    global _mouse_active
    if not _mouse_active:
        return
    _mouse_active = False
    _mouse_write(_MOUSE_OFF)


@contextmanager
def mouse_tracking():
    """Enable SGR mouse reporting for the duration of an interactive screen.

    The terminal is also put in cbreak/no-echo mode for the WHOLE screen.
    This second part is essential with all-motion tracking: between two
    ``_read_menu_key`` calls the tty would otherwise be back in canonical mode
    with ECHO on, and the terminal emulator would print every motion report as
    literal ``[<35;…M`` text at the bottom of the screen. Nested readers
    (``_read_menu_key``, preview's raw loop, progress) still save/restore their
    own settings; ours restores the original on exit.

    Yields True when tracking was actually enabled. The disable call is in a
    ``finally`` (and also registered at exit) so an exception/crash can never
    leave the terminal grabbing every click.
    """
    global _mouse_active, _raw_mode_active
    active = False
    old_term = None
    fd = None
    if _mouse_available():
        try:
            import sys
            if os.name != "nt" and sys.stdin.isatty():
                import termios
                import tty
                fd = sys.stdin.fileno()
                old_term = termios.tcgetattr(fd)
                tty.setcbreak(fd)
                _raw_mode_active = True
        except Exception:
            fd = None
            old_term = None
            _raw_mode_active = False
        _mouse_write(_MOUSE_ON)
        _mouse_active = True
        active = True
    try:
        yield active
    finally:
        if active:
            _mouse_off()
        if old_term is not None:
            try:
                import termios
                termios.tcsetattr(fd, termios.TCSADRAIN, old_term)
            except Exception:
                pass
        _raw_mode_active = False


try:
    import atexit as _atexit
    _atexit.register(_mouse_off)
except Exception:  # pragma: no cover
    pass


def _cursor_row(timeout: float = 0.15):
    """Ask the terminal for the cursor row (1-based), or None.

    Used by inline mouse menus: unlike alternate-screen menus, their first
    rendered row is wherever the cursor currently sits. A DSR query
    (``ESC[6n``) gives the exact anchor so click coordinates stay correct.
    Best-effort: unsupported terminals return None and the caller can fall
    back to a full-screen menu.
    """
    import sys
    try:
        if os.name == "nt" or not sys.stdin.isatty():
            return None
        import select as _sel
        import termios
        import tty
        import time as _t
        fd = sys.stdin.fileno()
        old = None
        if not _raw_mode_active:
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        try:
            sys.stdout.write("\x1b[6n")
            sys.stdout.flush()
            buf = b""
            deadline = _t.monotonic() + timeout
            while _t.monotonic() < deadline:
                left = deadline - _t.monotonic()
                r, _, _ = _sel.select([fd], [], [], max(0.0, left))
                if not r:
                    break
                buf += os.read(fd, 64)
                m = re.search(rb"\x1b\[(\d+);(\d+)R", buf)
                if m:
                    return int(m.group(1))
            return None
        finally:
            if old is not None:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        return None


def _renderable_height(renderable, width: int = None) -> int:
    """Number of terminal rows a renderable will occupy (for mouse hit-tests).

    Rich is the only reliable source of truth: panels, tables and text with
    embedded newlines wrap differently from their plain strings. Menus are
    small, so measuring each line once per frame is cheap; a failure degrades
    to one row instead of breaking the UI.
    """
    try:
        w = max(1, int(width or console.size.width))
        options = console.options.update(width=w)
        return max(1, len(console.render_lines(renderable, options, pad=False)))
    except Exception:
        return 1


def disable_terminal_reports():
    """
    Turn OFF terminal focus-reporting / mouse tracking — but turn ON bracketed
    paste.

    Some terminals (and mpv) enable focus reporting (``\\x1b[?1004h``): the
    terminal then sends ``\\x1b[I`` / ``\\x1b[O`` whenever the window gains/loses
    focus (e.g. Alt-Tab). If one of those bytes lands split across reads, a menu
    can mistake the leading ``\\x1b`` for a stray Esc — which looked like
    "FreeFlix closing by itself". Killing the reports at the source removes it.
    Called at startup and after every player exit (mpv may re-enable them).

    Bracketed paste (``\\x1b[?2004h``) is the opposite case : we WANT it. It
    wraps pastes as ``\\x1b[200~ … \\x1b[201~`` so a middle-click paste of
    terminal output (full of ANSI escapes) arrives as ONE blob the menus can
    swallow whole — instead of leaking bare ``\\x1b`` bytes that each look
    like an Esc press and walk the user back to Home untouched. All readers
    below consume the blob (menus ignore it, the search box inserts the text).
    """
    try:
        import sys
        if sys.stdout.isatty():
            sys.stdout.write(
                "\x1b[?1004l"                                   # focus off
                "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l"  # mouse off
                "\x1b[?2004h"                                   # bracketed paste ON
            )
            sys.stdout.flush()
    except Exception:
        pass


# ─── Bracketed-paste blobs ────────────────────────────────────────────
# With ?2004h on, a paste arrives as ESC[200~ + text + ESC[201~. Readers must
# swallow the whole blob : menus ignore it, the search box inserts the text,
# the binge prompt ignores it, the download cancel-counter skips it. A bare
# \x1b leaking out of a paste used to count as an Esc press (double-Esc
# walked straight to Home on one middle-click).
_PASTE_START = b"\x1b[200~"
_PASTE_END = b"\x1b[201~"
_PASTE_START_S = "\x1b[200~"
_PASTE_END_S = "\x1b[201~"
_PASTE_MAX = 8192  # never buffer more than 8 KB of pasted text


def _split_paste(data: bytes):
    """Split a buffer starting with a paste marker.

    Returns (text, rest) once the closing marker is present, where `text` is
    the pasted bytes (no markers) and `rest` anything after the blob (usually
    empty — dropped by callers in the freak overlap case). Returns (None,
    data) while unterminated (callers keep reading) or when data doesn't
    start with a marker.
    """
    if not data.startswith(_PASTE_START):
        return None, data
    i = data.find(_PASTE_END, len(_PASTE_START))
    if i < 0:
        return None, data
    return data[len(_PASTE_START):i], data[i + len(_PASTE_END):]


# Terminal replies must NEVER become keys : OSC (… ST/BEL), DA/XTWINOPS and
# friends arrive late/fragmented and their leading \x1b alone looks exactly
# like an Esc press (phantom back, even through the double-Esc gate when a
# reply carries several \x1b bytes). Swallow them whole, wherever they land.
_OSC_ENDS = (b"\x1b\\", b"\x07")
# Complete CSI replies (size/color reports…) : digits + final letter, longer
# than any arrow/focus sequence. Arrows (\x1b[A, len 3) and focus (\x1b[I/O)
# never match because of the length guard.
_CSI_REPLY = re.compile(rb"\x1b\[[0-9;?]+[a-zA-Z~]$")


def _split_reply(data: bytes):
    """Split a buffer starting with a terminal-reply introducer.

    Returns (True, rest) once the reply is complete (reply dropped, `rest`
    kept for normal decoding), (False, data) while unterminated. Replies
    covered : OSC `ESC ] … (ST|BEL)` (color queries, titles…) and anything
    starting with a lone ESC that isn't yet classifiable (callers keep
    waiting for more before deciding Esc-vs-sequence).
    """
    if data.startswith(b"\x1b]"):
        for end in _OSC_ENDS:
            i = data.find(end, 2)
            if i >= 0:
                return True, data[i + len(end):]
        return False, data
    return False, data


# ─── Breadcrumb trail (1.8) ────────────────────────────────────────────
# A tiny global stack rendered above every menu :
#   🏠 Home › Anime-Sama › Naruto › Season 2
# Handlers call crumb_reset()/crumb_push() at each level, so the
# user always knows where they are and what Esc will go back to.
_crumbs: list = []


def crumb_reset(*labels):
    """Replace the whole trail (e.g. entering a screen from Home)."""
    _crumbs[:] = [x for x in labels if x]


def crumb_push(label):
    if label:
        _crumbs.append(str(label))


def crumbs_text() -> str:
    return " › ".join(_crumbs)


class crumb:
    """Scoped breadcrumb level(s) : ``with crumb(series.title): …`` — the trail
    is restored on exit no matter how the block ends (break/return/exception).

    Accepts several labels for a single level, e.g.
    ``with crumb("Anime-Sama", day, date):`` (all pushed, all popped)."""

    def __init__(self, *labels):
        self.labels = [x for x in labels if x]

    def __enter__(self):
        self._n = len(_crumbs)
        for label in self.labels:
            crumb_push(label)
        return self

    def __exit__(self, *exc):
        del _crumbs[self._n:]
        return False


def _crumb_line(max_w: int) -> Text:
    """The breadcrumb, truncated from the LEFT so the deepest (most useful)
    levels stay visible. The chevrons are drawn in the accent colour and the
    last segment is bold-accent, so "where you are" pops out of the trail."""
    txt = crumbs_text()
    if cell_len(txt) > max_w - 4:
        while _crumbs and cell_len("… › " + txt) > max_w - 4:
            txt = txt.split(" › ", 1)[-1] if " › " in txt else txt[-(max_w - 8):]
            if " › " not in txt and cell_len("… › " + txt) <= max_w - 4:
                break
        txt = "… › " + txt
    parts = txt.split(" › ")
    out = Text("  ")
    for i, part in enumerate(parts):
        if i:
            out.append(" › ", style=color("accent"))
        is_last = i == len(parts) - 1
        out.append(part, style=f"bold {color('accent')}" if is_last else color("dim"))
    return out


def _status_mouse_action(x: int, plain: str):
    """Map a click on the bottom hint bar to help/filter/clear."""
    from .i18n import t as _t
    if not plain:
        return None
    wanted = (
        (_t("?: help"), "help"),
        (_t("/: filter"), "filter"),
        (_t("Esc: clear"), "clear"),
        (_t("Enter: select"), "select"),
        (_t("Esc: back"), "back"),
    )
    for token, action in wanted:
        i = plain.find(token)
        if i < 0:
            continue
        # The pill glyphs add at most a couple of cells around the label.
        if i - 2 <= (x - 1) < i + len(token):
            return action
    return None


def _status_bar(filtering: bool = False) -> Text:
    """Bottom hint line shown under every menu (consistent across screens)."""
    from .i18n import t as _t
    if filtering:
        bar = Text.assemble(
            Text("  ", style=color("dim")),
            _kbd(_t("type to filter")), Text(" · ", style=color("dim")),
            _kbd(_t("Enter: select")), Text(" · ", style=color("dim")),
            _kbd(_t("Esc: clear")),
        )
        return bar
    bar = Text.assemble(
        Text("  ↑/↓ · ", style=color("dim")),
        _kbd(_t("Enter: select")), Text(" · ", style=color("dim")),
        _kbd(_t("Esc: back")), Text(" · ", style=color("dim")),
        _kbd(_t("/: filter")), Text(" · ", style=color("dim")),
        _kbd(_t("?: help")),
    )
    # A fresh toast (download finished, …) rides along for a few seconds.
    tn = _current_toast()
    if tn is not None:
        msg, style = tn
        bar.append(Text("   ✓ ", style=style))
        bar.append(Text(msg, style=style))
    return bar


def _help_overlay() -> Panel:
    """The '?' help overlay : every keyboard shortcut in one panel, split in
    two columns (Menus | mpv player) so it stays compact."""
    from .i18n import t as _t
    from rich.table import Table
    menu_rows = [
        ("↑ / ↓",      _t("navigate")),
        ("Enter",      _t("select")),
        ("Esc",        _t("go back / cancel")),
        ("Space",      _t("toggle episode (multi-select)")),
        ("a",          _t("select all (multi-select)")),
        ("Esc Esc",    _t("cancel a running download")),
        ("Ctrl+C",     _t("quit FreeFlix")),
        ("? ",         _t("show / hide this help")),
    ]
    player_rows = [
        ("CTRL+1/2", _t("Anime4K quality (max / light)")),
        ("CTRL+0",   _t("Anime4K off")),
        ("q",        _t("close the player")),
    ]

    def _col(title, rows):
        tb = Table.grid(padding=(0, 1))
        tb.add_column()
        tb.add_column()
        tb.add_row(Text(f"{title}", style=f"bold {color('accent')}"), Text(""))
        for key_label, desc in rows:
            tb.add_row(
                Text(f"   {key_label:<9}", style=f"bold {color('info')}"),
                Text(f" {desc}", style="white"),
            )
        return tb

    grid = Table.grid(padding=(0, 4))
    grid.add_column()
    grid.add_column()
    grid.add_row(_col(_t("Menus"), menu_rows), _col(_t("In the player (mpv)"), player_rows))
    return Panel(grid, border_style=color("accent"),
                 title=f"[bold]{_t('Help')}[/bold]", expand=False)


def toast(message: str, kind: str = "success", seconds: float = 1.1):
    """
    Non-blocking confirmation: flash a brief styled message that clears itself
    (no "press Enter"). Plain print on a non-tty.
    """
    import time as _time
    styles = {"success": color("success"), "info": color("info"),
              "warning": color("warning"), "error": color("error")}
    marks = {"success": "✓", "info": "i", "warning": "!", "error": "✗"}
    style = styles.get(kind, color("info"))
    text = Text()
    text.append("  ▌ ", style=style)
    text.append(f"{marks.get(kind, 'i')} {message}", style=f"bold {style}")
    if not console.is_terminal:
        console.print(text)
        return
    try:
        with Live(text, console=console, refresh_per_second=4, transient=True):
            _time.sleep(seconds)
    except Exception:
        console.print(text)


# ─── Single-Esc Back navigation ─────────────────────────────────────
# One Esc press goes back immediately. Stray bytes are handled upstream :
# bracketed pastes are swallowed whole, terminal replies are swallowed,
# escape sequences are drained with a 200 ms idle budget, and chafa runs
# with --probe off + stdin closed so it emits no late replies. (A double-Esc
# gate existed briefly in 1.12-dev and was reverted per user request.)
# A fast double-Esc can arrive in ONE read (`\x1b\x1b`) : the drains below
# stash the second press here so the next _read_menu_key() call replays it
# instead of swallowing the pair.
_esc_carry = False


def _stash_esc_carry() -> None:
    global _esc_carry
    _esc_carry = True


def _take_esc_carry() -> bool:
    global _esc_carry
    if _esc_carry:
        _esc_carry = False
        return True
    return False


def _read_menu_key_raw():
    """
    Read one keypress for the arrow menus, returning readchar key constants.

    Why not just ``readchar.readkey()``? On POSIX, readchar reads Esc (``\\x1b``)
    then BLOCKS on a 2nd byte to tell a lone Esc from an arrow sequence
    (``\\x1b[A``) — so a lone Esc never fires until another key is pressed (that's
    why "Esc did nothing" on Linux but worked on Windows). Here we peek with a
    200 ms idle timeout: no follow-up byte ⇒ a real Esc. Windows / non-tty
    fall back to readchar (where Esc already returns immediately).
    """
    import sys

    # ── Windows : read via msvcrt and DRAIN escape sequences ourselves, so a
    # focus event (\x1b[I / \x1b[O sent by Windows Terminal on Alt-Tab) or a
    # mouse report can't be misread as a stray Esc (which made FreeFlix "press
    # Esc by itself" and close). readchar's Windows path mishandled these.
    if os.name == "nt":
        try:
            import msvcrt
            import time as _t
        except Exception:
            return readchar.readkey()
        try:
            ch = msvcrt.getwch()
        except Exception:
            return readchar.readkey()
        # Classic-console special keys (arrows/F-keys): the prefix is ALWAYS
        # followed by a scan code — read it unconditionally (gating on kbhit()
        # was the bug that made the arrow keys do nothing).
        if ch in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            return {"H": readchar.key.UP, "P": readchar.key.DOWN,
                    "M": readchar.key.RIGHT, "K": readchar.key.LEFT}.get(code, "")
        # VT-mode escape sequence (Windows Terminal): arrows are \x1b[A…, focus
        # events \x1b[I / \x1b[O. Wait briefly for the rest so a real arrow isn't
        # mistaken for a lone Esc; only a truly isolated \x1b is Esc.
        if ch == "\x1b":
            seq = ch
            # Drain loop with an idle budget (~200 ms of silence) instead of
            # a fixed iteration count : arrows resolve instantly, a slow
            # terminal still gets its tail, and a long bracketed paste is
            # consumed whole no matter its size.
            idle = 0
            paste_text = None
            spins = 0
            while True:
                spins += 1
                if spins > 2000:
                    return ""
                if msvcrt.kbhit():
                    idle = 0
                    seq += msvcrt.getwch()
                    if seq.startswith(_PASTE_START_S):
                        _text, _rest = _split_paste(seq.encode("utf-8", "ignore"))
                        if _text is not None:
                            paste_text = _text.decode("utf-8", "ignore")
                            break
                        if len(seq) >= _PASTE_MAX:
                            return ""
                        continue
                    if seq.startswith("\x1b]"):
                        _done, _rest = _split_reply(
                            seq.encode("utf-8", "ignore"))
                        if _done:
                            seq = _rest.decode("utf-8", "ignore") or ""
                            if not seq:
                                continue
                        elif len(seq) >= _PASTE_MAX:
                            return ""
                        else:
                            continue
                    if seq.startswith("\x1b[<"):
                        hits = list(_MOUSE_RE_S.finditer(seq))
                        if hits:
                            # A burst often contains several motion reports.
                            # Return the LAST one so the cursor jumps straight
                            # to the pointer's current position (no backlog).
                            return _mouse_from_match(hits[-1])
                        if len(seq) > 64:
                            return ""
                        continue  # partial SGR mouse report
                    if _CSI_REPLY.match(seq.encode("utf-8", "ignore")):
                        seq = ""
                        continue
                    if len(seq) >= 3:
                        break
                else:
                    idle += 1
                    if idle >= 25:
                        break
                    _t.sleep(0.008)
            if paste_text is not None:
                # Bracketed paste : menus ignore the blob (a multi-char str
                # falls through every branch), the search box inserts it.
                return paste_text
            if seq == "\x1b":
                return readchar.key.ESC
            # Fast double-Esc in one read (`\x1b\x1b…`) : replay the second
            # press on the next call instead of swallowing the pair.
            if seq[:2] == "\x1b\x1b":
                _stash_esc_carry()
                return readchar.key.ESC
            # Explicitly ignore focus events (\x1b[I / \x1b[O)
            if seq in ("\x1b[I", "\x1b[O"):
                return ""          # focus in/out → ignore
            _known = {"\x1b[A": readchar.key.UP, "\x1bOA": readchar.key.UP,
                    "\x1b[B": readchar.key.DOWN, "\x1bOB": readchar.key.DOWN,
                    "\x1b[C": readchar.key.RIGHT, "\x1b[D": readchar.key.LEFT,
                    }
            return _known.get(seq, "")          # focus/mouse/unknown → ignore
        if ch in ("\r", "\n"):
            return readchar.key.ENTER
        if ch == "\x03":
            return readchar.key.CTRL_C
        if ch in ("\x08", "\x7f"):
            return readchar.key.BACKSPACE
        return ch

    try:
        import termios
        import tty
        import select as _sel
        is_tty = sys.stdin.isatty()
    except Exception:
        is_tty = False
    if not is_tty:
        return readchar.readkey()

    fd = sys.stdin.fileno()
    outer_raw = _raw_mode_active
    old = None
    try:
        if not outer_raw:
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        ch = os.read(fd, 1)
        if ch == b"\x1b":
            # Drain the WHOLE escape sequence (arrows, but also focus events
            # \x1b[I / \x1b[O and mouse reports) before deciding. Only a truly
            # isolated \x1b — ~200 ms of silence — is a real Esc (a shorter
            # window misread split sequences under poster-load contention as
            # a lone Esc → phantom "back"). A bracketed paste is consumed
            # whole and returned as text (menus ignore it, search inserts it).
            seq = ch
            idle = 0
            paste_text = None
            spins = 0
            while True:
                spins += 1
                if spins > 500:
                    return ""  # garbage flood — give up, stay in menu
                r, _, _ = _sel.select([fd], [], [], 0.008)
                if r:
                    idle = 0
                    seq += os.read(fd, 64)
                    if seq.startswith(_PASTE_START):
                        _text, _rest = _split_paste(seq)
                        if _text is not None:
                            paste_text = _text
                            break
                        if len(seq) >= _PASTE_MAX:
                            return ""
                        continue
                    if seq.startswith(b"\x1b]"):
                        # Terminal reply (OSC color query, title…) : swallow
                        # it whole so its fragments never read as Esc.
                        _done, seq = _split_reply(seq)
                        if _done:
                            if not seq:
                                continue  # reply only — wait for real input
                        elif len(seq) >= _PASTE_MAX:
                            return ""
                        else:
                            continue  # partial reply — keep waiting
                    if seq.startswith(b"\x1b[<"):
                        hits = list(_MOUSE_RE_B.finditer(seq))
                        if hits:
                            # Use the newest report in the read chunk: the
                            # cursor follows the physical pointer immediately
                            # instead of replaying a queue of stale motion.
                            return _mouse_from_match(hits[-1])
                        if len(seq) > 64:
                            return ""
                        continue  # partial SGR mouse report
                    if _CSI_REPLY.match(seq):
                        # Complete CSI reply (size/color report…) : drop it
                        # and keep waiting for a real key.
                        seq = b""
                        continue
                    if len(seq) >= 3:  # enough for a CSI/SS3 arrow
                        break
                else:
                    idle += 1
                    if idle >= 25:
                        break
            if paste_text is not None:
                try:
                    return paste_text.decode("utf-8", "ignore")
                except Exception:
                    return ""
            if seq == b"\x1b":
                return readchar.key.ESC          # lone Esc → go back
            # Fast double-Esc in one read (`\x1b\x1b…`) : replay the second
            # press on the next call instead of swallowing the pair.
            if seq[:2] == b"\x1b\x1b":
                _stash_esc_carry()
                return readchar.key.ESC
            # Explicitly ignore focus events (\x1b[I / \x1b[O) and other non-arrow CSI
            if seq in (b"\x1b[I", b"\x1b[O"):
                return ""          # focus in/out → ignore, don't trigger Esc
            _known = {
                b"\x1b[A": readchar.key.UP,   b"\x1bOA": readchar.key.UP,
                b"\x1b[B": readchar.key.DOWN,  b"\x1bOB": readchar.key.DOWN,
                b"\x1b[C": readchar.key.RIGHT, b"\x1b[D": readchar.key.LEFT,
            }
            return _known.get(seq, "")          # other CSI/mouse → ignore
        if ch in (b"\r", b"\n"):
            return readchar.key.ENTER
        if ch == b"\x03":
            return readchar.key.CTRL_C
        if ch in (b"\x7f", b"\x08"):
            return readchar.key.BACKSPACE
        try:
            return ch.decode("utf-8", "ignore")
        except Exception:
            return ""
    finally:
        if old is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_menu_key():
    """Single entry point for menu key reads (carry replay + raw decode)."""
    if _take_esc_carry():
        return readchar.key.ESC
    return _read_menu_key_raw()


# Language / quality badges + status glyphs get their own colours in every
# menu (player lists, batch picker, theme list…). Labels stay PLAIN strings
# (so _fit truncation and tests are unaffected) — styling is applied here,
# centrally, on the already-fitted text. Spans never change display width,
# and unknown [...] tokens (e.g. "[1/6]", episode titles) are left alone.
_LANG_BADGE_ROLES = {
    "VF": "success",
    "VOSTFR": "info",
    "VO": "accent",
    "VFQ": "warning",
}
_OPT_TOKEN_PAT = re.compile(r"\[VFQ\]|\[VOSTFR\]|\[VF\]|\[VO\]|\b\d{3,4}p\b|✗|🔒|✓")
_THEME_DOT_PAT = re.compile(r"^\[([#\w]+)\]●\[/\] ")


def _kbd(label: str) -> Text:
    """A key hint as a theme-coloured rounded pill.

    Nerd-Font terminals get real rounded ends (E0B6 + E0B4) with the label
    on an accent background ; other terminals get ‹label› in accent — no
    tofu boxes, readable on dark AND light themes.
    """
    acc = color("accent")
    try:
        from .tracker import tracker as _trk
        nerd = (_trk.get_icon_style() or "").lower() == "nerd"
    except Exception:
        nerd = False
    out = Text()
    if nerd:
        # U+E0B6 left half circle + U+E0B4 right half circle (verified in
        # CaskaydiaCove Nerd Font ; E0B7 is ALSO a left half circle).
        out.append("\ue0b6", style=acc)
        out.append(f" {label} ", style=f"black on {acc}")
        out.append("\ue0b4", style=acc)
    else:
        out.append(f"‹{label}›", style=f"bold {acc}")
    return out


def _hl_match(text: str, q: str, base: str = "") -> Text:
    """Render `text` with the type-to-filter query `q` highlighted (bold
    accent, first case-insensitive match) so the user sees WHY a row matched.
    Badge colours are preserved around the highlight."""
    out = Text()
    if not q:
        out.append_text(_styled_option(text, base=base))
        return out
    i = text.lower().find(q.lower())
    if i < 0:
        out.append_text(_styled_option(text, base=base))
        return out
    out.append_text(_styled_option(text[:i], base=base))
    out.append(text[i:i + len(q)], style=f"bold {color('accent')}")
    out.append_text(_styled_option(text[i + len(q):], base=base))
    return out


def _scrollbar(pos: int, total: int, width: int = 5) -> Text:
    """Tiny viewport-position bar (▰▱) for long lists."""
    if total <= 1:
        return Text("▰" * width, style=color("dim"))
    n = min(width, max(1, round((pos + 1) / total * width)))
    t = Text()
    t.append("▰" * n, style=color("accent"))
    t.append("▱" * (width - n), style=color("dim"))
    return t


def _styled_option(text: str, base: str = "") -> Text:
    """Render a menu label with coloured badges.

    * ``[VF]``/``[VOSTFR]``/``[VO]``/``[VFQ]`` → themed language colours
    * ``1080p``/``720p``… → bold accent
    * ``✗`` → error, ``🔒`` → warning, ``✓`` → success
    * a leading ``[colour]●[/] `` (theme list) → a dot in that colour

    Everything else keeps ``base``. ``.plain`` is always ``text``.
    """
    out = Text()
    pos = 0
    m = _THEME_DOT_PAT.match(text)
    if m:
        out.append("● ", style=m.group(1))
        pos = m.end()
    base_style = base or None
    for mo in _OPT_TOKEN_PAT.finditer(text, pos):
        if mo.start() > pos:
            out.append(text[pos:mo.start()], style=base_style)
        tok = mo.group(0)
        if tok.startswith("["):
            out.append(tok, style=f"bold {color(_LANG_BADGE_ROLES.get(tok[1:-1], 'info'))}")
        elif tok == "✗":
            out.append(tok, style=f"bold {color('error')}")
        elif tok == "🔒":
            out.append(tok, style=color("warning"))
        elif tok == "✓":
            out.append(tok, style=f"bold {color('success')}")
        else:  # 480p / 720p / 1080p / 2160p : resolution colour scale
            try:
                _h = int(tok.rstrip("p"))
            except ValueError:
                _h = 0
            _role = ("dim" if _h <= 480 else "success" if _h <= 720
                     else "warning" if _h <= 1080 else "accent")
            out.append(tok, style=f"bold {color(_role)}")
        pos = mo.end()
    if pos < len(text):
        out.append(text[pos:], style=base_style)
    return out


_LEAVE_WORDS = {
    "back", "retour", "cancel", "annuler", "quit", "quitter",
    "exit", "sortir",
}


def _looks_like_leave(label: str, index: int, total: int) -> bool:
    """True when the chosen row is this menu's Back/Cancel/Exit entry.

    Restricted to the LAST row (every menu appends its leave option there) and
    matched on a small multilingual set, so media titles containing "Back" /
    "Exit" never trigger a screen wipe, while translated labels ("Retour",
    "Annuler", "Quitter") without the "←" arrow still do."""
    plain = re.sub(r"\[/?[^\]]*\]", "", str(label)).strip()
    if plain.startswith("←"):
        return True
    if index != total - 1:
        return False
    return plain.lstrip("←❌✗⚠!?· ").strip().lower() in _LEAVE_WORDS


def select_from_list(options: list[str], prompt: str, default_index: int = 0,
                     header: str = None, group_headers: dict = None,
                     top=None, flush_input: bool = False,
                     esc_selects_last: bool = True,
                     clear_on_back: bool = True,
                     inline: bool = False) -> int:
    """
    Display an interactive menu where users can navigate with arrow keys.

    Args:
        options: List of options to display
        prompt: Header text for the menu
        default_index: Index to select by default
        header: Optional banner text. When set, the decorative header panel is
            rendered INSIDE the Live region (above the menu) instead of being
            printed statically beforehand — so it reflows with the menu on
            every terminal resize and never wraps/stacks in the scrollback.
        group_headers: Optional ``{item_index: "Section title"}`` map. A dim
            section header line is drawn ABOVE the item at that index, so the
            list reads as grouped sections (e.g. Anime / Manga, then Films &
            Series). Headers are purely visual — navigation and the returned
            index still refer to the real items.
        clear_on_back: Wipe the screen when a Back/Cancel/Exit row is chosen
            (default). Set False for a sub-menu that returns to its parent
            inside the same detail view (seasons → languages → episodes), so
            the poster and context stay on screen until the series is left.

    Returns:
        Index of the selected option (0-based)
    """
    selected_index = max(0, min(default_index, len(options) - 1))
    start_index = 0
    show_help = {"on": False}
    flt = {"on": False, "q": ""}   # '/' type-to-filter
    mouse_on = _mouse_available()
    mouse_rows = []   # absolute row tag, rebuilt with every render
    mouse_page = {"n": 5}
    mouse_top = [1]   # first screen row occupied by the menu

    def _view():
        """Original indices currently shown (all, or the '/' filter matches)."""
        if flt["on"] and flt["q"]:
            q = flt["q"].lower()
            return [i for i, o in enumerate(options) if q in str(o).lower()]
        return list(range(len(options)))

    def _fit(text: str) -> str:
        """Truncate an option to the terminal width (in DISPLAY columns, so
        wide emoji are counted as 2) so it never wraps and breaks the Live
        render — leaving room for the selection-bar prefix."""
        max_w = max(8, console.size.width - 8)
        if cell_len(text) <= max_w:
            return text
        out = ""
        for ch in text:
            if cell_len(out + ch) > max_w - 1:
                break
            out += ch
        return out + "…"

    def generate_renderable():
        nonlocal start_index

        # '?' help overlay replaces the menu until any key is pressed.
        mouse_rows.clear()
        if show_help["on"]:
            return _help_overlay()

        view = _view()  # original indices currently shown (filter-aware)
        grouped = bool(group_headers) and not flt["on"]
        fq = flt["q"] if flt["on"] else ""  # highlight the filter match

        # Calculate dynamic window size based on terminal height
        term_height = console.size.height
        reserved_lines = 9 + (3 if header else 0) + (1 if flt["on"] else 0)
        if top is not None and not flt["on"]:
            reserved_lines += 9  # dashboard panel above the menu
        if grouped:
            reserved_lines += 2 * len(group_headers)
        available_height = max(3, term_height - reserved_lines)
        window_size = min(max(1, len(view)), available_height)
        mouse_page["n"] = window_size

        # Adjust start_index to keep selected_index (a VIEW position) visible
        if selected_index < start_index:
            start_index = selected_index
        elif selected_index >= start_index + window_size:
            start_index = selected_index - window_size + 1
        start_index = max(0, min(start_index, max(0, len(view) - window_size)))
        end_index = min(len(view), start_index + window_size)

        lines = []

        def add(line, tag=None, height=None):
            """Append a rendered line and remember its row for mouse hits.

            ``height=1`` is passed for pre-fitted rows so a hover repaint does
            not invoke Rich's renderer for each row.
            """
            lines.append(line)
            h = (height if height is not None
                 else (_renderable_height(line) if mouse_on else 1))
            mouse_rows.extend([tag] + [None] * (h - 1))

        # Optional dashboard/renderable above everything (e.g. the home screen).
        if top is not None and not flt["on"]:
            add(top)
        if header:
            add(_header_panel(header))
        if _crumbs:
            add(_crumb_line(console.size.width), ("crumb",))
        add(Text(f"\n❯ {iconify(prompt)}", style=f"bold {color('accent')}"))
        # Active filter line.
        if flt["on"]:
            add(Text(f"  / {flt['q']}▏", style=f"bold {color('info')}"),
                height=1)

        if not view:
            from .i18n import t as _t
            empty = Text()
            empty.append("\n     ")
            empty.append(icon("search"), style=color("dim"))
            empty.append(f"  {_t('No match — try another search')}", style=color("dim"))
            add(empty)

        if start_index > 0:
            add(Text(f"  ↑ … {start_index + 1}/{len(view)}",
                     style=color("dim")), ("page", "up"), height=1)

        for pos in range(start_index, end_index):
            idx = view[pos]
            if grouped and idx in group_headers:
                if pos != start_index:
                    add(Text(""), height=1)
                add(Text(f"  {group_headers[idx]}",
                         style=f"bold {color('info')}"), height=1)
            option = _fit(iconify(options[idx]))
            if pos == selected_index:
                # Soft, high-end cursor: chevron + accent rail + bold accent
                # text — no harsh full-width reverse. The prefix is 4 cells
                # ("❯ ▌ ") so the label lines up with the 4-space unselected
                # rows below. Badges keep their own colours on the cursor row.
                # The chevron breathes (slow bright pulse) so the menu feels
                # alive even when idle.
                bright = _pulse()
                row = Text()
                row.append("❯ ", style=f"bold {color('accent')}"
                           if bright else color("accent"))
                row.append("▌ ", style=color("accent")
                           if bright else color("dim"))
                row.append_text(_hl_match(option, fq,
                                          base=f"bold {color('accent')}"))
                add(row, ("item", pos), height=1)
            else:
                # Watched rows (✓ badge) render dim so the eye lands on what's
                # left to watch ; the cursor row always stays bright. Badges
                # keep their own colours either way.
                base = color("dim") if "✓" in option else ""
                un = Text("    ")
                un.append_text(_hl_match(option, fq, base=base))
                add(un, ("item", pos), height=1)

        if end_index < len(view):
            add(Text(f"  ↓ … {end_index}/{len(view)}",
                     style=color("dim")), ("page", "down"), height=1)

        # Status bar : consistent bottom hints on every menu.
        add(Text(""), height=1)
        status = _status_bar(filtering=flt["on"])
        add(status, ("status", status.plain), height=1)

        if mouse_on and not use_screen:
            # Inline menu: it starts where the cursor was. If the frame is
            # taller than the remaining screen, Rich scrolls, so clamp the
            # anchor to where the first row actually landed.
            anchor = min(mouse_top[0],
                         max(1, console.size.height - len(mouse_rows) + 1))
            mouse_top[0] = max(1, anchor)
        return Group(*lines)

    # Full-screen menus (those carrying a banner) render in the ALTERNATE
    # screen buffer (screen=True). Inline menus keep the transient in-place
    # render. With the mouse active, an inline menu needs a DSR cursor-row
    # anchor so clicks still map correctly; `inline=True` is used for the
    # planning action menu so the series poster printed above stays visible.
    if mouse_on and inline:
        flush_input_settled()
        anchor = _cursor_row()
        if anchor is None:
            inline = False
        else:
            mouse_top[0] = anchor
    use_screen = bool(header) or (mouse_on and not inline)
    # get_renderable=... : re-evaluate the frame on every auto-refresh so the
    # breathing cursor, the toast rail and the status line actually update
    # while the menu sits idle (previously the same frozen renderable was
    # repainted, so a toast posted by a background job only appeared after a
    # keypress). Refresh stays modest to keep big lists cheap.
    live_kwargs = (
        dict(console=console, refresh_per_second=8, screen=True,
             get_renderable=generate_renderable)
        if use_screen
        else dict(refresh_per_second=6, transient=True,
                  get_renderable=generate_renderable)
    )
    result = None  # ORIGINAL index chosen
    # Purge stale input at EVERY menu entry (not just Home): keystrokes typed
    # during a spinner/network wait or terminal focus events must never leak
    # into the fresh menu as a phantom Esc/Enter.
    flush_input_settled()
    if flush_input:
        # Kept for compat — already covered by the settled flush above.
        drain_stdin()
    with mouse_tracking():
        with Live(generate_renderable(), **live_kwargs) as live:
            while result is None:
                key = _read_menu_key()
                view = _view()
                n = max(1, len(view))

                # Help overlay open → any key/click closes it. Pure mouse
                # motion must NOT close it (the pointer always moves).
                if show_help["on"]:
                    if key == readchar.key.CTRL_C:
                        raise KeyboardInterrupt("Menu cancelled by user")
                    if isinstance(key, MouseEvent) and key.motion:
                        continue
                    show_help["on"] = False
                    live.refresh()
                    continue

                # Mouse: hover moves the cursor, wheel scrolls, right-click
                # goes back, left-click activates the row under the pointer.
                if isinstance(key, MouseEvent):
                    if key.motion:
                        rel = key.y - mouse_top[0]
                        tag = (mouse_rows[rel]
                               if 0 <= rel < len(mouse_rows) else None)
                        if tag and tag[0] == "item" and tag[1] != selected_index:
                            selected_index = tag[1]
                            live.refresh()
                        continue
                    if key.wheel:
                        step = -1 if key.wheel == "up" else 1
                        selected_index = (selected_index + step) % n
                    elif key.is_right:
                        if flt["on"]:
                            flt["on"] = False
                            flt["q"] = ""
                            selected_index = 0
                        elif esc_selects_last:
                            result = len(options) - 1
                    elif key.is_left:
                        rel = key.y - mouse_top[0]
                        tag = (mouse_rows[rel]
                               if 0 <= rel < len(mouse_rows) else None)
                        if tag and tag[0] == "item":
                            selected_index = tag[1]
                            if view:
                                result = view[selected_index]
                        elif tag and tag[0] == "page":
                            step = max(1, mouse_page["n"] - 1)
                            if tag[1] == "up":
                                selected_index = max(0, selected_index - step)
                            else:
                                selected_index = min(n - 1, selected_index + step)
                        elif tag and tag[0] == "crumb":
                            # The breadcrumb is a mouse Back button: one click
                            # goes up exactly like Esc.
                            if esc_selects_last:
                                result = len(options) - 1
                        elif tag and tag[0] == "status":
                            act = _status_mouse_action(key.x, tag[1])
                            if act == "help":
                                show_help["on"] = True
                            elif act == "filter":
                                flt["on"] = True
                                flt["q"] = ""
                                selected_index = 0
                            elif act == "clear":
                                flt["on"] = False
                                flt["q"] = ""
                                selected_index = 0
                            elif act == "select":
                                if view:
                                    result = view[selected_index]
                            elif act == "back":
                                if esc_selects_last:
                                    result = len(options) - 1
                    live.refresh()
                    continue

                # '/' type-to-filter mode.
                if flt["on"]:
                    if key == readchar.key.ESC:
                        flt["on"] = False
                        flt["q"] = ""
                        selected_index = 0
                    elif key == readchar.key.ENTER:
                        if view:
                            result = view[selected_index]
                    elif key == readchar.key.UP:
                        selected_index = (selected_index - 1) % n
                    elif key == readchar.key.DOWN:
                        selected_index = (selected_index + 1) % n
                    elif key == readchar.key.BACKSPACE:
                        flt["q"] = flt["q"][:-1]
                        selected_index = 0
                    elif key == readchar.key.CTRL_C:
                        raise KeyboardInterrupt("Menu cancelled by user")
                    elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                        flt["q"] += key
                        selected_index = 0
                    live.refresh()
                    continue

                # Normal mode.
                if key == "?":
                    show_help["on"] = True
                elif key == "/":
                    flt["on"] = True
                    flt["q"] = ""
                    selected_index = 0
                elif key == readchar.key.UP:
                    selected_index = (selected_index - 1) % n
                elif key == readchar.key.DOWN:
                    selected_index = (selected_index + 1) % n
                elif key == readchar.key.ENTER:
                    if view:
                        result = view[selected_index]
                elif key == readchar.key.ESC:
                    # Esc = go back : select the LAST option (the Back / Cancel /
                    # Exit entry every menu appends), which callers treat as "go up".
                    if esc_selects_last:
                        result = len(options) - 1
                elif key == readchar.key.CTRL_C:
                    raise KeyboardInterrupt("Menu cancelled by user")
                live.refresh()

    label = str(options[result])
    # A Back/Cancel/Exit selection means we are leaving this level: wipe the
    # screen so the previous level starts clean instead of stacking the old
    # menus, posters and confirmations in the scrollback. Detection is
    # multilingual, restricted to the LAST row (Back/Cancel/Exit are always the
    # final option), and falls back to the leading "←" — so a film literally
    # named "Back to the Future" no longer wipes the screen when picked, and a
    # translated "Annuler"/"Retour" without the arrow still does.
    leaving = _looks_like_leave(label, result, len(options))
    if leaving and clear_on_back:
        clear_screen()
    # Internal Back (clear_on_back=False) returns silently to the parent menu:
    # printing "❯ prompt ← Retour" would leave a stray line above the poster.
    if not leaving or clear_on_back:
        console.print(
            f"\n[bold {color('accent')}]❯ {iconify(prompt)}[/bold {color('accent')}] "
            f"[{color('success')}]{iconify(options[result])}[/{color('success')}]"
        )
    return result


def select_multiple(options, prompt, preselected=None, disabled=None):
    """
    Checkbox multi-select. ↑/↓ move · Space toggle · 'a' toggle all · Enter
    confirm · Esc cancel.

    `preselected` : iterable of indices checked initially (default: all enabled).
    `disabled`    : iterable of indices shown but NOT toggleable (e.g. already
                    downloaded) — never part of the result.

    Returns the sorted list of checked indices, or None if cancelled (Esc).
    """
    n = len(options)
    if n == 0:
        return []
    disabled = set(disabled or ())
    if preselected is None:
        checked = {i for i in range(n) if i not in disabled}
    else:
        checked = {i for i in preselected if i not in disabled}

    cursor = next((i for i in range(n) if i not in disabled), 0)
    page = 12

    flush_input_settled()

    from .i18n import t as _t

    mouse_on = _mouse_available()
    mouse_rows = []

    def _buttons_action(x, plain):
        for token, action in (
            (_t("a: all"), "all"),
            (_t("Enter: confirm"), "confirm"),
            (_t("Esc: back"), "cancel"),
        ):
            i = plain.find(token)
            if i >= 0 and i - 2 <= (x - 1) < i + len(token):
                return action
        return None

    def render():
        lines = []
        mouse_rows.clear()

        def add(line, tag=None):
            lines.append(line)
            h = _renderable_height(line) if mouse_on else 1
            mouse_rows.extend([tag] + [None] * (h - 1))

        add(Text(prompt, style=f"bold {color('accent')}"))
        add(Text(""))
        start = max(0, min(cursor - page // 2, max(0, n - page)))
        end = min(n, start + page)
        if start > 0:
            add(Text("  ↑ ...", style=color("dim")))
        for i in range(start, end):
            box = "[x]" if i in checked else "[ ]"
            if i in disabled:
                box = "[✓]"
            row = f"{box} {options[i]}"
            if i == cursor:
                cur = Text("❯ ", style=f"bold {color('accent')} reverse")
                cur.append_text(_styled_option(row, base=f"bold {color('accent')} reverse"))
                add(cur, ("item", i))
            elif i in disabled:
                dis = Text("  ")
                dis.append_text(_styled_option(row, base=color("dim")))
                add(dis, ("item", i))
            else:
                ena = Text("  ")
                ena.append_text(_styled_option(row, base="white"))
                add(ena, ("item", i))
        if end < n:
            add(Text("  ↓ ...", style=color("dim")))
        add(Text(""))
        add(Text(f"  {len(checked)} {_t('selected')}", style=color("info")))
        # Bottom hint / mouse buttons — highlight Space, which toggles.
        hint = Text.assemble(
            Text("  ↑/↓ · ", style=f"bold {color('accent')}"),
            _kbd(_t("Space: select")), Text(" · ", style=f"bold {color('accent')}"),
            _kbd(_t("a: all")), Text(" · ", style=f"bold {color('accent')}"),
            _kbd(_t("Enter: confirm")), Text(" · ", style=f"bold {color('accent')}"),
            _kbd(_t("Esc: back")),
        )
        add(hint, ("buttons", hint.plain))
        return Group(*lines)

    use_screen = bool(mouse_on)
    with mouse_tracking():
        with Live(render(), refresh_per_second=20,
                  screen=use_screen, transient=not use_screen) as live:
            while True:
                key = _read_menu_key()
                if isinstance(key, MouseEvent):
                    if key.motion:
                        rel = key.y - 1
                        tag = (mouse_rows[rel]
                               if 0 <= rel < len(mouse_rows) else None)
                        if tag and tag[0] == "item" and tag[1] != cursor:
                            cursor = tag[1]
                            live.update(render(), refresh=True)
                        continue
                    if key.wheel:
                        step = -1 if key.wheel == "up" else 1
                        cursor = (cursor + step) % n
                    elif key.is_right:
                        return None
                    elif key.is_left:
                        rel = key.y - 1
                        tag = (mouse_rows[rel]
                               if 0 <= rel < len(mouse_rows) else None)
                        if tag and tag[0] == "item":
                            cursor = tag[1]
                            if cursor not in disabled:
                                checked.discard(cursor) if cursor in checked else checked.add(cursor)
                        elif tag and tag[0] == "buttons":
                            act = _buttons_action(key.x, tag[1])
                            if act == "all":
                                enabled = {i for i in range(n) if i not in disabled}
                                checked = set() if checked >= enabled else set(enabled)
                            elif act == "confirm":
                                break
                            elif act == "cancel":
                                return None
                    live.update(render(), refresh=True)
                    continue
                if key == readchar.key.UP:
                    cursor = (cursor - 1) % n
                elif key == readchar.key.DOWN:
                    cursor = (cursor + 1) % n
                elif key == " ":
                    if cursor not in disabled:
                        checked.discard(cursor) if cursor in checked else checked.add(cursor)
                elif key in ("a", "A"):
                    enabled = {i for i in range(n) if i not in disabled}
                    checked = set() if checked >= enabled else set(enabled)
                elif key == readchar.key.ENTER:
                    break
                elif key == readchar.key.ESC:
                    return None
                elif key == readchar.key.CTRL_C:
                    raise KeyboardInterrupt("Menu cancelled by user")
                live.update(render(), refresh=True)

    return sorted(checked)


def _fit_w(text: str, max_w: int) -> str:
    """Truncate `text` to max_w DISPLAY columns with an ellipsis."""
    if max_w <= 1:
        return ""
    if cell_len(text) <= max_w:
        return text
    out = ""
    for ch in text:
        if cell_len(out + ch) > max_w - 1:
            break
        out += ch
    return out + "…"


def make_preview(cover="", title="", lines=None, panel_title=""):
    """Build one preview-pane entry for select_with_preview.

    Keeps every source consistent : a cover URL, a title, a list of info lines
    (empty ones are dropped), and the panel's header label. Use this so all
    providers feed the preview the exact same shape.
    """
    return {
        "cover": cover or "",
        "title": title or "",
        "lines": [ln for ln in (lines or []) if ln],
        "panel_title": panel_title or "",
    }


def select_with_preview(labels, prompt, previews, default_index=0):
    """
    Interactive list with a LIVE preview pane on the right (poster + info).
    Pure rich + chafa, 100% terminal. Optimised for fluidity :
      * posters render in BACKGROUND threads (cached) — navigation never
        blocks ; a ⏳ placeholder shows until a poster is ready ;
      * a non-blocking refresh loop (Unix raw mode) keeps it real-time :
        terminal resize reflows instantly and posters appear as they finish.
    Keys : ↑/↓ navigate · type to filter · Backspace · Enter select · Esc back.
    Returns the selected index into `labels`, or len(labels) for Back.
    """
    from . import terminal_image
    from .i18n import t as _t
    from concurrent.futures import ThreadPoolExecutor
    from rich.align import Align
    from rich.spinner import Spinner
    import time as _time

    n = len(labels)
    if n == 0:
        return 0
    # Full-screen preview needs a real terminal. Otherwise fall back to the
    # plain list — guarantees no ghost boxes / artifacts on dumb terminals.
    if not console.is_terminal:
        return select_from_list(labels, prompt)

    selected = max(0, min(default_index, n - 1))
    start = 0
    query = ""
    visible = list(range(n))
    back_sel = [False]   # keyboard/mouse cursor on the clickable Back row
    mouse_rows = []      # left-column row tags, refreshed by render()
    mouse_grid = {"left_w": 0, "grid_h": 0}

    # TWO pools, because the work has opposite needs :
    #  * downloads are I/O-bound and release the GIL → high concurrency is a
    #    free win (covers land on disk fast) ;
    #  * chafa + Text.from_ansi is CPU-bound and HOLDS the GIL → too many at
    #    once starve the UI thread and make navigation feel frozen.
    # So we download wide (6) and render narrow (2). Downloads are deduped per
    # URL ; renders per (url, cols, rows).
    # chafa runs as a SEPARATE process (subprocess releases the GIL while it
    # works), so more render workers just means posters appear sooner — the old
    # 2-worker cap was over-cautious. Downloads stay wide-open.
    dl_pool = ThreadPoolExecutor(max_workers=6)
    # 2 render workers : 4 concurrent max-quality chafa processes thrashed
    # the CPU during big searches and starved the input loop (arrow keys felt
    # stuck). Previews are small — 2 workers keep up without jank.
    rndr_pool = ThreadPoolExecutor(max_workers=2)
    # key -> last submit time. Time-based (not a plain set) so a render/download
    # that FAILED (transient host throttle) is retried after a short cooldown
    # instead of being blocked forever ("sometimes the poster never shows").
    submitted = {}
    dl_submitted = {}
    _RETRY_AFTER = 6.0

    def _submit(cover, cols, rows):
        import time as _time
        now = _time.time()
        key = (cover, cols, rows)
        if not cover:
            return
        # Already rendered successfully? never re-submit.
        if terminal_image.get_cached_text(cover, cols, rows) is not None:
            return
        if now - submitted.get(key, 0) < _RETRY_AFTER:
            return
        submitted[key] = now
        # Warm the download cache wide-open so the render workers almost always
        # find the image already on disk (render then skips the slow download).
        if now - dl_submitted.get(cover, 0) >= _RETRY_AFTER:
            dl_submitted[cover] = now
            dl_pool.submit(terminal_image.prefetch, cover)
        rndr_pool.submit(terminal_image.render_to_text, cover, cols, rows)

    def _prefetch_cover(cover):
        """Download `cover` in the background so the SHARP sixel overlay can be
        painted straight to the terminal once the image is on disk (the paint
        itself runs chafa positioned — no capture — for native resolution)."""
        import time as _time
        now = _time.time()
        if not cover or terminal_image.get_download_path(cover) is not None:
            return
        if now - dl_submitted.get(cover, 0) < _RETRY_AFTER:
            return
        dl_submitted[cover] = now
        dl_pool.submit(terminal_image.prefetch, cover)

    def _poster_text(cover, cols, rows):
        """Cached poster Text if ready, else None (queueing a render). Never
        blocks — the actual chafa work happens in the background pool."""
        if not cover or not terminal_image.chafa_available():
            return None
        cached = terminal_image.get_cached_text(cover, cols, rows)
        if cached is not None:
            return cached
        _submit(cover, cols, rows)
        return None

    def _poster_block(cover, p_cols, p_rows):
        """Preview poster, horizontally centered. Shows the rendered cover once
        ready, an animated spinner while it loads, or a placeholder glyph if no
        cover exists. The panel has a FIXED height + vertical centering, so the
        box never jumps whatever the poster's real height turns out to be."""
        txt = _poster_text(cover, p_cols, p_rows)
        if txt is not None:
            txt.no_wrap = True       # crop, never wrap → can't spill the frame
            txt.overflow = "crop"
            return Align.center(txt)
        if cover and terminal_image.chafa_available():
            return Align.center(Spinner("dots", style=color("accent")))
        return Align.center(Text(icon("poster"), style=color("dim")))

    def _dims():
        """Layout dimensions that ALWAYS fit the current terminal.

        The two columns (list + preview) are derived from the available width
        so their sum + padding never exceeds the screen. Hard minimums used to
        sum wider than narrow terminals, which pushed the preview panel off
        screen and made the poster overflow its frame mid-resize."""
        w = console.size.width
        h = max(8, console.size.height - 1)
        pad = 3  # grid inter-column padding + a small safety margin
        avail = max(12, w - pad)
        left_w = max(12, min(46, int(avail * 0.45)))
        right_w = max(8, avail - left_w)
        p_cols = max(6, right_w - 2)   # inside the panel borders
        p_rows = max(6, h - 8)
        return h, left_w, right_w, p_cols, p_rows

    # Remember the poster size we last warmed ALL covers at, so a terminal
    # resize re-renders every result's poster in the background (not just the
    # one currently on screen) — navigating after a resize hits the cache.
    warmed_size = [None]
    # Debounce that full re-warm during a resize DRAG : the visible poster keeps
    # tracking the new size every frame, but we only re-render ALL covers once
    # the size has settled (~180 ms), so a fast drag doesn't queue hundreds of
    # immediately-stale renders and choke the pool.
    pending_size = [None]
    pending_at = [0.0]

    def _prewarm(p_cols=None, p_rows=None):
        """Render ALL posters in the background (parallel) at the given size so
        navigation hits the cache instead of waiting per item. Submissions are
        deduped per (cover, cols, rows), so calling this repeatedly is cheap."""
        if not terminal_image.chafa_available():
            return
        if p_cols is None or p_rows is None:
            _, _, _, p_cols, p_rows = _dims()
        warmed_size[0] = (p_cols, p_rows)
        # Prioritise what the user is actually looking at : submit the selected
        # poster first, then fan out to its neighbours, then the rest. So the
        # visible cover (and the next/prev ones) render before far-off items.
        cur = visible[selected] if visible else 0
        order = sorted(range(len(previews)), key=lambda i: abs(i - cur))
        for i in order:
            _submit(previews[i].get("cover", ""), p_cols, p_rows)

    def _apply_filter():
        nonlocal visible, selected, start
        q = query.lower()
        visible = [i for i in range(n) if q in labels[i].lower()] if q else list(range(n))
        selected = 0
        start = 0

    def _list_lines(vis, sel, s, end, lw, on_back=False):
        """Build the left column and its mouse row map (top row = 1)."""
        head = f"/{query}" if query else iconify(prompt)
        # Counter + viewport bar so long lists show where you are.
        counter = Text.assemble(
            Text(f"  [{sel + 1}/{len(vis)}] " if vis else "", style=color("dim")),
            _scrollbar(sel, len(vis)) if vis else Text(""),
        )
        lines = []
        tags = []

        def add(line, tag=None, height=1):
            lines.append(line)
            tags.extend([tag] + [None] * (height - 1))

        # The head Text starts with a newline → exactly two rows. Every item
        # is pre-fitted to the column width by _fit_w, so one row each. This
        # avoids calling Rich's renderer for every hover repaint (the old
        # per-line measurement was the main source of mouse lag).
        add(Text(f"\n {head}", style=f"bold {color('accent')}"), height=2)
        add(counter, ("scroll", counter.plain))
        if s > 0:
            add(Text("  ↑ …", style=color("dim")), ("page", "up"))
        for pos in range(s, end):
            i = vis[pos]
            lab = _fit_w(iconify(labels[i]), lw - 5)
            if pos == sel:
                pad = max(1, lw - cell_len(f"  ▌ {lab}") - 1)
                srow = Text("  ▌ ", style=f"bold {color('accent')} reverse")
                srow.append_text(_styled_option(lab, base=f"bold {color('accent')} reverse"))
                srow.append(" " * pad, style=f"bold {color('accent')} reverse")
                add(srow, ("item", pos))
            else:
                urow = Text("    ")
                urow.append_text(_styled_option(lab, base="white"))
                add(urow, ("item", pos))
        if end < len(vis):
            add(Text("  ↓ …", style=color("dim")), ("page", "down"))
        if not vis:
            add(Text(f"    ({_t('no match')})", style=color("dim")))
        # Always-visible mouse target: clicking it is exactly Esc/Back.
        back = Text("  ")
        if on_back:
            back.append("▌ ", style=f"bold {color('accent')} reverse")
            back.append(f"{icon('back')} {_t('Back')}",
                        style=f"bold {color('accent')} reverse")
        else:
            back.append(icon("back"), style=color("dim"))
            back.append(f" {_t('Back')}", style=color("dim"))
        add(back, ("back",))
        return lines, tags

    # ── Live SIXEL overlay (photo-sharp preview) ─────────────────────────
    # When the terminal has sixel actually ON, the right-column poster is drawn
    # as REAL PIXELS painted over a reserved blank region after each Live frame
    # (see _paint_sixel), instead of Unicode blocks. Offsets are tunable so the
    # image can be nudged into the panel precisely (calibration).
    # Calibratable at runtime (no rebuild): nudge the poster into the panel with
    #   FREEFLIX_SIXEL_ROW=<n>  FREEFLIX_SIXEL_COL_PAD=<n>
    def _envint(name, default):
        try:
            return int(os.environ.get(name, default))
        except (TypeError, ValueError):
            return default
    _OV_ROW = _envint("FREEFLIX_SIXEL_ROW", 2)       # 1-based row of poster top
    _OV_COL_PAD = _envint("FREEFLIX_SIXEL_COL_PAD", 3)  # cols after the list → left edge
    overlay = [False]
    ov_region = {}
    painted = [None]   # last (cover, cols, rows) actually painted as sixel

    def render():
        nonlocal start
        h, left_w, right_w, p_cols, p_rows = _dims()
        # Reserve the last visible row for the clickable Back target.
        win = max(3, h - 5)
        vis = visible
        sel = selected if vis else -1
        s = start
        if sel < s:
            s = sel
        elif sel >= s + win:
            s = sel - win + 1
        s = max(0, min(s, max(0, len(vis) - win)))
        start = s
        end = min(len(vis), s + win)

        # Too narrow for a side-by-side preview → gracefully collapse to a
        # full-width list (no panel) instead of cramming/overflowing.
        show_preview = console.size.width >= 34 and right_w >= 14
        lw = left_w if show_preview else max(10, console.size.width - 2)
        left_lines, left_tags = _list_lines(vis, sel, s, end, lw,
                                             on_back=back_sel[0])
        left = Group(*left_lines)

        hint = Text(_t("↑/↓ navigate · type to filter · Enter · Esc"),
                    style=color("dim"), justify="center")
        # The hint itself is clickable (Enter = open, Esc = back).
        grid_h = max(len(left_tags), (win + 2) if show_preview else 0)
        mouse_rows[:] = left_tags + [None] * (grid_h - len(left_tags))
        mouse_rows.append(("hint", hint.plain))
        mouse_grid.update(left_w=left_w, grid_h=grid_h)

        if not show_preview:
            return Group(left, hint)

        # Resize handling : the visible poster tracks the new size immediately
        # (via _poster_block below), while the full background re-warm of every
        # cover is debounced until the size settles.
        if warmed_size[0] != (p_cols, p_rows):
            now = _time.monotonic()
            if pending_size[0] != (p_cols, p_rows):
                pending_size[0] = (p_cols, p_rows)
                pending_at[0] = now
            elif now - pending_at[0] >= 0.18:
                _prewarm(p_cols, p_rows)

        pv = previews[vis[sel]] if vis else {}
        cover = pv.get("cover", "")

        if overlay[0]:
            # Reserve a blank block the poster's height; the sixel is painted
            # OVER it after the frame. Record where to paint (top-left cell).
            _prefetch_cover(cover)
            ov_region.clear()
            ov_region.update({
                "cover": cover, "cols": p_cols, "rows": p_rows,
                "row": _OV_ROW, "col": left_w + _OV_COL_PAD,
            })
            ready = terminal_image.get_download_path(cover) is not None
            if cover and not ready:
                poster_widget = Align.center(Spinner("dots", style=color("accent")))
                # pad below the spinner so the title sits where the poster ends
                body = [poster_widget, Text("\n" * max(0, p_rows - 1))]
            else:
                body = [Text("\n" * max(0, p_rows - 1))]  # blank canvas for pixels
        else:
            body = [_poster_block(cover, p_cols, p_rows)]

        if pv.get("title"):
            body.append(Text(f"\n{pv['title']}", style=f"bold {color('header')}",
                             justify="center"))
        for ln in pv.get("lines", []):
            if ln:
                body.append(Text(ln, style=color("dim"), justify="center"))

        # Overlay keeps the poster at the TOP (deterministic row) ; blocks stay
        # vertically centered as before.
        right = Panel(
            Align.center(Group(*body), vertical="top" if overlay[0] else "middle"),
            border_style=color("border"),
            title=pv.get("panel_title", ""),
            height=win + 2,
            padding=(0, 1),
            expand=True,
        )

        grid = Table.grid(padding=(0, 1), expand=True)
        grid.add_column(width=left_w)
        grid.add_column(ratio=1)
        grid.add_row(left, right)
        return Group(grid, hint)

    def _scroll_jump(x, plain):
        """Click/drag the ▰▱ track: jump to that position in the list."""
        i = plain.find("▰")
        if i < 0:
            i = plain.find("▱")
        if i < 0:
            return None
        bar = plain[i:i + 5]
        if not (i <= (x - 1) < i + len(bar)):
            return None
        if not visible:
            return None
        frac = (x - 1 - i) / max(1, len(bar) - 1)
        return min(len(visible) - 1, max(0, round(frac * (len(visible) - 1))))

    def _hint_action(x, plain):
        for token, action in ((_t("Enter"), "select"), (_t("Esc"), "back")):
            i = plain.find(token)
            if i >= 0 and i - 2 <= (x - 1) < i + len(token):
                return action
        return None

    def _handle(key):
        nonlocal selected, query
        if isinstance(key, MouseEvent):
            if key.motion:
                rel = key.y - 1
                tag = (mouse_rows[rel]
                       if 0 <= rel < len(mouse_rows) else None)
                if tag and tag[0] == "scroll" and key.button == 0:
                    pos = _scroll_jump(key.x, tag[1])
                    if pos is not None and pos != selected:
                        selected = pos
                        back_sel[0] = False
                        return ("hover", None)
                if tag and tag[0] == "item" and visible:
                    if tag[1] != selected or back_sel[0]:
                        selected = tag[1]
                        back_sel[0] = False
                        return ("hover", None)
                    return None
                if tag and tag[0] == "back":
                    if not back_sel[0]:
                        back_sel[0] = True
                        return ("hover", None)
                    return None
                return None
            if key.wheel and visible:
                step = -1 if key.wheel == "up" else 1
                selected = (selected + step) % len(visible)
            elif key.is_right:
                return ("back", None)
            elif key.is_left:
                rel = key.y - 1
                tag = (mouse_rows[rel]
                       if 0 <= rel < len(mouse_rows) else None)
                if tag and tag[0] == "item" and visible:
                    return ("select", visible[tag[1]])
                if tag and tag[0] == "back":
                    return ("back", None)
                if tag and tag[0] == "scroll":
                    pos = _scroll_jump(key.x, tag[1])
                    if pos is not None and visible:
                        selected = pos
                        return ("hover", None)
                if tag and tag[0] == "page" and visible:
                    step = max(1, console.size.height - 8)
                    if tag[1] == "up":
                        selected = max(0, selected - step)
                    else:
                        selected = min(len(visible) - 1, selected + step)
                    back_sel[0] = False
                    return ("hover", None)
                if tag and tag[0] == "hint":
                    act = _hint_action(key.x, tag[1])
                    if act == "select" and visible:
                        return ("select", visible[selected])
                    if act == "back":
                        return ("back", None)
                # Clicking the poster/info pane opens the selected title too.
                if (not tag and visible and key.x > mouse_grid["left_w"]
                        and 1 <= key.y <= mouse_grid["grid_h"]):
                    return ("select", visible[selected])
            return None
        if key == "UP" and visible:
            if back_sel[0]:
                back_sel[0] = False
                selected = len(visible) - 1
            else:
                selected = (selected - 1) % len(visible)
        elif key == "DOWN" and visible:
            if not back_sel[0] and selected >= len(visible) - 1:
                back_sel[0] = True
            elif not back_sel[0]:
                selected += 1
        elif key == "ENTER":
            if back_sel[0]:
                return ("back", None)
            if visible:
                return ("select", visible[selected])
        elif key == "ESC":
            return ("back", None)
        elif key == "BACKSPACE":
            query = query[:-1]
            _apply_filter()
        elif key and len(key) == 1 and key.isprintable():
            query += key
            _apply_filter()
        return None

    def _finish(idx):
        console.print(
            f"\n[bold {color('accent')}] {iconify(prompt)}[/] "
            f"[{color('success')}]{iconify(labels[idx])}[/]"
        )
        return idx

    def _decode_key(data):
        nonlocal carry
        if not data:
            return None
        if data.startswith(b"\x1b[<"):
            hits = list(_MOUSE_RE_B.finditer(data))
            if not hits:
                return "IGN"       # incomplete mouse report
            ev = _mouse_from_match(hits[-1])
            carry = data[hits[-1].end():]
            return ev
        if data[:1] == b"\x1b":
            if len(data) == 1:
                return "ESC"  # a true, standalone Escape press
            if data[:2] == b"\x1b\x1b":
                # Fast double-Esc in one read : replay the second press.
                _stash_esc_carry()
                carry = data[2:]
                return "ESC"
            if data[1:2] in (b"[", b"O"):
                if len(data) < 3:
                    return "IGN"
                key = {b"A": "UP", b"B": "DOWN", b"C": "RIGHT",
                       b"D": "LEFT"}.get(data[2:3], "IGN")
                carry = data[3:]
                return key
            return "IGN"  # unknown escape sequence (focus event...) - ignore
        b0 = data[:1]
        if b0 in (b"\r", b"\n"):
            carry = data[1:]
            return "ENTER"
        if b0 in (b"\x7f", b"\x08"):
            carry = data[1:]
            return "BACKSPACE"
        if b0 == b"\x03":
            carry = data[1:]
            return "CTRLC"
        try:
            ch = data.decode("utf-8", "ignore")
            if not ch:
                return None
            # Keep the rest of a fast multi-key read for the next iteration.
            carry = data[len(ch[0].encode("utf-8")):]
            return ch[0]
        except Exception:
            return None

    def _is_loading():
        """True while periodic repaints are still needed : a resize re-warm is
        pending, or the poster currently on screen hasn't finished rendering
        (its spinner must keep ticking / be swapped for the image). When this is
        False the loop goes idle — navigation stays instant, CPU drops to ~0."""
        if not terminal_image.chafa_available():
            return False
        _, _, _, pc, pr = _dims()
        if warmed_size[0] != (pc, pr):
            return True
        if not visible:
            return False
        cover = previews[visible[selected]].get("cover", "")
        if not cover:
            return False
        if overlay[0]:
            return terminal_image.get_download_path(cover) is None
        return terminal_image.get_cached_text(cover, pc, pr) is None

    def _paint_sixel():
        """Paint the selected cover as SHARP sixel over the reserved region
        (called right after each Live frame). chafa writes straight to the
        terminal at the region's cell so it renders at native resolution; cursor
        is saved/restored. No-op until the image is downloaded. Best-effort."""
        if not overlay[0] or not ov_region:
            return False
        cover = ov_region.get("cover")
        if not cover:
            return False
        return terminal_image.render_sixel_positioned(
            cover, ov_region["cols"], ov_region["rows"],
            ov_region["row"], ov_region["col"], sys.stdout.fileno())

    _prewarm()  # start downloading/rendering every poster in the background

    import sys
    import os as _os

    use_raw = False
    try:
        import termios  # noqa: F401
        import tty  # noqa: F401
        import select as _sel  # noqa: F401
        use_raw = sys.stdin.isatty()
    except Exception:
        use_raw = False

    # Enable the photo-sharp SIXEL overlay when: we drive the raw POSIX loop
    # (so we control exactly when frames repaint), chafa is present, posters
    # aren't forced to blocks/off, and the terminal actually has sixel ON
    # (confirmed via DA1 — never paints garbage on a sixel-off terminal). This
    # is the DEFAULT for everyone (poster mode defaults to "auto"), including
    # existing users after an update — no setting to flip.
    try:
        from .tracker import tracker as _tracker
        _pmode = (_tracker.get_poster_mode() or "auto").lower()
        overlay[0] = (
            use_raw
            and terminal_image.chafa_available()
            and _pmode in ("auto", "sixel")
            and terminal_image.detect_image_protocol() == "sixel"
        )
    except Exception:
        overlay[0] = False

    chosen = {"idx": None}

    # Same purge as the other menus: background poster work runs while this
    # screen opens, so any key typed during the search must not leak in.
    flush_input_settled()

    mouse_gate = mouse_tracking()
    mouse_gate.__enter__()

    try:
        if use_raw:
            import termios
            import tty
            import select as _sel
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                last_size = (console.size.width, console.size.height)
                # auto_refresh OFF : rich would otherwise re-tokenize the poster
                # ~20x/s forever (~30% CPU) and fight the UI thread. Instead we
                # repaint ONLY on a key, a resize, or while something is loading.
                with Live(render(), console=console, screen=True,
                          auto_refresh=False) as live:
                    live.refresh()
                    _paint_sixel()   # first paint (once the sixel is ready)
                    import time as _ltime
                    last_anim_tick = [0.0]
                    carry = b""
                    while chosen["idx"] is None:
                        anim = _is_loading()
                        if carry:
                            data, carry = carry, b""
                            r = True
                        else:
                            r, _, _ = _sel.select([fd], [], [], 0.06 if anim else 0.25)
                            data = b""
                        dirty = False
                        if r:
                            if not data:
                                data = _os.read(fd, 16)
                            # A split escape/mouse report must be completed
                            # before decoding. Otherwise its tail becomes
                            # printable text in the search filter.
                            if _escape_incomplete(data):
                                deadline = _ltime.monotonic() + 0.20
                                while _escape_incomplete(data):
                                    left = deadline - _ltime.monotonic()
                                    if left <= 0:
                                        break
                                    r2, _, _ = _sel.select([fd], [], [], left)
                                    if not r2:
                                        break
                                    data += _os.read(fd, 64)
                                if _escape_incomplete(data) and data != b"\x1b":
                                    data = b""
                            pasted = False
                            if data.startswith(_PASTE_START):
                                # Bracketed paste (middle-click of terminal
                                # output) : swallow the whole blob and type
                                # its text into the filter instead of leaking
                                # bare \x1b bytes that each look like Esc.
                                _buf = data
                                while True:
                                    _tx, _ = _split_paste(_buf)
                                    if _tx is not None:
                                        break
                                    if len(_buf) >= _PASTE_MAX:
                                        _buf = b""
                                        break
                                    _r2, _, _ = _sel.select([fd], [], [], 0.20)
                                    if not _r2:
                                        break
                                    _buf += _os.read(fd, 64)
                                _tx, _ = _split_paste(_buf)
                                if _tx is not None:
                                    for _c in _tx.decode("utf-8", "ignore"):
                                        if _c.isprintable():
                                            query += _c
                                    _apply_filter()
                                    pasted = True
                                dirty = True
                            elif data.startswith(b"\x1b]"):
                                # Terminal reply (OSC color query, title…) :
                                # swallow to its terminator so fragments never
                                # read as Esc. Rest (often empty) decoded below.
                                _buf = data
                                while True:
                                    _done, _rest = _split_reply(_buf)
                                    if _done:
                                        _buf = _rest
                                        break
                                    if len(_buf) >= _PASTE_MAX:
                                        _buf = b""
                                        break
                                    _r2, _, _ = _sel.select([fd], [], [], 0.20)
                                    if not _r2:
                                        _buf = b""
                                        break
                                    _buf += _os.read(fd, 64)
                                data = _buf
                                dirty = True
                            if not pasted:
                                key = _decode_key(data) if data else None
                                if key == "CTRLC":
                                    raise KeyboardInterrupt("cancelled")
                                res = _handle(key) if key else None
                                if res:
                                    act, idx = res
                                    if act == "hover":
                                        dirty = True
                                    else:
                                        chosen["idx"] = n if act == "back" else idx
                                        dirty = True
                                else:
                                    # Pure hover over a non-selectable area must
                                    # not force a full frame repaint.
                                    dirty = not (isinstance(key, MouseEvent)
                                                 and key.motion)
                        cur = (console.size.width, console.size.height)
                        if cur != last_size:
                            last_size = cur
                            dirty = True
                        # Repaint policy (input stays snappy while loading) :
                        # a key/resize repaints IMMEDIATELY ; background
                        # loading only ticks the spinner at 4 fps. Repainting
                        # the full frame + a synchronous chafa sixel on every
                        # 60 ms iteration starved the input loop (arrows felt
                        # stuck, users over-pressed and jumped rows).
                        if dirty or anim:
                            now = _ltime.monotonic()
                            tick_due = (
                                anim and not dirty
                                and now - last_anim_tick[0] >= 0.25
                            )
                            if dirty or tick_due:
                                if tick_due:
                                    last_anim_tick[0] = now
                                live.update(render(), refresh=True)
                                # Rich just repainted the (blank) region → paint
                                # the real pixels back over it, but ONLY when
                                # the target changed (same cover/size/position
                                # needs no new chafa process). Only mark it
                                # painted when a real image was written (else
                                # the ready-transition below still fires once
                                # the sixel finishes).
                                if overlay[0] and ov_region:
                                    skey = (
                                        ov_region.get("cover"),
                                        ov_region.get("cols"),
                                        ov_region.get("rows"),
                                        ov_region.get("row"),
                                        ov_region.get("col"),
                                    )
                                    if painted[0] != skey and _paint_sixel():
                                        painted[0] = skey
                                else:
                                    # Block preview: note whether the image was
                                    # actually in THIS frame. If chafa is still
                                    # running, `painted` stays stale so the
                                    # ready-transition below repaints it without
                                    # waiting for a keypress.
                                    _, _, _, pc, pr = _dims()
                                    cc = (previews[visible[selected]].get("cover", "")
                                          if visible else "")
                                    if (cc and terminal_image.get_cached_text(
                                            cc, pc, pr) is not None):
                                        painted[0] = (cc, pc, pr)
                        elif visible:
                            # No key/resize/loading tick, but the selected
                            # poster may have JUST finished rendering (chafa is
                            # slow): swap spinner → image / paint the sixel
                            # immediately instead of waiting for a keypress.
                            cc = previews[visible[selected]].get("cover", "")
                            _, _, _, pc, pr = _dims()
                            if overlay[0] and ov_region:
                                k = (cc, pc, pr, ov_region.get("row"),
                                     ov_region.get("col"))
                                if (cc and painted[0] != k
                                        and terminal_image.get_download_path(cc) is not None):
                                    live.update(render(), refresh=True)
                                    _paint_sixel()
                                    painted[0] = k
                            elif cc:
                                k = (cc, pc, pr)
                                if (painted[0] != k
                                        and terminal_image.get_cached_text(cc, pc, pr)
                                        is not None):
                                    live.update(render(), refresh=True)
                                    painted[0] = k
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        else:
            mp = {readchar.key.UP: "UP", readchar.key.DOWN: "DOWN",
                  readchar.key.ENTER: "ENTER", readchar.key.ESC: "ESC",
                  readchar.key.BACKSPACE: "BACKSPACE"}
            # get_renderable=render so the background chafa render swaps the
            # spinner for the image on its own (same fix as the POSIX loop):
            # previously the frozen frame meant Windows users also had to press
            # a key to see a slow poster.
            with Live(console=console, refresh_per_second=4, screen=True,
                      get_renderable=render) as live:
                while chosen["idx"] is None:
                    raw = _read_menu_key()   # robust on Windows (drains focus events)
                    if raw == readchar.key.CTRL_C:
                        raise KeyboardInterrupt("cancelled")
                    if raw == "":
                        continue             # ignored focus/mouse event
                    res = _handle(mp.get(raw, raw))
                    if res:
                        act, idx = res
                        if act != "hover":
                            chosen["idx"] = n if act == "back" else idx
                    if not (isinstance(raw, MouseEvent) and raw.motion and not res):
                        live.update(render())
    finally:
        mouse_gate.__exit__(None, None, None)
        dl_pool.shutdown(wait=False)
        rndr_pool.shutdown(wait=False)

    idx = chosen["idx"]
    if idx is None or idx == n:
        clear_screen()  # leaving this level → previous level starts clean
        return n
    return _finish(idx)



def spinner(message: str):
    """
    Animated spinner shown while a slow operation (scraping, resolving a
    stream…) runs. Use as a context manager :

        with spinner("Searching…"):
            results = scraper.search(query)

    Only wrap pure work — don't prompt or start another Live inside it.
    """
    return console.status(
        f"[{color('info')}]{iconify(message)}[/{color('info')}]", spinner="dots"
    )


@contextmanager
def skeleton(label: str, lines: int = 4):
    """Shimmering placeholder bars while LIST content loads (search results,
    latest additions…). Same ``with`` contract as :func:`spinner` — swap it
    in wherever a list is being fetched so the wait itself looks alive :

        with skeleton(f"{t('Searching for')} {query}…"):
            results = scraper.search(query)

    A bright band sweeps each bar (staggered per row) on a background
    thread ; the whole block is transient and vanishes when done.
    Only wrap pure work — don't prompt or start another Live inside it.
    """
    live = None
    if console.is_terminal:
        try:
            live = Live(Text(""), console=console, refresh_per_second=12,
                        transient=True)
            live.start()
        except Exception:
            live = None
    stop = threading.Event()
    state = {"tick": 0}

    def _loop():
        widths = [0.92, 0.78, 0.85, 0.64, 0.71][:max(1, min(5, lines))]
        while not stop.is_set():
            state["tick"] += 1
            try:
                bw = max(24, min(56, console.size.width - 24))
                body = Text(iconify(label), style=color("dim"))
                for r, f in enumerate(widths):
                    n = max(8, int(bw * f))
                    pos = (state["tick"] * 3 + r * 7) % (n + 14) - 7
                    row = Text("\n  ")
                    for i in range(n):
                        d = abs(i - pos)
                        row.append(
                            "━",
                            style="bold bright_white" if d <= 3
                            else "white" if d <= 6 else color("dim"))
                    body.append_text(row)
                live.update(body)
            except Exception:
                pass
            time.sleep(0.08)

    thread = None
    if live is not None:
        thread = threading.Thread(target=_loop, daemon=True)
        thread.start()
    try:
        yield
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=0.5)
        if live is not None:
            try:
                live.stop()
            except Exception:
                pass


def _header_panel(text: str) -> Panel:
    """Build the decorative header panel (shared so the static print and the
    in-Live header stay pixel-identical and reflow the same way)."""
    from rich import box as _box
    return Panel(
        Text(iconify(text), style=color("header"), justify="center"),
        style=color("accent"),
        border_style=color("border"),
        box=_box.ROUNDED,
        padding=(0, 2),
    )


def print_header(text: str):
    """
    Print a styled header with a decorative panel.

    Args:
        text: Header text to display
    """
    console.print()
    console.print(_header_panel(text))


_suppress_print = threading.local()


def _badge(role: str, glyph: str) -> str:
    """A fixed-width coloured status pill (` ✓ `) so every message line starts
    with the same 3-cell badge — clean, aligned columns down the screen."""
    return f"[reverse bold {color(role)}] {glyph} [/]"


def print_success(message: str):
    """Print a success message with a checkmark."""
    if getattr(_suppress_print, "active", False):
        return
    console.print(f"{_badge('success', '✓')} {iconify(message)}")


def print_error(message: str):
    """Print an error message with an X."""
    if getattr(_suppress_print, "active", False):
        return
    console.print(f"{_badge('error', '✗')} {iconify(message)}")


def print_info(message: str):
    """Print an info message."""
    if getattr(_suppress_print, "active", False):
        return
    console.print(f"{_badge('info', 'ℹ')} {iconify(message)}")


def print_warning(message: str):
    """Print a warning message."""
    if getattr(_suppress_print, "active", False):
        return
    console.print(f"{_badge('warning', '⚠')} {iconify(message)}")


def clean_title(title: str) -> str:
    """
    Remove season and part indicators from a title to help with search.
    Example: "One Piece Season 4" -> "One Piece"
    """
    # Remove Season X, S2, Part 2, etc. (case insensitive)
    # Common patterns: Season 1, S1, Part 1, Cour 1, etc.
    patterns = [
        r"\s+Season\s+\d+",
        r"\s+S\d+",
        r"\s+Part\s+\d+",
        r"\s+Cour\s+\d+",
        r"\s+\d+(st|nd|rd|th)\s+Season",
        r"\s+-\s+\d+",  # Sometimes title - 2
    ]

    cleaned = title
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()
