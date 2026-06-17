"""Tests for Nerd Font detection and installation helpers."""

import os
import subprocess
import sys

import pytest

from freeflix_cli.setup_assistant import (
    detect_nerd_font,
    NERD_FONT_URL,
    NERD_FONT_NAME,
)


class TestDetectNerdFont:
    """detect_nerd_font() should return bool without crashing."""

    def test_returns_bool(self):
        result = detect_nerd_font()
        assert isinstance(result, bool)

    def test_no_exceptions(self):
        try:
            detect_nerd_font()
        except Exception as e:
            pytest.fail(f"detect_nerd_font raised {type(e).__name__}: {e}")

    def test_url_reachable(self):
        import urllib.request
        try:
            resp = urllib.request.urlopen(NERD_FONT_URL, timeout=15)
            assert resp.status == 302 or resp.status == 200
            resp.close()
        except Exception as e:
            pytest.fail(f"Nerd Font URL not reachable: {e}")

    def test_font_name_non_empty(self):
        assert NERD_FONT_NAME and len(NERD_FONT_NAME) > 5
