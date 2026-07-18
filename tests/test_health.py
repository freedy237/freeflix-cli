"""
Tests for the source health-badge logic (freeflix_cli.health).

The badge must be conservative : it appears ONLY for a fresh, definitive 'down'
result, and never for an up / unknown / stale source. These pin that contract
without touching the network.
"""

import time

from freeflix_cli import health


def _reset():
    with health._lock:
        health._status.clear()


def test_badge_only_for_fresh_down():
    _reset()
    with health._lock:
        health._status["french-stream"] = (time.time(), False)   # down, fresh
    badge = health.badge_for("French-Stream (Series and movies)")
    assert badge and "offline" in badge or badge.strip()  # non-empty badge


def test_no_badge_when_up():
    _reset()
    with health._lock:
        health._status["coflix"] = (time.time(), True)
    assert health.badge_for("Coflix (Series and movies)") == ""


def test_no_badge_for_unknown_source():
    _reset()
    assert health.badge_for("GoldenMS (Movies & Series)") == ""


def test_no_badge_when_stale():
    _reset()
    with health._lock:
        health._status["french-stream"] = (time.time() - health._TTL - 10, False)
    assert health.badge_for("French-Stream") == ""


def test_refresh_is_noop_when_fresh(monkeypatch):
    # If a sweep ran recently, refresh() must not launch another.
    _reset()
    health._last_run = time.time()
    health._checking = False
    started = {"n": 0}
    import threading
    real = threading.Thread

    def spy(*a, **k):
        started["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(threading, "Thread", spy)
    health.refresh({"french-stream": "https://example.invalid"})
    assert started["n"] == 0  # skipped — still fresh
