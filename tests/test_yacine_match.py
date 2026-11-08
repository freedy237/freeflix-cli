"""Tests for the YacineTV match catalogue and its local HLS proxy."""

import base64
import http.server
import json
import threading
import urllib.request


from freeflix_cli.scraping import yacine_match as ym


def _encrypt(obj, stamp="1793940000"):
    raw = json.dumps(obj, ensure_ascii=False).encode()
    key = ym._KEY + stamp.encode()
    return base64.b64encode(
        bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))).decode()


def test_decrypt_payload_roundtrip():
    obj = {"data": [{"champions": "الدوري الفرنسي", "id": "1"}]}
    assert ym.decrypt_payload(_encrypt(obj), "1793940000") == obj


def test_event_status_and_cameroon_timezone():
    now = 1_800_000_000
    live = ym.MatchEvent("1", "L", "C", now - 60, now + 3600, "A", "B")
    upcoming = ym.MatchEvent("2", "L", "C", now + 60, now + 7200, "A", "B")
    ended = ym.MatchEvent("3", "L", "C", now - 7200, now - 60, "A", "B")
    assert live.status(now) == "live"
    assert upcoming.status(now) == "upcoming"
    assert ended.status(now) == "ended"
    assert live.start_dt.utcoffset().total_seconds() == 3600


def test_pick_auto_prefers_hd():
    streams = [{"name": "Low"}, {"name": "SD"}, {"name": "HD"}]
    assert ym.pick_auto(streams)["name"] == "HD"
    assert ym.pick_auto([]) is None


def test_parse_events_skips_invalid_and_fills_end():
    data = {"data": [
        {"id": "1", "start_time": 100, "team_1": {"name": "A"},
         "team_2": {"name": "B"}},
        {"id": "", "start_time": 100},
        {"id": "2", "start_time": 0},
    ]}
    events = ym._parse_events(data)
    assert [e.id for e in events] == ["1"]
    assert events[0].end == 100 + 7200


def test_fetch_streams_parses_and_sorts(monkeypatch):
    monkeypatch.setattr(ym, "_hosts_to_try", lambda: ["api"])
    monkeypatch.setattr(ym, "_request_json", lambda *a, **k: {"data": [
        {"name": "Low", "url": "http://x/l.m3u8",
         "headers": {"Referer": "r", "User-Agent": "ua"}},
        {"name": "HD", "url": "http://x/h.m3u8", "referer": "r2",
         "user_agent": "ua2"},
        {"name": "bad", "url": "ftp://x"},
    ]})
    streams = ym.fetch_streams("1")
    assert [s["name"] for s in streams] == ["HD", "Low"]
    assert streams[0]["headers"]["Referer"] == "r2"
    assert streams[1]["headers"]["User-Agent"] == "ua"


def test_fetch_events_falls_back_to_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(ym, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(ym, "_hosts_to_try", lambda: ["api"])
    ev = ym.MatchEvent("1", "L", "C", 100, 200, "A", "B")
    ym._save_events([ev])

    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(ym, "_request_json", boom)
    events, cached = ym.fetch_events()
    assert cached is True
    assert [e.id for e in events] == ["1"]


class _Upstream(http.server.BaseHTTPRequestHandler):
    seen = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.endswith(".m3u8"):
            body = ("#EXTM3U\n#EXTINF:6,\n/seg/1.php\n"
                    "#EXTINF:6,\n/seg/2.php\n").encode()
            ctype = "application/vnd.apple.mpegurl"
        else:
            body = b"SEGMENT"
            ctype = "video/mp2t"
        type(self).seen["referer"] = self.headers.get("Referer")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_local_proxy_sends_exact_utf8_headers_and_rewrites_segments():
    from freeflix_cli.yacine_live_proxy import start_live_proxy

    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    port = upstream.server_address[1]
    ref = "http://yacinneeee.live\u2060\u200d\u2060ㅤ\u200c\u2060\u200d\u2060"
    proxy, local = start_live_proxy(
        f"http://127.0.0.1:{port}/live/index.m3u8",
        {"Referer": ref, "User-Agent": "UA"},
    )
    try:
        playlist = urllib.request.urlopen(local, timeout=10).read().decode()
        assert "/seg/1.php" not in playlist
        assert playlist.count(".ts") == 2
        seg = playlist.splitlines()[-1]
        data = urllib.request.urlopen(
            f"http://127.0.0.1:{proxy.httpd.server_address[1]}{seg}",
            timeout=10).read()
        assert data == b"SEGMENT"
        # http.server decodes header bytes as latin-1; re-encode to compare.
        wire = _Upstream.seen["referer"].encode("latin-1")
        assert wire == ref.encode("utf-8")
    finally:
        proxy.stop()
        upstream.shutdown()
        upstream.server_close()


def test_match_handler_lists_live_and_auto_quality(monkeypatch):
    import time

    from freeflix_cli.handlers import match as mh
    from freeflix_cli import player_manager
    from freeflix_cli.i18n import t

    now = int(time.time())
    ev = ym.MatchEvent("1", "Ligue 1", "beIN 1", now - 60, now + 3600,
                       "Toulouse", "Strasbourg")
    streams = [{"name": "HD", "url": "http://x/hd.m3u8",
                "headers": {"Referer": "r"}},
               {"name": "SD", "url": "http://x/sd.m3u8",
                "headers": {"Referer": "r"}}]
    monkeypatch.setattr(mh.ym, "fetch_events", lambda: ([ev], False))
    monkeypatch.setattr(mh.ym, "fetch_streams", lambda _id: streams)
    monkeypatch.setattr(mh, "_available_players", lambda: ["mpv"])
    calls = []

    def fake_select(options, prompt, **kw):
        calls.append(list(options))
        if len(calls) == 1:
            return 0                    # first match
        if len(calls) == 2:
            return len(streams)         # Auto (just before Back)
        return len(options) - 1         # Back on the next match list

    headers = {}

    def fake_select2(options, prompt, **kw):
        headers.setdefault("g", kw.get("group_headers"))
        return fake_select(options, prompt, **kw)

    monkeypatch.setattr(mh, "select_from_list", fake_select2)
    played = []
    monkeypatch.setattr(player_manager, "match_stream_reachable",
                        lambda *a, **k: (True, ""))
    monkeypatch.setattr(player_manager, "play_direct_stream",
                        lambda *a, **k: played.append(a) or True)

    mh.handle_match()
    # Grouping: the status lives in the section header, the row stays aligned.
    assert headers["g"], "expected status section headers"
    first_header = next(iter(headers["g"].values()))
    assert t("LIVE now") in first_header
    assert calls[1][-1] == t("← Back")
    assert "Auto" in calls[1][-2]
    assert played and "hd.m3u8" in played[0][0]


def test_localize_events_uses_dynamic_translation(monkeypatch, tmp_path):
    monkeypatch.setattr(ym, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(ym, "_translate_one",
                        lambda text, lang, timeout=5: {
                            "تولوز": "Toulouse", "ستراسبورغ": "Strasbourg",
                            "الدوري الفرنسي": "Ligue française",
                        }.get(text, text))
    ev = ym.MatchEvent("1", "الدوري الفرنسي", "beIN", 1, 2,
                       "تولوز", "ستراسبورغ")
    out = ym.localize_events([ev], "fr")
    assert out[0].home == "Toulouse"
    assert out[0].away == "Strasbourg"
    assert out[0].championship == "Ligue française"


def test_play_direct_stream_falls_back_to_mpv_for_manual(monkeypatch):
    from freeflix_cli import player_manager as pm
    from freeflix_cli import tracker
    from freeflix_cli import yacine_live_proxy

    class P:
        stopped = False

        def stop(self):
            self.stopped = True

    p = P()
    monkeypatch.setattr(yacine_live_proxy, "start_live_proxy",
                        lambda url, headers: (p, "http://127.0.0.1/x.m3u8"))
    monkeypatch.setattr(tracker.tracker, "get_player", lambda: "manual")
    monkeypatch.setattr(tracker.tracker, "get_match_player", lambda: None)
    monkeypatch.setattr(pm, "_resolve_or_install", lambda name: "/usr/bin/mpv")
    called = {}
    monkeypatch.setattr(pm, "_play_dash_mpv",
                        lambda exe, url, h, title, live=False:
                        called.update(exe=exe, url=url, live=live) or True)

    assert pm.play_direct_stream("http://cdn/x.m3u8", {"Referer": "r"},
                                 "A - B") is True
    assert called["exe"] == "/usr/bin/mpv"
    assert called["live"] is True
    assert p.stopped is True


def test_match_player_is_chosen_after_quality(monkeypatch):
    from freeflix_cli.handlers import match as mh
    from freeflix_cli import tracker

    monkeypatch.setattr(mh, "_available_players", lambda: ["mpv", "vlc"])
    seen = {}

    def fake_select(options, prompt, **kw):
        seen["options"] = options
        return 1  # VLC

    monkeypatch.setattr(mh, "select_from_list", fake_select)
    monkeypatch.setattr(tracker.tracker, "set_match_player",
                        lambda name: seen.setdefault("player", name))
    chosen = mh._choose_player("mpv", allow_cancel=True)
    assert chosen == "vlc"
    assert seen["player"] == "vlc"
    assert any("VLC" in o for o in seen["options"])
    assert any("Back" in o or "Retour" in o for o in seen["options"])


def test_play_direct_stream_respects_explicit_vlc(monkeypatch):
    from freeflix_cli import player_manager as pm
    from freeflix_cli import tracker
    from freeflix_cli import yacine_live_proxy

    class P:
        def stop(self):
            pass

    monkeypatch.setattr(yacine_live_proxy, "start_live_proxy",
                        lambda url, headers: (P(), "http://127.0.0.1/x.m3u8"))
    monkeypatch.setattr(tracker.tracker, "get_player", lambda: "mpv")
    monkeypatch.setattr(tracker.tracker, "get_match_player", lambda: "mpv")
    called = {}
    def fake_resolve(name):
        called["exe"] = name
        return "/usr/bin/vlc"

    monkeypatch.setattr(pm, "_resolve_or_install", fake_resolve)
    monkeypatch.setattr(pm.shutil, "which", lambda name: None)

    class Proc:
        returncode = 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(cmd, **kw):
        called["cmd"] = cmd
        return Proc()

    monkeypatch.setattr(pm.subprocess, "Popen", fake_popen)
    try:
        assert pm.play_direct_stream("http://cdn/x.m3u8", {"Referer": "r"},
                                     "A - B", player_name="vlc") is True
        assert called["exe"] == "vlc"
        assert called["cmd"][0] == "/usr/bin/vlc"
        assert "--no-one-instance" in called["cmd"]
        assert "--ignore-config" in called["cmd"]
        assert "--no-media-library" in called["cmd"]
        assert pm._VLC_KEEPALIVE
    finally:
        pm._stop_vlc_keepalive()


def test_match_channel_and_quality_estimates():
    from datetime import datetime, timedelta, timezone
    from freeflix_cli.handlers import match as mh

    now = datetime.now(tz=timezone(timedelta(hours=1)))
    ev = ym.MatchEvent("1", "Ligue 1", "beIN SPORTS 4",
                       int(now.timestamp()) - 60, int(now.timestamp()) + 3600,
                       "Toulouse", "Strasbourg")
    label = mh._match_label(ev, int(now.timestamp()), now)
    assert label.startswith("(B4)")
    hd = mh._quality_label({"name": "HD"})
    assert "5.0" in hd and "2.25" in hd
    low = mh._quality_label({"name": "Low"})
    assert "1.0" in low and "0.45" in low


def test_channel_aliases_and_other_channels():
    from freeflix_cli.handlers import match as mh
    assert mh._channel_label("beIN SPORTS 1") == "B1"
    assert mh._channel_label("beIN SPORTS 4") == "B4"
    assert mh._channel_label("beIN SPORTS 5") == "B5"
    assert mh._channel_label("Canal+ Sport") == "CS"


def test_future_4k_quality_estimate():
    from freeflix_cli.handlers import match as mh
    label = mh._quality_label({"name": "4K"})
    assert "2160p" in label and "15.0" in label and "6.75" in label


def test_other_teams_are_dynamic(monkeypatch, tmp_path):
    monkeypatch.setattr(ym, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(ym, "_translate_one",
                        lambda text, lang, timeout=5:
                        {"الأهلي": "Al Ahly", "الزمالك": "Zamalek"}.get(text, text))
    ev = ym.MatchEvent("x", "الدوري المصري", "Canal+ Sport", 1, 2,
                       "الأهلي", "الزمالك")
    out = ym.localize_events([ev], "fr")[0]
    assert out.home == "Al Ahly" and out.away == "Zamalek"
    assert out.championship == "الدوري المصري"


def test_channel_labels_cover_new_channels():
    from freeflix_cli.handlers import match as mh
    assert mh._channel_label("beIN SPORTS 6") == "B6"
    assert mh._channel_label("beIN SPORTS 8") == "B8"
    assert mh._channel_label("Dubai Sports 1") == "DS1"
    assert mh._channel_label("Canal+ Sport 2") == "CS2"
    assert mh._channel_label("Sky Sports F1") == "SSF"
    assert mh._channel_label("ESPN") == "E"
    assert mh._channel_label("") == ""


def test_every_channel_name_yields_a_short_badge():
    """Whatever the source sends, the label stays short (≤ 6 chars)."""
    from freeflix_cli.handlers import match as mh
    samples = [
        "beIN SPORTS 1", "beIN SPORTS 7", "beIN SPORTS 10",
        "Dubai Sports", "Dubai Sports 3", "Dubai Racing 2",
        "Canal+ Sport", "Canal+ Sport 2", "Sky Sports F1", "ESPN",
        "RMC Sport 1", "TF1", "Al Jazeera Sport 3", "BBC One HD",
        "Eurosport 1", "Fox Sports 2", "Sport TV 5", "Ziggo Sport",
    ]
    for name in samples:
        label = mh._channel_label(name)
        assert label and len(label) <= 6, (name, label)
        assert label != name or len(name) <= 6, (name, label)


def test_club_dictionary_overrides_bad_machine_translation(monkeypatch, tmp_path):
    """Curated club data wins over literal MT ("ليل" must never become "nuit")."""
    monkeypatch.setattr(ym, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(ym, "_translate_one",
                        lambda text, lang, timeout=5: "nuit" if text == "ليل" else text)
    ev = ym.MatchEvent("1", "Ligue 1", "beIN 1", 1, 2, "ليل", "رين")
    out = ym.localize_events([ev], "fr")[0]
    assert out.home.lower() != "nuit"
    assert "Lille" in out.home


def test_generic_translation_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(ym, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(ym, "_translate_one",
                        lambda text, lang, timeout=5: "night")
    assert ym._translate_cached("لعبة", "fr", {}) == "لعبة"


def test_channel_logo_lookup_is_bundled():
    from freeflix_cli.scraping.yacine_match import channel_logo
    assert channel_logo("beIN SPORTS 1").startswith("http")
    assert channel_logo("Dubai Sports 1").startswith("http")


def test_match_stream_reachable_reports_dns_failure(monkeypatch):
    from freeflix_cli import player_manager as pm
    import socket

    def boom(*a, **k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    ok, why = pm.match_stream_reachable(
        "https://dead.cdn.invalid/live/x.m3u8", {})
    assert ok is False and why


_TS_FIXTURE = ""


def _make_ts_fixture(path):
    """Tiny real MPEG-TS so ffmpeg can decode at least one frame."""
    import shutil as _sh
    import subprocess

    if not _sh.which("ffmpeg"):
        return False

    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "testsrc=size=64x64:rate=5", "-f", "lavfi", "-i",
         "sine=frequency=440", "-t", "2", "-c:v", "libx264",
         "-preset", "ultrafast", "-c:a", "aac", "-f", "mpegts", path],
        check=True, timeout=60)
    return True


def test_match_stream_reachable_true_for_local_manifest(monkeypatch, tmp_path):

    import http.server
    import threading
    from freeflix_cli import player_manager as pm

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if "seg" in self.path:
                body = b"\x47" * 188
            else:
                body = b"#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nseg.ts\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    # CI runners have no ffmpeg: force the proxy fallback path.
    monkeypatch.setattr(pm.shutil, "which",
                        lambda name: None if name == "ffmpeg" else "x")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        ok, why = pm.match_stream_reachable(
            f"http://127.0.0.1:{port}/live/index.m3u8", {})
        assert ok is True and why == ""
    finally:
        srv.shutdown()
        srv.server_close()


def test_dedupe_prefers_live_fixture_over_finished_copy():
    """The catalogue repeats fixtures; one row must be shown, the live one."""
    import time
    from freeflix_cli.handlers import match as mh

    now = int(time.time())
    finished = ym.MatchEvent("old", "NED", "Dubai Sports 1",
                             now - 7200, now - 5400, "Twente", "Ajax")
    live = ym.MatchEvent("new", "NED", "Dubai Sports 1",
                         now - 600, now + 6600, "Twente", "Ajax")
    other = ym.MatchEvent("o", "FRA", "beIN SPORTS 1",
                          now - 600, now + 6600, "Lens", "Marseille")
    kept = mh._dedupe([finished, live, other], now)
    assert len(kept) == 2
    twente = [e for e in kept if e.home == "Twente"][0]
    assert twente.id == "new" and twente.status(now) == "live"


def test_dedupe_never_lists_one_fixture_in_two_statuses():
    import time
    from freeflix_cli.handlers import match as mh

    now = int(time.time())
    events = [
        ym.MatchEvent("a", "L", "C1", now - 8000, now - 7000, "A", "B"),
        ym.MatchEvent("b", "L", "C2", now - 60, now + 7000, "A", "B"),
        ym.MatchEvent("c", "L", "C1", now + 9000, now + 16000, "A", "B"),
    ]
    kept = mh._dedupe(events, now)
    assert len(kept) == 1
    assert kept[0].status(now) == "live"


def test_preflight_rejects_manifest_with_dead_segments(monkeypatch):
    """A playlist whose segments 404 must not open a player."""
    import http.server
    import threading
    from freeflix_cli import player_manager as pm

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if "seg" in self.path:
                self.send_response(404)
                self.end_headers()
                return
            body = b"#EXTM3U\n#EXTINF:6,\nseg.ts\n"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    monkeypatch.setattr(pm.shutil, "which",
                        lambda name: None if name == "ffmpeg" else "x")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        ok, why = pm.match_stream_reachable(
            f"http://127.0.0.1:{srv.server_address[1]}/live/index.m3u8", {})
        assert ok is False
        assert why
    finally:
        srv.shutdown()
        srv.server_close()


def test_play_falls_back_to_another_source(monkeypatch):
    """When the chosen quality is dead, the next source is tried."""
    from freeflix_cli.handlers import match as mh
    from freeflix_cli import player_manager

    ev = ym.MatchEvent("1", "L", "beIN SPORTS 1", 1, 2, "A", "B")
    hd = {"name": "HD", "url": "https://dead.example/hd.m3u8", "headers": {}}
    multi = {"name": "Multi", "url": "https://ok.example/m.m3u8", "headers": {}}
    results = {"https://dead.example/hd.m3u8": (False, "dead"),
               "https://ok.example/m.m3u8": (True, "")}
    monkeypatch.setattr(player_manager, "match_stream_reachable",
                        lambda url, h: results[url])
    played = []
    monkeypatch.setattr(player_manager, "play_direct_stream",
                        lambda url, h, title, player_name=None:
                        played.append(url) or True)
    mh._play(ev, hd, "mpv", [hd, multi])
    assert played == ["https://ok.example/m.m3u8"]
