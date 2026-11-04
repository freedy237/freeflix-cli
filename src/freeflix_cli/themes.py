"""
Colour themes for the FreeFlix TUI.

Each theme maps a set of semantic ROLES to Rich colour strings (hex).
cli_utils reads the active theme via `color(role)` so every header,
prompt, message and menu picks up the user's chosen palette.

Roles (2.0 design tokens) :
  accent / accent_soft – signature colour and its quiet companion
  header / text        – primary type
  border / border_soft – structural hairlines
  surface / surface_alt – optional panel fills (None = terminal background)
  selection / selection_text – cursor rail colours
  success / error / info / warning – message colours
  dim / muted          – secondary text (arrows, hints, metadata)
"""

THEMES = {
    # ── FreeFlix 2.0 signature ────────────────────────────────────
    # Cinema Noir: warm ivory + amber on near-black, thin borders,
    # calm and editorial. The default from 2.0 on.
    "noir": {
        "label": "Cinema Noir",
        "accent": "#E6B45E",          # amber
        "accent_soft": "#6B5630",
        "header": "bold #F4EEE2",     # ivory
        "text": "#F4EEE2",
        "border": "#3A3A46",
        "border_soft": "#2C2C36",
        "surface": "#121216",
        "surface_alt": "#1A1A21",
        "selection": "#2A2117",
        "selection_text": "#FFF4D6",
        "success": "#9CCB8A",
        "error": "#D96C75",
        "info": "#7FA8B8",            # dusty blue
        "warning": "#E2C07A",
        "dim": "#8B8792",
        "muted": "#8B8792",
    },
    # Legacy neon look (pre-2.0 default).
    "default": {
        "label": "Legacy Cyan (pre-2.0)",
        "accent": "bright_cyan",
        "header": "bold white",
        "border": "bright_cyan",
        "success": "green",
        "error": "red",
        "info": "blue",
        "warning": "yellow",
        "dim": "dim",
    },
    # Catppuccin Mocha — https://github.com/catppuccin/catppuccin
    "catppuccin": {
        "label": "Catppuccin Mocha",
        "accent": "#89b4fa",   # blue
        "header": "bold #cdd6f4",
        "border": "#cba6f7",   # mauve
        "success": "#a6e3a1",  # green
        "error": "#f38ba8",    # red
        "info": "#89dceb",     # sky
        "warning": "#f9e2af",  # yellow
        "dim": "#6c7086",      # overlay0
    },
    # Dracula — https://draculatheme.com
    "dracula": {
        "label": "Dracula",
        "accent": "#bd93f9",   # purple
        "header": "bold #f8f8f2",
        "border": "#ff79c6",   # pink
        "success": "#50fa7b",  # green
        "error": "#ff5555",    # red
        "info": "#8be9fd",     # cyan
        "warning": "#f1fa8c",  # yellow
        "dim": "#6272a4",      # comment
    },
    # Nord — https://www.nordtheme.com
    "nord": {
        "label": "Nord",
        "accent": "#88c0d0",   # frost cyan
        "header": "bold #eceff4",
        "border": "#81a1c1",   # frost blue
        "success": "#a3be8c",  # aurora green
        "error": "#bf616a",    # aurora red
        "info": "#8fbcbb",     # frost teal
        "warning": "#ebcb8b",  # aurora yellow
        "dim": "#4c566a",      # polar night
    },
    # Gruvbox Dark — https://github.com/morhetz/gruvbox
    "gruvbox": {
        "label": "Gruvbox",
        "accent": "#fabd2f", "header": "bold #ebdbb2", "border": "#d79921",
        "success": "#b8bb26", "error": "#fb4934", "info": "#83a598",
        "warning": "#fe8019", "dim": "#928374",
    },
    # Tokyo Night — https://github.com/enkia/tokyo-night-vscode-theme
    "tokyonight": {
        "label": "Tokyo Night",
        "accent": "#7aa2f7", "header": "bold #c0caf5", "border": "#bb9af7",
        "success": "#9ece6a", "error": "#f7768e", "info": "#7dcfff",
        "warning": "#e0af68", "dim": "#565f89",
    },
    # Rosé Pine — https://rosepinetheme.com
    "rosepine": {
        "label": "Rosé Pine",
        "accent": "#c4a7e7", "header": "bold #e0def4", "border": "#ebbcba",
        "success": "#31748f", "error": "#eb6f92", "info": "#9ccfd8",
        "warning": "#f6c177", "dim": "#6e6a86",
    },
    # High-contrast monochrome (accessibility / e-ink).
    # Everforest Dark — https://github.com/sainnhe/everforest
    "everforest": {
        "label": "Everforest",
        "accent": "#83c092", "header": "bold #d3c6aa", "border": "#a7c080",
        "success": "#a7c080", "error": "#e67e80", "info": "#7fbbb3",
        "warning": "#dbbc7f", "dim": "#859289",
    },
    # Kanagawa (Wave) — https://github.com/rebelot/kanagawa.nvim
    "kanagawa": {
        "label": "Kanagawa",
        "accent": "#7e9cd8", "header": "bold #dcd7ba", "border": "#957fb8",
        "success": "#98bb6c", "error": "#e46876", "info": "#7aa89f",
        "warning": "#e6c384", "dim": "#727169",
    },
    # Solarized Dark — https://ethanschoonover.com/solarized
    "solarized": {
        "label": "Solarized Dark",
        "accent": "#268bd2", "header": "bold #93a1a1", "border": "#2aa198",
        "success": "#859900", "error": "#dc322f", "info": "#268bd2",
        "warning": "#b58900", "dim": "#586e75",
    },
    # High-contrast monochrome (accessibility / e-ink).
    "mono": {
        "label": "Monochrome",
        "accent": "bright_white", "header": "bold white", "border": "white",
        "success": "bright_white", "error": "bright_white", "info": "white",
        "warning": "bright_white", "dim": "grey58",
    },
}

DEFAULT_THEME = "noir"


def list_themes():
    """Return [(key, label), ...] for the settings menu."""
    return [(k, v["label"]) for k, v in THEMES.items()]


def active_theme() -> dict:
    """
    The user's current theme (falls back to default), with an optional custom
    accent colour overlaid on top (Settings → Appearance → Theme → accent).

    2.0 ships dark palettes only: Cinema Noir and the legacy dark themes.
    """
    name = DEFAULT_THEME
    accent = None
    try:
        from .tracker import tracker
        name = tracker.get_theme()
        accent = tracker.get_custom_accent()
    except Exception:
        pass
    theme = dict(THEMES.get(name, THEMES[DEFAULT_THEME]))
    if accent:
        theme["accent"] = accent
        theme["border"] = accent
    return theme


def preview_theme(name: str, accent: str = None) -> dict:
    """Return a theme dict for previewing (name + optional accent), without
    touching the saved settings."""
    theme = dict(THEMES.get(name, THEMES[DEFAULT_THEME]))
    if accent:
        theme["accent"] = accent
        theme["border"] = accent
    return theme


_ROLE_FALLBACK = {
    "text": "header",
    "muted": "dim",
    "border_soft": "border",
    "surface": None,       # leave the terminal background
    "surface_alt": None,
    "selection": "accent",
    "selection_text": None,  # literal colour, handled by _LITERAL_FALLBACK
    "accent_soft": "accent",
}

# Roles whose fallback is a literal Rich colour, not another role key.
_LITERAL_FALLBACK = {
    "selection_text": "black",
}


def color(role: str) -> str:
    """Return the Rich colour string for a semantic role in the active theme.

    Older palette packs only define the original 7 roles; the 2.0 roles
    (surface/text/muted/selection…) fall back sensibly so third-party or
    user-added themes keep working.
    """
    theme = active_theme()
    if role in theme and theme[role] is not None:
        return theme[role]
    if role in _LITERAL_FALLBACK:
        return _LITERAL_FALLBACK[role]
    fallback = _ROLE_FALLBACK.get(role)
    if fallback is None:
        return "default"  # terminal background / default foreground
    return theme.get(fallback, THEMES[DEFAULT_THEME].get(fallback, "white"))
