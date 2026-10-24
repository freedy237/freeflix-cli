"""
Tests for the Android first-run setup path in setup_assistant.

All mocked (no device) : Android detection routes setup to the Android wizard,
the package installer picks pkg/apt correctly, the player counts as present via
mpv-android, and is_setup_complete gates on the setup_done flag.
"""

import subprocess

import freeflix_cli.setup_assistant as sa


def test_have_player_on_android(monkeypatch):
    monkeypatch.setattr(sa, "_is_android", lambda: True)
    monkeypatch.setattr("freeflix_cli.platform_android.available", lambda: True)
    # no mpv/vlc binary on PATH, but mpv-android handoff is available
    monkeypatch.setattr(sa.shutil, "which", lambda b: None)
    monkeypatch.setattr(sa, "_have_managed", lambda bins: False)
    assert sa._have(("mpvnet", "mpv", "vlc")) is True


def test_is_setup_complete_android_gates_on_flag(monkeypatch):
    monkeypatch.setattr(sa, "_is_android", lambda: True)
    sa.tracker.data.pop("setup_done", None)
    assert sa.is_setup_complete() is False
    sa.tracker.data["setup_done"] = True
    try:
        assert sa.is_setup_complete() is True
    finally:
        sa.tracker.data.pop("setup_done", None)


def test_android_install_uses_pkg(monkeypatch):
    monkeypatch.setattr(sa.shutil, "which", lambda name: "/data/.../pkg" if name == "pkg" else None)
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.setdefault("cmd", cmd))
    assert sa._android_install_pkgs(["ffmpeg", "aria2"]) is True
    assert seen["cmd"][:3] == ["pkg", "install", "-y"]
    assert "ffmpeg" in seen["cmd"] and "aria2" in seen["cmd"]


def test_android_install_uses_apt_in_proot(monkeypatch):
    monkeypatch.setattr(sa.shutil, "which",
                        lambda name: "/usr/bin/apt-get" if name == "apt-get" else None)
    monkeypatch.setattr(sa.os, "geteuid", lambda: 0, raising=False)
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.setdefault("cmd", cmd))
    assert sa._android_install_pkgs(["ffmpeg"]) is True
    assert seen["cmd"][0] == "apt-get"


def test_run_setup_routes_to_android(monkeypatch):
    monkeypatch.setattr(sa, "_is_android", lambda: True)
    monkeypatch.setattr(sa, "is_setup_complete", lambda: False)
    monkeypatch.setattr(sa, "ask_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(sa, "_android_install_pkgs", lambda pkgs: True)
    saved = {}
    monkeypatch.setattr(sa.tracker, "set_player", lambda p: saved.setdefault("player", p))
    monkeypatch.setattr(sa.tracker, "_save_data", lambda: None)
    assert sa.run_setup(force=True) is True
    assert saved["player"] == "android"
    assert sa.tracker.data.get("setup_done") is True
    sa.tracker.data.pop("setup_done", None)
