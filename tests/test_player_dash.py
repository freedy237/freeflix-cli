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
