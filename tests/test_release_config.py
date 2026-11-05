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
