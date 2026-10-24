"""In-app update prompt: announce → y/n → install → Enter → reload."""

import freeflix_cli.update_checker as uc


def _fake_plan(monkeypatch, current="1.0.0", latest="1.1.0"):
    monkeypatch.setattr(uc, "_running_version", lambda pkg: current)
    monkeypatch.setattr(uc, "_cached_latest", lambda pkg: latest)


def test_update_plan_none_when_up_to_date(monkeypatch):
    _fake_plan(monkeypatch, "1.13.9", "1.13.9")
    assert uc.update_plan() is None


def test_update_plan_detects_newer(monkeypatch):
    _fake_plan(monkeypatch, "1.13.9", "1.14.0")
    assert uc.update_plan() == ("1.13.9", "1.14.0")


def test_update_plan_compares_running_code_not_stale_metadata(monkeypatch):
    """A source checkout can hold 1.13.9 while dist-info says 1.11.6."""
    _fake_plan(monkeypatch, "1.13.9", "1.13.9")
    monkeypatch.setattr(uc, "_installed_version", lambda pkg: "1.11.6")
    assert uc.update_plan() is None


def test_ask_update_returns_the_clickable_prompt(monkeypatch):
    import freeflix_cli.cli_utils as cu
    for expected in (True, False):
        _fake_plan(monkeypatch)
        monkeypatch.setattr(cu, "ask_yes_no", lambda *a, _e=expected, **k: _e)
        monkeypatch.setattr(uc, "console", type("C", (), {"print": lambda *a, **k: None})())
        assert uc.ask_update() is expected


def test_ask_update_handles_ctrl_c_as_no(monkeypatch):
    import freeflix_cli.cli_utils as cu
    _fake_plan(monkeypatch)
    monkeypatch.setattr(uc, "console", type("C", (), {"print": lambda *a, **k: None})())

    def _boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cu, "ask_yes_no", _boom)
    assert uc.ask_update() is False


def test_ask_update_skips_when_no_new_version(monkeypatch):
    import freeflix_cli.cli_utils as cu
    _fake_plan(monkeypatch, "1.13.9", "1.13.9")
    asked = []
    monkeypatch.setattr(cu, "ask_yes_no", lambda p, **k: asked.append(p) or True)
    assert uc.ask_update() is False
    assert asked == []  # no question when there is nothing to install


def test_installer_kind_detection(monkeypatch):
    cases = [
        ("/home/u/.local/share/uv/tools/freeflix-cli/bin/python3",
         "/home/u/.local/share/uv/tools/freeflix-cli", "uv"),
        ("/home/u/.local/pipx/venvs/freeflix-cli/bin/python",
         "/home/u/.local/pipx/venvs/freeflix-cli", "pipx"),
        ("/usr/bin/python3", "/usr", "pip"),
        ("/home/u/project/.venv/bin/python", "/home/u/project/.venv", "pip"),
    ]
    for exe, prefix, expected in cases:
        monkeypatch.setattr(uc.sys, "executable", exe)
        monkeypatch.setattr(uc.sys, "prefix", prefix)
        monkeypatch.setattr(uc.sys, "frozen", False, raising=False)
        assert uc.installer_kind() == expected, exe


def test_uv_install_upgrades_with_uv(monkeypatch):
    monkeypatch.setattr(uc, "installer_kind", lambda: "uv")
    monkeypatch.setattr(uc.shutil, "which",
                        lambda name: "/usr/bin/uv" if name == "uv" else None)
    cmd, label = uc._upgrade_command("freeflix-cli")
    assert cmd == ["/usr/bin/uv", "tool", "upgrade", "freeflix-cli"]
    assert label == "uv tool upgrade"


def test_pipx_install_upgrades_with_pipx(monkeypatch):
    monkeypatch.setattr(uc, "installer_kind", lambda: "pipx")
    monkeypatch.setattr(uc.shutil, "which",
                        lambda name: "/usr/bin/pipx" if name == "pipx" else None)
    cmd, label = uc._upgrade_command("freeflix-cli")
    assert cmd == ["/usr/bin/pipx", "upgrade", "freeflix-cli"]
    assert label == "pipx upgrade"


def test_pip_install_upgrades_with_the_same_interpreter(monkeypatch):
    monkeypatch.setattr(uc, "installer_kind", lambda: "pip")
    monkeypatch.setattr(uc.sys, "executable", "/opt/py/bin/python3")
    cmd, label = uc._upgrade_command("freeflix-cli")
    assert cmd == ["/opt/py/bin/python3", "-m", "pip", "install",
                   "--upgrade", "freeflix-cli"]
    assert label == "pip install --upgrade"


def test_run_update_never_pips_into_a_source_checkout(monkeypatch):
    monkeypatch.setattr(uc, "_dev_checkout", lambda: True)
    _fake_plan(monkeypatch, "1.13.9", "1.14.0")
    ran = []
    monkeypatch.setattr(uc.subprocess, "run", lambda *a, **k: ran.append(a) or None)
    printed = []
    monkeypatch.setattr(uc, "print_info", lambda m, *a, **k: printed.append(m))
    monkeypatch.setattr(uc, "print_success", lambda m, *a, **k: printed.append(m))
    assert uc.run_update() is True
    assert ran == []  # nothing installed
    assert any("source" in str(m).lower() or "code source" in str(m).lower()
               for m in printed)


def test_run_update_still_uses_uv_even_from_a_checkout(monkeypatch):
    """Only pip would clobber a checkout; uv/pipx installs must still update."""
    monkeypatch.setattr(uc, "_dev_checkout", lambda: True)
    monkeypatch.setattr(uc, "installer_kind", lambda: "uv")
    monkeypatch.setattr(uc.shutil, "which",
                        lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(uc, "update_plan", lambda pkg="freeflix-cli": ("1.0", "2.0"))
    ran = []
    monkeypatch.setattr(uc.subprocess, "run",
                        lambda cmd, **k: ran.append(cmd) or type("R", (), {"returncode": 0})())
    monkeypatch.setattr(uc, "print_info", lambda *a, **k: None)
    monkeypatch.setattr(uc, "print_success", lambda *a, **k: None)
    assert uc.run_update() is True
    assert ran[0][:3] == ["/usr/bin/uv", "tool", "upgrade"]


def test_prompt_and_update_installs_then_reloads(monkeypatch):
    _fake_plan(monkeypatch)
    order = []
    monkeypatch.setattr(uc, "ask_update", lambda *a, **k: order.append("ask") or True)
    monkeypatch.setattr(uc, "run_update", lambda *a, **k: order.append("install") or True)
    monkeypatch.setattr("freeflix_cli.cli_utils.pause",
                        lambda *a, **k: order.append("pause") or None)
    monkeypatch.setattr(uc, "reload_process", lambda: order.append("reload"))
    monkeypatch.setattr(uc, "print_info", lambda *a, **k: None)
    uc.prompt_and_update()
    assert order == ["ask", "install", "pause", "reload"]


def test_prompt_and_update_install_failure_keeps_running(monkeypatch):
    order = []
    monkeypatch.setattr(uc, "ask_update", lambda *a, **k: order.append("ask") or True)
    monkeypatch.setattr(uc, "run_update", lambda *a, **k: order.append("install") or False)
    monkeypatch.setattr("freeflix_cli.cli_utils.pause",
                        lambda *a, **k: order.append("pause") or None)
    monkeypatch.setattr(uc, "reload_process", lambda: order.append("reload"))
    assert uc.prompt_and_update() is False
    assert order == ["ask", "install", "pause"]  # no reload on failure


def test_update_installs_new_system_tools_after_upgrade(monkeypatch):
    """A release with a new requirement must pull it in, not wait for a restart."""
    monkeypatch.setattr(uc, "installer_kind", lambda: "uv")
    monkeypatch.setattr(uc.shutil, "which",
                        lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(uc, "_dev_checkout", lambda: False)
    monkeypatch.setattr(uc, "update_plan", lambda pkg="freeflix-cli": ("1.0", "2.0"))
    monkeypatch.setattr(uc.subprocess, "run",
                        lambda cmd, **k: type("R", (), {"returncode": 0})())
    monkeypatch.setattr(uc, "print_info", lambda *a, **k: None)
    monkeypatch.setattr(uc, "print_success", lambda *a, **k: None)
    checked = []
    monkeypatch.setattr(uc, "_new_tools_missing", lambda: checked.append(True) or False)
    assert uc.run_update() is True
    assert checked == [True]  # release tools are checked right after upgrade


def test_prompt_and_update_declined_does_nothing(monkeypatch):
    order = []
    monkeypatch.setattr(uc, "ask_update", lambda *a, **k: order.append("ask") or False)
    monkeypatch.setattr(uc, "run_update", lambda *a, **k: order.append("install") or True)
    monkeypatch.setattr(uc, "reload_process", lambda: order.append("reload"))
    assert uc.prompt_and_update() is False
    assert order == ["ask"]
