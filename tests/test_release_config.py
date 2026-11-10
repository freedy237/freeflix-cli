"""Guards for the release chain.

These are cheap text assertions, but they catch the failures that are only
visible at tag time (and are irreversible once PyPI accepted a version):
missing test gate, missing version check, dead binaries workflow, unsigned
artifacts.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_release_requires_tests_and_version_match():
    yml = _read(".github/workflows/release.yml")
    assert "needs: test" in yml
    assert "Version matches the tag" in yml
    assert "GITHUB_REF_NAME" in yml and "pyproject" in yml
    assert "twine check" in yml
    assert "SHA256SUMS" in yml


def test_release_dispatches_binaries_explicitly():
    yml = _read(".github/workflows/release.yml")
    # `release: published` created with GITHUB_TOKEN does not start a workflow.
    assert "gh workflow run binaries.yml" in yml
    assert "actions: write" in yml


def test_binaries_workflow_is_reachable_and_bundles_data():
    yml = _read(".github/workflows/binaries.yml")
    assert "workflow_dispatch:" in yml
    assert "tag:" in yml
    assert "data/source_portal.jsonc" in yml
    assert "data/selectors.jsonc" in yml
    assert "--doctor" in yml  # smoke test imports the real app


def test_ci_has_timeout_coverage_and_installer_checks():
    yml = _read(".github/workflows/ci.yml")
    assert "--timeout=120" in yml
    assert "--cov-fail-under=40" in yml
    assert "PowerShell syntax" in yml
    assert "ruff==0.17.3" in yml
    # macOS is a separate, non-blocking workflow (runners are often unavailable).
    macos = _read(".github/workflows/macos.yml")
    assert "macos-latest" in macos and "workflow_dispatch:" in macos


def test_installer_scripts_are_tolerant_and_verified():
    sh = _read("scripts/install.sh")
    assert "for p in" in sh              # one package at a time
    assert "failed+=(" in sh
    ps = _read("scripts/install.ps1")
    assert "Tls12" in ps
    assert "uvArch" in ps
    py = _read("scripts/install.py")
    assert "winreg" in py and "REG_EXPAND_SZ" in py
    assert '"setx"' not in py


def test_changelog_documents_current_version():
    version = re.search(
        r'^version = "([^"]+)"', _read("pyproject.toml"), re.M
    ).group(1)
    changelog = _read("CHANGELOG.md")
    assert re.search(rf"^## {re.escape(version)}\b", changelog, re.M), (
        f"CHANGELOG.md has no '## {version}' section"
    )


def test_pyinstaller_data_files_exist():
    for rel in ("data/source_portal.jsonc", "data/selectors.jsonc"):
        assert (ROOT / rel).is_file(), rel


def test_setup_checksum_pins_match_bundled_configs():
    """A config edit must update setup_assistant._FILE_PINS in the same release.

    Otherwise first-run setup downloads the new file and refuses it as
    "tampered" (the 2.4.2 -> 2.4.3 mpv.conf drift broke fresh installs).
    """
    import hashlib

    from freeflix_cli import setup_assistant as sa

    for name in ("mpv.conf", "input.conf", "freeflix_position.lua"):
        raw = (ROOT / "config" / name).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        crlf = hashlib.sha256(raw.replace(b"\n", b"\r\n")).hexdigest()
        # The pin may be the LF digest (repo content) or the CRLF one (set from
        # a Windows checkout): both validate the same file.
        assert sa._FILE_PINS[name]["sha256"] in (digest, crlf), (
            f"{name} changed: update _FILE_PINS[{name!r}]['sha256'] "
            f"to {digest} (LF) or {crlf} (CRLF)"
        )


def test_every_pinned_file_verifies_with_lf_and_crlf(tmp_path):
    """Pins are set by Windows users too, so both line endings must pass.

    The file served over HTTPS is the raw LF blob unless someone added a
    `.gitattributes` eol rule; a Windows checkout (`core.autocrlf=true`)
    yields CRLF. An LF-only pin is unusable on half the platforms, and a
    CRLF-only pin is wrong for `curl`.
    """
    import hashlib

    from freeflix_cli import setup_assistant as sa

    pinned = [n for n, i in sa._FILE_PINS.items() if i.get("sha256")]
    assert len(pinned) >= 3
    for name in pinned:
        info = {**sa._FILE_PINS[name], "min_bytes": 1}
        lf = b"# " + name.encode() + b"\na=b\n"
        crlf = lf.replace(b"\n", b"\r\n")
        assert hashlib.sha256(lf).hexdigest() != hashlib.sha256(crlf).hexdigest()
        probe = tmp_path / name
        for payload in (lf, crlf):
            probe.write_bytes(payload)
            # The pin may have been computed on either line ending: both
            # hashes must be accepted for the same file.
            expected = hashlib.sha256(payload).hexdigest()
            assert sa._verify_archive(probe, {**info, "sha256": expected}, name) is True
        # And a pin for the *other* line ending must still pass.
        probe.write_bytes(crlf)
        assert sa._verify_archive(
            probe, {**info, "sha256": hashlib.sha256(lf).hexdigest()},
            name) is True


def test_setup_never_overwrites_an_existing_config(monkeypatch, tmp_path):
    """A user-tuned mpv.conf must survive a setup retry (Linux included)."""
    from freeflix_cli import setup_assistant as sa

    monkeypatch.setattr(sa, "get_mpv_config_dir", lambda: tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "mpv.conf").write_text("hwdec=vaapi-copy\n", encoding="utf-8")

    downloaded = []

    def fake_dl(url, dest, label=None):
        downloaded.append(dest.name)
        dest.write_text("stock\n", encoding="utf-8")
        return True

    monkeypatch.setattr(sa, "_download_verified", fake_dl)
    assert sa.install_config_files() is True
    assert (tmp_path / "mpv.conf").read_text(encoding="utf-8") == "hwdec=vaapi-copy\n"
    assert "mpv.conf" not in downloaded
    assert "input.conf" in downloaded  # missing files are still pulled
