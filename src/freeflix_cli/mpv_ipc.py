"""
Talk to a running mpv over its JSON IPC channel (``--input-ipc-server``).

Why : the old resume mechanism relied on a lua script writing the position to a
file *on exit*, so a crash / kill lost the position, and we never learned WHY
mpv stopped (finished vs quit). Over IPC we can :

  • save ``time-pos`` LIVE during playback (survives a crash) ;
  • learn the end reason (``eof`` → episode finished → auto-play next ;
    ``quit``/``stop`` → the user left → stop the binge).

Everything here is strictly best-effort : the caller keeps the lua-file path as
the authoritative fallback, and any IPC failure is swallowed so it can never
disrupt playback. Cross-platform : an AF_UNIX socket on Linux/macOS, a named
pipe (``\\\\.\\pipe\\…``) on Windows.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import uuid

_IS_WIN = sys.platform in ("win32", "cygwin")


def make_ipc_path() -> str:
    """A fresh, unique IPC endpoint path for one mpv launch."""
    tag = uuid.uuid4().hex[:12]
    if _IS_WIN:
        return rf"\\.\pipe\freeflix-mpv-{tag}"
    return os.path.join(tempfile.gettempdir(), f"freeflix-mpv-{tag}.sock")


class MpvIPC:
    """Minimal client for mpv's newline-delimited JSON IPC protocol."""

    def __init__(self, path: str):
        self.path = path
        self._conn = None          # socket (unix) or file object (win pipe)
        self._buf = b""
        self._req = 0

    # ── connection ────────────────────────────────────────────────
    def connect(self, timeout: float = 15.0) -> bool:
        """Wait for mpv to create the endpoint, then connect. Best-effort."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if _IS_WIN:
                    # mpv exposes the pipe as a file we can open r+b.
                    self._conn = open(self.path, "r+b", buffering=0)
                else:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.settimeout(1.0)
                    s.connect(self.path)
                    self._conn = s
                return True
            except (FileNotFoundError, ConnectionRefusedError, OSError):
                time.sleep(0.2)
        return False

    # ── low-level IO ──────────────────────────────────────────────
    def _write(self, data: bytes) -> None:
        if _IS_WIN:
            self._conn.write(data)
            self._conn.flush()
        else:
            self._conn.sendall(data)

    def _read_some(self) -> bytes:
        if _IS_WIN:
            return self._conn.read(4096) or b""
        return self._conn.recv(4096)

    def _next_line(self, timeout: float = 1.0):
        """Return the next complete JSON object (dict) or None on timeout/close."""
        end = time.time() + timeout
        while b"\n" not in self._buf:
            if time.time() > end:
                return None
            try:
                chunk = self._read_some()
            except socket.timeout:
                return None
            except Exception:
                return None
            if not chunk:
                return None  # peer closed (mpv exited)
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        line = line.strip()
        if not line:
            return {}
        try:
            return json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            return {}

    # ── commands ──────────────────────────────────────────────────
    def send_command(self, *args) -> int:
        """Fire a command (no reply wait). Returns its request_id. Best-effort."""
        self._req += 1
        rid = self._req
        payload = json.dumps({"command": list(args), "request_id": rid})
        try:
            self._write(payload.encode("utf-8") + b"\n")
        except Exception:
            pass
        return rid

    def close(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None


class PlaybackMonitor:
    """
    Runs a background thread that watches ONE mpv session over IPC, saving the
    live position through *on_position(pos, dur)* and recording the end reason.

    Usage :
        mon = PlaybackMonitor(path, on_position=save)
        mon.start()
        ...run mpv (blocks)...
        mon.stop()
        if mon.finished_naturally(): play_next()
    """

    def __init__(self, path: str, on_position=None, poll: float = 3.0):
        self.path = path
        self.on_position = on_position
        self.poll = poll
        self.end_reason = None          # "eof" | "quit" | "stop" | "error" | None
        self.last_pos = None
        self.last_dur = None
        self._stop = threading.Event()
        self._thread = None
        self._pending = {}   # request_id -> property name

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def finished_naturally(self) -> bool:
        """True if mpv reached end-of-file (as opposed to the user quitting)."""
        if self.end_reason == "eof":
            return True
        # Fallback : some builds don't emit end-file ; treat "watched to ~the
        # end" as finished so auto-next still works.
        if (self.last_pos is not None and self.last_dur and self.last_dur > 0
                and self.last_pos / self.last_dur >= 0.90):
            return True
        return False

    def _run(self) -> None:
        client = MpvIPC(self.path)
        try:
            if not client.connect():
                return
            next_poll = 0.0
            while not self._stop.is_set():
                now = time.time()
                if now >= next_poll:
                    self._pending[client.send_command("get_property", "time-pos")] = "time-pos"
                    self._pending[client.send_command("get_property", "duration")] = "duration"
                    next_poll = now + self.poll
                msg = client._next_line(timeout=0.5)
                if msg is None:
                    # timeout or mpv closed the socket
                    if client._conn is None:
                        break
                    continue
                self._handle(msg)
        except Exception:
            pass
        finally:
            # A final position read is done via whatever we last saw.
            if self.on_position and self.last_pos is not None:
                try:
                    self.on_position(self.last_pos, self.last_dur)
                except Exception:
                    pass
            client.close()

    def _handle(self, msg: dict) -> None:
        if not isinstance(msg, dict):
            return
        if "event" in msg:
            if msg["event"] == "end-file":
                self.end_reason = msg.get("reason") or self.end_reason
            return
        # get_property reply : {"data": <val>, "error": "success", "request_id"}.
        # Map it back to the property we asked for via the request_id.
        rid = msg.get("request_id")
        prop = self._pending.pop(rid, None) if rid is not None else None
        if prop is None or msg.get("error") != "success":
            return
        data = msg.get("data")
        if not isinstance(data, (int, float)):
            return
        if prop == "duration":
            self.last_dur = float(data)
        elif prop == "time-pos":
            self.last_pos = float(data)
            if self.on_position:
                try:
                    self.on_position(self.last_pos, self.last_dur)
                except Exception:
                    pass
