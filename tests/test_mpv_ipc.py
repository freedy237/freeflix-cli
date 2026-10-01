"""
Tests for the mpv JSON-IPC client (freeflix_cli.mpv_ipc).

A tiny fake "mpv" AF_UNIX server speaks the real protocol (newline-delimited
JSON : replies to get_property with the request_id echoed, and an end-file
event), so we can verify live position tracking + end-reason detection WITHOUT
a real mpv. AF_UNIX only → skipped on Windows.
"""

import json
import socket
import threading
import time

import pytest

from freeflix_cli import mpv_ipc

pytestmark = pytest.mark.skipif(mpv_ipc._IS_WIN, reason="AF_UNIX fake server is POSIX-only")


class _FakeMpv:
    """Answers get_property time-pos/duration and then emits end-file: eof."""

    def __init__(self, path, pos=118.0, dur=120.0, end_reason="eof"):
        self.path = path
        self.pos, self.dur, self.end_reason = pos, dur, end_reason
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(path)
        self._srv.listen(1)
        self._srv.settimeout(5)
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    def _serve(self):
        conn, _ = self._srv.accept()
        conn.settimeout(3)
        buf = b""
        replies = 0
        try:
            while True:
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    req = json.loads(line)
                    cmd = req.get("command", [])
                    rid = req.get("request_id")
                    if cmd[:1] == ["get_property"]:
                        prop = cmd[1]
                        val = self.pos if prop == "time-pos" else self.dur
                        conn.sendall(
                            (json.dumps({"data": val, "error": "success",
                                         "request_id": rid}) + "\n").encode()
                        )
                        replies += 1
                        if replies >= 2:  # after one pos+dur pair, end the file
                            conn.sendall(
                                (json.dumps({"event": "end-file",
                                             "reason": self.end_reason}) + "\n").encode()
                            )
        except Exception:
            pass
        finally:
            conn.close()

    def close(self):
        self._srv.close()


def test_connect_and_track_position_and_eof(tmp_path):
    path = str(tmp_path / "mpv.sock")
    fake = _FakeMpv(path, pos=118.0, dur=120.0, end_reason="eof")
    try:
        seen = []
        mon = mpv_ipc.PlaybackMonitor(path, on_position=lambda p, d: seen.append((p, d)), poll=0.2)
        mon.start()
        time.sleep(1.2)
        mon.stop()
        assert mon.last_pos == 118.0
        assert mon.last_dur == 120.0
        assert seen and seen[-1][0] == 118.0
        assert mon.end_reason == "eof"
        assert mon.finished_naturally() is True
    finally:
        fake.close()


def test_quit_is_not_finished(tmp_path):
    path = str(tmp_path / "mpv2.sock")
    # user quit early (pos far from end) → not "finished"
    fake = _FakeMpv(path, pos=10.0, dur=120.0, end_reason="quit")
    try:
        mon = mpv_ipc.PlaybackMonitor(path, poll=0.2)
        mon.start()
        time.sleep(1.0)
        mon.stop()
        assert mon.end_reason == "quit"
        assert mon.finished_naturally() is False
    finally:
        fake.close()


def test_connect_times_out_without_server(tmp_path):
    path = str(tmp_path / "nope.sock")
    client = mpv_ipc.MpvIPC(path)
    assert client.connect(timeout=0.5) is False


def test_make_ipc_path_is_unique():
    assert mpv_ipc.make_ipc_path() != mpv_ipc.make_ipc_path()


def test_ipc_dir_is_private():
    import os
    import stat
    d = mpv_ipc._ipc_dir()
    assert d and os.path.isdir(d)
    mode = stat.S_IMODE(os.stat(d).st_mode)
    assert mode == 0o700, oct(mode)


def test_make_ipc_path_inside_private_dir():
    import os
    p = mpv_ipc.make_ipc_path()
    assert os.path.dirname(p) == mpv_ipc._ipc_dir()
    assert os.path.basename(p).startswith("freeflix-mpv-")


def test_connect_failure_leaks_no_fd(tmp_path):
    import os
    import sys
    if sys.platform.startswith("win") or not os.path.isdir("/proc/self/fd"):
        return  # comptage de fd dispo seulement sous Linux
    def _fds():
        return len(os.listdir("/proc/self/fd"))
    before = _fds()
    client = mpv_ipc.MpvIPC(str(tmp_path / "nope.sock"))
    assert client.connect(timeout=0.6) is False
    assert _fds() <= before + 1, "socket fuit à chaque tentative ratée"


def test_close_unlinks_socket_file():
    import os
    p = mpv_ipc.make_ipc_path()
    with open(p, "w") as f:
        f.write("stale")
    mpv_ipc.MpvIPC(p).close()
    assert not os.path.exists(p)
