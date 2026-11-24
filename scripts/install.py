"""
FreeFlix CLI — bootstrap installer.

Usage:
  curl -fsSL https://raw.githubusercontent.com/freedy237/freeflix-cli/main/scripts/install.py | python3

Detects your OS, installs ``uv`` if missing, then installs FreeFlix
via ``uv tool install freeflix-cli``.  No package manager, no sudo,
no pre-requisites beyond Python itself.
"""

from __future__ import annotations

import os
import re
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
    m = sys.platform
    if m.startswith("linux"):
        return "linux"
    if m == "darwin":
        return "macos"
    if m in ("win32", "cygwin"):
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

    # ── Windows : user-level PATH via the registry ──────────────────
    if os_name == "windows":
        cur = os.environ.get("PATH", "")
        if str(bin_dir).lower() in cur.lower():
            _ok(f"{bin_dir} is already in PATH")
            return
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Environment", 0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE,
            )
            try:
                user_path, _kind = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                user_path = ""
            parts = [p for p in str(user_path).split(";") if p]
            if not any(str(bin_dir).lower() == p.lower() for p in parts):
                parts.insert(0, str(bin_dir))
                # REG_EXPAND_SZ keeps %USERPROFILE%-style entries working;
                # setx would truncate at 1024 and write a literal "%PATH%".
                winreg.SetValueEx(
                    key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(parts)
                )
            winreg.CloseKey(key)
            _ok(f"Added {bin_dir} to user PATH (new terminal needed)")
        except Exception as exc:
            _fail(f"Could not update PATH: {exc}")
            _say(f'Add "{bin_dir}" to PATH manually.')
        return

    # ── Linux / macOS : write the shell rc that is actually READ ──────
    # Interactive bash reads ~/.bashrc (not ~/.profile), zsh reads ~/.zshrc.
    # Writing the wrong file is why "freeflix: command not found" survived a
    # successful install in a new terminal.
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        target = Path.home() / ".zshrc"
    elif "bash" in shell:
        target = Path.home() / ".bashrc"
    else:
        target = Path.home() / ".profile"

    export_line = f'export PATH="{bin_dir}:$PATH"'
    try:
        content = target.read_text(encoding="utf-8", errors="replace") \
            if target.exists() else ""
    except Exception:
        content = ""

    for line in content.splitlines():
        if str(bin_dir) in line and "export PATH" in line:
            _ok(f"{bin_dir} is already in {target.name}")
            return

    try:
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"\n# Added by FreeFlix CLI\n{export_line}\n"
        target.write_text(content, encoding="utf-8")
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


def _uv_tools() -> dict:
    """``uv tool list`` as {name: version} (empty dict when uv fails)."""
    try:
        result = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
        tools = {}
        for line in (result.stdout or "").splitlines():
            m = re.match(r"^([A-Za-z0-9_.-]+) v?([0-9][^\s]*)$", line.strip())
            if m:
                tools[m.group(1)] = m.group(2)
        return tools
    except Exception:
        return {}


def _run_uv(cmd: list) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800,
        )
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except FileNotFoundError:
        return 127, "uv not found on PATH"


def _install_tool(name: str) -> bool:
    """Install *name* once, then upgrade in place instead of reinstalling.

    The old code always passed ``--force``, so every run of the installer
    re-downloaded the wheel/*tool* even when the installed version was
    already current (the reported "ça télécharge encore" loop).
    """
    installed = _uv_tools().get(name)
    if installed:
        # `uv tool upgrade` only fetches a newer release; when up to date it
        # is a fast no-op. An offline/failed upgrade is not an install error.
        rc, _out = _run_uv(["uv", "tool", "upgrade", name])
        if rc == 0:
            _ok(f"{name} already installed ({installed}) — up to date")
        else:
            _ok(f"{name} already installed ({installed})")
        return True

    cmd = ["uv", "tool", "install", name]
    if name == "freeflix-cli":
        # Pin a stable, well-tested CPython (3.12 — the code supports 3.9+)
        # so a fresh install never lands on a bleeding-edge interpreter.
        cmd += ["--python", "3.12"]
    rc, out = _run_uv(cmd)
    if "is already installed" in out:
        _ok(f"{name} is already installed")
        return True
    if rc != 0:
        _fail(out.strip() or f"uv exited with code {rc}")
        return False
    _ok(f"{name} installed")
    return True


# ── main ─────────────────────────────────────────────────────────────────────

HEADER = r"""
  ╭────────────────────────────────╮
  │  FreeFlix CLI  —  Bootstrap    │
  ╰────────────────────────────────╯
"""

# Keep in sync with pyproject.toml `[project] version`.
VERSION = "2.6.1"


def _usage():
    print(__doc__.strip())
    print()
    print("Options:")
    print("  -h, --help   Show this help and exit")
    print("  --version    Show version and exit")
    sys.exit(0)


def main():
    args = sys.argv[1:]
    for a in args:
        if a in ("-h", "--help"):
            _usage()
        if a in ("--version",):
            print(f"FreeFlix CLI installer v{VERSION}")
            sys.exit(0)

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
    # uv tool installs its shims in ~/.local/bin; make them visible in THIS
    # session too (uv's own installer only edits the shell rc).
    _ensure_path(_local_bin())
    for tool in ("freeflix-cli", "yt-dlp"):
        if not _install_tool(tool):
            sys.exit(1)

    _ok("FreeFlix installed successfully!")
    print()
    _ensure_permanent_path()
    if not _on_path("freeflix"):
        _fail("The freeflix launcher is not on PATH yet.")
        _say(f'Add "{_local_bin()}" to PATH, then open a new terminal.')
    print()
    print("  Run:  freeflix")


if __name__ == "__main__":
    main()
