"""DASH playback path (Vidlink): mpv must receive the signed CDN headers."""

import subprocess as _sp
from types import SimpleNamespace

from freeflix_cli import player_manager as pm


def test_dash_mpv_forwards_signed_headers(monkeypatch):
    captured = {}

    monkeypatch.setattr(pm, "_mpv_config_args", lambda: [])
    monkeypatch.setattr(pm, "_mpv_resilience_args", lambda: [])
    monkeypatch.setattr(pm, "_mpv_position_args", lambda title: ([], "", ""))
    monkeypatch.setattr(pm, "_mpv_ipc_args", lambda key: ([], None))
    monkeypatch.setattr(pm, "_save_mpv_position", lambda *a, **k: None)
    # _nvidia_env() probes the GPU with lspci/nvidia-smi; keep it out of the
    # capture (and out of CI runners that have no GPU).
    monkeypatch.setattr(pm, "_nvidia_env", lambda: {})
    # Replace only player_manager's reference: patching the global
    # subprocess.run would also capture background probes (lspci, …) on a
    # busy CI runner.
    monkeypatch.setattr(
        pm, "subprocess",
        SimpleNamespace(
            run=lambda cmd, **kw: captured.setdefault("cmd", cmd),
            CalledProcessError=_sp.CalledProcessError,
        ),
    )

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://vidlink.pro/",
        "Origin": "https://vidlink.pro",
        "Cookie": "CloudFront-Policy=x;CloudFront-Signature=y",
        "Connection": "keep-alive",
        "Accept-Encoding": "gzip",
        "X-Bad": "a,b",
    }
    ok = pm._play_dash_mpv(
        "mpv",
        "https://sacdn.example.com/dash/1/index_web.mpd",
        headers,
        "Test",
        subtitle_path="/tmp/sub.srt",
    )

    assert ok is True
    cmd = captured["cmd"]
    assert cmd[-1].endswith("index_web.mpd")
    field_arg = next(c for c in cmd if c.startswith("--http-header-fields="))
    assert "Cookie: CloudFront-Policy=x;CloudFront-Signature=y" in field_arg
    assert "Referer: https://vidlink.pro/" in field_arg
    assert "Connection" not in field_arg
    assert "Accept-Encoding" not in field_arg
    assert "X-Bad" not in field_arg  # comma would corrupt mpv's list
    assert "--sub-files=/tmp/sub.srt" in cmd
    assert "--title=Test" in cmd


def test_probe_dash_reads_representations(monkeypatch):
    mpd = """<?xml version="1.0"?>
    <MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
      <Period><AdaptationSet>
        <Representation id="1080" bandwidth="5300000" width="1920" height="1080"/>
        <Representation id="720" bandwidth="3000000" width="1280" height="720"/>
        <Representation id="360" bandwidth="900000" width="640" height="360"/>
      </AdaptationSet></Period>
    </MPD>"""
    monkeypatch.setattr(pm, "shared_session", lambda: object())
    monkeypatch.setattr(pm, "_safe_probe_text", lambda *a, **k: mpd)

    assert pm._probe_dash("https://cdn/master.mpd", {}) == [
        {"height": 1080, "mbps": 5.3},
        {"height": 720, "mbps": 3.0},
        {"height": 360, "mbps": 0.9},
    ]


def test_analyze_dash_uses_manifest_parser(monkeypatch):
    monkeypatch.setattr(
        pm, "_probe_stream", lambda *a, **k: {"variants": [], "blocked": None}
    )
    monkeypatch.setattr(
        pm, "_probe_dash", lambda *a, **k: [{"height": 1080, "mbps": 5.3}]
    )
    monkeypatch.setattr(pm, "_ffprobe_quality", lambda *a, **k: None)

    info = pm._analyze_stream_quality_uncached(
        "https://cdn/master.mpd", {"Referer": "https://vidlink.pro/"}
    )
    assert info["ok"] is True
    assert info["qualities"] == [{"height": 1080, "mbps": 5.3}]
    assert info["stream_url"] == "https://cdn/master.mpd"


def test_ffprobe_forwards_signed_headers(monkeypatch):
    captured = {}

    class _R:
        stdout = '{"streams":[{"height":1080,"bit_rate":"5000000"}]}'

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _R()

    monkeypatch.setattr(pm.shutil, "which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        pm, "subprocess",
        SimpleNamespace(run=fake_run, CalledProcessError=_sp.CalledProcessError),
    )

    headers = {
        "Referer": "https://vidlink.pro/",
        "Cookie": "CloudFront-Policy=x;CloudFront-Signature=y",
        "X-Playback-Environment": "dash-hevc",
        "Connection": "keep-alive",
        "Accept-Encoding": "gzip",
    }
    assert pm._ffprobe_quality("https://cdn/master.mpd", headers) == {
        "height": 1080, "mbps": 5.0,
    }
    # The -headers value is the argument right after the flag.
    hdr_arg = captured["cmd"][captured["cmd"].index("-headers") + 1]
    assert "Referer: https://vidlink.pro/" in hdr_arg
    assert "Cookie: CloudFront-Policy=x" in hdr_arg
    assert "X-Playback-Environment: dash-hevc" in hdr_arg
    assert "Connection" not in hdr_arg
    assert "Accept-Encoding" not in hdr_arg
