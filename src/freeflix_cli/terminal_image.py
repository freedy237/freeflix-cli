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


# url -> local file path. The downloaded IMAGE is cached per URL (independent
# of render size) so resizing only re-runs chafa on the local file instead of
# re-downloading. Files are kept for the session and cleaned up at exit.
_img_cache = {}


def _download(url: str, attempts: int = 3):
    """
    Get a local file path for `url`'s image, downloading it ONCE.

    The result is cached per URL : the first call downloads, every later call
    (e.g. a different render size during a terminal resize) reuses the same
    local file, so we never re-download just to re-scale. Returns the path or
    None.

    Retries a couple of times because some cover hosts (e.g. Anime-Sama's
    covers on raw.githubusercontent.com) rate-limit / time out
    intermittently, which made posters appear "only when they felt like it".
    """
    if not url or _rq is None:
        return None
    # Protocol-relative URLs (//host/…, common on Coflix/TMDB) can't be
    # fetched as-is — give them a scheme.
    if url.startswith("//"):
        url = "https:" + url

    # Reuse the already-downloaded file if we still have it.
    cached = _img_cache.get(url)
    if cached and os.path.exists(cached):
        return cached

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
                _img_cache[url] = path
                return path
        except Exception:
            pass
        if i < attempts - 1:
            time.sleep(0.4)
    return None


def prefetch(url: str):
    """Download (and cache) an image without rendering it. Pure I/O, releases
    the GIL — safe to run with high concurrency in a download pool so covers
    are on disk by the time the (CPU-bound, low-concurrency) chafa render runs."""
    return _download(url)


def _cleanup_images():
    for p in _img_cache.values():
        try:
            os.remove(p)
        except OSError:
            pass
    _img_cache.clear()


try:
    import atexit as _atexit
    _atexit.register(_cleanup_images)
except Exception:  # pragma: no cover
    pass


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


_text_cache = {}


def render_to_text(url: str, cols: int = 30, rows: int = 16):
    """
    Render an image as a rich Text of coloured Unicode blocks (chafa
    --format symbols → Text.from_ansi), so it can live INSIDE a rich Layout
    (the preview pane). Cached per (url, size). Returns an empty Text if it
    can't render (no chafa / download failed).
    """
    from rich.text import Text

    key = (url, cols, rows)
    if key in _text_cache:
        return _text_cache[key]

    result = Text("")
    if url and chafa_available():
        path = _download(url)
        if path:
            try:
                out = subprocess.run(
                    [_CHAFA_PATH, "--format", "symbols", "--size", f"{cols}x{rows}", path],
                    capture_output=True, text=True, timeout=8,
                ).stdout
                if out:
                    result = Text.from_ansi(out)
            except Exception:
                pass
    _text_cache[key] = result
    return result


def get_cached_text(url: str, cols: int = 30, rows: int = 16):
    """
    Return the already-rendered Text for (url, size) from cache, or None if
    it hasn't been rendered yet. NEVER does network/chafa work — safe to call
    from a UI render loop (the actual rendering is done in a background
    thread via render_to_text()).
    """
    return _text_cache.get((url, cols, rows))


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
