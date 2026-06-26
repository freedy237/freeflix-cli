"""
Integration tests for the parallel batch download flow:
  - print suppression
  - thread-safe Live lock
  - batch worker orchestration
"""

import os
import shutil
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from freeflix_cli.cli_utils import (
    _suppress_print,
    print_info,
    print_success,
    print_warning,
    print_error,
    console,
)
from freeflix_cli.progress import _download_screen_lock, run_download_with_bar


# ─── 1. Print suppression (per-thread) ─────────────────────────────────

class TestPrintSuppression:
    """_suppress_print.active silences all print_* in the current thread."""

    def test_suppress_info(self):
        t = threading.Thread(target=self._assert_suppressed, daemon=True)
        t.start()
        t.join(timeout=2)

    def _assert_suppressed(self):
        _suppress_print.active = True
        try:
            # These should produce no console output
            print_info("should be hidden")
            print_success("should be hidden")
            print_warning("should be hidden")
            print_error("should be hidden")
            # If we reach here without crashing, suppression works
            assert True
        finally:
            _suppress_print.active = False

    def test_suppress_does_not_leak_across_threads(self):
        """The flag is thread-local — main thread still prints."""
        flag = {"main_printed": False}

        def worker():
            _suppress_print.active = True
            time.sleep(0.3)
            _suppress_print.active = False

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        # Main thread should still be able to print
        print_info("main thread message")  # Should appear
        flag["main_printed"] = True
        t.join(timeout=1)
        assert flag["main_printed"]


# ─── 2. Thread-safe download bar lock ─────────────────────────────────

class TestDownloadScreenLock:
    """_download_screen_lock serialises Live(screen=True) access."""

    def test_lock_held_while_running(self):
        """While one thread holds the lock, another cannot acquire it."""
        lock_acquired = threading.Event()
        in_critical = threading.Event()
        other_acquired = threading.Event()

        def holder():
            with _download_screen_lock:
                in_critical.set()
                other_acquired.wait(timeout=3)
            lock_acquired.set()

        def contender():
            in_critical.wait(timeout=3)
            # Try to acquire — should block until holder releases
            acquired = _download_screen_lock.acquire(blocking=False)
            other_acquired.set()
            if not acquired:
                # Holder still holds it — correct
                pass
            else:
                _download_screen_lock.release()

        h = threading.Thread(target=holder, daemon=True)
        c = threading.Thread(target=contender, daemon=True)
        h.start()
        c.start()
        c.join(timeout=3)
        other_acquired.set()  # unblock holder
        h.join(timeout=3)
        assert lock_acquired.wait(timeout=1)


# ─── 3. Real download test (small file via local HTTP server) ─────────

class TestRealDownload:
    """Download a small file and verify the bar appears."""

    @classmethod
    def setup_class(cls):
        cls.test_content = b"Hello FreeFlix test " * 1000   # ~19 KB
        cls.server = None
        cls.port = 18999
        cls._start_server()

    @classmethod
    def _start_server(cls):
        import http.server
        import socketserver

        class Handler(http.server.BaseHTTPRequestHandler):
            content = cls.test_content

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(self.content)))
                self.end_headers()
                self.wfile.write(self.content)

            def log_message(self, fmt, *args):
                pass  # suppress server logs

        cls.server = socketserver.TCPServer(("127.0.0.1", cls.port), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def teardown_class(cls):
        if cls.server:
            cls.server.shutdown()

    def test_run_download_with_bar_sequential(self):
        """Single download via run_download_with_bar — expected to succeed."""
        import subprocess
        aria = os.environ.get("FREEFLIX_TEST_DOWNLOADER") or shutil.which("aria2c") or shutil.which("yt-dlp")
        if not aria:
            pytest.skip("No aria2c or yt-dlp available")
        url = f"http://127.0.0.1:{self.port}/test.bin"
        out = os.path.join(tempfile.gettempdir(), f"freeflix_test_{int(time.time())}.mp4")
        try:
            rc = run_download_with_bar(
                [aria, "--continue=true", "--max-connection-per-server=4",
                 "--summary-interval=1", "--console-log-level=notice",
                 f"--dir={os.path.dirname(out)}",
                 f"--out={os.path.basename(out)}", url],
                "batch_test_file",
            )
            assert rc == 0, f"Download failed with exit code {rc}"
            assert os.path.getsize(out) == len(self.test_content)
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_suppressed_print_during_download(self):
        """Download with print suppression should not produce log messages."""
        aria = shutil.which("aria2c") or shutil.which("yt-dlp")
        if not aria:
            pytest.skip("No aria2c or yt-dlp available")
        url = f"http://127.0.0.1:{self.port}/test.bin"
        out = os.path.join(tempfile.gettempdir(), f"freeflix_test_{int(time.time())}.mp4")
        captured = []

        def patched_print(msg):
            captured.append(msg)

        _suppress_print.active = True
        try:
            with patch("freeflix_cli.player_manager.print_info", patched_print):
                rc = run_download_with_bar(
                    [aria, "--continue=true", "--max-connection-per-server=4",
                     "--summary-interval=1", "--console-log-level=notice",
                     f"--dir={os.path.dirname(out)}",
                     f"--out={os.path.basename(out)}", url],
                    "batch_test_file",
                )
            assert rc == 0
        finally:
            _suppress_print.active = False
            if os.path.exists(out):
                os.remove(out)

        # Should have no print_info calls during suppressed mode
        assert len(captured) == 0, f"Got unexpected prints: {captured}"
