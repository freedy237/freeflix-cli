"""
Cross-platform setup assistant for FreeFlix.

Triggered on first launch (or via `freeflix --setup`). Detects OS + GPU,
downloads & installs the tuned mpv.conf / input.conf / lua hook /
Anime4K Mode A_S shaders to the user's mpv config dir. On Linux, also
installs PRIME render-offload wrappers when a discrete Nvidia/AMD GPU
is detected so standalone mpv calls also use the dGPU.

No package-data bundling : we fetch the configs straight from this
repo's main branch, which keeps the wheel small.
"""

import os
import sys
import time
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict

from .cli_utils import print_info, print_success, print_warning, print_error
from .tracker import tracker


REPO_RAW = "https://raw.githubusercontent.com/freedy237/freeflix-cli/main"
ANIME4K_RAW = "https://raw.githubusercontent.com/bloc97/Anime4K/master/glsl"


# ─── OS detection ─────────────────────────────────────────────────────
def detect_os() -> str:
    """Return 'linux', 'macos', 'windows', or 'unknown'."""
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform in ("win32", "cygwin"):
        return "windows"
    return "unknown"


# ─── GPU detection ────────────────────────────────────────────────────
def detect_gpus() -> Dict[str, bool]:
    """Return flags : nvidia, amd_discrete, intel_integrated, apple_silicon."""
    flags = {
        "nvidia": False,
        "amd_discrete": False,
        "intel_integrated": False,
        "apple_silicon": False,
    }
    os_name = detect_os()

    # Nvidia : universal — `nvidia-smi` returns 0 only if drivers are installed
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0 and "GPU" in r.stdout:
                flags["nvidia"] = True
        except Exception:
            pass

    if os_name == "linux":
        if shutil.which("lspci"):
            try:
                r = subprocess.run(
                    ["lspci", "-nn"], capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0:
                    lines = r.stdout.lower().splitlines()
                    for line in lines:
                        if " amd " in f" {line} " or "ati " in line or "radeon" in line:
                            if "vga" in line or "3d controller" in line or "display" in line:
                                flags["amd_discrete"] = True
                        if "intel" in line and ("graphics" in line or "vga" in line):
                            flags["intel_integrated"] = True
            except Exception:
                pass

    elif os_name == "macos":
        try:
            r = subprocess.run(["uname", "-m"], capture_output=True, text=True, timeout=2)
            if "arm64" in r.stdout:
                flags["apple_silicon"] = True
        except Exception:
            pass

    elif os_name == "windows":
        # Use PowerShell instead of wmic (deprecated on Win11)
        try:
            r = subprocess.run(
                ["powershell", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=8,
            )
            out = (r.stdout or "").lower()
            if "nvidia" in out or "geforce" in out or "quadro" in out:
                flags["nvidia"] = True
            if "amd" in out or "radeon" in out:
                flags["amd_discrete"] = True
            if "intel" in out and ("graphics" in out or "hd " in out or "iris" in out):
                flags["intel_integrated"] = True
        except Exception:
            pass

    return flags


# ─── Paths ────────────────────────────────────────────────────────────
def get_mpv_config_dir() -> Path:
    """
    Return FreeFlix's DEDICATED mpv config dir (not the global one).
    mpv is launched by FreeFlix with --config-dir pointing here, so our
    tuned config (Anime4K, big cache, position hook) applies ONLY to
    FreeFlix playback — the user's normal `mpv file.mkv` stays vanilla.

    Linux/macOS : ~/.config/freeflix/mpv
    Windows     : %APPDATA%/freeflix/mpv
    """
    if detect_os() == "windows":
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return Path(appdata) / "freeflix" / "mpv"
    return Path.home() / ".config" / "freeflix" / "mpv"


def get_local_bin_dir() -> Path:
    """Where to drop PRIME wrappers — Linux only."""
    return Path.home() / ".local" / "bin"


# ─── State checks ─────────────────────────────────────────────────────
def is_setup_complete() -> bool:
    """True if mpv.conf + at least one Anime4K shader are installed."""
    cfg = get_mpv_config_dir()
    if not (cfg / "mpv.conf").exists():
        return False
    shaders = cfg / "shaders"
    if not shaders.exists() or not any(shaders.glob("Anime4K_*.glsl")):
        return False
    return True


# ─── Runtime dependency gate (idempotent / resumable) ─────────────────
# label -> (winget id for Windows, acceptable binary names, essential?)
# Essential tools gate playback ; the rest are quality-of-life (posters,
# faster downloads) and never block.
_TOOLS = [
    ("player",  "mpv.net",         ("mpvnet", "mpv", "vlc"), True),
    ("yt-dlp",  "yt-dlp.yt-dlp",   ("yt-dlp",),              True),
    ("ffmpeg",  "Gyan.FFmpeg",     ("ffmpeg",),              True),
    ("aria2",   "aria2.aria2",     ("aria2c",),              False),
    ("chafa",   "hpjansson.Chafa", ("chafa",),               False),
]


def _have(bins) -> bool:
    return any(shutil.which(b) for b in bins)


def missing_essential_tools() -> list:
    """Essential tools that aren't on PATH (empty list == ready to play)."""
    return [label for (label, _id, bins, ess) in _TOOLS if ess and not _have(bins)]


def missing_tools() -> list:
    """All tools (essential + optional) that aren't installed yet."""
    return [(label, _id, bins) for (label, _id, bins, _e) in _TOOLS if not _have(bins)]


def runtime_ready() -> bool:
    return not missing_essential_tools()


def _winget_install(pkg_id: str) -> None:
    try:
        # capture_output so winget's own logs don't fight the loading screen.
        subprocess.run(
            ["winget", "install", "--silent",
             "--accept-source-agreements", "--accept-package-agreements",
             "--id", pkg_id],
            check=False, capture_output=True, text=True,
        )
    except Exception:
        pass


def ensure_runtime_deps(auto_install: bool = True) -> bool:
    """
    Resumable dependency gate, run on every launch until it succeeds ONCE.

    Behaviour the user asked for : as long as the "all good" flag isn't cached,
    each launch re-checks what's already installed and installs ONLY what's
    still missing (it never restarts a finished install, and it never jumps
    ahead while essential tools are absent). Once everything essential is
    present, ``system_deps_ok`` is cached so future launches short-circuit
    instantly.

    Returns True when the essential tools (a player + yt-dlp + ffmpeg) exist.
    """
    if tracker.data.get("system_deps_ok"):
        return True
    if runtime_ready():
        tracker.data["system_deps_ok"] = True
        tracker._save_data()
        return True

    os_name = detect_os()

    # Windows can self-heal silently via winget (only the missing pieces),
    # behind the big FreeFlix loading screen with a progress bar tracking
    # which tool is installing.
    if auto_install and os_name == "windows" and shutil.which("winget"):
        todo = missing_tools()
        if todo:
            from . import progress as _progress
            with _progress.LoadingScreen(status="Installing dependencies…") as _ls:
                total = len(todo)
                for i, (label, pkg_id, bins) in enumerate(todo):
                    _ls.status(f"Installing {label}…", frac=i / total)
                    if not _have(bins):
                        _winget_install(pkg_id)
                _ls.status("Finishing up…", frac=1.0)
                time.sleep(0.3)

    if runtime_ready():
        tracker.data["system_deps_ok"] = True
        tracker._save_data()
        print_success("All required tools are installed.")
        return True

    # Still missing essentials → guide, and DON'T cache, so the next launch
    # picks up where this one left off.
    print_warning("Some required tools are still missing: "
                  + ", ".join(missing_essential_tools()))
    if os_name == "windows":
        print_info("Run this (re-runnable — installs only what's missing):")
        print_info("  powershell -ExecutionPolicy Bypass -File scripts\\install.ps1")
        print_info("then open a NEW Windows Terminal and run:  freeflix")
    elif os_name == "linux":
        print_info("Run the installer:  ./scripts/install.sh")
    elif os_name == "macos":
        print_info("Run the installer:  ./scripts/install-mac.sh")
    return False


# ─── Downloads ────────────────────────────────────────────────────────
def _download(url: str, dest: Path) -> bool:
    """Download `url` into `dest`. Returns True on success."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=30) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return True
    except Exception as e:
        print_warning(f"Could not download {url} ({type(e).__name__}: {e})")
        return False


def install_config_files() -> bool:
    """Pull mpv.conf, input.conf and the lua hook from the repo."""
    cfg = get_mpv_config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "scripts").mkdir(parents=True, exist_ok=True)

    ok = True
    files = [
        (f"{REPO_RAW}/config/mpv.conf",                  cfg / "mpv.conf"),
        (f"{REPO_RAW}/config/input.conf",                cfg / "input.conf"),
        (f"{REPO_RAW}/config/freeflix_position.lua",     cfg / "scripts" / "freeflix_position.lua"),
    ]
    for url, dest in files:
        if _download(url, dest):
            print_success(f"  ✓ {dest}")
        else:
            ok = False
    return ok


def install_anime4k_shaders() -> bool:
    """Download Mode A_S shaders (lighter) from bloc97's repo."""
    cfg = get_mpv_config_dir()
    sh_dir = cfg / "shaders"
    sh_dir.mkdir(parents=True, exist_ok=True)

    ok = True
    shaders = [
        (f"{ANIME4K_RAW}/Restore/Anime4K_Clamp_Highlights.glsl",  sh_dir / "Anime4K_Clamp_Highlights.glsl"),
        (f"{ANIME4K_RAW}/Restore/Anime4K_Restore_CNN_S.glsl",     sh_dir / "Anime4K_Restore_CNN_S.glsl"),
        (f"{ANIME4K_RAW}/Restore/Anime4K_Restore_CNN_VL.glsl",    sh_dir / "Anime4K_Restore_CNN_VL.glsl"),
        (f"{ANIME4K_RAW}/Upscale/Anime4K_Upscale_CNN_x2_S.glsl",  sh_dir / "Anime4K_Upscale_CNN_x2_S.glsl"),
        (f"{ANIME4K_RAW}/Upscale/Anime4K_Upscale_CNN_x2_VL.glsl", sh_dir / "Anime4K_Upscale_CNN_x2_VL.glsl"),
    ]
    for url, dest in shaders:
        if _download(url, dest):
            print_success(f"  ✓ {dest.name}")
        else:
            ok = False
    return ok


def _linux_pkg_cmd(pkg: str):
    """Return the install command for `pkg` for the detected package manager."""
    candidates = [
        ("dnf", ["sudo", "dnf", "install", "-y", pkg]),
        ("apt-get", ["sudo", "apt-get", "install", "-y", pkg]),
        ("pacman", ["sudo", "pacman", "-S", "--needed", "--noconfirm", pkg]),
        ("zypper", ["sudo", "zypper", "install", "-y", pkg]),
        ("apk", ["sudo", "apk", "add", pkg]),
    ]
    for binname, cmd in candidates:
        if shutil.which(binname):
            return cmd
    return None


def _linux_chafa_cmd():
    """Return the install command for chafa for the detected package manager."""
    return _linux_pkg_cmd("chafa")


# Per-OS install command for the media players FreeFlix can launch.
_PLAYER_PACKAGES = {
    "mpv": {"linux": "mpv", "macos": "mpv", "winget": "mpv.net"},
    "vlc": {"linux": "vlc", "macos": "vlc", "winget": "VideoLAN.VLC"},
}


def install_media_player(name: str) -> bool:
    """
    Install a media player (mpv / vlc) via the OS package manager. Interactive
    (asks first). Returns True if the player ends up available afterwards.

    Used both by the first-run wizard and on-demand at playback time when the
    chosen player turns out to be missing.
    """
    spec = _PLAYER_PACKAGES.get(name)
    if not spec:
        return False

    os_name = detect_os()
    if os_name == "linux":
        cmd = _linux_pkg_cmd(spec["linux"])
    elif os_name == "macos":
        cmd = ["brew", "install", spec["macos"]] if shutil.which("brew") else None
    elif os_name == "windows":
        cmd = (
            ["winget", "install", "--silent", "--accept-source-agreements",
             "--accept-package-agreements", "--id", spec["winget"]]
            if shutil.which("winget") else None
        )
    else:
        cmd = None

    if not cmd:
        print_warning(
            f"No package manager found to install {name}. Install it manually, "
            "then try again."
        )
        return False

    try:
        ans = input(f"Install {name} now? ({' '.join(cmd)}) [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if ans in ("n", "no"):
        return False

    print_info(f"Installing {name}…")
    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        print_warning(f"{name} install failed ({type(e).__name__}: {e})")
        return False

    # Windows winget often needs a fresh shell for PATH ; mpv.net is mpvnet.exe.
    ok = bool(shutil.which(name) or (name == "mpv" and shutil.which("mpvnet")))
    if ok:
        print_success(f"  ✓ {name} installed")
    else:
        print_warning(
            f"  ! {name} installed but not yet on PATH — open a NEW terminal "
            "and relaunch freeflix."
        )
    return ok


def install_chafa() -> bool:
    """
    Install chafa (anime posters in the terminal) using the OS package
    manager. Interactive : asks before touching the system. Returns True
    if chafa ends up available.
    """
    if shutil.which("chafa"):
        print_success("chafa already installed — anime posters enabled")
        return True

    os_name = detect_os()
    if os_name == "linux":
        cmd = _linux_chafa_cmd()
    elif os_name == "macos":
        cmd = ["brew", "install", "chafa"] if shutil.which("brew") else None
    elif os_name == "windows":
        cmd = (
            ["winget", "install", "--silent", "--accept-source-agreements",
             "--accept-package-agreements", "--id", "hpjansson.Chafa"]
            if shutil.which("winget") else None
        )
    else:
        cmd = None

    if not cmd:
        print_warning(
            "Could not find a package manager for chafa. Install it manually "
            "to enable anime posters (https://hpjansson.org/chafa/)."
        )
        return False

    print_info("chafa draws anime cover art inside the terminal (optional).")
    try:
        ans = input(f"Install chafa now? ({' '.join(cmd)}) [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if ans in ("n", "no"):
        return False

    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        print_warning(f"chafa install failed ({type(e).__name__}: {e})")
        return False

    if shutil.which("chafa"):
        print_success("  ✓ chafa installed — anime posters enabled")
        return True
    print_warning("  ! chafa still not found — posters will stay off for now")
    return False


def install_prime_wrappers(gpus: Dict[str, bool]) -> bool:
    """
    Linux only : if a discrete GPU is detected (Nvidia OR AMD), drop
    a ~/.local/bin/mpv wrapper that sets the PRIME render-offload env
    vars before exec-ing the system binary.
    """
    if detect_os() != "linux":
        return True
    if not (gpus.get("nvidia") or gpus.get("amd_discrete")):
        return True

    bindir = get_local_bin_dir()
    bindir.mkdir(parents=True, exist_ok=True)

    if gpus.get("nvidia"):
        offload_block = (
            'export __NV_PRIME_RENDER_OFFLOAD=1\n'
            'export __GLX_VENDOR_LIBRARY_NAME=nvidia\n'
            'export __VK_LAYER_NV_optimus=NVIDIA_only\n'
        )
        gpu_label = "Nvidia"
    else:
        # AMD discrete : `DRI_PRIME=1` routes the GL/Vulkan context to it
        offload_block = 'export DRI_PRIME=1\n'
        gpu_label = "AMD"

    target = bindir / "mpv"
    target.write_text(
        "#!/usr/bin/env bash\n"
        f"# FreeFlix PRIME wrapper — routes mpv to the {gpu_label} dGPU.\n"
        "# Delete this file (rm ~/.local/bin/mpv) to disable.\n"
        "\n"
        + offload_block
        + "\nexec /usr/bin/mpv \"$@\"\n"
    )
    target.chmod(0o755)

    # Warn if ~/.local/bin isn't in PATH
    if str(bindir) not in os.environ.get("PATH", "").split(":"):
        print_warning(
            f"  ! {bindir} is not in your PATH — add this to ~/.bashrc / ~/.zshrc :\n"
            f'      export PATH="$HOME/.local/bin:$PATH"'
        )
    return True


# ─── FlareSolverr : optional Cloudflare auto-solver ───────────────────
def _flaresolverr_running(url: str = "http://127.0.0.1:8191/") -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _container_runtime():
    """
    Return a usable container runtime : 'podman' (rootless, preferred — no
    sudo, no daemon, Fedora default) then 'docker'. None if neither works.
    """
    for cmd in ("podman", "docker"):
        if not shutil.which(cmd):
            continue
        try:
            r = subprocess.run([cmd, "info"], capture_output=True, timeout=12)
            if r.returncode == 0:
                return cmd
        except Exception:
            continue
    return None


FS_IMAGE = "ghcr.io/flaresolverr/flaresolverr:latest"


def _flaresolverr_make_persistent(runtime: str):
    """
    Linux + podman : make the container auto-start on boot via a systemd
    user service + lingering. (Docker uses --restart unless-stopped + its
    daemon, so nothing extra needed there.)
    """
    if detect_os() != "linux" or runtime != "podman":
        return
    try:
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        if user:
            subprocess.run(["loginctl", "enable-linger", user],
                           capture_output=True, timeout=10)
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        gen = subprocess.run(
            ["podman", "generate", "systemd", "--new", "--name", "flaresolverr",
             "--restart-policy=always"],
            capture_output=True, text=True, timeout=25,
        )
        if gen.returncode == 0 and gen.stdout.strip():
            (unit_dir / "flaresolverr.service").write_text(gen.stdout)
            # Hand the container over to systemd.
            subprocess.run(["podman", "stop", "flaresolverr"], capture_output=True)
            subprocess.run(["podman", "rm", "flaresolverr"], capture_output=True)
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
            subprocess.run(["systemctl", "--user", "enable", "--now",
                            "flaresolverr.service"], capture_output=True, timeout=30)
            print_success("  ✓ FlareSolverr set to auto-start on boot")
    except Exception:
        pass


def install_flaresolverr() -> bool:
    """
    Optional, fully automated : set up FlareSolverr (auto-solves Cloudflare
    JS challenges) so FreeFlix keeps working without pasting a token.

    Cross-platform, A-to-Z :
      * Linux  : Podman rootless (preferred) or Docker ; installs Podman via
                 the distro package manager if neither is present ; makes it
                 persistent (systemd user service + lingering).
      * macOS  : Podman/Docker if present, else guidance.
      * Windows: Docker Desktop if present, else guidance.
    """
    if _flaresolverr_running():
        print_success("FlareSolverr already running on :8191")
        return True

    os_name = detect_os()
    print_info("FlareSolverr auto-solves Cloudflare challenges (optional, ~1 GB image).")

    runtime = _container_runtime()

    # No runtime → try to provide one.
    if not runtime:
        if os_name == "linux":
            cmd = _linux_pkg_cmd("podman")
            if cmd:
                print_info("No Docker/Podman found. Podman is the easiest (rootless).")
                try:
                    ans = input(f"Install Podman now? ({' '.join(cmd)}) [Y/n] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    return False
                if ans not in ("n", "no"):
                    subprocess.run(cmd, check=False)
                    runtime = _container_runtime()
        elif os_name == "macos":
            print_warning(
                "Install a container runtime to enable FlareSolverr, e.g.:\n"
                "  brew install podman && podman machine init && podman machine start\n"
                "  (or Docker Desktop), then re-run `freeflix --setup`."
            )
            return False
        elif os_name == "windows":
            print_warning(
                "Install Docker Desktop to enable FlareSolverr:\n"
                "  winget install Docker.DockerDesktop\n"
                "  then re-run `freeflix --setup`."
            )
            return False

    if not runtime:
        print_warning("No container runtime available — FlareSolverr skipped.")
        return False

    try:
        ans = input(f"Set up FlareSolverr via {runtime} now? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if ans in ("n", "no"):
        return False

    # Reuse an existing container, else pull & create it.
    subprocess.run([runtime, "start", "flaresolverr"], capture_output=True)
    if not _flaresolverr_running():
        print_info(f"Pulling & starting FlareSolverr via {runtime} (first run "
                   "downloads ~Chromium)…")
        try:
            subprocess.run(
                [runtime, "run", "-d", "--name", "flaresolverr",
                 "--restart", "unless-stopped", "-p", "8191:8191", FS_IMAGE],
                check=False,
            )
        except Exception as e:
            print_warning(f"Could not start FlareSolverr ({type(e).__name__}: {e})")
            return False

    # Make it survive reboots (Linux + podman).
    _flaresolverr_make_persistent(runtime)

    import time as _time
    for _ in range(10):
        if _flaresolverr_running():
            print_success("FlareSolverr is up on http://127.0.0.1:8191")
            return True
        _time.sleep(2)
    print_info("FlareSolverr started — it may need a moment to be ready.")
    return True


# ─── Windows : install the media players ──────────────────────────────
def install_windows_players() -> bool:
    """
    Windows : install mpv (mpv.net) and VLC via winget so FreeFlix can
    actually launch them. Users who installed FreeFlix with `uv` never ran
    install.ps1, so the players may be missing. The tuned mpv config is
    applied separately by install_config_files() into %APPDATA%/freeflix/mpv.

    mpv.net's binary is mpvnet.exe ; player_manager.get_mpv_path() resolves
    both that and the winget shim, so FreeFlix can call it.
    """
    if detect_os() != "windows":
        return True
    if not shutil.which("winget"):
        print_warning(
            "winget not found. Install 'App Installer' from the Microsoft "
            "Store, or install mpv.net and VLC manually, so FreeFlix can "
            "launch them."
        )
        return False

    wanted = [
        ("mpv.net", "mpv.net (mpv for Windows)", ("mpv", "mpvnet")),
        ("VideoLAN.VLC", "VLC media player", ("vlc",)),
    ]
    for pkg_id, label, bins in wanted:
        if any(shutil.which(b) for b in bins):
            print_success(f"  ✓ {label} already installed")
            continue
        print_info(f"Installing {label} via winget…")
        try:
            subprocess.run(
                ["winget", "install", "--silent",
                 "--accept-source-agreements", "--accept-package-agreements",
                 "--id", pkg_id],
                check=False,
            )
        except Exception as e:
            print_warning(f"  ! {label} install failed ({type(e).__name__}: {e})")

    print_info(
        "If mpv/VLC aren't found immediately, open a NEW terminal so the "
        "PATH refreshes, then run `freeflix` again."
    )
    return True


# ─── Platform-specific guidance ───────────────────────────────────────
def print_platform_guidance_windows(gpus: Dict[str, bool]):
    """
    Windows 10/11 picks the GPU per-app via Settings → Display → Graphics.
    We can't set this programmatically (it's a UWP setting tied to the
    user shell). Best we can do is point the user there.
    """
    # Icons : the #1 Windows gotcha is running in the legacy cmd.exe console,
    # which can't render the TUI glyphs. Always show this.
    print_info("─" * 60)
    print_info("Icons not showing as crisp glyphs on Windows?")
    print_info("─" * 60)
    print_info("  1. Use 'Windows Terminal' (Store / winget), NOT the old")
    print_info("     cmd.exe window — legacy console can't draw the glyphs.")
    print_info("  2. scripts/install.ps1 installs 'CaskaydiaCove Nerd Font'.")
    print_info("     In Windows Terminal: Settings > Defaults > Appearance >")
    print_info("     Font face -> CaskaydiaCove Nerd Font.")
    print_info("  3. Then in FreeFlix: Settings > Icon Style -> nerd.")
    print_info("     (Emoji icons are the default and work out of the box.)")
    print_info("")

    if not (gpus.get("nvidia") or gpus.get("amd_discrete")):
        return
    gpu = "Nvidia" if gpus.get("nvidia") else "AMD"
    print_info("─" * 60)
    print_info(f"Windows GPU offload : {gpu} dGPU detected")
    print_info("─" * 60)
    print_info("Windows handles GPU selection natively — no PRIME wrappers")
    print_info("needed. To force mpv to use the dGPU, do this ONCE :")
    print_info("")
    print_info("  Option A — Windows Graphics Settings (easiest)")
    print_info("    Settings → System → Display → Graphics")
    print_info("    Browse → C:\\Program Files\\mpv\\mpv.exe (or mpv.net)")
    print_info("    Options → High performance → Save")
    print_info("")
    if gpus.get("nvidia"):
        print_info("  Option B — Nvidia Control Panel (per-app profile)")
        print_info("    Nvidia Control Panel → Manage 3D settings")
        print_info("    Program Settings tab → Add → pick mpv.exe")
        print_info("    'Preferred graphics processor' → High-performance Nvidia")
        print_info("")


def print_platform_guidance_macos(gpus: Dict[str, bool]):
    """macOS picks the GPU automatically per-app based on energy needs."""
    print_info("─" * 60)
    if gpus.get("apple_silicon"):
        print_info("macOS Apple Silicon detected")
        print_info("─" * 60)
        print_info("Apple Silicon has a single unified GPU — no offload needed.")
    else:
        print_info("macOS Intel detected")
        print_info("─" * 60)
        print_info("macOS auto-selects between iGPU and dGPU based on app")
        print_info("activity (Energy Saver). No manual action required.")


# ─── Top-level wizard ─────────────────────────────────────────────────
def run_setup(force: bool = False) -> bool:
    """
    Main entry point. Interactive wizard (uses input()) ; suppresses
    itself if setup is already complete and `force` is False.
    """
    if is_setup_complete() and not force:
        return False

    os_name = detect_os()
    gpus = detect_gpus()

    print_info("─" * 60)
    print_info(f"FreeFlix CLI — first-run setup ({os_name})")
    print_info("─" * 60)
    print_info(f"GPUs detected : {[k for k,v in gpus.items() if v] or ['none']}")
    print_info("")
    print_info("This will :")
    print_info("  1. Install tuned mpv.conf + input.conf + position-resume hook")
    print_info("  2. Download Anime4K shaders (Mode A_S + A_VL, ~290 KB)")
    print_info("  3. Offer to install chafa (anime posters in the terminal)")
    print_info("  4. Offer to set up FlareSolverr (auto-solve Cloudflare, optional)")
    if os_name == "linux" and (gpus["nvidia"] or gpus["amd_discrete"]):
        gpu = "Nvidia" if gpus["nvidia"] else "AMD"
        print_info(f"  3. Install a PRIME wrapper so standalone mpv uses the {gpu} dGPU")
    print_info("")

    try:
        ans = input("Proceed? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print_info("Aborted.")
        return False
    if ans in ("n", "no"):
        # Remember the decline so we don't re-prompt every launch
        tracker.data["setup_declined"] = True
        tracker._save_data()
        return False

    print_info("\n[1/3] Installing mpv configuration…")
    install_config_files()
    print_info("\n[2/3] Downloading Anime4K shaders…")
    install_anime4k_shaders()
    print_info("\n[+] Anime posters (chafa)…")
    install_chafa()
    print_info("\n[+] Cloudflare auto-solver (FlareSolverr, optional)…")
    install_flaresolverr()
    if os_name == "linux":
        print_info("\n[3/3] Installing PRIME wrapper…")
        install_prime_wrappers(gpus)
    elif os_name == "windows":
        print_info("\n[3/3] Installing media players (mpv + VLC)…")
        install_windows_players()
        print_platform_guidance_windows(gpus)
    elif os_name == "macos":
        print_platform_guidance_macos(gpus)

    tracker.data["setup_done"] = True
    tracker.data.pop("setup_declined", None)
    tracker._save_data()

    print_success("\n✓ Setup complete. Launching FreeFlix…\n")
    return True


# ─── Post-upgrade migrations ──────────────────────────────────────────
def _ver_tuple(v):
    out = []
    for part in str(v or "0").split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


# Each entry : (version_that_introduced_it, description, action).
# `action` MUST be idempotent (check presence first) — it runs once, on the
# first launch after upgrading PAST that version. Use it to install a newly
# required tool, refresh configs, or clean up a removed feature.
#   e.g. ("1.6.0", "Feature X removed — cleaning up", _cleanup_x)
def _migrations():
    return [
        ("1.5.7", "Anime posters need chafa", install_chafa),
    ]


def run_pending_migrations(current_version: str) -> None:
    """
    Run the migration steps for every version newer than the last one we
    set up, then record the current version. Called on launch so an
    upgrade (uv/pipx/pip) self-finishes on first run.
    """
    if not current_version or current_version == "dev":
        return

    last = tracker.get_last_setup_version()
    if last is None:
        # First launch with the migration system : adopt the current version
        # without replaying history (a fresh install already ran setup, and
        # in-app features still offer any missing tool on demand).
        tracker.set_last_setup_version(current_version)
        return

    if _ver_tuple(last) >= _ver_tuple(current_version):
        return  # same version or a downgrade — nothing to do

    pending = [
        (ver, desc, action)
        for ver, desc, action in _migrations()
        if _ver_tuple(last) < _ver_tuple(ver) <= _ver_tuple(current_version)
    ]
    if pending:
        print_info(f"Finalizing upgrade {last} → {current_version}…")
        for ver, desc, action in pending:
            print_info(f"  • {desc}")
            try:
                action()
            except Exception as e:
                print_warning(f"    (skipped: {type(e).__name__})")

    tracker.set_last_setup_version(current_version)


def should_prompt_setup() -> bool:
    """True if we should ask the user to run setup."""
    if is_setup_complete():
        return False
    if tracker.data.get("setup_declined"):
        return False  # user said no, don't pester
    return True
