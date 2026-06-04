"""
Render anime posters INSIDE the terminal, via chafa.

chafa stays 100% inside the terminal : it prints either sixel graphics
(photo quality) or coloured Unicode blocks (▀▄) to stdout. Unlike
ueberzug it does NOT create an overlay window, so it works in Konsole
under Wayland with zero extra setup.

Everything degrades gracefully :
  * chafa not installed         → functions are no-ops (return False) ;
  * image download fails        → no-op ;
  * poster mode set to "off"    → no-op.

So the rest of the app can call render_url() unconditionally.
"""

import os
import shutil
import subprocess
import tempfile
import time

from .tracker import tracker

try:
    from curl_cffi import requests as _rq
except Exception:  # pragma: no cover - curl_cffi should always be present
    _rq = None

try:
    from rich.console import Console

    _console = Console()
except Exception:  # pragma: no cover
    _console = None

# Cache the chafa lookup so we don't hit the filesystem every call.
_CHAFA_PATH = None


def chafa_available() -> bool:
    """True if the `chafa` binary is on PATH."""
    global _CHAFA_PATH
    if _CHAFA_PATH is None:
        _CHAFA_PATH = shutil.which("chafa") or ""
    return bool(_CHAFA_PATH)


def reset_cache():
    """Forget the cached chafa lookup (call after installing chafa)."""
    global _CHAFA_PATH
    _CHAFA_PATH = None


def _poster_size():
    """
    Responsive poster size (columns x rows) derived from the live terminal
    size, so the cover scales with the window and never overflows.
    """
    cols, rows = 80, 24
    try:
        if _console is not None:
            cols, rows = _console.size.width, _console.size.height
        else:
            ts = shutil.get_terminal_size((80, 24))
            cols, rows = ts.columns, ts.lines
    except Exception:
        pass

    # Poster takes ~1/3 of the width, clamped to a sane range, and a
    # height roughly proportional (anime covers are ~2:3 portrait).
    width = max(16, min(40, cols // 3))
    height = max(8, min(22, rows - 6))
    return width, height


def _download(url: str, attempts: int = 3):
    """
    Download `url` to a temp file. Returns the path or None.

    Retries a couple of times because some cover hosts (e.g. Anime-Sama's
    covers on raw.githubusercontent.com) rate-limit / time out
    intermittently, which made posters appear "only when they felt like it".
    """
    if not url or _rq is None:
        return None

    suffix = ".jpg"
    low = url.lower()
    for ext in (".png", ".webp", ".jpeg", ".jpg", ".gif"):
        if ext in low:
            suffix = ext
            break

    for i in range(attempts):
        try:
            r = _rq.get(url, impersonate="chrome", timeout=12)
            if r.status_code == 200 and r.content:
                fd, path = tempfile.mkstemp(prefix="freeflix_poster_", suffix=suffix)
                with os.fdopen(fd, "wb") as f:
                    f.write(r.content)
                return path
        except Exception:
            pass
        if i < attempts - 1:
            time.sleep(0.4)
    return None


def render_url(url: str, width: int = None, height: int = None) -> bool:
    """
    Download an image URL and draw it in the terminal with chafa.

    Returns True if something was actually drawn, False otherwise (so the
    caller can decide whether to print a text-only fallback).
    """
    mode = (tracker.get_poster_mode() or "auto").lower()
    if mode == "off" or not chafa_available():
        return False

    if width is None or height is None:
        w, h = _poster_size()
        width = width or w
        height = height or h

    path = _download(url)
    if not path:
        return False

    try:
        cmd = [_CHAFA_PATH, "--size", f"{width}x{height}"]
        # "sixel" forces photo-quality output (needs Konsole Sixel enabled);
        # "auto" lets chafa pick the best format the terminal advertises.
        if mode == "sixel":
            cmd += ["--format", "sixels"]
        cmd.append(path)
        subprocess.run(cmd, check=False)
        return True
    except Exception:
        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def show_poster(cover_url: str, title: str = None, info_lines=None) -> bool:
    """
    Present an anime : draw its poster (if possible) then print the title
    and a few info lines underneath. Safe to call always — if no cover or
    no chafa, it just prints the text info.

    Returns True if a poster image was drawn.
    """
    drew = render_url(cover_url) if cover_url else False

    if _console is not None:
        if title:
            _console.print(f"\n[bold cyan]{title}[/bold cyan]")
        for line in info_lines or []:
            if line:
                _console.print(f"  [dim]{line}[/dim]")
    else:  # pragma: no cover
        if title:
            print(title)
        for line in info_lines or []:
            if line:
                print("  " + str(line))
    return drew
