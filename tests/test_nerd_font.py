"""Tests for Nerd Font detection and installation helpers."""


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

    def test_url_is_https_zip(self):
        # Offline check: the live URL is exercised by the installer, not by
        # unit tests (CI must stay deterministic without network access).
        assert NERD_FONT_URL.startswith("https://")
        assert NERD_FONT_URL.endswith(".zip")

    def test_font_name_non_empty(self):
        assert NERD_FONT_NAME and len(NERD_FONT_NAME) > 5
