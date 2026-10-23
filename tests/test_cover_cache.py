"""Persistent cover cache: instant posters + auto-refresh when art changes."""

import os

from freeflix_cli import terminal_image as ti


class _R:
    def __init__(self, content=b"poster", status=200, headers=None):
        self.content = content
        self.status_code = status
        self.headers = headers or {}


def _isolate(tmp_path, monkeypatch):
    """Point the cover cache at tmp_path and clear the in-memory state."""
    monkeypatch.setattr(ti, "_cover_index", {})
    monkeypatch.setattr(ti, "_img_cache", {})
    monkeypatch.setattr(ti, "_cover_dir", lambda: str(tmp_path))
    return tmp_path / "index.json"


def test_cover_download_is_stored_and_reused(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return _R(b"\xff\xd8img", headers={"ETag": '"abc"'})

    monkeypatch.setattr(ti._rq, "get", fake_get)

    url = "https://cdn/poster.jpg"
    first = ti._download(url)
    assert first and os.path.exists(first)
    assert ti.cover_version(url) == "abc"
    # Second call: no network, same file.
    assert ti._download(url) == first
    assert len(calls) == 1
    # Persisted index → survives a process restart.
    ti._cover_index = None
    ti._img_cache = {}
    assert ti._download(url) == first
    assert len(calls) == 1


def test_cover_version_absent_for_unknown_url(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert ti.cover_version("https://nope/x.jpg") is None


def test_cover_changed_detects_new_etag(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ti._rq, "get", lambda url, **k: _R(headers={"ETag": '"v1"', "Content-Length": "6"})
    )
    url = "https://cdn/p.jpg"
    ti._download(url)

    monkeypatch.setattr(ti, "_probe_cover", lambda u, timeout=4: (200, "v1", 6))
    assert ti.cover_changed(url) is False

    # 304 (unchanged) and a new ETag: both decided by the ETag, not the size.
    monkeypatch.setattr(ti, "_probe_cover", lambda u, timeout=4: (304, "v1", 0))
    assert ti.cover_changed(url) is False
    monkeypatch.setattr(ti, "_probe_cover", lambda u, timeout=4: (200, "v2", 6))
    assert ti.cover_changed(url) is True


def test_cover_changed_uses_size_when_no_etag(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ti._rq, "get", lambda url, **k: _R(b"abcdef", headers={"Content-Length": "6"})
    )
    url = "https://cdn/q.jpg"
    ti._download(url)

    monkeypatch.setattr(ti, "_probe_cover", lambda u, timeout=4: (200, "", 6))
    assert ti.cover_changed(url) is False
    monkeypatch.setattr(ti, "_probe_cover", lambda u, timeout=4: (200, "", 999))
    assert ti.cover_changed(url) is True


def test_cover_changed_ignores_unreachable_host(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(ti._rq, "get", lambda url, **k: _R())
    url = "https://cdn/r.jpg"
    ti._download(url)
    monkeypatch.setattr(ti, "_probe_cover", lambda u, timeout=4: (0, "", 0))
    assert ti.cover_changed(url) is False


def test_refresh_cover_replaces_the_file(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(ti._rq, "get", lambda url, **k: _R(b"old", headers={"ETag": '"v1"'}))
    url = "https://cdn/s.jpg"
    ti._download(url)

    monkeypatch.setattr(ti._rq, "get", lambda url, **k: _R(b"new!", headers={"ETag": '"v2"'}))
    assert ti.refresh_cover(url) is True
    assert ti.cover_version(url) == "v2"
    new_path = ti._download(url)
    assert os.path.exists(new_path)
    with open(new_path, "rb") as f:
        assert f.read() == b"new!"


def test_cleanup_keeps_persistent_covers(tmp_path, monkeypatch):
    """Exiting must not delete the persistent poster cache.

    ``_img_cache`` also holds session temp files; only those are removed.
    """
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(ti._rq, "get", lambda url, **k: _R(b"cover"))
    url = "https://cdn/keep.jpg"
    kept = ti._download(url)

    temp = tmp_path.parent / (tmp_path.name + "-session.jpg")
    temp.write_bytes(b"temp")
    ti._img_cache["https://cdn/temp.jpg"] = str(temp)

    ti._cleanup_images()
    assert os.path.exists(kept)
    assert not os.path.exists(temp)


def test_prefetch_many_warms_every_cover(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    seen = []

    def fake_get(url, **kw):
        seen.append(url)
        return _R(b"x")

    monkeypatch.setattr(ti._rq, "get", fake_get)
    urls = ["https://cdn/a.jpg", "https://cdn/b.jpg", "https://cdn/a.jpg", ""]
    ti.prefetch_many(urls)
    # Each distinct poster fetched once (through the wsrv fast CDN).
    assert len(seen) == 2
    assert sum("a.jpg" in u for u in seen) == 1
    assert sum("b.jpg" in u for u in seen) == 1
    # Already cached → second warm-up does no network.
    seen.clear()
    ti.prefetch_many(urls)
    assert seen == []
