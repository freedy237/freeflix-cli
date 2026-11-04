"""Unit coverage for the small, previously untested modules.

The audit found that `cli.py`, `doctor.py`, `providers_registry.py`,
`config_loader.py`, `install_health.py` and the UI primitives were only
exercised indirectly (or not at all). These tests keep the entry points,
argument handling and config parsing honest without any network.
"""

import json
import os
import stat
from types import SimpleNamespace

import pytest

from freeflix_cli import cli, config_loader, doctor, install_health, languages
from freeflix_cli import themes, ui
from freeflix_cli.providers_registry import ProviderRegistry
from freeflix_cli.tracker import tracker


# ── cli entry point ──────────────────────────────────────────────────

def test_cli_version_prints_a_version(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["freeflix", "--version"])
    assert cli.main() == 0
    out = capsys.readouterr().out.strip()
    assert out and out[0].isdigit()


def test_cli_help_mentions_doctor(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["freeflix", "--help"])
    assert cli.main() == 0
    assert "--doctor" in capsys.readouterr().out


def test_cli_doctor_delegates(monkeypatch):
    import freeflix_cli.doctor as doctor_mod

    monkeypatch.setattr("sys.argv", ["freeflix", "--doctor"])
    monkeypatch.setattr(doctor_mod, "cli_doctor", lambda: 7)
    assert cli.main() == 7


# ── provider registry ───────────────────────────────────────────────

def test_registry_filters_by_language_and_keeps_order():
    reg = ProviderRegistry()
    reg.register("any", lambda: None)
    reg.register("fr-only", lambda: None, supported_languages=["fr"])
    reg.register("en-only", lambda: None, supported_languages=["en"])
    assert [p["name"] for p in reg.get_providers("fr")] == ["any", "fr-only"]
    assert [p["name"] for p in reg.get_providers("en")] == ["any", "en-only"]
    assert len(reg.get_providers(None)) == 3
    reg.clear()
    assert reg.get_providers(None) == []


# ── JSONC loading ───────────────────────────────────────────────────

def test_jsonc_strips_comments_and_trailing_commas():
    raw = '{\n // a comment\n "url": "https://x/y",\n "n": 2,\n}'
    cleaned = config_loader.strip_trailing_commas(
        config_loader.strip_json_comments(raw))
    assert json.loads(cleaned) == {"url": "https://x/y", "n": 2}


def test_local_jsonc_missing_returns_default(tmp_path):
    assert config_loader.load_local_jsonc(str(tmp_path / "nope.jsonc"), {"a": 1}) == {"a": 1}


def test_local_jsonc_valid_and_invalid(tmp_path, capsys):
    ok = tmp_path / "ok.jsonc"
    ok.write_text('// c\n{"a": 1,}', encoding="utf-8")
    assert config_loader.load_local_jsonc(str(ok), {}) == {"a": 1}
    bad = tmp_path / "bad.jsonc"
    bad.write_text("{not json", encoding="utf-8")
    assert config_loader.load_local_jsonc(str(bad), {"fallback": True}) == {"fallback": True}


def test_remote_jsonc_falls_back_offline(monkeypatch):
    class _R:
        text = '{"a": 1}'

        def raise_for_status(self):
            raise OSError("offline")

    monkeypatch.setattr(config_loader.requests, "get", lambda *a, **k: _R())
    assert config_loader.load_remote_jsonc("https://x/data.jsonc", {"d": 1}) == {"d": 1}


# ── doctor ───────────────────────────────────────────────────────────

def test_doctor_ffmpeg_uses_single_dash(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="ffmpeg version 9\n", stderr="")

    monkeypatch.setattr(doctor.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    status, ver, path = doctor._check_binary("ffmpeg", "ffmpeg")
    assert status == "OK" and "9" in ver and path.endswith("ffmpeg")
    assert seen["cmd"][1] == "-version"


def test_doctor_missing_binary():
    assert doctor._check_binary("nope", "definitely-not-a-real-binary")[0] == "MISSING"


def test_doctor_fmt_size(tmp_path):
    f = tmp_path / "x"
    f.write_bytes(b"x" * 10)
    assert doctor._fmt_size(f).endswith("B")


# ── install health / languages ──────────────────────────────────────

def test_install_state_reports_code_version():
    state = install_health.install_state()
    assert state["code_version"] == install_health.CODE_VERSION
    assert isinstance(state["shims"], list)


def test_languages_list_is_usable():
    langs = languages.get_all_languages()
    assert langs and all(isinstance(code, str) and label for code, label in langs)


# ── themes / UI primitives / i18n ──────────────────────────────────

def test_preview_theme_does_not_touch_settings(monkeypatch):
    monkeypatch.setattr(tracker, "get_theme", lambda: "noir")
    t = themes.preview_theme("dracula")
    assert t["label"] == "Dracula"
    assert tracker.get_theme() == "noir"


def test_wordmark_and_rule_render_plain_text(monkeypatch):
    monkeypatch.setattr(tracker, "get_theme", lambda: "noir")
    monkeypatch.setattr(tracker, "get_custom_accent", lambda: None)
    assert ui.wordmark().plain == "FreeFlix"
    assert "section" in ui.rule("Section").plain.lower()


def test_i18n_switches_language(monkeypatch):
    from freeflix_cli.i18n import t

    monkeypatch.setattr(tracker, "get_language", lambda: "fr")
    assert t("Yes") == "Oui"
    monkeypatch.setattr(tracker, "get_language", lambda: "en")
    assert t("Yes") == "Yes"


# ── download metadata / filenames ──────────────────────────────────

def test_resume_meta_redacts_cookies_and_is_private(tmp_path):
    from freeflix_cli import player_manager as pm

    d = tmp_path / "stage"
    d.mkdir()
    pm._write_resume_meta(
        str(d), url="https://cdn/x", headers={
            "Cookie": "vz_ok=secret", "Referer": "https://site/",
            "Authorization": "Bearer secret",
        })
    meta = json.loads((d / pm._RESUME_META).read_text(encoding="utf-8"))
    assert meta["headers"] == {"Referer": "https://site/"}
    if os.name != "nt":
        mode = stat.S_IMODE(os.stat(d / pm._RESUME_META).st_mode)
        assert mode == 0o600


@pytest.mark.parametrize("name,expected", [
    ("CON", "_CON"),
    ("nul.mp4", "_nul.mp4"),
    ("COM1", "_COM1"),
    ("LPT9.txt", "_LPT9.txt"),
    ("Episode 1", "Episode 1"),
])
def test_windows_reserved_filenames(name, expected):
    from freeflix_cli.player_manager import _sanitize_filename

    assert _sanitize_filename(name) == expected


def test_filename_strips_trailing_dots_and_spaces():
    from freeflix_cli.player_manager import _sanitize_filename

    assert _sanitize_filename("  Title.  ") == "Title"
