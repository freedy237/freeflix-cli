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
# A size suffix: optional [KMGT] + optional i + B, or just plain B.
_SZ = r"(?:\d+(?:\.\d+)?\s*(?:[KMGT]i?)?B)"

_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_FRAG = re.compile(r"frag\s+(\d+)\s*/\s*(\d+)")
_SPEED = re.compile(r"(\d+(?:\.\d+)?\s*[KMGT]i?B/s)")
_DL_ARIA = re.compile(r"DL:\s*(" + _SZ + r")")
_SIZES = re.compile(r"(" + _SZ + r")\s*/\s*(" + _SZ + r")")
_OF = re.compile(r"\bof\s+~?\s*(" + _SZ + r")")
_ETA = re.compile(r"ETA[:\s]+([\d:mshdMSHD]+)")


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


def _render_download(title: str, info: dict, tick: int,
                     cancel_hint: str = None) -> Panel:
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
    dl, tot = info.get("downloaded"), info.get("total")
    if dl and tot:
        det.append(f"{dl} / {tot}")
    elif tot:
        det.append(f"~{tot}")
    elif dl:
        # Unknown total (e.g. sibnet serves the mp4 with no Content-Length, so
        # aria2c reports X/0B and there's no % to show) — still show how much
        # has come down so the user sees real activity, not "starting…".
        det.append(dl)
    if info.get("speed"):
        det.append(f"{icon('stats')} {info['speed']}")
    if info.get("eta"):
        det.append(f"ETA {info['eta']}")
    detail = Text("   ".join(det) if det else "starting…", style=color("dim"))

    body = [head, Text(""), barline, Text(""), detail]
    if cancel_hint:
        body.append(Text(""))
        body.append(Text(cancel_hint, style=color("warning")
                         if cancel_hint.startswith("!") else color("dim")))

    # A centered box, not a full-width banner : clamp to a sane width.
    box_w = max(34, min(60, console.size.width - 8))
    return Panel(
        Group(*body),
        border_style=color("border"),
        title=Text("Download", style=color("info")),
        padding=(0, 2),
        width=box_w,
    )


_download_screen_lock = threading.Lock()


class _EscCancel:
    """
    Non-blocking "press Esc twice to cancel" detector for the download screens.

    Used as a context manager : it puts the terminal in cbreak mode on enter
    and restores it on exit. ``poll()`` returns True once the user has pressed
    Esc twice (either in one burst, or within 2 s). Arrow/CSI escape sequences
    (``\\x1b[…``) are ignored so they don't count as Esc. No-op on a non-tty
    (Windows / piped) — there, Ctrl-C stays the way to abort.
    """

    def __init__(self):
        self._fd = None
        self._old = None
        self._armed = 0.0
        self.active = False

    def __enter__(self):
        import sys
        try:
            import termios
            import tty
            if sys.stdin.isatty():
                self._fd = sys.stdin.fileno()
                self._old = termios.tcgetattr(self._fd)
                tty.setcbreak(self._fd)
                self.active = True
        except Exception:
            self.active = False
        return self

    def poll(self) -> bool:
        if not self.active:
            return False
        import os
        import select
        try:
            r, _, _ = select.select([self._fd], [], [], 0)
            if not r:
                return False
            data = os.read(self._fd, 32)
        except Exception:
            return False
        escs, i = 0, 0
        while i < len(data):
            if data[i:i + 1] == b"\x1b":
                if data[i + 1:i + 2] in (b"[", b"O"):
                    i += 3  # arrow / CSI sequence — not a lone Esc
                    continue
                escs += 1
            i += 1
        if escs >= 2:
            return True
        if escs == 1:
            now = time.monotonic()
            if self._armed and now - self._armed <= 2.0:
                return True
            self._armed = now
        return False

    @property
    def armed(self) -> bool:
        return bool(self._armed) and time.monotonic() - self._armed <= 2.0

    def hint(self) -> str:
        if not self.active:
            return ""
        return "! Esc again to cancel" if self.armed else "Esc Esc : cancel"

    def __exit__(self, *exc):
        if self._old is not None:
            try:
                import termios
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            except Exception:
                pass
        return False


class BatchView:
    """Shared progress for N parallel downloads — renders all at once.

    Thread‑safe: workers call ``.update(title, info)`` from any thread ;
    the main thread calls ``.render(tick, series_title)`` for the Live display.
    """

    def __init__(self, labels: list[str]):
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        for lb in labels:
            self._data[lb] = {"frac": None, "speed": None,
                              "downloaded": None, "total": None,
                              "done": False, "ok": None}
        self._items = list(labels)
        self._cancel = threading.Event()

    def cancel(self):
        """Signal all running download workers to abort (Esc Esc)."""
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def update(self, label: str, info: dict):
        """Called by a worker thread with each parsed progress tick."""
        with self._lock:
            ep = self._data.get(label)
            if ep is None:
                return
            for k in ("frac", "speed", "downloaded", "total", "eta"):
                v = info.get(k)
                if v is not None:
                    ep[k] = v

    def mark_done(self, label: str, ok: bool):
        """Called when a worker finishes (success or failure)."""
        with self._lock:
            ep = self._data.get(label)
            if ep is None:
                return
            ep["done"] = True
            ep["ok"] = ok
            if ok:
                ep["frac"] = max(ep.get("frac") or 0, 0.999)
                if not ep.get("downloaded"):
                    ep["downloaded"] = "✓"
                if not ep.get("speed"):
                    ep["speed"] = "done"

    @property
    def finished(self) -> bool:
        with self._lock:
            return all(ep["done"] for ep in self._data.values())

    def render(self, tick: int, series_title: str) -> Panel:
        """Build a single Panel showing all episodes and their progress."""
        with self._lock:
            data = {k: dict(v) for k, v in self._data.items()}

        total = len(data)
        done = sum(1 for v in data.values() if v["ok"])
        head = Text.assemble(
            (f"{icon('download')} ", color("accent")),
            (series_title, f"bold {color('header')}"),
            (f"  [{done}/{total}]", color("info")),
        )

        box_w = max(60, min(90, console.size.width - 6))
        inner = box_w - 6  # border(2) + padding(4)

        body = []
        for label, ep in data.items():
            frac = ep["frac"]
            speed = ep.get("speed") or ""
            dl = ep.get("downloaded") or ""
            status_char = "✓" if ep["ok"] else ("✗" if ep["done"] else " ")
            # reserve space for: status(2) + spaces(4) + pct(5) + speed + dl
            label_w = min(32, inner - 30 - len(speed) - len(dl))
            bar_w = inner - label_w - 27 - len(speed) - len(dl)
            bar_w = max(4, min(bar_w, 26))
            if frac is not None:
                b = bar(frac, bar_w)
                pct = f"  {int(frac * 100):2d}%"
            else:
                b = indeterminate(tick, bar_w)
                pct = ""
            line = Text.assemble(
                (f" {status_char} ", "green" if ep["ok"]
                 else "red" if ep["done"] else color("dim")),
                (label[:label_w].ljust(label_w), color("dim") if ep["done"] else ""),
                b,
                (pct, color("info")),
                ("  " + speed, color("dim")),
                ("  " + dl, color("dim")),
            )
            body.append(line)

        return Panel(
            Group(head, Text(""), *body),
            border_style=color("border"),
            title=Text("Batch Download", style=color("info")),
            padding=(0, 2),
            width=box_w,
        )


def run_download_with_bar(cmd: list, title: str, extra_env: dict = None,
                          batch_callback=None, cancel_check=None) -> int:
    """
    Run a download command (yt-dlp / aria2c), hide its raw logs, and show a
    clean themed progress bar (speed, downloaded/total, ETA) instead.

    Returns the process exit code. Falls back to a normal streamed run on a
    non-tty or if anything in the live UI goes wrong, so downloads never break.

    Thread‑safe for parallel downloads: a module‑level lock serialises access to
    the full‑screen ``Live(screen=True)`` display so only one themed progress
    bar is visible at a time.  The actual subprocess (yt-dlp / aria2c) is
    started *before* the lock is acquired, so all downloads run concurrently.
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
                parts = re.split(rb"[\r\n]", buf)
                buf = parts.pop()
                for raw in parts:
                    s = raw.decode("utf-8", "replace").strip()
                    if not s:
                        continue
                    state["tail"].append(s)
                    if len(state["tail"]) > 10:
                        state["tail"].pop(0)
                    # Keep ONLY progress-bearing lines as the "current" line.
                    # aria2c prints each "[#… (X%) … DL:…]" line inside a
                    # multi-line summary block (… / FILE:/ ---- / blank), and
                    # that trailing junk would otherwise overwrite the progress
                    # line before the UI loop (polling at ~12 fps) ever reads
                    # it — leaving the bar stuck on "starting". yt-dlp's
                    # "[download] X%" lines stand alone, hence they worked.
                    if ("%" in s or "[download]" in s
                            or s.startswith("[#") or "DL:" in s):
                        state["line"] = s
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
        return subprocess.run(cmd, env=env).returncode

    reader = threading.Thread(target=_reader, args=(proc,), daemon=True)
    reader.start()

    def _frame(info, tick, hint=None):
        h = max(8, console.size.height - 1)
        return Align.center(_render_download(title, info, tick, hint),
                            vertical="middle", height=h)

    tick = 0
    last = {"frac": None, "speed": None, "downloaded": None,
            "total": None, "eta": None}
    seen_ytdlp = False

    # ── Batch mode (no display, report to callback) ──────────────────
    if batch_callback is not None:
        while not state["done"] or proc.poll() is None:
            if cancel_check is not None and cancel_check():
                try:
                    proc.terminate()
                except Exception:
                    pass
                break
            tick += 1
            line = state["line"]
            if line:
                info = parse_progress(line)
                if "[download]" in line:
                    seen_ytdlp = True
                use_for_frac = ("[download]" in line) if seen_ytdlp else True
                if info["frac"] is not None and use_for_frac and info["frac"] > 0:
                    if last["frac"] is None or info["frac"] >= last["frac"]:
                        last["frac"] = info["frac"]
                for k in ("speed", "eta", "downloaded", "total"):
                    v = info[k]
                    if v and not re.match(
                        r"^0(?:\.0+)?\s*(?:[KMGT]?i?)?B(?:/s)?$", v
                    ):
                        last[k] = v
            batch_callback(title, dict(last))
            time.sleep(0.08)

        if last["frac"] is not None and last["frac"] > 0:
            last["frac"] = max(last["frac"], 0.999)
        elif last["frac"] is None:
            last["frac"] = 1.0
            last["downloaded"] = last.get("downloaded") or "✓"
            last["speed"] = last.get("speed") or "done"
        batch_callback(title, dict(last))

        proc.wait()
        reader.join(timeout=0.5)
        return proc.returncode

    # ── Normal mode (Live display) ──────────────────────────────────
    # Only one thread at a time may use the full-screen Live display.
    # Subprocess was started above, so downloads run concurrently.
    with _download_screen_lock:
        try:
            with _EscCancel() as esc, Live(
                _frame(last, 0, esc.hint()), console=console,
                refresh_per_second=12, screen=True,
            ) as live:
                while not state["done"] or proc.poll() is None:
                    if esc.poll():
                        # Esc pressed twice → abort, reusing the Ctrl-C path
                        # below (terminate the subprocess, leave the partial
                        # for resume).
                        raise KeyboardInterrupt("cancelled (Esc Esc)")
                    tick += 1
                    line = state["line"]
                    if line:
                        info = parse_progress(line)
                        if "[download]" in line:
                            seen_ytdlp = True
                        use_for_frac = ("[download]" in line) if seen_ytdlp else True
                        # Skip frac=0 so the bar stays indeterminate (bouncing
                        # blocks) instead of appearing "stuck at 0%".
                        if info["frac"] is not None and use_for_frac and info["frac"] > 0:
                            if last["frac"] is None or info["frac"] >= last["frac"]:
                                last["frac"] = info["frac"]
                        for k in ("speed", "eta", "downloaded", "total"):
                            v = info[k]
                            if v and not re.match(
                                r"^0(?:\.0+)?\s*(?:[KMGT]?i?)?B(?:/s)?$", v
                            ):
                                last[k] = v
                    live.update(_frame(last, tick, esc.hint()))
                    time.sleep(0.08)
            if last["frac"] is not None and last["frac"] > 0:
                last["frac"] = max(last["frac"], 0.999)
            elif last["frac"] is None:
                # Download finished without ever showing progress (very fast
                # file, or aria2c summary interval didn't fire before
                # completion).  Show as complete.
                last["frac"] = 1.0
                last["downloaded"] = last.get("downloaded") or "✓"
                last["speed"] = last.get("speed") or "done"
            live.update(_frame(last, tick))
        except KeyboardInterrupt:
            try:
                proc.terminate()
            except Exception:
                pass
            raise
        except Exception:
            pass

    proc.wait()
    reader.join(timeout=0.5)
    return proc.returncode



