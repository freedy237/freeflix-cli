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

        # Responsive logo : full ANSI-shadow wordmark on wide terminals,
        # a compact one when the big one (≈60 cols) wouldn't fit.
        if w >= 64 and h >= 14:
            console.print(Align.center(Text(_LOGO, style=f"bold {color('accent')}")))
        else:
            console.print(
                Align.center(Text("🍿 FREEFLIX", style=f"bold {color('accent')}"))
            )

        # Tagline adapts to width too (full vs short).
        if w >= 56:
            tag = "Movies · Series · Anime — straight from your terminal"
        else:
            tag = "Movies · Series · Anime"
        console.print(Align.center(Text(tag, style=color("info"))))

        if version:
            console.print(
                Align.center(Text(f"v{version}", style=color("dim")))
            )
        console.print()
        time.sleep(duration)
    except Exception:
        # Never let the splash block startup.
        pass
