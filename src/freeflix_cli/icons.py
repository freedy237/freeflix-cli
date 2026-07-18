"""
Icon set abstraction.

FreeFlix uses emoji by default (work everywhere), but users with a
**Nerd Font** installed and selected in their terminal can switch to crisp,
monospace, theme-coloured glyphs. Two parallel sets are kept here ; the
active one is chosen by the `icon_style` tracker setting ("emoji" | "nerd").

Call icon("anime") instead of hard-coding the glyph, so a single setting
flips the whole UI. Unknown names fall back to "" so nothing breaks.
"""

from .tracker import tracker

# Semantic name -> emoji (default, universal).
_EMOJI = {
    # Sources
    "anime": "🎌",
    "sparkle": "✨",
    "manga": "🎴",
    "star": "🌟",
    "flag_fr": "🇫🇷",
    "wave": "🌊",
    # UI
    "home": "🍿",
    "search": "🔍",
    "tv": "📺",
    "globe": "🌍",
    "settings": "⚙",
    "download": "📥",
    "folder": "📁",
    "stats": "📊",
    "info": "ℹ",
    "theme": "🎨",
    "poster": "🖼",
    "play": "▶",
    "back": "←",
    "movie": "🎬",
    "book": "📖",
    "history": "📜",
    "exit": "❌",
    "gamepad": "🎮",
    "subtitle": "📝",
    "fire": "🔥",
    "repeat": "🔁",
    "up": "⬆",
    "party": "🎉",
    "flag_us": "🇺🇸",
    "movie_clap": "🎬",
    "loading": "⏳",
    "offline": "⚠",
}

# Semantic name -> Nerd Font codepoint (Font Awesome range, present in every
# Nerd Font). Built with chr() so the source stays plain-ASCII and correct.
# Renders as a box if the terminal font is NOT a Nerd Font, hence emoji
# stays the default.
_NERD = {
    # Sources
    "anime": chr(0xF26C),     # television
    "sparkle": chr(0xF005),   # star
    "manga": chr(0xF02D),     # book
    "star": chr(0xF005),      # star
    "flag_fr": chr(0xF024),   # flag
    "wave": chr(0xF0ED),      # cloud-download
    # UI
    "home": chr(0xF008),      # film
    "search": chr(0xF002),    # magnifier
    "tv": chr(0xF26C),        # television
    "globe": chr(0xF0AC),     # globe
    "settings": chr(0xF013),  # gear
    "download": chr(0xF019),  # download
    "folder": chr(0xF07B),    # folder
    "stats": chr(0xF080),     # bar-chart
    "info": chr(0xF05A),      # info-circle
    "theme": chr(0xF1FC),     # paint-brush
    "poster": chr(0xF03E),    # image
    "play": chr(0xF04B),      # play
    "back": chr(0xF060),      # arrow-left
    "movie": chr(0xF008),     # film
    "book": chr(0xF02D),      # book
    "history": chr(0xF1DA),   # history
    "exit": chr(0xF08B),      # sign-out
    "gamepad": chr(0xF11B),   # gamepad
    "subtitle": chr(0xF15C),  # file-text
    "fire": chr(0xF06D),      # fire
    "repeat": chr(0xF01E),    # repeat
    "up": chr(0xF062),        # arrow-up
    "party": chr(0xF06B),     # gift
    "flag_us": chr(0xF024),   # flag
    "movie_clap": chr(0xF008),  # film
    "loading": chr(0xF252),   # hourglass
    "offline": chr(0xF071),   # exclamation-triangle
}


def _style() -> str:
    return tracker.get_icon_style() if hasattr(tracker, "get_icon_style") else "emoji"


def icon(name: str) -> str:
    """Return the glyph for `name` in the active icon style."""
    table = _NERD if _style() == "nerd" else _EMOJI
    return table.get(name, "")


# Reverse map (emoji glyph -> Nerd Font glyph) so we can convert ANY emoji
# found in already-built strings, centrally, without touching every call site.
_EMOJI_TO_NERD = {
    em: _NERD[name] for name, em in _EMOJI.items() if name in _NERD and em
}


def iconify(text: str) -> str:
    """
    In Nerd Font mode, replace every known emoji in `text` with its Nerd
    Font glyph. No-op in emoji mode. Applied centrally in cli_utils
    (headers, menus, messages) so the whole UI follows the icon setting
    without per-string edits.
    """
    if not text or _style() != "nerd":
        return text
    for em, nf in _EMOJI_TO_NERD.items():
        if em in text:
            text = text.replace(em, nf)
    return text
