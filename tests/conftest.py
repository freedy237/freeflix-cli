"""Shared test fixtures.

All tests run with ISOLATED caches: the persistent HTTP cache and the
portal-origin cache are redirected to a per-test tmp dir. Without this, a
developer's real cache (populated by using the app) leaks into the mocks and
makes tests order/time dependent — exactly what bit `test_hianime_episodes_parse`
when catalogue caching was added.

The managed-binary directory is isolated too: `test_managed_binaries` used to
create and `shutil.rmtree` the REAL ``~/.local/share/freeflix-cli/bin``, which
could delete the ffmpeg/mpv/chafa that FreeFlix downloaded for the user.
"""

import pytest

from freeflix_cli import httpcache, setup_assistant
from freeflix_cli.scraping import utils as scraping_utils


@pytest.fixture(autouse=True)
def _isolate_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(httpcache, "_DIR", tmp_path / "http-cache")
    monkeypatch.setattr(
        scraping_utils,
        "_origin_cache_file",
        lambda: tmp_path / "origins.json",
    )
    yield


@pytest.fixture(autouse=True)
def _isolate_managed_bin(tmp_path, monkeypatch):
    """Never let a test create/delete the user's real managed binaries."""
    monkeypatch.setattr(
        setup_assistant,
        "_bin_dir",
        lambda: tmp_path / "managed-bin",
    )
    yield
