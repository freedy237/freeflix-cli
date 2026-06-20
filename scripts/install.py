"""
FreeFlix CLI — bootstrap installer.

Usage:  curl -fsSL https://freeflix.app/install.py | python3

Detects your OS, installs ``uv`` if missing, then installs FreeFlix
via ``uv tool install freeflix-cli``.  No package manager, no sudo,
no pre-requisites beyond Python itself.
"""

from __future__ import annotations

import os
import sys
import stat
import shutil
import tarfile
import zipfile
import platform
import tempfile
import subprocess
import urllib.request
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────


def _os_name() -> str | None:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform in ("win32", "cygwin"):
        return "windows"
    return None


def _arch() -> str | None:
    m = platform.machine().lower()
    table = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "x64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }
    return table.get(m)


def _local_bin() -> Path:
    return Path.home() / ".local" / "bin"


def _on_path(name: str) -> bool:
    return shutil.which(name) is not None


def _say(msg: str):
    print(f"  • {msg}")


def _ok(msg: str):
    print(f"  ✓ {msg}")


def _fail(msg: str):
    print(f"  ✗ {msg}", file=sys.stderr)


# ── uv install ───────────────────────────────────────────────────────────────

_UV_BASE = "https://github.com/astral-sh/uv/releases/latest/download"

_UV_ASSETS: dict[tuple[str, str], str] = {
    ("linux", "x86_64"): f"{_UV_BASE}/uv-x86_64-unknown-linux-gnu.tar.gz",
    ("linux", "aarch64"): f"{_UV_BASE}/uv-aarch64-unknown-linux-gnu.tar.gz",
    ("macos", "x86_64"): f"{_UV_BASE}/uv-x86_64-apple-darwin.tar.gz",
    ("macos", "aarch64"): f"{_UV_BASE}/uv-aarch64-apple-darwin.tar.gz",
    ("windows", "x86_64"): f"{_UV_BASE}/uv-x86_64-pc-windows-msvc.zip",
}


def _ensure_path(bin_dir: Path):
    """Add *bin_dir* to this session's PATH."""
    cur = os.environ.get("PATH", "")
    if str(bin_dir) not in cur:
        os.environ["PATH"] = str(bin_dir) + os.pathsep + cur


def _ensure_permanent_path():
    """
    Persistently add ``~/.local/bin`` to PATH so the user does *not* need
    to restart the terminal after installation.
    """
    bin_dir = _local_bin()
    os_name = _os_name()

    # ── Windows : user-level PATH via setx ──────────────────────────
    if os_name == "windows":
        cur = os.environ.get("PATH", "")
        if str(bin_dir).lower() in cur.lower():
            _ok(f"{bin_dir} is already in PATH")
            return
        try:
            subprocess.run(
                ["setx", "PATH", f"{bin_dir};%PATH%"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            _ok(f"Added {bin_dir} to user PATH (new terminal needed)")
        except Exception as exc:
            _fail(f"Could not update PATH: {exc}")
        return

    # ── Linux / macOS : write shell rc file ─────────────────────────
    candidates: list[Path] = []
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        candidates.append(Path.home() / ".zshrc")
    if "bash" in shell:
        candidates.append(Path.home() / ".bashrc")
    candidates.append(Path.home() / ".profile")

    export_line = f'export PATH="{bin_dir}:$PATH"'

    for rc in candidates:
        if rc.exists():
            content = rc.read_text()
            if str(bin_dir) in content and "export PATH" in content:
                _ok(f"{bin_dir} is already in {rc.name}")
                return

    # No rc has it — append to the first existing rc, or create .profile
    target: Path | None = None
    for rc in candidates:
        if rc.exists():
            target = rc
            break
    if target is None:
        target = Path.home() / ".profile"

    try:
        if target.exists():
            content = target.read_text()
            if not content.endswith("\n"):
                content += "\n"
        else:
            content = ""
        content += f"\n# Added by FreeFlix CLI\n{export_line}\n"
        target.write_text(content)
        _ok(f"Added {bin_dir} to PATH in {target.name}")
        print(f"     Run:  source {target.name}")
    except Exception as exc:
        _fail(f"Could not update {target}: {exc}")


def _install_uv() -> bool:
    """Download the uv binary for the current OS/arch into ~/.local/bin/."""
    key = (_os_name(), _arch())
    url = _UV_ASSETS.get(key)
    if not url:
        _fail(f"No uv build for {key[0]}/{key[1]}")
        return False

    bin_dir = _local_bin()
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = "uv.exe" if key[0] == "windows" else "uv"
    dest = bin_dir / exe

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        arc = tmp / "uv-archive"

        _say("Downloading uv …")
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                with open(arc, "wb") as f:
                    shutil.copyfileobj(r, f)
        except Exception as exc:
            _fail(f"Download failed: {exc}")
            return False

        extracted: Path | None = None

        if url.endswith(".tar.gz"):
            with tarfile.open(arc, "r:gz") as tar:
                for m in tar.getmembers():
                    if m.name.endswith(f"/{exe}") or m.name == exe:
                        if sys.version_info >= (3, 14):
                            tar.extract(m, tmp, filter="data")
                        else:
                            tar.extract(m, tmp, set_attrs=False)
                        extracted = tmp / m.name
                        break
        elif url.endswith(".zip"):
            with zipfile.ZipFile(arc) as zf:
                for name in zf.namelist():
                    if name.endswith(f"/{exe}") or name == exe:
                        zf.extract(name, tmp)
                        extracted = tmp / name
                        break

        if extracted is None or not extracted.is_file():
            _fail("Could not locate the uv binary inside the archive")
            return False

        shutil.copy2(extracted, dest)
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    _ok(f"uv installed → {dest}")
    _ensure_path(bin_dir)
    return True


# ── FreeFlix install ─────────────────────────────────────────────────────────


def _install_tool(name: str) -> bool:
    """Run ``uv tool install <name>``."""
    try:
        result = subprocess.run(
            ["uv", "tool", "install", name],
            capture_output=True,
            text=True,
        )
        out = (result.stdout or "") + (result.stderr or "")
        if "is already installed" in out:
            _ok(f"{name} is already installed")
            return True
        if result.returncode != 0:
            _fail(out.strip() or f"uv exited with code {result.returncode}")
            return False
        _ok(f"{name} installed")
        return True
    except FileNotFoundError:
        _fail("uv not found on PATH")
        return False


# ── main ─────────────────────────────────────────────────────────────────────

HEADER = r"""
  ╭────────────────────────────────╮
  │  FreeFlix CLI  —  Bootstrap    │
  ╰────────────────────────────────╯
"""


def main():
    print(HEADER)

    os_name = _os_name()
    if not os_name:
        _fail("Unsupported operating system")
        sys.exit(1)

    arch = _arch()
    if not arch:
        _fail("Unsupported CPU architecture")
        sys.exit(1)

    if sys.version_info < (3, 9):
        _fail("Python 3.9 or newer is required")
        sys.exit(1)

    # ── uv ──────────────────────────────────────────────────────────
    if _on_path("uv"):
        _ok("uv is already installed")
    else:
        _say("uv not found — installing …")
        if not _install_uv():
            _fail("Could not install uv automatically.")
            print("  Install it manually with one of:")
            print("    curl -LsSf https://astral.sh/uv/install.sh | sh")
            print("    or visit  https://docs.astral.sh/uv/#getting-started")
            sys.exit(1)

    # ── FreeFlix + yt-dlp ──────────────────────────────────────────
    for tool in ("freeflix-cli", "yt-dlp"):
        if not _install_tool(tool):
            sys.exit(1)

    _ok("FreeFlix installed successfully!")
    print()
    _ensure_permanent_path()
    print()
    print("  Run:  freeflix")


if __name__ == "__main__":
    main()
