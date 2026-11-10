"""Windows player discovery / installation.

Regression guard for the "mpv is installed but FreeFlix says it is missing"
reports: mpv.net only ships ``mpvnet.exe`` (GUI wrapper), so the real
``mpv.exe`` CLI from winget must be preferred and its shim folder refreshed.
"""


def test_get_mpv_path_prefers_real_mpv(monkeypatch):
    from freeflix_cli import player_manager as pm

    found = {"mpv": "/opt/mpv", "mpvnet": "/opt/mpvnet"}
    monkeypatch.setattr(pm.shutil, "which", lambda name: found.get(name))

    assert pm.get_mpv_path() == "/opt/mpv"


def test_get_mpv_path_falls_back_to_mpvnet(monkeypatch):
    from freeflix_cli import player_manager as pm

    monkeypatch.setattr(pm.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        pm.shutil, "which",
        lambda name: "/opt/mpvnet" if name == "mpvnet" else None,
    )

    assert pm.get_mpv_path() == "/opt/mpvnet"


def test_get_mpv_path_finds_winget_package_dir(monkeypatch):
    """winget portable packages are not always linked into Links\\."""
    from freeflix_cli import player_manager as pm

    monkeypatch.setattr(pm.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pm.shutil, "which", lambda name: None)
    monkeypatch.setattr(pm.os.path, "exists", lambda path: False)
    monkeypatch.setattr(
        pm.glob, "glob",
        lambda pattern, recursive=False: (
            [r"C:\Users\u\WinGet\Packages\shinchiro.mpv\mpv.exe"]
            if "shinchiro.mpv" in pattern else []
        ),
    )

    assert pm.get_mpv_path().endswith("mpv.exe")


def test_windows_mpv_install_tries_real_cli_before_mpvnet(monkeypatch):
    from freeflix_cli import player_manager as pm
    from freeflix_cli import setup_assistant as sa

    monkeypatch.setattr(sa, "detect_os", lambda: "windows")
    monkeypatch.setattr(
        sa.shutil, "which",
        lambda name: "winget" if name == "winget" else None,
    )
    monkeypatch.setattr(sa, "ask_yes_no", lambda *a, **k: True)

    calls = []
    monkeypatch.setattr(
        sa.subprocess, "run",
        lambda cmd, **kwargs: calls.append(cmd),
    )

    # First candidate fails to produce a binary, second one succeeds.
    results = iter([None, r"C:\mpv\mpv.exe"])
    monkeypatch.setattr(pm, "get_mpv_path", lambda: next(results))

    assert sa.install_media_player("mpv") is True
    ids = [cmd[cmd.index("--id") + 1] for cmd in calls]
    assert ids == ["shinchiro.mpv", "mpv-player.mpv-CI.MSVC"]
