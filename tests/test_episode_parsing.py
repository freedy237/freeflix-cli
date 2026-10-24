"""Episode lists: correct numeric order, no empty/dead placeholders."""

from freeflix_cli.scraping import french_stream as fs


def test_french_stream_episodes_are_numeric_and_skip_dead_hosts(monkeypatch):
    info = {
        "vf": {
            "10": {"uqload": "https://uqload.vc/embed-10.html"},
            "2": {"vidzy": "https://vidzy.cc/embed-2.html"},
            "1": {"voe": "https://voe.sx/e/1"},
            "3": {"netu": "https://netu.tv/e/dead"},
        }
    }
    # The dead host must not be kept as an episode.
    monkeypatch.setattr(fs, "_is_usable_player_link",
                        lambda link: "netu" not in link)
    eps = fs.get_episodes_from_lang("vf", info)
    assert [e.title for e in eps] == ["Episode 1", "Episode 2", "Episode 10"]
    assert all(e.players for e in eps)


def test_french_stream_reads_all_language_keys(monkeypatch):
    info = {
        "vff": {"1": {"uqload": "https://uqload.vc/embed-vff.html"}},
        "vfq": {"1": {"voe": "https://voe.sx/e/vfq"}},
        "info": {"1": {"title": "x"}},
        "vostfr": {},
    }

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return info

    monkeypatch.setattr(fs, "_get", lambda *a, **k: _R())
    monkeypatch.setattr(fs, "_is_usable_player_link", lambda link: True)
    html = ('<html><head><meta property="og:title" content="X"></head></html>')
    season = fs.get_series_season("https://french-stream.net/1-x.html", html)
    assert list(season.episodes) == ["vff", "vfq"]
    assert all(v and v[0].players for v in season.episodes.values())
