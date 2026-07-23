"""
Tests for the persistent HTTP cache (freeflix_cli.httpcache).

Pins the contract the scrapers rely on : fresh hit returns the body, a miss /
expired / ttl<=0 returns None, the CachedResponse shim quacks like a curl_cffi
response, and clear()/stats() behave.
"""

import json
import time

import pytest

from freeflix_cli import httpcache


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(httpcache, "_DIR", tmp_path / "http")
    yield


URL = "https://anime-sama/catalogue/?search=one+piece"


def test_miss_then_hit():
    assert httpcache.get(URL, 60) is None
    httpcache.store(URL, "<html>ok</html>")
    assert httpcache.get(URL, 60) == "<html>ok</html>"


def test_ttl_zero_disables():
    httpcache.store(URL, "x")
    assert httpcache.get(URL, 0) is None
    assert httpcache.get(URL, -5) is None


def test_expiry():
    httpcache.store(URL, "x")
    p = httpcache._path(URL)
    rec = json.loads(p.read_text())
    rec["ts"] = time.time() - 100
    p.write_text(json.dumps(rec))
    assert httpcache.get(URL, 60) is None      # older than ttl
    assert httpcache.get(URL, 200) == "x"      # within a longer ttl


def test_cached_response_shim():
    r = httpcache.CachedResponse('{"a": 1}')
    assert r.status_code == 200
    assert r.from_cache is True
    assert r.raise_for_status() is None
    assert r.json() == {"a": 1}


def test_clear_and_stats():
    httpcache.store(URL, "x")
    httpcache.store(URL + "2", "yy")
    count, mb = httpcache.stats()
    assert count == 2 and mb >= 0
    assert httpcache.clear() == 2
    assert httpcache.stats()[0] == 0


def test_distinct_urls_distinct_entries():
    httpcache.store("https://a", "AAA")
    httpcache.store("https://b", "BBB")
    assert httpcache.get("https://a", 60) == "AAA"
    assert httpcache.get("https://b", 60) == "BBB"
