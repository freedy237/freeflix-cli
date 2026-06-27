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
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def get_user_input(prompt: str, default: str = None, header: str = None) -> str:
    """
    Get user input with a styled prompt.

    Args:
        prompt: The prompt text to display
        default: The default value to display
        header: Optional banner. When set on a real terminal, the prompt is
            shown FULL-SCREEN with the header panel rendered inside a Live
            (alternate-screen) region and the text typed in raw mode — so a
            terminal resize reflows everything instantly with no wrapped/
            stacked header left behind. Falls back to the plain prompt
            otherwise.

    Returns:
        The user's input as a string
    """
    if header and console.is_terminal:
        try:
            return _input_fullscreen(prompt, default, header)
        except Exception:
            pass  # any raw-mode issue -> plain prompt below

    styled_prompt = Text(f"\n❯ {iconify(prompt)}: ", style=f"bold {color('accent')}")
    console.print(styled_prompt, end="")
    return input().strip() or default


def _input_fullscreen(prompt: str, default: str, header: str) -> str:
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

    text = ""
    result = {"val": None}

    def render():
        body = [
            _header_panel(header),
            Text(f"\n ❯ {iconify(prompt)}", style=f"bold {color('accent')}"),
            Text(f"\n   {text}▏", style="white"),
        ]
        if default and not text:
            body.append(Text(f"\n   ({iconify('default')}: {default})",
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
                live.update(render())
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    return result["val"].strip() or default


def pause():
    """Wait for user input before continuing."""
    console.input(f"\n[{color('dim')}]Press Enter to continue...[/{color('dim')}]")


def select_from_list(options: list[str], prompt: str, default_index: int = 0,
                     header: str = None, group_headers: dict = None) -> int:
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

        # Calculate dynamic window size based on terminal height
        term_height = console.size.height
        # Reserve lines for prompt (2), header/spacing (2), arrows (2) -> ~6 lines reserve.
        # The in-Live header panel eats 3 more rows when present ; each section
        # header line eats ~2 more.
        reserved_lines = 6 + (3 if header else 0)
        if group_headers:
            reserved_lines += 2 * len(group_headers)
        available_height = max(3, term_height - reserved_lines)
        window_size = min(len(options), available_height)

        # Adjust start_index to keep selected_index in view
        if selected_index < start_index:
            start_index = selected_index
        elif selected_index >= start_index + window_size:
            start_index = selected_index - window_size + 1

        # Ensure start_index is valid
        start_index = max(0, min(start_index, len(options) - window_size))
        end_index = min(len(options), start_index + window_size)

        lines = []
        # Header panel lives INSIDE the Live region so it reflows with the menu
        # on resize (no static full-width panel left to wrap/stack above).
        if header:
            lines.append(_header_panel(header))
        lines.append(Text(f"\n❯ {iconify(prompt)}", style=f"bold {color('accent')}"))

        # Up arrow indicator
        if start_index > 0:
            lines.append(Text("  ↑ ...", style=color("dim")))

        bar_width = max(20, console.size.width)
        for idx in range(start_index, end_index):
            # Section header above this item (grouped menus).
            if group_headers and idx in group_headers:
                if idx != start_index:
                    lines.append(Text(""))  # spacer between sections
                lines.append(Text(f"  {group_headers[idx]}",
                                  style=f"bold {color('info')}"))
            option = _fit(iconify(options[idx]))
            if idx == selected_index:
                # Full-width selection bar : reverse video follows the theme
                # accent. Pad with cell_len (handles wide emoji) so the bar
                # spans the row without wrapping.
                label = f"  ▌  {option}"
                pad = max(1, bar_width - cell_len(label) - 1)
                lines.append(
                    Text(label + " " * pad, style=f"bold {color('accent')} reverse")
                )
            else:
                lines.append(Text(f"     {option}", style="white"))

        # Down arrow indicator
        if end_index < len(options):
            lines.append(Text("  ↓ ...", style=color("dim")))

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
    with Live(generate_renderable(), **live_kwargs) as live:
        while True:
            key = readchar.readkey()

            if key == readchar.key.UP:
                selected_index = (selected_index - 1) % len(options)
                live.update(generate_renderable())
            elif key == readchar.key.DOWN:
                selected_index = (selected_index + 1) % len(options)
                live.update(generate_renderable())
            elif key == readchar.key.ENTER:
                break
            elif key == readchar.key.ESC:
                # Esc = go back / cancel, anywhere in FreeFlix. Every menu in the
                # app appends its Back / Cancel / Exit entry LAST, and callers
                # treat the last index (idx >= len(real_items)) as "go back" — so
                # selecting the last option reliably steps up one level.
                selected_index = len(options) - 1
                break
            elif key == readchar.key.CTRL_C:
                raise KeyboardInterrupt("Menu cancelled by user")

    console.print(
        f"\n[bold {color('accent')}]❯ {iconify(prompt)}[/bold {color('accent')}] "
        f"[{color('success')}]{iconify(options[selected_index])}[/{color('success')}]"
    )
    return selected_index


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
            key = readchar.readkey()
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
    dl_pool = ThreadPoolExecutor(max_workers=6)
    rndr_pool = ThreadPoolExecutor(max_workers=2)
    submitted = set()
    dl_submitted = set()

    def _submit(cover, cols, rows):
        key = (cover, cols, rows)
        if not cover or key in submitted:
            return
        submitted.add(key)
        # Warm the download cache wide-open so the render workers almost always
        # find the image already on disk (render then skips the slow download).
        if cover not in dl_submitted:
            dl_submitted.add(cover)
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
        import termios, tty, select as _sel  # noqa: F401
        use_raw = sys.stdin.isatty()
    except Exception:
        use_raw = False

    chosen = {"idx": None}

    try:
        if use_raw:
            import termios, tty, select as _sel
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
                    raw = readchar.readkey()
                    if raw == readchar.key.CTRL_C:
                        raise KeyboardInterrupt("cancelled")
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
