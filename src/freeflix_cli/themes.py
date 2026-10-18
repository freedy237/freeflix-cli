"""
Colour themes for the FreeFlix TUI.

Each theme maps a set of semantic ROLES to Rich colour strings (hex).
cli_utils reads the active theme via `color(role)` so every header,
prompt, message and menu picks up the user's chosen palette.

Roles :
  accent   – signature colour : selection highlight, prompts, borders
  header   – header panel text
  success / error / info / warning – message colours
  dim      – muted text (arrows, hints)
"""

THEMES = {
    # The original FreeFlix look (cyan/green).
    "default": {
        "label": "Default (cyan)",
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
    # Catppuccin Latte — the LIGHT palette. Header text is DARK so it stays
    # readable on a light-background terminal (the default theme's "bold white"
    # header is invisible there).
    "latte": {
        "label": "Catppuccin Latte (light)",
        "accent": "#1e66f5", "header": "bold #4c4f69", "border": "#8839ef",
        "success": "#40a02b", "error": "#d20f39", "info": "#04a5e5",
        "warning": "#df8e1d", "dim": "#9ca0b0",
    },
    # High-contrast monochrome (accessibility / e-ink).
    "mono": {
        "label": "Monochrome",
        "accent": "bright_white", "header": "bold white", "border": "white",
        "success": "bright_white", "error": "bright_white", "info": "white",
        "warning": "bright_white", "dim": "grey58",
    },
}

DEFAULT_THEME = "default"


def list_themes():
    """Return [(key, label), ...] for the settings menu."""
    return [(k, v["label"]) for k, v in THEMES.items()]


def _terminal_is_light():
    """True when the terminal reports a LIGHT background via COLORFGBG.

    COLORFGBG is "<fg>;<bg>" with ANSI indices (e.g. "15;0" = light text on
    black, "0;15" = dark text on white). Background index >= 7 means light.
    Returns None when unknown."""
    import os
    raw = os.environ.get("COLORFGBG", "").strip()
    if not raw:
        return None
    try:
        bg = int(raw.split(";")[-1])
    except (ValueError, IndexError):
        return None
    return bg >= 7


def active_theme() -> dict:
    """
    The user's current theme (falls back to default), with an optional custom
    accent colour overlaid on top (Settings → Appearance → Theme → accent).

    Smart default: when the user never chose a theme and the terminal reports
    a LIGHT background, use the light palette automatically — a white-on-white
    UI would otherwise be unreadable. An explicit theme always wins.
    """
    name = DEFAULT_THEME
    accent = None
    try:
        from .tracker import tracker
        name = tracker.get_theme()
        accent = tracker.get_custom_accent()
    except Exception:
        pass
    if name == DEFAULT_THEME and _terminal_is_light():
        name = "latte"
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


def color(role: str) -> str:
    """Return the Rich colour string for a semantic role in the active theme."""
    theme = active_theme()
    return theme.get(role, THEMES[DEFAULT_THEME].get(role, "white"))
