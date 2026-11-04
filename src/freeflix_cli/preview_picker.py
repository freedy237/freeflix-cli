"""Preview-pane list picker (poster + metadata beside the menu).

Extracted from cli_utils.py: the widget is ~800 lines of its own, with a
dedicated render thread pool and a raw-mode key loop. cli_utils re-exports
``select_with_preview`` lazily so existing imports keep working.
"""

from __future__ import annotations

import os

import readchar
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .icons import icon, iconify
from .themes import color
from .cli_utils import (
    MouseEvent,
    _fit_w,
    _mouse_set,
    _read_menu_key,
    _scrollbar,
    _styled_option,
    clear_screen,
    console,
    flush_input_settled,
    mouse_tracking,
    select_from_list,
)

__all__ = ["select_with_preview"]


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
        """Warm the posters around the cursor, not the whole result list.

        Rendering 50+ covers through chafa in the background (even with only
        2 workers) competed with the input loop and made the first seconds of
        a long list sluggish. We now DOWNLOAD every cover (cheap, I/O-bound)
        but RENDER only the selected one ±7; a distant row is rendered on
        demand when the cursor reaches it.
        """
        if not terminal_image.chafa_available():
            return
        if p_cols is None or p_rows is None:
            _, _, _, p_cols, p_rows = _dims()
        warmed_size[0] = (p_cols, p_rows)
        # Prioritise what the user is actually looking at: render the visible
        # poster and its closest neighbours first; only download the rest.
        cur = visible[selected] if visible else 0
        order = sorted(range(len(previews)), key=lambda i: abs(i - cur))
        for rank, i in enumerate(order):
            cover = previews[i].get("cover", "")
            if rank < 8:
                _submit(cover, p_cols, p_rows)
            else:
                _prefetch_cover(cover)

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
        add(Text(f"\n  {head}", style=f"bold {color('text')}"), height=2)
        add(counter, ("scroll", counter.plain))
        if s > 0:
            add(Text("  ↑ …", style=color("dim")), ("page", "up"))
        for pos in range(s, end):
            i = vis[pos]
            lab = _fit_w(iconify(labels[i]), lw - 5)
            if pos == sel:
                srow = Text("  ▌ ", style=f"bold {color('accent')}")
                srow.append_text(_styled_option(lab, base=f"bold {color('text')}"))
                add(srow, ("item", pos))
            else:
                urow = Text("    ")
                urow.append_text(_styled_option(lab, base=color("text")))
                add(urow, ("item", pos))
        if end < len(vis):
            add(Text("  ↓ …", style=color("dim")), ("page", "down"))
        if not vis:
            add(Text(f"    ({_t('no match')})", style=color("dim")))
        # Always-visible mouse target: clicking it is exactly Esc/Back.
        back = Text("  ")
        if on_back:
            back.append("▌ ", style=f"bold {color('accent')}")
            back.append(f"{icon('back')} {_t('Back')}",
                        style=f"bold {color('text')}")
        else:
            back.append(icon("back"), style=color("muted"))
            back.append(f" {_t('Back')}", style=color("muted"))
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
            body.append(Text(f"\n{pv['title']}", style=f"bold {color('text')}",
                             justify="center"))
        for ln in pv.get("lines", []):
            if ln:
                body.append(Text(ln, style=color("muted"), justify="center"))

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
        if isinstance(key, MouseEvent) and query:
            # While a query is typed, mouse motion is noise (and a split
            # report can end up in the filter): keyboard-only, like the
            # select_from_list filter.
            return None
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
            if not query:
                _mouse_set(True)  # back to hover/click
        elif key and len(key) == 1 and key.isprintable():
            query += key
            _apply_filter()
            if query:
                _mouse_set(False)  # typing: stop the motion-report flood
        return None

    def _finish(idx):
        console.print(
            f"\n[bold {color('accent')}] {iconify(prompt)}[/] "
            f"[{color('success')}]{iconify(labels[idx])}[/]"
        )
        return idx

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
                    key_map = {
                        readchar.key.UP: "UP", readchar.key.DOWN: "DOWN",
                        readchar.key.ENTER: "ENTER", readchar.key.ESC: "ESC",
                        readchar.key.BACKSPACE: "BACKSPACE",
                    }
                    while chosen["idx"] is None:
                        anim = _is_loading()
                        key = _read_menu_key(timeout=0.06 if anim else 0.25)
                        dirty = False
                        if key == readchar.key.CTRL_C:
                            raise KeyboardInterrupt("cancelled")
                        if key not in (None, ""):
                            if key in key_map:
                                # Arrow/Enter/Esc/Backspace constants are
                                # 3-char strings too: map them BEFORE the
                                # paste/printable branch.
                                _act = key_map[key]
                            elif isinstance(key, str) and len(key) > 1:
                                # Bracketed paste, already decoded by the shared
                                # reader: type its text into the filter.
                                for _c in key:
                                    if _c.isprintable():
                                        query += _c
                                _apply_filter()
                                if query:
                                    _mouse_set(False)
                                dirty = True
                                _act = None
                            else:
                                _act = key
                            if _act is not None:
                                res = _handle(_act)
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
                                    dirty = not (
                                        isinstance(key, MouseEvent) and key.motion)
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

