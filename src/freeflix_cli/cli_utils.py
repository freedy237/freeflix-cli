import os
import readchar
import re
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.cells import cell_len
from rich import print as rprint

from .themes import color
from .icons import iconify

console = Console()


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def get_user_input(prompt: str, default: str = None) -> str:
    """
    Get user input with a styled prompt.

    Args:
        prompt: The prompt text to display
        default: The default value to display

    Returns:
        The user's input as a string
    """
    styled_prompt = Text(f"\n❯ {iconify(prompt)}: ", style=f"bold {color('accent')}")
    console.print(styled_prompt, end="")
    return input().strip() or default


def pause():
    """Wait for user input before continuing."""
    console.input(f"\n[{color('dim')}]Press Enter to continue...[/{color('dim')}]")


def select_from_list(options: list[str], prompt: str, default_index: int = 0) -> int:
    """
    Display an interactive menu where users can navigate with arrow keys.

    Args:
        options: List of options to display
        prompt: Header text for the menu
        default_index: Index to select by default

    Returns:
        Index of the selected option (0-based)
    """
    selected_index = max(0, min(default_index, len(options) - 1))
    start_index = 0

    def _fit(text: str) -> str:
        """Truncate an option to the terminal width (in DISPLAY columns, so
        wide emoji are counted as 2) so it never wraps and breaks the Live
        render — leaving room for the selection-bar prefix."""
        max_w = max(8, console.size.width - 8)
        if cell_len(text) <= max_w:
            return text
        out = ""
        for ch in text:
            if cell_len(out + ch) > max_w - 1:
                break
            out += ch
        return out + "…"

    def generate_renderable():
        nonlocal start_index

        # Calculate dynamic window size based on terminal height
        term_height = console.size.height
        # Reserve lines for prompt (2), header/spacing (2), arrows (2) -> ~6 lines reserve
        reserved_lines = 6
        available_height = max(3, term_height - reserved_lines)
        window_size = min(len(options), available_height)

        # Adjust start_index to keep selected_index in view
        if selected_index < start_index:
            start_index = selected_index
        elif selected_index >= start_index + window_size:
            start_index = selected_index - window_size + 1

        # Ensure start_index is valid
        start_index = max(0, min(start_index, len(options) - window_size))
        end_index = min(len(options), start_index + window_size)

        lines = [Text(f"\n❯ {iconify(prompt)}", style=f"bold {color('accent')}")]

        # Up arrow indicator
        if start_index > 0:
            lines.append(Text("  ↑ ...", style=color("dim")))

        bar_width = max(20, console.size.width)
        for idx in range(start_index, end_index):
            option = _fit(iconify(options[idx]))
            if idx == selected_index:
                # Full-width selection bar : reverse video follows the theme
                # accent. Pad with cell_len (handles wide emoji) so the bar
                # spans the row without wrapping.
                label = f"  ▌  {option}"
                pad = max(1, bar_width - cell_len(label) - 1)
                lines.append(
                    Text(label + " " * pad, style=f"bold {color('accent')} reverse")
                )
            else:
                lines.append(Text(f"     {option}", style="white"))

        # Down arrow indicator
        if end_index < len(options):
            lines.append(Text("  ↓ ...", style=color("dim")))

        return Group(*lines)

    with Live(generate_renderable(), refresh_per_second=10, transient=True) as live:
        while True:
            key = readchar.readkey()

            if key == readchar.key.UP:
                selected_index = (selected_index - 1) % len(options)
                live.update(generate_renderable())
            elif key == readchar.key.DOWN:
                selected_index = (selected_index + 1) % len(options)
                live.update(generate_renderable())
            elif key == readchar.key.ENTER:
                break
            elif key == readchar.key.CTRL_C:
                raise KeyboardInterrupt("Menu cancelled by user")

    console.print(
        f"\n[bold {color('accent')}]❯ {iconify(prompt)}[/bold {color('accent')}] "
        f"[{color('success')}]{iconify(options[selected_index])}[/{color('success')}]"
    )
    return selected_index


def spinner(message: str):
    """
    Animated spinner shown while a slow operation (scraping, resolving a
    stream…) runs. Use as a context manager :

        with spinner("Searching…"):
            results = scraper.search(query)

    Only wrap pure work — don't prompt or start another Live inside it.
    """
    return console.status(
        f"[{color('info')}]{iconify(message)}[/{color('info')}]", spinner="dots"
    )


def print_header(text: str):
    """
    Print a styled header with a decorative panel.

    Args:
        text: Header text to display
    """
    console.print()
    panel = Panel(
        Text(iconify(text), style=color("header"), justify="center"),
        style=color("accent"),
        border_style=color("border"),
        padding=(0, 2),
    )
    console.print(panel)


def print_success(message: str):
    """Print a success message with a checkmark."""
    console.print(f"[{color('success')}]✓[/{color('success')}] {iconify(message)}")


def print_error(message: str):
    """Print an error message with an X."""
    console.print(f"[{color('error')}]✗[/{color('error')}] {iconify(message)}")


def print_info(message: str):
    """Print an info message."""
    console.print(f"[{color('info')}]ℹ[/{color('info')}] {iconify(message)}")


def print_warning(message: str):
    """Print a warning message."""
    console.print(f"[{color('warning')}]⚠[/{color('warning')}] {iconify(message)}")


def clean_title(title: str) -> str:
    """
    Remove season and part indicators from a title to help with search.
    Example: "One Piece Season 4" -> "One Piece"
    """
    # Remove Season X, S2, Part 2, etc. (case insensitive)
    # Common patterns: Season 1, S1, Part 1, Cour 1, etc.
    patterns = [
        r"\s+Season\s+\d+",
        r"\s+S\d+",
        r"\s+Part\s+\d+",
        r"\s+Cour\s+\d+",
        r"\s+\d+(st|nd|rd|th)\s+Season",
        r"\s+-\s+\d+",  # Sometimes title - 2
    ]

    cleaned = title
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()
