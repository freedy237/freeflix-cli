#!/usr/bin/env bash
# FreeFlix CLI — Linux installer
# Supports : Fedora/RHEL (dnf), Debian/Ubuntu (apt), Arch/Manjaro (pacman),
#            openSUSE (zypper), Alpine (apk).
# Installs system dependencies (mpv, yt-dlp, ffmpeg, aria2, libnotify)
# then installs the freeflix package via uv (preferred) or pipx.

set -euo pipefail

BLUE="\033[1;34m"; GREEN="\033[1;32m"; YELLOW="\033[1;33m"; RED="\033[1;31m"; NC="\033[0m"
log()   { echo -e "${BLUE}»${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}!${NC} $*"; }
err()   { echo -e "${RED}✗${NC} $*" >&2; }

# ─── 1. Detect distro ────────────────────────────────────────────────
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        echo "${ID:-unknown}"
    else
        echo "unknown"
    fi
}

DISTRO=$(detect_distro)
log "Detected distro : ${DISTRO}"

# ─── 2. Install system packages ──────────────────────────────────────
SYSTEM_PKGS_FEDORA="mpv yt-dlp ffmpeg aria2 libnotify python3 python3-pip curl"
SYSTEM_PKGS_DEBIAN="mpv yt-dlp ffmpeg aria2 libnotify-bin python3 python3-pip python3-venv curl"
SYSTEM_PKGS_ARCH="mpv yt-dlp ffmpeg aria2 libnotify python python-pip curl"
SYSTEM_PKGS_OPENSUSE="mpv yt-dlp ffmpeg aria2 libnotify-tools python3 python3-pip curl"
SYSTEM_PKGS_ALPINE="mpv yt-dlp ffmpeg aria2 libnotify python3 py3-pip curl"

install_system_pkgs() {
    case "$DISTRO" in
        fedora|rhel|centos|rocky|alma)
            log "Installing via dnf (sudo password may be required)…"
            sudo dnf install -y $SYSTEM_PKGS_FEDORA
            ;;
        debian|ubuntu|linuxmint|pop)
            log "Installing via apt (sudo password may be required)…"
            sudo apt-get update
            sudo apt-get install -y $SYSTEM_PKGS_DEBIAN
            ;;
        arch|manjaro|endeavouros)
            log "Installing via pacman (sudo password may be required)…"
            sudo pacman -S --needed --noconfirm $SYSTEM_PKGS_ARCH
            ;;
        opensuse*|suse|sles)
            log "Installing via zypper (sudo password may be required)…"
            sudo zypper install -y $SYSTEM_PKGS_OPENSUSE
            ;;
        alpine)
            log "Installing via apk (sudo password may be required)…"
            sudo apk add $SYSTEM_PKGS_ALPINE
            ;;
        *)
            err "Unsupported distro : ${DISTRO}"
            err "Install these packages manually : mpv yt-dlp ffmpeg aria2 libnotify python3 pip"
            exit 1
            ;;
    esac
    ok "System packages installed"
}

# ─── 3. Install freeflix-cli (uv preferred, pipx fallback) ───────────
install_freeflix() {
    if command -v uv >/dev/null 2>&1; then
        log "Installing freeflix-cli via uv…"
        uv tool install --force "$PROJECT_ROOT"
    elif command -v pipx >/dev/null 2>&1; then
        log "Installing freeflix-cli via pipx…"
        pipx install --force "$PROJECT_ROOT"
    else
        warn "Neither uv nor pipx found. Installing pipx first…"
        python3 -m pip install --user --upgrade pipx
        python3 -m pipx ensurepath
        export PATH="$HOME/.local/bin:$PATH"
        pipx install --force "$PROJECT_ROOT"
    fi
    ok "freeflix command installed"
}

# ─── 4. Wire the shared mpv config (optional) ───────────────────────
install_mpv_config() {
    log "Installing default mpv config (Anime4K toggle, anti-crash) ?"
    read -rp "  [Y/n] " ans
    [[ "${ans:-Y}" =~ ^[Nn] ]] && return 0

    mkdir -p "$HOME/.config/mpv/scripts" "$HOME/.config/mpv/shaders"

    cp "$PROJECT_ROOT/config/mpv.conf"               "$HOME/.config/mpv/mpv.conf"
    cp "$PROJECT_ROOT/config/input.conf"             "$HOME/.config/mpv/input.conf"
    cp "$PROJECT_ROOT/config/freeflix_position.lua"  "$HOME/.config/mpv/scripts/freeflix_position.lua"

    # Fetch Anime4K shaders (Mode A_VL, ~290 KB total)
    log "Downloading Anime4K shaders…"
    BASE="https://raw.githubusercontent.com/bloc97/Anime4K/master/glsl"
    curl -fsSL -o "$HOME/.config/mpv/shaders/Anime4K_Clamp_Highlights.glsl"  "$BASE/Restore/Anime4K_Clamp_Highlights.glsl"
    curl -fsSL -o "$HOME/.config/mpv/shaders/Anime4K_Restore_CNN_VL.glsl"    "$BASE/Restore/Anime4K_Restore_CNN_VL.glsl"
    curl -fsSL -o "$HOME/.config/mpv/shaders/Anime4K_Upscale_CNN_x2_VL.glsl" "$BASE/Upscale/Anime4K_Upscale_CNN_x2_VL.glsl"

    ok "mpv config installed (CTRL+1 toggles Anime4K)"
}

# ─── Main ────────────────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log "Project root : $PROJECT_ROOT"

install_system_pkgs
install_freeflix
install_mpv_config

# ─── 5. Optional : Nvidia PRIME wrappers for hybrid laptops ─────────
install_nvidia_wrappers() {
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        return 0  # No Nvidia GPU → nothing to do
    fi
    log "Nvidia GPU detected. Install PRIME wrapper so mpv routes"
    log "to the dGPU automatically (faster Anime4K) ?"
    read -rp "  [Y/n] " ans
    [[ "${ans:-Y}" =~ ^[Nn] ]] && return 0

    mkdir -p "$HOME/.local/bin"
    cp "$PROJECT_ROOT/scripts/wrappers/mpv" "$HOME/.local/bin/mpv"
    chmod +x "$HOME/.local/bin/mpv"

    if ! echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
        warn "$HOME/.local/bin is NOT in PATH — add it to ~/.bashrc / ~/.zshrc :"
        warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
    ok "Nvidia PRIME wrappers installed"
}
install_nvidia_wrappers

echo
ok "Installation complete. Run :  ${GREEN}freeflix${NC}"
