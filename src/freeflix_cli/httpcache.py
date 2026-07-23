"""
Tiny persistent HTTP cache for idempotent GETs (searches, episode/season lists,
metadata). NOT for stream resolution — those URLs are short-lived.

Design :
  • one small JSON file per URL under the user cache dir, keyed by a hash ;
  • TTL-based freshness (caller passes the TTL, 0 disables) ;
  • a `CachedResponse` shim so scrapers can treat a cache hit exactly like a
    curl_cffi response (`.text`, `.status_code`, `.json()`, `.raise_for_status()`)
    and their call sites stay unchanged.

Everything is best-effort : any I/O error just behaves as a cache miss, so the
cache can never break a fetch — at worst it re-downloads.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from platformdirs import user_cache_dir

_DIR = Path(user_cache_dir("freeflix-cli", "PaulExplorer")) / "http"
DEFAULT_TTL = 3600  # 1 hour


class CachedResponse:
    """Minimal stand-in for a curl_cffi response served from the cache."""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.from_cache = True

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        return None  # only 200 bodies are ever cached


def _path(url: str) -> Path:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return _DIR / f"{h}.json"


def get(url: str, ttl: int = DEFAULT_TTL) -> str | None:
    """Return the cached body for *url* if present and younger than *ttl*, else None."""
    if not ttl or ttl <= 0:
        return None
    try:
        with open(_path(url), encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    if time.time() - rec.get("ts", 0) > ttl:
        return None
    return rec.get("text")


def store(url: str, text: str) -> None:
    """Persist *text* as the cached body for *url* (atomic, best-effort)."""
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        p = _path(url)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"url": url, "ts": time.time(), "text": text}, f, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        pass


def clear() -> int:
    """Delete every cached entry. Returns how many files were removed."""
    n = 0
    try:
        for p in _DIR.glob("*.json"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    except OSError:
        pass
    return n


def stats() -> tuple[int, float]:
    """Return (entry_count, total_MB) for the cache — for the settings screen."""
    count = 0
    size = 0
    try:
        for p in _DIR.glob("*.json"):
            try:
                size += p.stat().st_size
                count += 1
            except OSError:
                pass
    except OSError:
        pass
    return count, size / (1024 * 1024)
