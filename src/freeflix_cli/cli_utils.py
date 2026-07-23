import os
import readchar
import re
import threading
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.cells import cell_len
from rich.table import Table
from .themes import color
from .icons import iconify, icon

console = Console()


def clear_screen():
    """Clear the terminal screen.

    Uses Rich's console.clear() (an ANSI escape) instead of shelling out to
    `clear`/`cls` : no subprocess per clear, and it can't be hijacked by a
    `clear`/`cls` binary earlier on PATH.
    """
    console.clear()


def get_user_input(prompt: str, default: str = None, header: str = None,
                   history: list = None) -> str:
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
    if header and console.is_terminal:
        try:
            return _input_fullscreen(prompt, default, header, history)
        except Exception:
            pass  # any raw-mode issue -> plain prompt below

    styled_prompt = Text(f"\n❯ {iconify(prompt)}: ", style=f"bold {color('accent')}")
    console.print(styled_prompt, end="")
    return input().strip() or default


def _input_fullscreen(prompt: str, default: str, header: str,
                      history: list = None) -> str:
    """Full-screen, resize-safe single-line text prompt (Unix raw mode).

    Renders the header panel + prompt + live-typed text inside a screen=True
    Live, so resizing the window reflows the whole frame with no leftovers.
    Enter submits, Esc cancels (returns the default), Ctrl-C raises.
    """
    import sys

    import termios
    import tty
    import select as _sel

    if not sys.stdin.isatty():
        raise RuntimeError("not a tty")

    from .i18n import t as _t
    text = ""
    result = {"val": None}
    history = history or []
    hist_idx = {"i": -1}   # -1 = live text, 0.. = into history

    def render():
        body = [
            _header_panel(header),
            Text(f"\n ❯ {iconify(prompt)}", style=f"bold {color('accent')}"),
            Text(f"\n   {text}▏", style="white"),
        ]
        if default and not text:
            body.append(Text(f"\n   ({iconify('default')}: {default})",
                             style=color("dim")))
        if history:
            recent = "   ".join(f"↺ {h}" for h in history[:4])
            body.append(Text(f"\n\n   {_t('Recent searches')}",
                             style=f"bold {color('info')}"))
            body.append(Text(f"\n   {recent[:76]}", style=color("dim")))
            body.append(Text(f"\n   {_t('↑/↓ recall · type to search')}",
                             style=color("dim")))
        return Group(*body)

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        with Live(render(), console=console, refresh_per_second=20, screen=True) as live:
            while result["val"] is None:
                r, _, _ = _sel.select([fd], [], [], 0.08)
                if r:
                    data = os.read(fd, 16)
                    if data == b"\x1b":
                        r2, _, _ = _sel.select([fd], [], [], 0.05)
                        if r2:
                            data += os.read(fd, 16)
                    if data[:1] == b"\x1b":
                        if len(data) == 1:
                            result["val"] = ""  # lone Esc -> cancel
                        elif history and data[1:3] in (b"[A", b"OA"):  # Up
                            if hist_idx["i"] < len(history) - 1:
                                hist_idx["i"] += 1
                                text = history[hist_idx["i"]]
                        elif history and data[1:3] in (b"[B", b"OB"):  # Down
                            if hist_idx["i"] > 0:
                                hist_idx["i"] -= 1
                                text = history[hist_idx["i"]]
                            else:
                                hist_idx["i"] = -1
                                text = ""
                        # else: arrow/focus escape sequence -> ignore
                    else:
                        b0 = data[:1]
                        if b0 in (b"\r", b"\n"):
                            result["val"] = text
                        elif b0 in (b"\x7f", b"\x08"):
                            text = text[:-1]
                        elif b0 == b"\x03":
                            raise KeyboardInterrupt("cancelled")
                        else:
                            try:
                                ch = data.decode("utf-8", "ignore")
                            except Exception:
                                ch = ""
                            for c in ch:
                                if c.isprintable():
                                    text += c
                                    hist_idx["i"] = -1  # back to live editing
                live.update(render())
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    return result["val"].strip() or default


def pause():
    """Wait for user input before continuing."""
    console.input(f"\n[{color('dim')}]Press Enter to continue...[/{color('dim')}]")


def confirm_or_timeout(message: str, seconds: int = 6, default: bool = True) -> bool:
    """
    Show *message* with a live countdown and auto-return *default* when it
    elapses — used for auto-play-next / binge : the next episode starts on its
    own unless the user intervenes. Enter/Space/y = accept, Esc/n/q = decline.

    On a non-interactive terminal it returns *default* immediately (never
    blocks a script). Fully cross-platform (POSIX select + Windows msvcrt).
    """
    import sys
    import time as _time
    from .i18n import t as _t

    if not console.is_terminal or not sys.stdin.isatty():
        return default

    accent = color("accent")
    dim = color("dim")

    def _render(remaining):
        return Text.from_markup(
            f"  [bold {accent}]{iconify(message)}[/]   "
            f"[{dim}]{_t('Enter')}: {_t('yes')} · {_t('Esc')}: {_t('no')} · "
            f"{_t('auto in')} {remaining}s[/]"
        )

    end = _time.time() + seconds
    decided = None

    if os.name == "nt":
        import msvcrt
        with Live(_render(seconds), console=console, refresh_per_second=8,
                  transient=True) as live:
            while _time.time() < end and decided is None:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\r", "\n", " ", "y", "Y"):
                        decided = True
                    elif ch in ("\x1b", "n", "N", "q", "Q"):
                        decided = False
                else:
                    _time.sleep(0.05)
                live.update(_render(max(0, int(end - _time.time()) + 1)))
    else:
        import termios
        import tty
        import select as _sel
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            with Live(_render(seconds), console=console, refresh_per_second=8,
                      transient=True) as live:
                while _time.time() < end and decided is None:
                    r, _, _ = _sel.select([fd], [], [], 0.15)
                    if r:
                        ch = os.read(fd, 1)
                        if ch in (b"\r", b"\n", b" ", b"y", b"Y"):
                            decided = True
                        elif ch in (b"\x1b", b"n", b"N", b"q", b"Q"):
                            decided = False
                    live.update(_render(max(0, int(end - _time.time()) + 1)))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    return default if decided is None else decided


def disable_terminal_reports():
    """
    Turn OFF terminal focus-reporting / mouse tracking / bracketed paste.

    Some terminals (and mpv) enable focus reporting (``\\x1b[?1004h``): the
    terminal then sends ``\\x1b[I`` / ``\\x1b[O`` whenever the window gains/loses
    focus (e.g. Alt-Tab). If one of those bytes lands split across reads, a menu
    can mistake the leading ``\\x1b`` for a stray Esc — which looked like
    "FreeFlix closing by itself". Killing the reports at the source removes it.
    Called at startup and after every player exit (mpv may re-enable them).
    """
    try:
        import sys
        if sys.stdout.isatty():
            sys.stdout.write(
                "\x1b[?1004l"                                   # focus off
                "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l"  # mouse off
                "\x1b[?2004l"                                   # bracketed paste off
            )
            sys.stdout.flush()
    except Exception:
        pass


# ─── Breadcrumb trail (1.8) ────────────────────────────────────────────
# A tiny global stack rendered above every menu :
#   🏠 Home › Anime-Sama › Naruto › Season 2
# Handlers call crumb_reset()/crumb_push()/crumb_pop() at each level, so the
# user always knows where they are and what Esc will go back to.
_crumbs: list = []


def crumb_reset(*labels):
    """Replace the whole trail (e.g. entering a screen from Home)."""
    _crumbs[:] = [x for x in labels if x]


def crumb_push(label):
    if label:
        _crumbs.append(str(label))


def crumb_pop():
    if _crumbs:
        _crumbs.pop()


def crumbs_text() -> str:
    return " › ".join(_crumbs)


class crumb:
    """Scoped breadcrumb level : ``with crumb(series.title): …`` — the trail is
    restored on exit no matter how the block ends (break/return/exception)."""

    def __init__(self, label):
        self.label = label

    def __enter__(self):
        self._n = len(_crumbs)
        crumb_push(self.label)
        return self

    def __exit__(self, *exc):
        del _crumbs[self._n:]
        return False


def _crumb_line(max_w: int) -> Text:
    """The breadcrumb as a single dim line, truncated from the LEFT so the
    deepest (most useful) levels stay visible."""
    txt = crumbs_text()
    if cell_len(txt) > max_w - 4:
        while _crumbs and cell_len("… › " + txt) > max_w - 4:
            txt = txt.split(" › ", 1)[-1] if " › " in txt else txt[-(max_w - 8):]
            if " › " not in txt and cell_len("… › " + txt) <= max_w - 4:
                break
        txt = "… › " + txt
    return Text(f"  {txt}", style=color("dim"))


def _status_bar(filtering: bool = False) -> Text:
    """Bottom hint line shown under every menu (consistent across screens)."""
    from .i18n import t as _t
    if filtering:
        hint = f"  {_t('type to filter')} · {_t('Enter: select')} · {_t('Esc: clear')}"
    else:
        hint = (f"  ↑/↓ · {_t('Enter: select')} · {_t('Esc: back')} · "
                f"{_t('/: filter')} · {_t('?: help')}")
    return Text(hint, style=color("dim"))


def _help_overlay() -> Panel:
    """The '?' help overlay : every keyboard shortcut in one panel."""
    from .i18n import t as _t
    rows = [
        ("↑ / ↓",      _t("navigate")),
        ("Enter",      _t("select")),
        ("Esc",        _t("go back / cancel")),
        ("Space",      _t("toggle episode (multi-select)")),
        ("a",          _t("select all (multi-select)")),
        ("Esc Esc",    _t("cancel a running download")),
        ("Ctrl+C",     _t("quit FreeFlix")),
        ("? ",         _t("show / hide this help")),
    ]
    body = Text()
    body.append(f"\n  {_t('Keyboard shortcuts')}\n\n", style=f"bold {color('accent')}")
    for key_label, desc in rows:
        body.append(f"   {key_label:<9}", style=f"bold {color('info')}")
        body.append(f" {desc}\n", style="white")
    body.append(f"\n  {_t('In the player (mpv)')}\n\n", style=f"bold {color('accent')}")
    for key_label, desc in [
        ("CTRL+1/2", _t("Anime4K quality (max / light)")),
        ("CTRL+0",   _t("Anime4K off")),
        ("q",        _t("close the player")),
    ]:
        body.append(f"   {key_label:<9}", style=f"bold {color('info')}")
        body.append(f" {desc}\n", style="white")
    return Panel(body, border_style=color("accent"),
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
    text = Text(f"  {marks.get(kind, 'i')} {message}", style=f"bold {style}")
    if not console.is_terminal:
        console.print(text)
        return
    try:
        with Live(text, console=console, refresh_per_second=4, transient=True):
            _time.sleep(seconds)
    except Exception:
        console.print(text)


def _read_menu_key():
    """
    Read one keypress for the arrow menus, returning readchar key constants.

    Why not just ``readchar.readkey()``? On POSIX, readchar reads Esc (``\\x1b``)
    then BLOCKS on a 2nd byte to tell a lone Esc from an arrow sequence
    (``\\x1b[A``) — so a lone Esc never fires until another key is pressed (that's
    why "Esc did nothing" on Linux but worked on Windows). Here we peek with a
    50 ms timeout: no follow-up byte ⇒ a real Esc. Windows / non-tty fall back
    to readchar (where Esc already returns immediately).
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
            for _ in range(6):
                if msvcrt.kbhit():
                    seq += msvcrt.getwch()
                    if len(seq) >= 3:
                        break
                else:
                    _t.sleep(0.004)
            if seq == "\x1b":
                return readchar.key.ESC
            return {"\x1b[A": readchar.key.UP, "\x1bOA": readchar.key.UP,
                    "\x1b[B": readchar.key.DOWN, "\x1bOB": readchar.key.DOWN,
                    "\x1b[C": readchar.key.RIGHT, "\x1b[D": readchar.key.LEFT,
                    }.get(seq, "")          # focus/mouse/unknown → ignore
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
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = os.read(fd, 1)
        if ch == b"\x1b":
            # Drain the WHOLE escape sequence (arrows, but also focus events
            # \x1b[I / \x1b[O and mouse reports) before deciding. Only a truly
            # isolated \x1b — nothing follows within 50 ms — is a real Esc.
            seq = ch
            while True:
                r, _, _ = _sel.select([fd], [], [], 0.05)
                if not r:
                    break
                seq += os.read(fd, 8)
                if len(seq) >= 3:  # enough for a CSI/SS3 arrow
                    break
            if seq == b"\x1b":
                return readchar.key.ESC          # lone Esc → go back
            return {
                b"\x1b[A": readchar.key.UP,   b"\x1bOA": readchar.key.UP,
                b"\x1b[B": readchar.key.DOWN,  b"\x1bOB": readchar.key.DOWN,
                b"\x1b[C": readchar.key.RIGHT, b"\x1b[D": readchar.key.LEFT,
            }.get(seq, "")          # focus/mouse/unknown CSI → ignore
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
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def select_from_list(options: list[str], prompt: str, default_index: int = 0,
                     header: str = None, group_headers: dict = None,
                     top=None) -> int:
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

    Returns:
        Index of the selected option (0-based)
    """
    selected_index = max(0, min(default_index, len(options) - 1))
    start_index = 0
    show_help = {"on": False}
    flt = {"on": False, "q": ""}   # '/' type-to-filter

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
        if show_help["on"]:
            return _help_overlay()

        view = _view()  # original indices currently shown (filter-aware)
        grouped = bool(group_headers) and not flt["on"]

        # Calculate dynamic window size based on terminal height
        term_height = console.size.height
        reserved_lines = 9 + (3 if header else 0) + (1 if flt["on"] else 0)
        if top is not None and not flt["on"]:
            reserved_lines += 9  # dashboard panel above the menu
        if grouped:
            reserved_lines += 2 * len(group_headers)
        available_height = max(3, term_height - reserved_lines)
        window_size = min(max(1, len(view)), available_height)

        # Adjust start_index to keep selected_index (a VIEW position) visible
        if selected_index < start_index:
            start_index = selected_index
        elif selected_index >= start_index + window_size:
            start_index = selected_index - window_size + 1
        start_index = max(0, min(start_index, max(0, len(view) - window_size)))
        end_index = min(len(view), start_index + window_size)

        lines = []
        # Optional dashboard/renderable above everything (e.g. the home screen).
        if top is not None and not flt["on"]:
            lines.append(top)
        if header:
            lines.append(_header_panel(header))
        if _crumbs:
            lines.append(_crumb_line(console.size.width))
        lines.append(Text(f"\n❯ {iconify(prompt)}", style=f"bold {color('accent')}"))
        # Active filter line.
        if flt["on"]:
            lines.append(Text(f"  / {flt['q']}▏", style=f"bold {color('info')}"))

        if not view:
            lines.append(Text("     (no match)", style=color("dim")))

        if start_index > 0:
            lines.append(Text("  ↑ ...", style=color("dim")))

        bar_width = max(20, console.size.width)
        for pos in range(start_index, end_index):
            idx = view[pos]
            if grouped and idx in group_headers:
                if pos != start_index:
                    lines.append(Text(""))
                lines.append(Text(f"  {group_headers[idx]}",
                                  style=f"bold {color('info')}"))
            option = _fit(iconify(options[idx]))
            if pos == selected_index:
                label = f"  ▌  {option}"
                pad = max(1, bar_width - cell_len(label) - 1)
                lines.append(
                    Text(label + " " * pad, style=f"bold {color('accent')} reverse")
                )
            else:
                lines.append(Text(f"     {option}", style="white"))

        if end_index < len(view):
            lines.append(Text("  ↓ ...", style=color("dim")))

        # Status bar : consistent bottom hints on every menu.
        lines.append(Text(""))
        lines.append(_status_bar(filtering=flt["on"]))

        return Group(*lines)

    # Full-screen menus (those carrying a banner) render in the ALTERNATE
    # screen buffer (screen=True): the whole frame is repainted every refresh,
    # so a terminal resize leaves NO stacked/wrapped leftovers in the
    # scrollback. Inline menus (no header) keep the transient in-place render
    # so any context printed above them stays visible.
    use_screen = bool(header)
    live_kwargs = (
        dict(console=console, refresh_per_second=20, screen=True)
        if use_screen
        else dict(refresh_per_second=10, transient=True)
    )
    result = None  # ORIGINAL index chosen
    with Live(generate_renderable(), **live_kwargs) as live:
        while result is None:
            key = _read_menu_key()
            view = _view()
            n = max(1, len(view))

            # Help overlay open → any key closes it (arrows don't navigate).
            if show_help["on"]:
                if key == readchar.key.CTRL_C:
                    raise KeyboardInterrupt("Menu cancelled by user")
                show_help["on"] = False
                live.update(generate_renderable())
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
                live.update(generate_renderable())
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
                result = len(options) - 1
            elif key == readchar.key.CTRL_C:
                raise KeyboardInterrupt("Menu cancelled by user")
            live.update(generate_renderable())

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

    from .i18n import t as _t

    def render():
        lines = [Text(prompt, style=f"bold {color('accent')}"), Text("")]
        start = max(0, min(cursor - page // 2, max(0, n - page)))
        end = min(n, start + page)
        if start > 0:
            lines.append(Text("  ↑ ...", style=color("dim")))
        for i in range(start, end):
            box = "[x]" if i in checked else "[ ]"
            if i in disabled:
                box = "[✓]"
            row = f"{box} {options[i]}"
            if i == cursor:
                lines.append(Text(f"❯ {row}", style=f"bold {color('accent')} reverse"))
            elif i in disabled:
                lines.append(Text(f"  {row}", style=color("dim")))
            else:
                lines.append(Text(f"  {row}", style="white"))
        if end < n:
            lines.append(Text("  ↓ ...", style=color("dim")))
        lines.append(Text(""))
        lines.append(Text(f"  {len(checked)} {_t('selected')}", style=color("info")))
        # Bottom hint — highlight Space, which toggles the current line.
        lines.append(Text(
            f"  ↑/↓ · {_t('Space: select')} · {_t('a: all')} · "
            f"{_t('Enter: confirm')} · {_t('Esc: back')}",
            style=f"bold {color('accent')}"))
        return Group(*lines)

    with Live(render(), refresh_per_second=20, transient=True) as live:
        while True:
            key = _read_menu_key()
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
            live.update(render())

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
    rndr_pool = ThreadPoolExecutor(max_workers=4)
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

    def _list_lines(vis, sel, s, end, lw):
        """Build the scrollable result list (left column), truncated to `lw`."""
        head = f"/{query}" if query else iconify(prompt)
        counter = f"  [{sel + 1}/{len(vis)}]" if vis else ""
        lines = [Text(f"\n {head}{counter}\n", style=f"bold {color('accent')}")]
        if s > 0:
            lines.append(Text("  ↑ …", style=color("dim")))
        for pos in range(s, end):
            i = vis[pos]
            lab = _fit_w(iconify(labels[i]), lw - 5)
            if pos == sel:
                bar = f"  ▌ {lab}"
                pad = max(1, lw - cell_len(bar) - 1)
                lines.append(Text(bar + " " * pad, style=f"bold {color('accent')} reverse"))
            else:
                lines.append(Text(f"    {lab}", style="white"))
        if end < len(vis):
            lines.append(Text("  ↓ …", style=color("dim")))
        if not vis:
            lines.append(Text("    (no match)", style=color("dim")))
        return lines

    def render():
        nonlocal start
        h, left_w, right_w, p_cols, p_rows = _dims()
        win = max(3, h - 4)
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
        left = Group(*_list_lines(vis, sel, s, end, lw))

        hint = Text("↑/↓ naviguer · taper pour filtrer · Entrée · Échap",
                    style=color("dim"), justify="center")

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
        body = [_poster_block(pv.get("cover", ""), p_cols, p_rows)]
        if pv.get("title"):
            body.append(Text(f"\n{pv['title']}", style=f"bold {color('header')}",
                             justify="center"))
        for ln in pv.get("lines", []):
            if ln:
                body.append(Text(ln, style=color("dim"), justify="center"))

        right = Panel(
            Align.center(Group(*body), vertical="middle"),
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

    def _handle(key):
        nonlocal selected, query
        if key == "UP" and visible:
            selected = (selected - 1) % len(visible)
        elif key == "DOWN" and visible:
            selected = (selected + 1) % len(visible)
        elif key == "ENTER" and visible:
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
        if data[:1] == b"\x1b":
            if len(data) == 1:
                return "ESC"  # a true, standalone Escape press
            if data[1:2] in (b"[", b"O"):
                return {b"A": "UP", b"B": "DOWN", b"C": "RIGHT",
                        b"D": "LEFT"}.get(data[2:3], "IGN")
            return "IGN"  # unknown escape sequence (focus event...) - ignore
        b0 = data[:1]
        if b0 in (b"\r", b"\n"):
            return "ENTER"
        if b0 in (b"\x7f", b"\x08"):
            return "BACKSPACE"
        if b0 == b"\x03":
            return "CTRLC"
        try:
            ch = data.decode("utf-8", "ignore")
            return ch[0] if ch else None
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
        return bool(cover) and terminal_image.get_cached_text(cover, pc, pr) is None

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

    chosen = {"idx": None}

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
                    while chosen["idx"] is None:
                        anim = _is_loading()
                        r, _, _ = _sel.select([fd], [], [], 0.06 if anim else 0.25)
                        dirty = False
                        if r:
                            data = _os.read(fd, 16)
                            if data == b"\x1b":
                                # Lone ESC may be a split escape sequence
                                # (arrow / focus event) - wait briefly for more.
                                r2, _, _ = _sel.select([fd], [], [], 0.05)
                                if r2:
                                    data += _os.read(fd, 16)
                            key = _decode_key(data) if data else None
                            if key == "CTRLC":
                                raise KeyboardInterrupt("cancelled")
                            res = _handle(key) if key else None
                            if res:
                                act, idx = res
                                chosen["idx"] = n if act == "back" else idx
                            dirty = True
                        cur = (console.size.width, console.size.height)
                        if cur != last_size:
                            last_size = cur
                            dirty = True
                        if dirty or anim:
                            live.update(render(), refresh=True)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        else:
            mp = {readchar.key.UP: "UP", readchar.key.DOWN: "DOWN",
                  readchar.key.ENTER: "ENTER", readchar.key.ESC: "ESC",
                  readchar.key.BACKSPACE: "BACKSPACE"}
            with Live(render(), console=console, refresh_per_second=12, screen=True) as live:
                while chosen["idx"] is None:
                    raw = _read_menu_key()   # robust on Windows (drains focus events)
                    if raw == readchar.key.CTRL_C:
                        raise KeyboardInterrupt("cancelled")
                    if raw == "":
                        continue             # ignored focus/mouse event
                    res = _handle(mp.get(raw, raw))
                    if res:
                        act, idx = res
                        chosen["idx"] = n if act == "back" else idx
                    live.update(render())
    finally:
        dl_pool.shutdown(wait=False)
        rndr_pool.shutdown(wait=False)

    idx = chosen["idx"]
    if idx is None or idx == n:
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


def _header_panel(text: str) -> Panel:
    """Build the decorative header panel (shared so the static print and the
    in-Live header stay pixel-identical and reflow the same way)."""
    return Panel(
        Text(iconify(text), style=color("header"), justify="center"),
        style=color("accent"),
        border_style=color("border"),
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


def print_success(message: str):
    """Print a success message with a checkmark."""
    if getattr(_suppress_print, "active", False):
        return
    console.print(f"[{color('success')}]✓[/{color('success')}] {iconify(message)}")


def print_error(message: str):
    """Print an error message with an X."""
    if getattr(_suppress_print, "active", False):
        return
    console.print(f"[{color('error')}]✗[/{color('error')}] {iconify(message)}")


def print_info(message: str):
    """Print an info message."""
    if getattr(_suppress_print, "active", False):
        return
    console.print(f"[{color('info')}]ℹ[/{color('info')}] {iconify(message)}")


def print_warning(message: str):
    """Print a warning message."""
    if getattr(_suppress_print, "active", False):
        return
    console.print(f"[{color('warning')}]⚠[/{color('warning')}] {iconify(message)}")


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
