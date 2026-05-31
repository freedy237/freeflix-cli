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


# ─── Platform-specific guidance ───────────────────────────────────────
def print_platform_guidance_windows(gpus: Dict[str, bool]):
    """
    Windows 10/11 picks the GPU per-app via Settings → Display → Graphics.
    We can't set this programmatically (it's a UWP setting tied to the
    user shell). Best we can do is point the user there.
    """
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
    if os_name == "linux":
        print_info("\n[3/3] Installing PRIME wrapper…")
        install_prime_wrappers(gpus)
    elif os_name == "windows":
        print_platform_guidance_windows(gpus)
    elif os_name == "macos":
        print_platform_guidance_macos(gpus)

    tracker.data["setup_done"] = True
    tracker.data.pop("setup_declined", None)
    tracker._save_data()

    print_success("\n✓ Setup complete. Launching FreeFlix…\n")
    return True


def should_prompt_setup() -> bool:
    """True if we should ask the user to run setup."""
    if is_setup_complete():
        return False
    if tracker.data.get("setup_declined"):
        return False  # user said no, don't pester
    return True
