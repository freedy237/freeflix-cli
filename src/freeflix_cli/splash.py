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
        if console.size.height < 14 or console.size.width < 64:
            return  # too small — don't garble the screen
        clear_screen()
        console.print()
        console.print(Align.center(Text(_LOGO, style=f"bold {color('accent')}")))

        tagline = Text(
            "Movies · Series · Anime — straight from your terminal",
            style=color("info"),
        )
        console.print(Align.center(tagline))

        if version:
            console.print(
                Align.center(Text(f"v{version}", style=color("dim")))
            )
        console.print()
        time.sleep(duration)
    except Exception:
        # Never let the splash block startup.
        pass
