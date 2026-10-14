"""
Launch splash screen — ASCII art logo coloured with the active theme.
"""

from rich.align import Align
from rich.cells import cell_len
from rich.text import Text

from .cli_utils import console
from .themes import color
from .i18n import t

# FreeFlix wordmark (ANSI Shadow style).
_LOGO = r"""
 ███████╗██████╗ ███████╗███████╗███████╗██╗     ██╗██╗  ██╗
 ██╔════╝██╔══██╗██╔════╝██╔════╝██╔════╝██║     ██║╚██╗██╔╝
 █████╗  ██████╔╝█████╗  █████╗  █████╗  ██║     ██║ ╚███╔╝
 ██╔══╝  ██╔══██╗██╔══╝  ██╔══╝  ██╔══╝  ██║     ██║ ██╔██╗
 ██║     ██║  ██║███████╗███████╗██║     ███████╗██║██╔╝ ██╗
 ╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝     ╚══════╝╚═╝╚═╝  ╚═╝
"""


def _shine_line(line: str, center: float, base_style: str,
                core_half: float = 2.0, halo: float = 5.0) -> Text:
    """One logo line with a soft gleam centered at ``center`` (cell columns).

    Shine applies to LETTERS only — background spaces always keep the base
    style, so the band never looks like a sweeping block. Falloff is a
    brightness gradient (bright-white core → white halo → base), which
    reads as a light sweep on dark themes and degrades gracefully to the
    plain logo on light ones. Column accounting is cell-based so wide
    glyphs (emoji fallback mark) don't shift the band."""
    out = Text()
    col = 0
    for ch in line:
        w = cell_len(ch) or 1
        if ch.strip():
            d = abs(col + w / 2 - center)
            if d <= core_half:
                style = "bold bright_white"
            elif d <= core_half + halo:
                style = "white"
            else:
                style = base_style
        else:
            style = base_style
        out.append(ch, style=style)
        col += w
    return out


def logo_renderable(width: int = None, height: int = None,
                    animate: bool = False, tick: int = 0):
    """Return the themed FreeFlix wordmark, centered and responsive (full
    ANSI-shadow art on wide terminals, a compact mark otherwise). Shared by
    the splash and the loading screen so they always match.

    :param animate: loop a soft shine across the letters (driven by
        ``tick``, independent of the progress bar — one full sweep ≈ 2 s,
        seamless wrap so it can run any number of passes).
    """
    try:
        w = width if width is not None else console.size.width
        h = height if height is not None else console.size.height
    except Exception:
        w, h = 80, 24
    base = f"bold {color('accent')}"
    if w >= 64 and h >= 14:
        lines = _LOGO.strip("\n").split("\n")
    else:
        from .icons import icon
        lines = [f"{icon('home')} FREEFLIX"]
    if not animate:
        return Align.center(Text("\n".join(lines), style=base))
    span = max((sum(cell_len(c) or 1 for c in ln) for ln in lines),
               default=0)
    # Seamless loop: the band travels off-screen right and re-enters left,
    # so the cut is invisible and passes can repeat forever.
    margin = 10
    cycle = span + 2 * margin
    speed = cycle / 30  # ≈ one sweep every ~1.8 s at 16 fps
    center = (tick * speed) % cycle - margin
    body = Text()
    for i, ln in enumerate(lines):
        if i:
            body.append("\n")
        body.append_text(_shine_line(ln, center, base))
    return Align.center(body)


def tagline_text(width: int = None) -> Text:
    """Themed responsive tagline used under the logo."""
    try:
        w = width if width is not None else console.size.width
    except Exception:
        w = 80
    tag = (t("Movies · Series · Anime — straight from your terminal")
           if w >= 56 else t("Movies · Series · Anime"))
    return Text(tag, style=color("info"))



