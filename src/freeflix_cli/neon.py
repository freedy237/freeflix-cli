"""Neon travelling-light panel (home dashboard).

A rounded box whose border carries a bright segment looping around the
perimeter forever — like a light running along the edges. The panel title
(``FreeFlix``) and subtitle (``anime · manga · movies · series``) light up
as the comet passes over them.

The menu already repaints through a Rich ``Live`` region several times per
second, so a time-driven renderable animates with zero threads : each
repaint just draws the comet at its current position.
"""

import time

from rich.cells import cell_len
from rich.segment import Segment


class NeonPanel:
    """Rounded expanding panel with a light looping around its border."""

    def __init__(self, renderable, *, title="", title_style="bold",
                 subtitle="", subtitle_style="dim",
                 border_style="cyan", loop_seconds=4.0,
                 pad_x=2, pad_y=1, clock=None):
        self._inner = renderable
        self._title = title
        self._title_style = title_style
        self._subtitle = subtitle
        self._subtitle_style = subtitle_style
        self._border_style = border_style
        self._loop = max(1.0, loop_seconds)
        self._pad_x = pad_x
        self._pad_y = pad_y
        self._clock = clock or time.monotonic

    # -- internals --------------------------------------------------
    def _plain_panel(self):
        from rich import box
        from rich.panel import Panel
        return Panel(
            self._inner, border_style=self._border_style, expand=True,
            box=box.ROUNDED, padding=(self._pad_y, self._pad_x),
            title=f"[{self._title_style}]{self._title}[/]",
            title_align="left",
            subtitle=f"[{self._subtitle_style}]{self._subtitle}[/]",
            subtitle_align="right",
        )

    def __rich_console__(self, console, options):
        w = options.max_width or console.size.width
        if w < 48:
            # Too narrow for the travelling light: static panel, same look.
            yield from self._plain_panel().__rich_console__(console, options)
            return
        base = console.get_style(self._border_style)
        core = console.get_style("bold bright_white")
        halo = console.get_style("white")
        title_s = console.get_style(self._title_style)
        sub_s = console.get_style(self._subtitle_style)

        # Comet tail: truecolor gradient from hot white down to the theme
        # accent over TAIL cells behind the head (named-colour fallback
        # when the terminal can't do truecolor).
        try:
            accent_rgb = base.color.get_truecolor() if base.color else None
        except Exception:
            accent_rgb = None
        if not isinstance(accent_rgb, tuple):
            accent_rgb = (255, 255, 255)
        TAIL = 36
        tail = []
        for i in range(TAIL + 1):
            f = i / TAIL
            if console.color_system == "truecolor":
                from rich.color import Color as _Color
                from rich.style import Style as _Style
                r = round(255 + (accent_rgb[0] - 255) * f)
                g = round(255 + (accent_rgb[1] - 255) * f)
                b = round(255 + (accent_rgb[2] - 255) * f)
                tail.append(_Style(color=_Color.from_rgb(r, g, b), bold=True))
            else:
                tail.append(console.get_style(
                    "bold bright_white" if i < TAIL // 3
                    else "white" if i < 2 * TAIL // 3 else self._border_style))

        inner_w = w - 2 - 2 * self._pad_x
        lines = console.render_lines(
            self._inner, options.update(width=inner_w), pad=True)
        h = len(lines) + 2 * self._pad_y + 2

        # Clockwise perimeter path (no duplicated corners).
        path = [(x, 0) for x in range(w)]
        path += [(w - 1, y) for y in range(1, h)]
        path += [(x, h - 1) for x in range(w - 2, -1, -1)]
        path += [(0, y) for y in range(h - 2, 0, -1)]
        total = len(path)
        index_of = {p: i for i, p in enumerate(path)}
        center = (self._clock() * total / self._loop) % total

        from . import motion
        _reduced = motion.reduced()

        def glow(x, y):
            """Comet style at a border cell: white-hot head, short halo
            ahead, long gradient tail melting into the theme accent.
            Reduced motion: the border stays still (no comet)."""
            if _reduced:
                return None
            idx = index_of[(x, y)]
            behind = (center - idx) % total
            ahead = (idx - center) % total
            if min(behind, ahead) <= 1.0:
                return core
            if ahead <= 3:
                return halo
            if behind <= TAIL:
                return tail[int(behind)]
            return None

        # Title sits on the top edge after "╭─ " ; subtitle mirrors it at
        # the bottom-right before " ─╯". Both glow when the comet passes.
        title = self._title
        sub = self._subtitle
        sub_w = sum(cell_len(c) or 1 for c in sub)
        sub_start = max(4, w - 4 - sub_w + 1)
        pad = " " * self._pad_x
        blank = " " * inner_w

        def edge_char(x, y):
            """(char, base style) of the border at x, y. Title and subtitle
            are spaced exactly like a Rich panel: ``╭─ FreeFlix ─…`` and
            ``…─ anime · … · séries ─╯`` (single spaces both sides)."""
            n_title = len(title)
            chars = list(sub)
            n_sub = len(chars)
            if y == 0:
                if x == 0:
                    return "╭", base
                if x == w - 1:
                    return "╮", base
                if x == 1:
                    return "─", base
                if x == 2 or x == 3 + n_title:
                    return " ", base
                if 3 <= x < 3 + n_title:
                    return title[x - 3], title_s
                return "─", base
            if y == h - 1:
                if x == 0:
                    return "╰", base
                if x == w - 1:
                    return "╯", base
                if x == w - 2:
                    return "─", base
                if x == w - 3 or x == sub_start - 1:
                    return " ", base
                if sub_start <= x < sub_start + n_sub:
                    return chars[x - sub_start], sub_s
                return "─", base
            return "│", base

        for y in range(h):
            if y == 0 or y == h - 1:
                for x in range(w):
                    ch, style = edge_char(x, y)
                    yield Segment(ch, glow(x, y) or style)
            else:
                ch0, st0 = "│", base
                ch1, st1 = "│", base
                yield Segment(ch0, glow(0, y) or st0)
                yield Segment(pad, base)
                inner_row = y - 1 - self._pad_y
                if 0 <= inner_row < len(lines):
                    yield from lines[inner_row]
                else:
                    yield Segment(blank, base)
                yield Segment(pad, base)
                yield Segment(ch1, glow(w - 1, y) or st1)
            yield Segment.line()
