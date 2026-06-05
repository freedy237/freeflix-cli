"""
Launch splash screen — ASCII art logo coloured with the active theme.
"""

import time
from rich.align import Align
from rich.text import Text

from .cli_utils import console, clear_screen
from .themes import color

# FreeFlix wordmark (ANSI Shadow style).
_LOGO = r"""
 ███████╗██████╗ ███████╗███████╗███████╗██╗     ██╗██╗  ██╗
 ██╔════╝██╔══██╗██╔════╝██╔════╝██╔════╝██║     ██║╚██╗██╔╝
 █████╗  ██████╔╝█████╗  █████╗  █████╗  ██║     ██║ ╚███╔╝
 ██╔══╝  ██╔══██╗██╔══╝  ██╔══╝  ██╔══╝  ██║     ██║ ██╔██╗
 ██║     ██║  ██║███████╗███████╗██║     ███████╗██║██╔╝ ██╗
 ╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝     ╚══════╝╚═╝╚═╝  ╚═╝
"""


def logo_renderable(width: int = None, height: int = None):
    """Return the themed FreeFlix wordmark, centered and responsive (full
    ANSI-shadow art on wide terminals, a compact mark otherwise). Shared by
    the splash and the loading screen so they always match."""
    try:
        w = width if width is not None else console.size.width
        h = height if height is not None else console.size.height
    except Exception:
        w, h = 80, 24
    if w >= 64 and h >= 14:
        return Align.center(Text(_LOGO, style=f"bold {color('accent')}"))
    from .icons import icon
    return Align.center(Text(f"{icon('home')} FREEFLIX", style=f"bold {color('accent')}"))


def tagline_text(width: int = None) -> Text:
    """Themed responsive tagline used under the logo."""
    try:
        w = width if width is not None else console.size.width
    except Exception:
        w = 80
    tag = ("Movies · Series · Anime — straight from your terminal"
           if w >= 56 else "Movies · Series · Anime")
    return Text(tag, style=color("info"))


def show_splash(version: str = "", duration: float = 1.2):
    """
    Render the logo centered, themed, with a tagline + version, then
    pause briefly. Skipped silently on tiny terminals.
    """
    try:
        w, h = console.size.width, console.size.height
        if h < 10 or w < 26:
            return  # genuinely too small — don't garble the screen

        clear_screen()
        console.print()
        console.print(logo_renderable(w, h))
        console.print(Align.center(tagline_text(w)))
        if version:
            console.print(Align.center(Text(f"v{version}", style=color("dim"))))
        console.print()
        time.sleep(duration)
    except Exception:
        # Never let the splash block startup.
        pass
