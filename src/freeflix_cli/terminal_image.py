"""
Render posters INSIDE the terminal, via chafa — as REAL PIXELS when possible.

chafa is only the encoder; the goal is to *avoid* its blocky Unicode-block
output and use a true graphics protocol whenever the terminal speaks one, so
posters look photo-sharp instead of like coloured ▀▄ mosaics:

  • kitty graphics  → Kitty, Ghostty, WezTerm            (sharpest)
  • iTerm2 inline   → iTerm2 (macOS), WezTerm
  • sixel           → KDE Konsole, foot, Windows Terminal, xterm(+sixel)…
  • Unicode blocks  → universal last-resort fallback (any terminal, SSH, cmd)

``detect_image_protocol`` picks the best one; sixel is confirmed by ASKING the
terminal (DA1) so we never paint escape garbage on a terminal where sixel is
merely *possible* but currently off (e.g. Konsole's default).

Everything degrades gracefully :
  * chafa not installed         → functions are no-ops (return False) ;
  * image download fails        → no-op ;
  * poster mode set to "off"    → no-op ;
  * no pixel protocol           → coloured Unicode blocks.

So the rest of the app can call render_url() unconditionally, on any OS.
"""

from __future__ import annotations  # `str | None` annotations work on Python 3.9

import os
import re
import shutil
import subprocess
import tempfile

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
    """Forget cached probes (call after installing chafa or toggling the
    terminal's Sixel setting) so protocol detection re-runs fresh."""
    global _CHAFA_PATH, _CHAFA_VER, _SIXEL_OK
    _CHAFA_PATH = None
    _CHAFA_VER = None
    _SIXEL_OK = None


_CHAFA_VER = None


def _chafa_version() -> tuple:
    """(major, minor) of the installed chafa, cached. (0, 0) if unknown."""
    global _CHAFA_VER
    if _CHAFA_VER is None:
        _CHAFA_VER = (0, 0)
        try:
            out = subprocess.run([_CHAFA_PATH, "--version"],
                                 capture_output=True, text=True, timeout=3,
                                 encoding="utf-8", errors="replace").stdout or ""
            m = re.search(r"(\d+)\.(\d+)", out)
            if m:
                _CHAFA_VER = (int(m.group(1)), int(m.group(2)))
        except Exception:
            pass
    return _CHAFA_VER


def _int(s) -> int:
    """Parse an int from a string (e.g. KONSOLE_VERSION='260403'), else 0."""
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def detect_image_protocol() -> str:
    """
    The best REAL-PIXEL image protocol the current terminal speaks, so we hand
    chafa a graphics format (photo-quality) instead of Unicode blocks. Returns
    'kitty' | 'iterm' | 'sixel' | 'auto'.

    Detection is env-based (zero-risk, cross-platform: Linux / macOS / Windows)
    and covers every mainstream pixel-capable terminal. 'auto' means "let chafa
    autodetect" — a safe fallback that still upgrades on some terminals.

    Pixel support by terminal (all handled below):
      • kitty protocol : Kitty, Ghostty, WezTerm            (chafa ≥ 1.12)
      • iTerm2 inline  : iTerm2 (macOS), WezTerm             (chafa ≥ 1.6)
      • sixel          : Konsole, foot, Windows Terminal,
                         contour, mlterm, xterm(+sixel), rio (chafa ≥ 1.4)
    """
    env = os.environ
    term = (env.get("TERM") or "").lower()
    prog = (env.get("TERM_PROGRAM") or "").lower()
    ver = _chafa_version()

    # 1) kitty graphics protocol — sharpest. Kitty / Ghostty / WezTerm.
    if ver >= (1, 12) and (
        env.get("KITTY_WINDOW_ID") or "kitty" in term
        or prog == "ghostty" or env.get("GHOSTTY_RESOURCES_DIR")
        or "WEZTERM_PANE" in env
    ):
        return "kitty"

    # 2) iTerm2 inline images — macOS iTerm2.
    if ver >= (1, 6) and (prog == "iterm.app" or env.get("ITERM_SESSION_ID")):
        return "iterm"

    # 3) sixel — the widest pixel protocol (Konsole, foot, Windows Terminal,
    #    contour, mlterm, rio, sixel-enabled xterm).
    if ver >= (1, 4):
        # Terminals where sixel is ALWAYS ON (no toggle) → trust the env, because
        # many of them (Konsole included) don't advertise sixel in their DA1
        # reply, so the query below would wrongly say "no" and we'd fall back to
        # blocks. Konsole has shipped sixel enabled-by-default since 22.12
        # (KONSOLE_VERSION 221200); foot always supports it.
        kv = _int(env.get("KONSOLE_VERSION"))
        if kv >= 221200 or "foot" in term:
            return "sixel"
        # Otherwise CONFIRM via DA1 — covers Windows Terminal (opt-in), contour,
        # mlterm, rio, and sixel-enabled xterm — and, crucially, never emits
        # sixel to a terminal that has it OFF (which would paint escape garbage).
        if _terminal_supports_sixel():
            return "sixel"

    return "auto"


# Tri-state cache : None = not probed yet, True/False = probe result.
_SIXEL_OK = None


def _terminal_supports_sixel() -> bool:
    """Ask the terminal (Primary Device Attributes) whether sixel is ACTIVE.

    Sends ``ESC [ c`` and parses the reply ``ESC [ ? … c`` : attribute ``4``
    means sixel. Universal (every VT100+ terminal answers DA1) and authoritative
    — it reflects whether sixel is actually enabled RIGHT NOW, not just that the
    emulator could do it. Cached; best-effort (any issue → False → blocks).

    Must run on the MAIN thread (it briefly puts the tty in cbreak mode); the
    inline-blocks path never calls it, and the full-screen render does so from
    the main thread. Windows has no termios, so we trust Windows Terminal's env.
    """
    global _SIXEL_OK
    if _SIXEL_OK is not None:
        return _SIXEL_OK
    _SIXEL_OK = False
    try:
        import sys
        if os.name == "nt":
            # Windows has no termios, so DA1 can't be queried — and WT_SESSION
            # only proves the terminal IS Windows Terminal, NOT that its
            # opt-in "Experimental: Sixel" flag is enabled (off by default).
            # Trusting it painted sixels that never render → blank preview
            # pane and blank full-screen posters. Fail closed (blocks) ;
            # users who really enabled Sixel can force poster mode "sixel".
            _SIXEL_OK = False
            return _SIXEL_OK
        import termios
        import tty
        import select as _sel
        fdin, fdout = sys.stdin.fileno(), sys.stdout.fileno()
        if not (os.isatty(fdin) and os.isatty(fdout)):
            return False
        old = termios.tcgetattr(fdin)
        buf = b""
        try:
            tty.setcbreak(fdin)
            os.write(fdout, b"\x1b[c")
            import time as _t
            deadline = _t.time() + 0.4
            while _t.time() < deadline:
                r, _, _ = _sel.select([fdin], [], [], max(0.0, deadline - _t.time()))
                if not r:
                    break
                chunk = os.read(fdin, 128)
                if not chunk:
                    break
                buf += chunk
                if b"c" in chunk:
                    break
        finally:
            termios.tcsetattr(fdin, termios.TCSADRAIN, old)
            try:
                termios.tcflush(fdin, termios.TCIFLUSH)  # drop any stray bytes
            except Exception:
                pass
        m = re.search(rb"\x1b\[\?([0-9;]+)c", buf)
        if m:
            _SIXEL_OK = b"4" in m.group(1).split(b";")
    except Exception:
        _SIXEL_OK = False
    return _SIXEL_OK


def warm_up() -> str:
    """Probe the terminal ONCE, on the main thread, at startup — before any
    Rich Live grabs the tty — so the sixel DA1 query never races the UI. Returns
    the detected protocol (also caches it). Safe no-op if chafa is absent."""
    try:
        return detect_image_protocol()
    except Exception:
        return "auto"


def sixel_hint() -> str | None:
    """A one-line tip when the terminal is a KNOWN sixel-capable one but sixel
    came back OFF — so the user can flip it on for photo-sharp posters. Returns
    None when nothing to say (kitty/iterm/other, or sixel already on)."""
    env = os.environ
    if detect_image_protocol() != "auto":
        return None  # already using a real pixel protocol
    if env.get("KONSOLE_VERSION"):
        return ("Konsole can show photo-sharp posters via Sixel — enable it in "
                "Settings → Edit Profile → Terminal Features → Sixel graphics.")
    if env.get("WT_SESSION"):
        return ("Windows Terminal can show sharper posters via Sixel — enable "
                "\"Experimental: Sixel\" in its settings.")
    return None


def _render_format(mode: str):
    """chafa --format value for the full-screen poster, or None to let chafa
    autodetect. `mode` is the user's poster setting.

    'auto' now picks the sharpest protocol the terminal actually supports
    (kitty > iterm > sixel), so ANY pixel-capable terminal gets photo-quality
    posters instead of blocks — while unknown terminals fall back safely."""
    if mode == "sixel":
        return "sixels"
    if mode == "blocks":
        return "symbols"          # explicit user override → force Unicode blocks
    if mode == "auto":
        proto = detect_image_protocol()
        if proto == "kitty" or proto == "iterm":
            return proto
        if proto == "sixel":
            return "sixels"
    return None


def _color_args() -> list:
    """
    Force full (truecolor) output when the terminal advertises it, so posters
    stay sharp. Cross-distro/SSH sessions often don't propagate COLORTERM, so
    chafa mis-detects the depth and falls back to 256/16 colors → visibly
    BLURRY / banded. We only UPGRADE to full when we're sure (COLORTERM says
    truecolor) — never downgrade — so this can't make any terminal look worse.
    """
    ct = (os.environ.get("COLORTERM") or "").lower()
    if "truecolor" in ct or "24bit" in ct:
        return ["--colors", "full"]
    return []


def _quality_args() -> list:
    """Max chafa work factor : better symbol/color matching → noticeably sharper
    output (posters are small, so the extra CPU is negligible)."""
    return ["--work", "9"]


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


def _is_fast_cdn(url: str) -> bool:
    """High-resolution, fast CDNs we fetch DIRECTLY (no wsrv resize) to keep the
    full detail. They serve chafa-readable JPEG. (jsdelivr/anime-sama is fast too
    but serves WEBP thumbnails → we route those through wsrv for jpg + resize.)"""
    u = url or ""
    return ("image.tmdb.org" in u or "s4.anilist.co" in u
            or "m.media-amazon.com" in u)


def _upgrade_source(url: str) -> str:
    """Bump a low-res cover URL to full resolution so a LARGE on-screen poster
    keeps real detail (faces, small text) instead of an upscaled blur. Covers
    every CDN our sources use; unknown hosts are returned unchanged.

      • TMDB (Coflix/French-Stream/Papystreaming/French-Manga):
            …/t/p/w400/…  →  …/t/p/original/…   (full ~1500–2000 px scan)
      • IMDB / Amazon via Cinemeta (GoldenMS):
            …._V1_SX250.jpg  →  …._V1_SX1000.jpg  (250 px → 1000 px)

    AniList (GoldenAnime) is handled at the SOURCE instead — its per-size file
    names differ, so the URL can't be rewritten; the scraper asks for
    ``coverImage.extraLarge`` directly. The bigger file is downloaded ONCE,
    cached, and chafa downscales it to the pane — so it only ever helps."""
    if not url:
        return url
    url = re.sub(r"(image\.tmdb\.org/t/p/)(?:w\d+|original)/", r"\1original/", url)
    url = re.sub(r"(m\.media-amazon\.com/images/[^ ]*?\._V1_)[A-Za-z0-9_,]*(\.jpg)",
                 r"\1SX1000\2", url, flags=re.IGNORECASE)
    return url


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

    # Reuse the already-downloaded file if we still have it (keyed by the
    # ORIGINAL url so callers are unchanged).
    cached = _img_cache.get(url)
    if cached and os.path.exists(cached):
        return cached

    # Fetch a HIGHER-RESOLUTION source when we can, so a large on-screen poster
    # keeps real detail (faces, small text) instead of an upscaled blur. Many
    # covers are TMDB `…/t/p/w400/…` (only 400 px wide) — bump the size segment.
    src = _upgrade_source(url)

    # Fetch order:
    #  • Fast, high-res CDNs (TMDB / AniList / Metahub) → fetch the upgraded URL
    #    DIRECTLY so we keep the full resolution (wsrv would resize it DOWN to
    #    its width and cost us the detail we just gained). wsrv stays as a
    #    fallback if the direct fetch fails.
    #  • Everything else (slow/throttled origin hosts) → wsrv first (it resizes
    #    + serves from a fast CDN), origin as fallback.
    if _is_fast_cdn(src):
        fetch_urls = [u for u in (src, _fast_url(src)) if u]
    else:
        fetch_urls = [u for u in (_fast_url(src), src) if u]

    # One quick attempt per URL (wsrv CDN first, then the origin). A short 8 s
    # timeout keeps a throttled host from stalling the poster for tens of
    # seconds — a missing cover is far better than a frozen UI.
    for fetch_url in fetch_urls:
        try:
            r = _rq.get(fetch_url, impersonate="chrome", timeout=8)
            if r.status_code == 200 and r.content:
                fd, path = tempfile.mkstemp(prefix="freeflix_poster_", suffix=".jpg")
                with os.fdopen(fd, "wb") as f:
                    f.write(r.content)
                _img_cache[url] = path
                return path
        except Exception:
            pass
    return None


def _fast_url(url: str, width: int = 720) -> str:
    """Rewrite a cover URL to go through wsrv.nl, which resizes it to `width`px
    and serves it from a fast CDN — small + quick, even when the source host is
    slow/throttled. Returns "" for already-proxied URLs.

    720px + q=90 keeps the download tiny (~80 KB) while giving the SIXEL renderer
    enough source pixels that the poster never blurs from upscaling, even in a
    large/maximised window."""
    if not url or "wsrv.nl" in url:
        return ""
    import urllib.parse
    src = url.split("://", 1)[-1]  # wsrv wants the URL without the scheme
    return ("https://wsrv.nl/?url=" + urllib.parse.quote(src, safe="")
            + f"&w={width}&q=90&output=jpg")


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
        cmd += _color_args()      # crisp truecolor when the terminal supports it
        cmd += _quality_args()    # max work factor → sharper
        # Prefer a real graphics protocol (kitty/iterm = photo quality) when we
        # can confirm the terminal speaks it; "sixel" forces sixels; otherwise
        # leave it to chafa's own autodetection (blocks as a last resort).
        fmt = _render_format(mode)
        if fmt:
            cmd += ["--format", fmt]
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
    ok = False
    if url and chafa_available():
        path = _download(url)
        if path:
            try:
                # encoding="utf-8" is REQUIRED : chafa emits UTF-8 block glyphs
                # (▀▄) + truecolor escapes. Without it, text=True decodes with
                # the locale codec — cp1252 on Windows — and raises
                # UnicodeDecodeError, so posters silently never rendered during
                # search on Windows (only the direct full-screen render worked).
                out = subprocess.run(
                    [_CHAFA_PATH, "--format", "symbols", *_color_args(),
                     *_quality_args(), "--size", f"{cols}x{rows}", path],
                    capture_output=True, text=True, timeout=8,
                    encoding="utf-8", errors="replace",
                ).stdout
                if out:
                    result = Text.from_ansi(out)
                    ok = True
            except Exception:
                pass
    # Only cache a SUCCESSFUL render. Caching an empty result used to make a
    # transient download/render failure permanent ("sometimes never shows") —
    # now a later attempt can still succeed.
    if ok:
        _text_cache[key] = result
    return result


# ── SIXEL overlay for the live search-list preview ────────────────────
# The inline preview (render_to_text) is blocky because it's captured Text in a
# Rich Layout. For photo-sharp pixels we instead paint chafa's SIXEL DIRECTLY to
# the terminal, positioned over a reserved region (done in cli_utils).
#
# CRUCIAL: chafa must write to the REAL terminal (not a captured pipe) — that's
# the only way it can ioctl(TIOCGWINSZ) for the true cell pixel size and render
# at native resolution. Capturing the output makes chafa assume a smaller cell
# → fewer pixels → an upscaled, BLURRY poster (the bug this replaces). This is
# exactly what render_url/show_poster does, which is why those are sharp.
def get_download_path(url: str):
    """The local path of `url`'s already-downloaded image, or None. Pure cache
    lookup — never hits the network, so it's safe to poll from the UI loop
    (the download itself is done in the background via prefetch())."""
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    p = _img_cache.get(url)
    return p if (p and os.path.exists(p)) else None


def render_sixel_positioned(url: str, cols: int, rows: int,
                            row: int, col: int, out_fd: int) -> bool:
    """Paint `url`'s cover as SIXEL at screen cell (row, col), sized cols×rows,
    writing straight to `out_fd` (the terminal) so chafa renders at native
    resolution — SHARP, same as the full-screen poster. Cursor is saved/restored
    so the surrounding Rich frame is undisturbed. No-op (False) until the image
    is downloaded; never blocks the UI (no network here). stdin is /dev/null so
    chafa can't touch the keyboard, and the format is forced (no capability
    query)."""
    path = get_download_path(url)
    if not path or not chafa_available():
        return False
    try:
        os.write(out_fd, b"\x1b7" + ("\x1b[%d;%dH" % (row, col)).encode())
        subprocess.run(
            [_CHAFA_PATH, "--format", "sixels", *_color_args(), *_quality_args(),
             "--size", f"{cols}x{rows}", path],
            stdin=subprocess.DEVNULL, stdout=out_fd, stderr=subprocess.DEVNULL,
            timeout=8,
        )
        os.write(out_fd, b"\x1b8")
        return True
    except Exception:
        try:
            os.write(out_fd, b"\x1b8")
        except Exception:
            pass
        return False


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
