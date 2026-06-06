"""
Themed progress bars + loading screens (the ``▰▰▱`` style).

One place for every "something is happening" visual so they all share the
look and follow the active colour theme:

  * bar(frac)          -> a determinate ▰▰▱ bar (0..1)
  * indeterminate(t)   -> an animated bouncing ▰ block (unknown progress)
  * LoadingScreen      -> full-screen FreeFlix logo + bar + status line,
                          animated on a background thread (launch / install)
  * run_download_with_bar(...) -> run yt-dlp / aria2c, SWALLOW their noisy
                          logs and show a clean bar with speed + sizes + ETA.

Everything degrades gracefully: on a non-interactive terminal the loading
screen is a no-op and the download runner just streams the backend normally.
"""

import os
import re
import subprocess
import threading
import time

from rich.console import Group
from rich.text import Text
from rich.align import Align
from rich.live import Live
from rich.panel import Panel

from .cli_utils import console
from .themes import color
from .icons import icon

FILLED = "▰"
EMPTY = "▱"


# ─── Bars ─────────────────────────────────────────────────────────────
def bar(frac: float, width: int = 26) -> Text:
    """A determinate ▰▰▱ bar for ``frac`` in [0, 1], themed."""
    try:
        frac = max(0.0, min(1.0, float(frac)))
    except (TypeError, ValueError):
        frac = 0.0
    n = int(round(frac * width))
    t = Text()
    t.append(FILLED * n, style=color("accent"))
    t.append(EMPTY * (width - n), style=color("dim"))
    return t


def indeterminate(tick: int, width: int = 26) -> Text:
    """An animated ▰ block bouncing across an empty ▱ track (unknown %)."""
    span = 4
    travel = max(1, width - span)
    period = travel * 2
    p = tick % period
    start = p if p <= travel else period - p
    t = Text()
    for i in range(width):
        on = start <= i < start + span
        t.append(FILLED if on else EMPTY,
                 style=color("accent") if on else color("dim"))
    return t


# ─── Loading screen (logo + bar + status) ─────────────────────────────
class LoadingScreen:
    """
    Full-screen FreeFlix splash with a live progress bar, animated on a
    background thread so the foreground can do real work (checks, installs)
    and just call ``.status(text, frac)`` to update it.

    Use as a context manager::

        with LoadingScreen(version="1.6.0") as ls:
            ls.status("Checking dependencies…")
            ...
            ls.status("Installing mpv", frac=0.5)

    On a non-tty it's a silent no-op.
    """

    def __init__(self, version: str = "", status: str = "Starting up…"):
        self.version = version
        self._status = status
        self._frac = None          # None -> indeterminate animation
        self._tick = 0
        self._stop = threading.Event()
        self._thread = None
        self._live = None
        self._active = False

    # public API -------------------------------------------------------
    def status(self, text: str = None, frac: float = None):
        if text is not None:
            self._status = text
        self._frac = frac
        if not self._active:  # fallback echo when there's no live screen
            return

    def __enter__(self):
        if not console.is_terminal:
            return self
        try:
            self._live = Live(self._render(), console=console,
                              refresh_per_second=20, screen=True, transient=True)
            self._live.start()
            self._active = True
            self._thread = threading.Thread(target=self._animate, daemon=True)
            self._thread.start()
        except Exception:
            self._active = False
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        if self._live:
            try:
                self._live.stop()
            except Exception:
                pass
        self._active = False
        return False

    # internals --------------------------------------------------------
    def _animate(self):
        while not self._stop.is_set():
            self._tick += 1
            try:
                if self._live:
                    self._live.update(self._render())
            except Exception:
                pass
            time.sleep(0.06)

    def _render(self):
        w = console.size.width
        h = console.size.height
        from . import splash
        body = [splash.logo_renderable(w, h), Text("")]
        body.append(Align.center(splash.tagline_text(w)))
        if self.version:
            body.append(Align.center(Text(f"v{self.version}", style=color("dim"))))
        body.append(Text(""))

        track = self._frac if self._frac is not None else None
        b = bar(track, 28) if track is not None else indeterminate(self._tick, 28)
        pct = f"  {int(track * 100):3d}%" if track is not None else ""
        body.append(Align.center(Text.assemble(b, (pct, color("info")))))
        body.append(Text(""))
        body.append(Align.center(Text(self._status, style=color("dim"))))

        inner = Group(*body)
        # Vertically center the whole thing on the screen.
        return Align.center(inner, vertical="middle", height=max(8, h - 1))


# ─── Download progress (filters yt-dlp / aria2c logs) ─────────────────
_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_FRAG = re.compile(r"frag\s+(\d+)\s*/\s*(\d+)")
_SPEED = re.compile(r"(\d+(?:\.\d+)?\s*[KMGT]i?B/s)")
_DL_ARIA = re.compile(r"DL:\s*(\d+(?:\.\d+)?\s*[KMGT]i?B)")
_SIZES = re.compile(r"(\d+(?:\.\d+)?\s*[KMGT]i?B)\s*/\s*(\d+(?:\.\d+)?\s*[KMGT]i?B)")
_OF = re.compile(r"\bof\s+~?\s*(\d+(?:\.\d+)?\s*[KMGT]i?B)")
_ETA = re.compile(r"ETA[:\s]+(\d{1,2}:\d{2}(?::\d{2})?|\d+s)")


def parse_progress(line: str) -> dict:
    """Best-effort extract {frac, speed, downloaded, total, eta} from a
    yt-dlp or aria2c progress line. Any field may be None."""
    info = {"frac": None, "speed": None, "downloaded": None,
            "total": None, "eta": None}

    m = _FRAG.search(line)          # HLS overall (frag i/N) wins
    if m and int(m.group(2)):
        info["frac"] = int(m.group(1)) / int(m.group(2))
    else:
        m = _PCT.search(line)
        if m:
            info["frac"] = float(m.group(1)) / 100.0

    m = _SPEED.search(line)
    if m:
        info["speed"] = re.sub(r"\s+", "", m.group(1))
    else:
        m = _DL_ARIA.search(line)   # aria2c "DL:5.2MiB" -> per second
        if m:
            info["speed"] = re.sub(r"\s+", "", m.group(1)) + "/s"

    m = _SIZES.search(line)
    if m:
        info["downloaded"] = re.sub(r"\s+", "", m.group(1))
        info["total"] = re.sub(r"\s+", "", m.group(2))
    else:
        m = _OF.search(line)
        if m:
            info["total"] = re.sub(r"\s+", "", m.group(1))

    m = _ETA.search(line)
    if m:
        info["eta"] = m.group(1)
    return info


def _render_download(title: str, info: dict, tick: int) -> Panel:
    frac = info.get("frac")
    head = Text.assemble(
        (f"{icon('download')} ", color("accent")),
        (title, f"bold {color('header')}"),
    )

    if frac is not None:
        b = bar(frac, 28)
        pct = f"  {int(frac * 100):3d}%"
    else:
        b = indeterminate(tick, 28)
        pct = ""
    barline = Text.assemble(b, (pct, color("info")))

    det = []
    if info.get("downloaded") and info.get("total"):
        det.append(f"{info['downloaded']} / {info['total']}")
    elif info.get("total"):
        det.append(f"~{info['total']}")
    if info.get("speed"):
        det.append(f"{icon('stats')} {info['speed']}")
    if info.get("eta"):
        det.append(f"ETA {info['eta']}")
    detail = Text("   ".join(det) if det else "starting…", style=color("dim"))

    # A centered box, not a full-width banner : clamp to a sane width.
    box_w = max(34, min(60, console.size.width - 8))
    return Panel(
        Group(head, Text(""), barline, Text(""), detail),
        border_style=color("border"),
        title=Text("Download", style=color("info")),
        padding=(0, 2),
        width=box_w,
    )


def run_download_with_bar(cmd: list, title: str, extra_env: dict = None) -> int:
    """
    Run a download command (yt-dlp / aria2c), hide its raw logs, and show a
    clean themed progress bar (speed, downloaded/total, ETA) instead.

    Returns the process exit code. Falls back to a normal streamed run on a
    non-tty or if anything in the live UI goes wrong, so downloads never break.
    """
    env = None
    if extra_env:
        env = dict(os.environ)
        env.update(extra_env)

    if not console.is_terminal:
        return subprocess.run(cmd, env=env).returncode

    state = {"line": "", "tail": [], "done": False}

    def _reader(proc):
        buf = b""
        try:
            while True:
                chunk = proc.stdout.read(256)
                if not chunk:
                    break
                buf += chunk
                # yt-dlp / aria2c update progress with \r ; split on both.
                parts = re.split(rb"[\r\n]", buf)
                buf = parts.pop()
                for raw in parts:
                    s = raw.decode("utf-8", "replace").strip()
                    if not s:
                        continue
                    state["line"] = s
                    state["tail"].append(s)
                    if len(state["tail"]) > 10:
                        state["tail"].pop(0)
        except Exception:
            pass
        finally:
            state["done"] = True

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, env=env,
        )
    except Exception:
        # Couldn't even start under capture — fall back to a plain run.
        return subprocess.run(cmd, env=env).returncode

    reader = threading.Thread(target=_reader, args=(proc,), daemon=True)
    reader.start()

    def _frame(info, tick):
        # Full-screen, vertically centered → repaints whole screen each frame,
        # so a resize reflows cleanly and nothing is left behind on exit.
        h = max(8, console.size.height - 1)
        return Align.center(_render_download(title, info, tick),
                            vertical="middle", height=h)

    tick = 0
    last = {"frac": None, "speed": None, "downloaded": None,
            "total": None, "eta": None}
    seen_ytdlp = False
    try:
        # screen=True : alternate buffer, fully responsive, erases on exit.
        with Live(_frame(last, 0), console=console,
                  refresh_per_second=12, screen=True) as live:
            while not state["done"] or proc.poll() is None:
                tick += 1
                line = state["line"]
                if line:
                    info = parse_progress(line)
                    if "[download]" in line:
                        seen_ytdlp = True
                    # Fraction source, kept STABLE/monotonic:
                    #  * yt-dlp HLS -> only yt-dlp's own "[download] … (frag a/b)"
                    #    lines count ; aria2c's interleaved per-fragment lines are
                    #    used for speed only, never the bar (no backward jumps).
                    #  * pure aria2c (direct .mp4) -> its single-file % is overall.
                    use_for_frac = ("[download]" in line) if seen_ytdlp else True
                    if info["frac"] is not None and use_for_frac:
                        if last["frac"] is None or info["frac"] >= last["frac"]:
                            last["frac"] = info["frac"]
                    for k in ("speed", "eta", "downloaded", "total"):
                        if info[k]:
                            last[k] = info[k]
                live.update(_frame(last, tick))
                time.sleep(0.08)
            if last["frac"] is not None:
                last["frac"] = max(last["frac"], 0.999)
            live.update(_frame(last, tick))
    except KeyboardInterrupt:
        try:
            proc.terminate()
        except Exception:
            pass
        raise
    except Exception:
        # UI failed mid-flight — let the process finish without the bar.
        pass

    proc.wait()
    reader.join(timeout=0.5)
    return proc.returncode
