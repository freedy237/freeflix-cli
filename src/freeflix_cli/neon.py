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
                 pad_x=2, pad_y=1, clock=None,
                 animate=True, box_style=None, light_style=None,
                 cell_speed=None, static_edge_style=None):
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
        self._animate = bool(animate)
        self._box_style = box_style
        self._light_style = light_style
        # Optional constant speed in border cells per second. Hosts that
        # repaint at animation_fps can use this to move exactly ~1 cell per
        # frame, which is the smoothest a terminal cell grid allows.
        self._cell_speed = cell_speed
        # Optional colour for the parts of the frame the light has left behind.
        # None = keep border_style (the classic behaviour).
        self._static_edge_style = static_edge_style

    @property
    def animation_fps(self) -> int:
        """Suggested Live refresh rate for hosts that drive this panel.

        The menu's default 8 fps is fine for a slowly breathing cursor, but
        the travelling light needs a higher cadence to move smoothly across
        the border. Reduced motion keeps the static fallback and 8 fps.
        """
        from . import motion
        return 30 if self._animate and not motion.reduced() else 0

    # -- internals --------------------------------------------------
    def _plain_panel(self):
        from rich import box
        from rich.panel import Panel
        from rich.text import Text as _Text
        title = self._title
        if not isinstance(title, _Text):
            title = f"[{self._title_style}]{title}[/]"
        subtitle = self._subtitle
        if not isinstance(subtitle, _Text):
            subtitle = f"[{self._subtitle_style}]{subtitle}[/]"
        return Panel(
            self._inner, border_style=self._border_style, expand=True,
            box=(self._box_style or box.ROUNDED),
            padding=(self._pad_y, self._pad_x),
            title=title,
            title_align="left",
            subtitle=subtitle,
            subtitle_align="right",
        )

    def __rich_console__(self, console, options):
        from . import motion
        if not self._animate or motion.reduced():
            yield from self._plain_panel().__rich_console__(console, options)
            return
        w = options.max_width or console.size.width
        if w < 48:
            # Too narrow for the travelling light: static panel, same look.
            yield from self._plain_panel().__rich_console__(console, options)
            return
        # `base` = the glass panel's interior (stays dark). `edge_base` = the
        # visible frame at rest, so the light can pass over a frame that is
        # always drawn (Cinema Noir uses the same soft grey as the top banner).
        base = console.get_style(self._border_style)
        edge_base = (console.get_style(self._static_edge_style)
                     if self._static_edge_style else base)
        light = console.get_style(self._light_style or self._border_style)
        core = console.get_style("bold bright_white")
        halo = console.get_style("white")
        title_s = console.get_style(self._title_style)
        sub_s = console.get_style(self._subtitle_style)

        # Comet tail: truecolor gradient from hot white down to the travelling
        # light's colour over TAIL cells behind the head (named-colour fallback
        # when the terminal can't do truecolor). The frame stays its own colour,
        # which can be black, so only the moving light is visible.
        try:
            accent_rgb = light.color.get_truecolor() if light.color else None
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
                    else "white" if i < 2 * TAIL // 3
                    else (self._light_style or self._border_style)))

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
        duration = self._loop
        if self._cell_speed:
            duration = total / max(1.0, float(self._cell_speed))
        center = (self._clock() * total / max(1.0, duration)) % total

        def glow(x, y):
            """Comet style at a border cell: white-hot head, short halo
            ahead, long gradient tail melting into the theme accent.
            Reduced motion already fell back to the static panel above."""
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
        # Either may be a Rich Text (the 2.0 two-tone wordmark), so styles are
        # read per character instead of flattening the whole title.
        from rich.text import Text as _Text

        def _cells(value, fallback):
            if isinstance(value, _Text):
                plain = value.plain
                return (list(plain),
                        [value.get_style_at_offset(console, i)
                         for i in range(len(plain))])
            text = str(value)
            return list(text), [fallback] * len(text)

        title_chars, title_styles = _cells(self._title, title_s)
        sub_chars, sub_styles = _cells(self._subtitle, sub_s)
        n_title = len(title_chars)
        n_sub = len(sub_chars)
        sub_w = sum(cell_len(c) or 1 for c in sub_chars)
        sub_start = max(4, w - 4 - sub_w + 1)
        pad = " " * self._pad_x
        blank = " " * inner_w

        def edge_char(x, y):
            """(char, base style) of the border at x, y. Title and subtitle
            are spaced exactly like a Rich panel: ``╭─ FreeFlix ─…`` and
            ``…─ anime · … · séries ─╯`` (single spaces both sides)."""
            if y == 0:
                if x == 0:
                    return "╭", edge_base
                if x == w - 1:
                    return "╮", edge_base
                if x == 1:
                    return "─", edge_base
                if x == 2 or x == 3 + n_title:
                    return " ", edge_base
                if 3 <= x < 3 + n_title:
                    return title_chars[x - 3], title_styles[x - 3]
                return "─", edge_base
            if y == h - 1:
                if x == 0:
                    return "╰", edge_base
                if x == w - 1:
                    return "╯", edge_base
                if x == w - 2:
                    return "─", edge_base
                if x == w - 3 or x == sub_start - 1:
                    return " ", edge_base
                if sub_start <= x < sub_start + n_sub:
                    return sub_chars[x - sub_start], sub_styles[x - sub_start]
                return "─", edge_base
            return "│", edge_base

        for y in range(h):
            if y == 0 or y == h - 1:
                for x in range(w):
                    ch, style = edge_char(x, y)
                    yield Segment(ch, glow(x, y) or style)
            else:
                ch0, st0 = "│", edge_base
                ch1, st1 = "│", edge_base
                yield Segment(ch0, glow(0, y) or st0)
                yield Segment(pad, edge_base)
                inner_row = y - 1 - self._pad_y
                if 0 <= inner_row < len(lines):
                    yield from lines[inner_row]
                else:
                    yield Segment(blank, edge_base)
                yield Segment(pad, edge_base)
                yield Segment(ch1, glow(w - 1, y) or st1)
            yield Segment.line()
