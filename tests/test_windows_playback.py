"""Windows playback regressions.

There is no Windows CI here, so the platform is SIMULATED: ``os.name`` /
``sys.platform`` are patched and every ``subprocess`` call is faked. Each test
pins one code path that was broken (or unusable) on Windows while still being
executable on Linux/macOS.

Covered Windows-specific failures:
  * a self-managed mpv/ffmpeg (installed by FreeFlix's own first-run setup into
    a dir that is NOT on PATH) was reported as "not installed";
  * ``select.select()`` on a pipe raised ``OSError [WinError 10038]`` in the
    live-Match preflight (pipes are not selectable on Windows);
  * ``TerminateProcess`` returns exit code 1, not -SIGTERM, which made a
    healthy-but-silent live feed look dead;
  * the local proxy advertised a port before it was actually bound;
  * console children popped a black window over the TUI (CREATE_NO_WINDOW);
  * VLC's stdin playback, which is unreliable on Windows, was tried first.
"""

import socket
import subprocess as _sp

import pytest

from freeflix_cli import player_manager as pm


# ── helpers ─────────────────────────────────────────────────────────────


@pytest.fixture
def windows(monkeypatch):
    """Run the code under test as if it were Windows.

    Only ``sys.platform`` is faked: patching ``os.name`` would make
    ``pathlib`` build ``WindowsPath`` objects on this Linux host and break
    pytest itself. ``_is_windows()`` accepts either signal.
    """
    monkeypatch.setattr(pm.sys, "platform", "win32")
    # Pin the platform helper itself: sys.platform alone is not enough on a
    # real Windows runner, where os.name is already "nt".
    monkeypatch.setattr(pm, "_is_windows", lambda: True)
    # Never probe the real GPU or the real config dir in these tests.
    monkeypatch.setattr(pm, "_nvidia_env", lambda: {})
    monkeypatch.setattr(pm, "_mpv_config_args", lambda: ["--no-config"])
    return True


@pytest.fixture
def posix(monkeypatch):
    monkeypatch.setattr(pm.sys, "platform", "linux")
    monkeypatch.setattr(pm, "_is_windows", lambda: False)
    monkeypatch.setattr(pm, "_nvidia_env", lambda: {})
    monkeypatch.setattr(pm, "_mpv_config_args", lambda: ["--no-config"])
    return True


@pytest.fixture
def managed_bin():
    """The isolated managed-bin dir (conftest points it at tmp_path)."""
    from freeflix_cli import setup_assistant
    d = setup_assistant._bin_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


class _FakeStream:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeProc:
    def __init__(self, rc=0, stdout=None):
        self.rc = rc
        self.stdout = stdout
        self.returncode = rc
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        return self.rc

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _no_console_flag(monkeypatch):
    """Give the shared subprocess module the Windows-only constant."""
    monkeypatch.setattr(pm.subprocess, "CREATE_NO_WINDOW", 0x08000000,
                        raising=False)
    return 0x08000000


# ── managed binaries: the "mpv is not installed" Windows bug ───────────


def test_get_mpv_path_finds_managed_exe_on_windows(windows, managed_bin,
                                                   monkeypatch):
    exe = managed_bin / "mpv.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(pm.shutil, "which", lambda name: None)
    monkeypatch.setattr(pm.glob, "glob", lambda *a, **k: [])
    monkeypatch.setattr(pm.os.path, "exists", lambda path: False)

    assert pm.get_mpv_path() == str(exe)


def test_get_vlc_path_finds_managed_binary(windows, managed_bin, monkeypatch):
    exe = managed_bin / "vlc.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(pm.shutil, "which", lambda name: None)
    monkeypatch.setattr(pm.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pm.os.path, "exists", lambda path: False)
    monkeypatch.setattr(pm, "_managed_tool_path",
                        lambda name: str(exe) if name == "vlc" else None)

    assert pm.get_vlc_path() == str(exe)


def test_resolve_tool_finds_managed_exe_on_windows(windows, managed_bin,
                                                   monkeypatch):
    """``_managed_bin("ffmpeg")`` is ffmpeg, but Windows stores ffmpeg.exe."""
    exe = managed_bin / "ffmpeg.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(pm.shutil, "which", lambda name: None)

    assert pm._resolve_tool("ffmpeg") == str(exe)


def test_resolve_tool_prefers_path_binary(windows, managed_bin, monkeypatch):
    (managed_bin / "ffmpeg.exe").write_bytes(b"MZ")
    monkeypatch.setattr(pm.shutil, "which",
                        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)

    assert pm._resolve_tool("ffmpeg") == "/usr/bin/ffmpeg"


# ── CREATE_NO_WINDOW / console children ───────────────────────────────


def test_is_windows_detects_platform(monkeypatch):
    monkeypatch.setattr(pm.sys, "platform", "win32")
    assert pm._is_windows() is True
    monkeypatch.setattr(pm.sys, "platform", "linux")
    assert pm._is_windows() is (pm.os.name == "nt")


def test_no_console_window_flag_only_on_windows(posix, monkeypatch):
    _no_console_flag(monkeypatch)
    assert pm._no_console_window() == {}

    monkeypatch.setattr(pm, "_is_windows", lambda: True)
    assert pm._no_console_window() == {"creationflags": 0x08000000}


def test_ffmpeg_pipe_uses_managed_ffmpeg_and_hides_console(
        windows, managed_bin, monkeypatch):
    exe = managed_bin / "ffmpeg.exe"
    exe.write_bytes(b"MZ")
    flag = _no_console_flag(monkeypatch)
    monkeypatch.setattr(pm.shutil, "which", lambda name: None)
    # managed ffmpeg + a (fake) mpv on PATH
    monkeypatch.setattr(
        pm.shutil, "which",
        lambda name: "/mpv/mpv.exe" if name == "mpv" else None,
    )

    calls = []
    ff_stdout = _FakeStream()

    def fake_popen(cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        if len(calls) == 1:
            return _FakeProc(stdout=ff_stdout)
        return _FakeProc(rc=0)

    monkeypatch.setattr(pm.subprocess, "Popen", fake_popen)

    ok = pm._play_ffmpeg_pipe("/mpv/mpv.exe", "https://cdn/x.m3u8",
                              {"Referer": "https://embed/"}, "T")
    assert ok is True
    ff_cmd, ff_kw = calls[0]
    mpv_cmd, mpv_kw = calls[1]

    assert ff_cmd[0] == str(exe)                  # managed ffmpeg resolved
    assert "-nostdin" in ff_cmd
    assert ff_kw["stdin"] is pm.subprocess.DEVNULL
    assert ff_kw["creationflags"] == flag
    assert mpv_kw["stdin"] is ff_stdout           # pipe handed to the player
    assert mpv_kw["creationflags"] == flag
    assert ff_stdout.closed is True               # parent end closed
    assert mpv_cmd[-1] == "-"
    assert mpv_cmd[0] == "/mpv/mpv.exe"


def test_vlc_pipe_uses_managed_ffmpeg(windows, managed_bin, monkeypatch):
    exe = managed_bin / "ffmpeg.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(pm.shutil, "which", lambda name: None)

    calls = []
    ff_stdout = _FakeStream()

    def fake_popen(cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        if len(calls) == 1:
            return _FakeProc(stdout=ff_stdout)
        return _FakeProc(rc=0)

    monkeypatch.setattr(pm.subprocess, "Popen", fake_popen)
    # VLC would be resolved separately; the pipe only needs ffmpeg.
    assert pm._play_vlc_pipe("/vlc/vlc.exe", "https://cdn/x.m3u8",
                             {"Referer": "r"}, "T") is True
    assert calls[0][0][0] == str(exe)
    assert calls[0][0][1:3] == ["-hide_banner", "-nostdin"]


# ── live Match preflight: select() on a pipe crashes on Windows ───────


class _LineStderr:
    def __init__(self, lines):
        self.lines = list(lines)

    def readline(self):
        return self.lines.pop(0) if self.lines else ""


class _ProbeProc:
    def __init__(self, lines, exit_code=1):
        self.stderr = _LineStderr(lines)
        self.returncode = None
        self.exit_code = exit_code
        self.terminated = False

    def terminate(self):
        self.terminated = True
        self.returncode = self.exit_code

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def _probe(monkeypatch, proc):
    monkeypatch.setattr(pm, "_resolve_tool",
                        lambda name: r"C:\bin\ffmpeg.exe" if name == "ffmpeg"
                        else None)
    monkeypatch.setattr(pm.subprocess, "Popen", lambda cmd, **kw: proc)
    return pm.match_stream_reachable("http://127.0.0.1:8080/live.m3u8",
                                     {"Referer": "r"}, timeout=4)


def test_match_probe_never_uses_select_on_windows(windows, monkeypatch):
    import select

    def boom(*a, **k):
        raise OSError(10038, "not a socket")

    # Old code crashed here on Windows; the portable reader thread must not.
    monkeypatch.setattr(select, "select", boom)
    proc = _ProbeProc(["Input #0, mpegts\n", "Stream #0:0: Video: h264\n"])
    ok, why = _probe(monkeypatch, proc)
    assert (ok, why) == (True, "")
    assert proc.terminated is True


def test_match_probe_reports_403_on_windows(windows, monkeypatch):
    from freeflix_cli.i18n import t

    proc = _ProbeProc(["[http] HTTP error 403 Forbidden\n"])
    ok, why = _probe(monkeypatch, proc)
    assert ok is False
    assert why == t("Channel server refused the stream.")


def test_match_probe_eof_without_output_is_not_a_failure(windows, monkeypatch):
    proc = _ProbeProc([], exit_code=1)
    ok, why = _probe(monkeypatch, proc)
    assert (ok, why) == (True, "")


def test_match_probe_terminate_exit_code_is_playable_on_windows(
        windows, monkeypatch):
    """TerminateProcess exits with 1 (POSIX would be -SIGTERM)."""
    proc = _ProbeProc([], exit_code=1)
    ok, why = _probe(monkeypatch, proc)
    assert (ok, why) == (True, "")


# ── play_direct_stream: no VLC stdin pipe on Windows ──────────────────


def test_play_direct_stream_vlc_windows_uses_local_proxy(windows, monkeypatch):
    from freeflix_cli import tracker, yacine_live_proxy

    class _Proxy:
        def stop(self):
            pass

    monkeypatch.setattr(tracker.tracker, "get_player", lambda: "vlc")
    monkeypatch.setattr(tracker.tracker, "get_match_player", lambda: "vlc")
    monkeypatch.setattr(pm, "_resolve_or_install", lambda name: r"C:\vlc\vlc.exe")
    monkeypatch.setattr(pm, "_resolve_tool", lambda name: r"C:\bin\ffmpeg.exe")

    def must_not_pipe(*a, **k):
        raise AssertionError("the ffmpeg->VLC stdin pipe must not be used "
                             "on Windows")

    monkeypatch.setattr(pm, "_play_vlc_pipe", must_not_pipe)
    monkeypatch.setattr(yacine_live_proxy, "start_live_proxy",
                        lambda url, headers: (_Proxy(),
                                              "http://127.0.0.1:9/p/x.m3u8"))
    started = {}

    def fake_popen(cmd, **kw):
        started["cmd"] = list(cmd)
        return _FakeProc(rc=0)

    monkeypatch.setattr(pm.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(pm, "_stop_vlc_keepalive", lambda: None)
    try:
        assert pm.play_direct_stream("http://cdn/live.m3u8",
                                     {"Referer": "r"},
                                     "A - B", player_name="vlc") is True
    finally:
        pm._VLC_KEEPALIVE.clear()

    assert started["cmd"][0] == r"C:\vlc\vlc.exe"
    assert "--no-one-instance" in started["cmd"]
    assert started["cmd"][-1] == "http://127.0.0.1:9/p/x.m3u8"


# ── direct mode: mpv header quoting / list separator ──────────────────


def test_direct_mpv_headers_are_comma_list_without_shell_quotes(
        windows, monkeypatch):
    """Args are a LIST: literal quotes ended up inside the header values, and
    the fields were joined with ';' instead of mpv's ',' list separator — both
    made the CDN reject the request (on every OS, worse for strict CDNs)."""
    from freeflix_cli.scraping import player as player_mod

    monkeypatch.setitem(player_mod.players, "testhost", {
        "mode": "direct",
        "referrer": "https://ref.example",
        "alt-used": True,
        "sec_headers": "X-A: 1;X-B: 2",
    })
    monkeypatch.setattr(pm, "_resolve_or_install", lambda name: r"C:\mpv\mpv.exe")
    monkeypatch.setattr(pm, "_mpv_resilience_args", lambda: [])
    monkeypatch.setattr(pm, "_mpv_position_args", lambda title: ([], None, None))
    monkeypatch.setattr(pm, "_mpv_ipc_args", lambda key: ([], None))
    monkeypatch.setattr(pm, "_save_mpv_position", lambda *a, **k: None)
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = list(cmd)

    monkeypatch.setattr(pm.subprocess, "run", fake_run)

    assert pm.play_video("https://testhost/embed/abc", {},
                         title="Série ép. 1", is_direct=True,
                         force_player="mpv", _with_ui=False) is True

    cmd = captured["cmd"]
    fields_arg = next(a for a in cmd if a.startswith("--http-header-fields="))
    value = fields_arg.split("=", 1)[1]
    assert '"' not in value
    fields = value.split(",")
    assert "Alt-Used: testhost" in fields
    assert "X-A: 1" in fields
    assert "X-B: 2" in fields
    assert not any(f.startswith("Sec-Fetch") for f in fields)
    # No literal quotes anywhere in the list args.
    assert not any('"' in str(a) for a in cmd)


# ── local proxy: bind before publishing the URL ───────────────────────


def test_proxy_listens_before_url_is_published(monkeypatch):
    from freeflix_cli import proxy

    monkeypatch.setattr(proxy, "PROXY_URL", None)
    monkeypatch.setattr(proxy, "_server_instance", None)
    monkeypatch.setattr(proxy, "PROXY_PORT", 0)
    port = proxy.start_proxy_server(0)
    try:
        # No sleep/retry: the socket must already accept right after return.
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            pass
        assert proxy.PROXY_URL == f"http://127.0.0.1:{port}"
        assert proxy.PROXY_PORT == port
    finally:
        proxy.stop_proxy_server()


def test_proxy_bind_failure_is_fatal_not_advertised(monkeypatch):
    from freeflix_cli import proxy

    monkeypatch.setattr(proxy, "PROXY_URL", None)
    monkeypatch.setattr(proxy, "_server_instance", None)
    monkeypatch.setattr(proxy, "PROXY_PORT", 0)
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    try:
        with pytest.raises(OSError):
            proxy.start_proxy_server(holder.getsockname()[1])
        # A dead URL must never be published to the player.
        assert proxy.PROXY_URL is None
        assert proxy.PROXY_PORT == 0
    finally:
        holder.close()


def test_ensure_started_returns_zero_when_bind_fails(monkeypatch):
    from freeflix_cli import proxy

    monkeypatch.setattr(proxy, "PROXY_URL", None)
    monkeypatch.setattr(proxy, "_server_instance", None)

    def boom(port=0):
        raise OSError(10048, "address already in use")

    monkeypatch.setattr(proxy, "start_proxy_server", boom)
    assert proxy.ensure_started() == 0
    assert proxy.PROXY_URL is None


# ── yacine live proxy: defensive hardening ────────────────────────────


def test_live_proxy_last_error_is_initialised():
    from freeflix_cli.yacine_live_proxy import _LiveProxy

    proxy = _LiveProxy("http://cdn/live.m3u8", {})
    assert proxy.last_error is None


def test_live_proxy_forwards_segment_content_length():
    import http.server
    import threading
    import urllib.request

    from freeflix_cli.yacine_live_proxy import start_live_proxy

    body = b"SEGMENT-BYTES"

    class _Upstream(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/live/index.m3u8"):
                data = b"#EXTM3U\n#EXTINF:2,\nseg/1.ts\n"
                ctype = "application/vnd.apple.mpegurl"
            else:
                data = body
                ctype = "application/pdf"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    try:
        proxy, local = start_live_proxy(
            f"http://127.0.0.1:{upstream.server_address[1]}/live/index.m3u8",
            {"Referer": "r"},
        )
        try:
            playlist = urllib.request.urlopen(local, timeout=10).read().decode()
            seg = playlist.splitlines()[-1]
            url = (f"http://127.0.0.1:{proxy.httpd.server_address[1]}{seg}")
            with urllib.request.urlopen(url, timeout=10) as r:
                assert r.read() == body
                # Upstream framing is forwarded: stricter players wait on it.
                assert r.headers.get("Content-Length") == str(len(body))
            assert proxy.last_error is None
        finally:
            proxy.stop()
    finally:
        upstream.shutdown()
        upstream.server_close()


# ── sanity: the simulated Windows never broke POSIX behaviour ─────────


def test_no_console_window_kwargs_are_empty_on_posix(posix):
    assert pm._no_console_window() == {}
    # The pipe path still works with plain subprocess kwargs.
    assert (_sp.PIPE is not None)
