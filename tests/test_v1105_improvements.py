"""Tests for the 1.10.5 batch: binary integrity gate, HTTP-cache eviction,
proxy segment cache, and the smooth progress bar."""

import hashlib
import os
import time

import pytest


# ── Binary integrity gate ─────────────────────────────────────────────
def test_verify_archive_rejects_truncated(tmp_path):
    from freeflix_cli import setup_assistant as sa
    p = tmp_path / "a.zip"
    p.write_bytes(b"x" * 100)
    assert sa._verify_archive(p, {"min_bytes": 1000}, "test") is False


def test_verify_archive_accepts_when_above_floor(tmp_path):
    from freeflix_cli import setup_assistant as sa
    p = tmp_path / "a.zip"
    p.write_bytes(b"x" * 2000)
    assert sa._verify_archive(p, {"min_bytes": 1000}, "test") is True


def test_verify_archive_checksum_mismatch_rejected(tmp_path):
    from freeflix_cli import setup_assistant as sa
    p = tmp_path / "a.zip"
    p.write_bytes(b"hello world")
    assert sa._verify_archive(p, {"sha256": "0" * 64}, "test") is False


def test_verify_archive_checksum_match_accepted(tmp_path):
    from freeflix_cli import setup_assistant as sa
    data = b"hello world"
    p = tmp_path / "a.zip"
    p.write_bytes(data)
    good = hashlib.sha256(data).hexdigest()
    assert sa._verify_archive(p, {"sha256": good}, "test") is True


def test_pinned_catalog_entries_have_sha256():
    """Every version-frozen (non-`latest`) managed binary must carry a sha256."""
    from freeflix_cli import setup_assistant as sa
    for os_name, tools in sa._BINARY_SOURCES.items():
        for label, info in tools.items():
            if "releases/latest" in info["url"]:
                continue  # nightly build — hash can't be pinned
            assert info.get("sha256"), f"{os_name}/{label} missing sha256"
            assert info.get("min_bytes"), f"{os_name}/{label} missing min_bytes"


# ── HTTP-cache eviction ───────────────────────────────────────────────
def test_httpcache_prune_drops_stale(tmp_path, monkeypatch):
    from freeflix_cli import httpcache
    monkeypatch.setattr(httpcache, "_DIR", tmp_path)
    old = tmp_path / "old.json"
    fresh = tmp_path / "fresh.json"
    old.write_text("{}")
    fresh.write_text("{}")
    # Age `old` well past the max.
    past = time.time() - 999_999
    os.utime(old, (past, past))
    removed = httpcache.prune(max_age_s=3600, max_mb=999)
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_httpcache_prune_enforces_size_cap(tmp_path, monkeypatch):
    from freeflix_cli import httpcache
    monkeypatch.setattr(httpcache, "_DIR", tmp_path)
    # Three 1 MB files, cap at ~2 MB → oldest one is evicted.
    for i in range(3):
        f = tmp_path / f"{i}.json"
        f.write_bytes(b"x" * (1024 * 1024))
        os.utime(f, (time.time() - (10 - i), time.time() - (10 - i)))
    removed = httpcache.prune(max_age_s=10_000_000, max_mb=2.0)
    assert removed >= 1
    assert not (tmp_path / "0.json").exists()  # oldest gone first


# ── Smooth progress bar ───────────────────────────────────────────────
@pytest.mark.parametrize("pct", [0, 1, 22, 50, 61, 99, 100])
def test_progress_bar_shows_pct(pct):
    from freeflix_cli import main
    t = main._progress_bar_text(pct, width=12)
    assert f"{pct}%" in t.plain


def test_progress_bar_clamps():
    from freeflix_cli import main
    assert "100%" in main._progress_bar_text(150, width=12).plain
    assert "0%" in main._progress_bar_text(-5, width=12).plain


# ── New themes present ────────────────────────────────────────────────
def test_new_themes_registered():
    from freeflix_cli import themes
    for key in ("everforest", "kanagawa", "solarized", "latte"):
        assert key in themes.THEMES
        # A light theme must NOT use a white header (invisible on light bg).
    assert "white" not in themes.THEMES["latte"]["header"]
