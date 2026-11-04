"""FreeFlix 2.0 visual primitives (Cinema Noir).

Small, semantic building blocks used by the home screen, headers and theme
preview. They intentionally avoid hard-coded hex colours: every colour comes
from the active theme via :func:`freeflix_cli.themes.color`.
"""

from __future__ import annotations

from rich import box
from rich.panel import Panel
from rich.text import Text

from .themes import color


# Warm ink used by Cinema Noir for the two-tone wordmark. Kept here as a
# literal (not from the theme dict) because the wordmark is a brand mark: it
# must stay recognisable even if someone overrides the accent colour.
_NOIR_INK = "#F4EEE2"
_NOIR_AMBER = "#E6B45E"


def _on_black_theme() -> bool:
    """True for the Cinema Noir signature palette (and any near-black one).

    The wordmark keeps the Cinema Noir colours only when the active theme is
    genuinely dark; on another dark palette it follows that palette instead.
    """
    surface = color("surface")
    try:
        from rich.color import Color
        rgb = Color.parse(surface).get_truecolor()
        return (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) / 1000 < 40
    except Exception:
        # "default" / named colours → assume the terminal is dark.
        return surface in ("default", "black") or surface.startswith("#0")


def wordmark() -> Text:
    """The 2.0 wordmark: compact two-tone, no letterspaced banner.

    Terminal fonts cannot be swapped at runtime, so the identity is carried by
    weight, case and colour instead: Free in the accent, Flix in ivory. On the
    Cinema Noir / black palettes it uses the signature warm amber + ivory that
    stays readable against the black frame.
    """
    out = Text()
    if _on_black_theme():
        out.append("Free", style=f"bold {_NOIR_AMBER}")
        out.append("Flix", style=f"bold {_NOIR_INK}")
    else:
        out.append("Free", style=f"bold {color('accent')}")
        out.append("Flix", style=f"bold {color('text')}")
    return out


def rule(label: str = "", style: str = "border_soft") -> Text:
    """A hairline rule, optionally carrying a small uppercase label."""
    line = Text()
    if label:
        line.append(label.upper(), style=f"bold {color('accent')}")
        line.append("  ", style=color(style))
    width = 0
    try:
        from .cli_utils import console
        width = max(8, console.size.width - 4)
    except Exception:
        width = 72
    used = len(line.plain) + 2
    line.append("─" * max(4, width - used), style=color(style))
    return line


def section(title: str, meta: str = "") -> Text:
    """A section heading + optional muted meta, aligned to the 2-space grid.

    The label keeps its normal casing ("Reprendre", not "REPRENDRE"): the 2.0
    home reads like an editorial title, not a shouted eyebrow.
    """
    out = Text("  ")
    out.append(str(title), style=f"bold {color('accent')}")
    if meta:
        out.append("   " + str(meta), style=color("muted"))
    return out


def meta(text: str) -> Text:
    return Text(str(text), style=color("muted"))


def chip(text: str, role: str = "info") -> Text:
    """A quiet inline badge: colour + brackets, no block background."""
    out = Text(" ")
    out.append(f"[{text}]", style=f"bold {color(role)}")
    out.append(" ")
    return out


def panel(renderable, *, title=None, subtitle=None,
          border: str = "border_soft") -> Panel:
    """The house panel: horizontal hairlines, no heavy box, generous air."""
    title_text = title
    if isinstance(title, str):
        title_text = Text(title, style=f"bold {color('text')}")
    sub_text = subtitle
    if isinstance(subtitle, str):
        sub_text = Text(subtitle, style=color("muted"))
    return Panel(
        renderable,
        box=box.HORIZONTALS,
        border_style=color(border),
        padding=(0, 1),
        title=title_text,
        title_align="left",
        subtitle=sub_text,
        subtitle_align="right",
    )
