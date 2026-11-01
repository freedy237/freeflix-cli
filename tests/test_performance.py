"""Performance guards: no hidden network resolve in listings, real caching."""

from types import SimpleNamespace

from freeflix_cli import player_manager as pm
from freeflix_cli.handlers import playback
from freeflix_cli.scraping import french_stream as fs
from freeflix_cli.scraping import player as player_mod


def test_french_stream_liveness_is_head_only_and_cached(monkeypatch):
    """Listing players must not run a full extractor (fsvid/vidzy: 90 s)."""
    fs._player_alive_cache.clear()
    calls = []
    monkeypatch.setattr(
        fs, "_probe_embed",
        lambda link: calls.append(link) or SimpleNamespace(status_code=200),
    )
    monkeypatch.setattr(
        player_mod, "get_hls_link",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not resolve")),
    )

    assert fs._player_alive("https://voe.sx/e/perf-a") is True
    assert fs._player_alive("https://voe.sx/e/perf-a") is True
    assert calls == ["https://voe.sx/e/perf-a"]  # second hit = cache, no HEAD


def test_french_stream_liveness_drops_404(monkeypatch):
    fs._player_alive_cache.clear()
    monkeypatch.setattr(
        fs, "_probe_embed", lambda link: SimpleNamespace(status_code=404)
    )
    assert fs._player_alive("https://voe.sx/e/perf-dead") is False


def test_expected_hls_info_is_cached(monkeypatch):
    pm._hls_info_cache.clear()
    calls = []
    monkeypatch.setattr(
        pm, "_expected_hls_info_uncached",
        lambda *a, **k: calls.append(1) or (123.0, 4.0),
    )
    url = "https://cdn.example/perf-media.m3u8"
    assert pm._expected_hls_info(url) == (123.0, 4.0)
    assert pm._expected_hls_info(url) == (123.0, 4.0)
    assert len(calls) == 1


def test_player_menu_hides_dead_and_ad_players(monkeypatch):
    """Analysis filters failed embeds + 30 s ads before the menu is drawn."""
    dead = SimpleNamespace(name="dead", url="https://dead.example/e/1")
    ad = SimpleNamespace(name="ad", url="https://ad.example/e/2")
    good = SimpleNamespace(name="good", url="https://good.example/e/3")
    episode = SimpleNamespace(players=[dead, ad, good], title="Episode 1")

    def fake_quality(url, headers=None, timeout=20):
        if "dead" in url:
            return {"ok": False}
        if "ad" in url:
            return {"ok": True, "duration": 30.0}
        return {"ok": True, "qualities": [{"height": 720, "mbps": 2.0}]}

    monkeypatch.setattr(playback.player, "is_supported", lambda url: True)
    monkeypatch.setattr(playback, "_dedup_players", lambda ps: ps)
    monkeypatch.setattr(playback.tracker, "get_analyze_players", lambda: True)
    monkeypatch.setattr(playback.tracker, "get_subtitle_search", lambda: False)
    monkeypatch.setattr(playback.tracker, "get_last_server", lambda: "")
    monkeypatch.setattr(playback, "analyze_stream_quality", fake_quality)
    monkeypatch.setattr(pm, "prefetch_stream", lambda *a, **k: None)
    captured = {}

    def fake_select(opts, prompt, **kw):
        captured["opts"] = opts
        return len(opts) - 1  # ← Back

    monkeypatch.setattr(playback, "select_from_list", fake_select)

    assert playback.play_episode_flow(
        "French-Stream", "Show", "Season 1", episode,
        "https://x/show", "https://x/show/season1", headers={},
    ) is False
    assert len(captured["opts"]) == 2  # only "good" + Back
    assert "dead" not in captured["opts"][0]
    assert "ad" not in captured["opts"][0]
    assert "good" in captured["opts"][0]
