"""Shared test fixtures.

All tests run with ISOLATED caches: the persistent HTTP cache and the
portal-origin cache are redirected to a per-test tmp dir. Without this, a
developer's real cache (populated by using the app) leaks into the mocks and
makes tests order/time dependent — exactly what bit `test_hianime_episodes_parse`
when catalogue caching was added.
"""

import pytest

from freeflix_cli import httpcache
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
