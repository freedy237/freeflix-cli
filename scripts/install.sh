#!/usr/bin/env bash
# FreeFlix CLI — Linux installer
# Supports : Fedora/RHEL (dnf), Debian/Ubuntu (apt), Arch/Manjaro (pacman),
#            openSUSE (zypper), Alpine (apk).
# Installs system dependencies (mpv, yt-dlp, ffmpeg, aria2, libnotify)
# then installs the freeflix package via uv.

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
# chafa renders anime posters inline in the terminal ; vlc is the alt player.
SYSTEM_PKGS_FEDORA="mpv vlc yt-dlp ffmpeg aria2 libnotify chafa python3 python3-pip curl"
SYSTEM_PKGS_DEBIAN="mpv vlc yt-dlp ffmpeg aria2 libnotify-bin chafa python3 python3-pip python3-venv curl"
SYSTEM_PKGS_ARCH="mpv vlc yt-dlp ffmpeg aria2 libnotify chafa python python-pip curl"
SYSTEM_PKGS_OPENSUSE="mpv vlc yt-dlp ffmpeg aria2 libnotify-tools chafa python3 python3-pip curl"
SYSTEM_PKGS_ALPINE="mpv vlc yt-dlp ffmpeg aria2 libnotify chafa python3 py3-pip curl"

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

# ─── 3. Install freeflix-cli ─────────────────────────────────────────
install_uv_if_missing() {
    if command -v uv >/dev/null 2>&1; then
        return 0
    fi
    log "uv not found — installing …"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        err "Could not install uv automatically."
        err "Visit https://docs.astral.sh/uv/#getting-started"
        exit 1
    fi
    ok "uv installed"
}

install_freeflix() {
    install_uv_if_missing
    log "Installing freeflix-cli via uv…"
    uv tool install --force "$PROJECT_ROOT"
    ok "freeflix command installed"
}

ensure_permanent_path() {
    local bin_dir="$HOME/.local/bin"
    # Already on PATH for this session → check if it's in the shell config
    local rc
    case "${SHELL:-}" in
        *zsh*) rc="$HOME/.zshrc" ;;
        *bash*) rc="$HOME/.bashrc" ;;
        *) rc="$HOME/.profile" ;;
    esac
    if ! grep -qs "$bin_dir" "$rc" 2>/dev/null; then
        {
            echo ""
            echo "# Added by FreeFlix CLI"
            echo "export PATH=\"$bin_dir:\$PATH\""
        } >> "$rc"
        ok "$bin_dir added to $rc (source it or open a new terminal)"
    else
        ok "$bin_dir already in $rc"
    fi
}

# ─── 4. Wire the shared mpv config (optional) ───────────────────────
install_mpv_config() {
    log "Installing default mpv config (Anime4K toggle, anti-crash) ?"
    read -rp "  [Y/n] " ans
    [[ "${ans:-Y}" =~ ^[Nn] ]] && return 0

    mkdir -p "$HOME/.config/freeflix/mpv/scripts" "$HOME/.config/freeflix/mpv/shaders"

    cp "$PROJECT_ROOT/config/mpv.conf"               "$HOME/.config/freeflix/mpv/mpv.conf"
    cp "$PROJECT_ROOT/config/input.conf"             "$HOME/.config/freeflix/mpv/input.conf"
    cp "$PROJECT_ROOT/config/freeflix_position.lua"  "$HOME/.config/freeflix/mpv/scripts/freeflix_position.lua"

    # Fetch Anime4K shaders (Mode A_VL, ~290 KB total)
    log "Downloading Anime4K shaders…"
    BASE="https://raw.githubusercontent.com/bloc97/Anime4K/master/glsl"
    curl -fsSL -o "$HOME/.config/freeflix/mpv/shaders/Anime4K_Clamp_Highlights.glsl"  "$BASE/Restore/Anime4K_Clamp_Highlights.glsl"
    curl -fsSL -o "$HOME/.config/freeflix/mpv/shaders/Anime4K_Restore_CNN_VL.glsl"    "$BASE/Restore/Anime4K_Restore_CNN_VL.glsl"
    curl -fsSL -o "$HOME/.config/freeflix/mpv/shaders/Anime4K_Upscale_CNN_x2_VL.glsl" "$BASE/Upscale/Anime4K_Upscale_CNN_x2_VL.glsl"

    ok "mpv config installed (CTRL+1 toggles Anime4K)"
}

# ─── Nerd Font (crisp TUI icons) — idempotent, best-effort ──────────
install_nerd_font() {
    if fc-list 2>/dev/null | grep -qiE "CaskaydiaCove|Nerd Font"; then
        ok "Nerd Font already installed"
        return 0
    fi
    log "Install a Nerd Font for crisp TUI icons ?"
    read -rp "  [Y/n] " ans
    [[ "${ans:-Y}" =~ ^[Nn] ]] && return 0
    if ! command -v unzip >/dev/null 2>&1; then
        warn "unzip not found — skipping Nerd Font (emoji icons still work)."
        return 0
    fi
    local dest tmp url
    dest="$HOME/.local/share/fonts"
    tmp="$(mktemp -d)"
    url="https://github.com/ryanoasis/nerd-fonts/releases/latest/download/CascadiaCode.zip"
    log "Downloading CaskaydiaCove Nerd Font…"
    if curl -fsSL -o "$tmp/CascadiaCode.zip" "$url" && unzip -oq "$tmp/CascadiaCode.zip" -d "$tmp/nf"; then
        mkdir -p "$dest"
        cp "$tmp"/nf/*.ttf "$dest/" 2>/dev/null || true
        fc-cache -f "$dest" >/dev/null 2>&1 || true
        ok "Nerd Font installed (select 'CaskaydiaCove Nerd Font' in your terminal)"
    else
        warn "Could not download the Nerd Font — emoji icons still work."
    fi
    rm -rf "$tmp"
}

# ─── Main ────────────────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log "Project root : $PROJECT_ROOT"

install_system_pkgs
install_freeflix
ensure_permanent_path
install_mpv_config
install_nerd_font

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

# ─── 6. Optional : FlareSolverr (auto-solve Cloudflare) ──────────────
# Podman (rootless, no sudo) is preferred ; Docker is the fallback. On
# Podman we also register a systemd --user service so it survives reboots.
FS_IMAGE="ghcr.io/flaresolverr/flaresolverr:latest"

flaresolverr_persistent_podman() {
    loginctl enable-linger "$USER" >/dev/null 2>&1 || true
    mkdir -p "$HOME/.config/systemd/user"
    if podman generate systemd --new --name flaresolverr --restart-policy=always \
         > "$HOME/.config/systemd/user/flaresolverr.service" 2>/dev/null; then
        podman stop flaresolverr >/dev/null 2>&1 || true
        podman rm flaresolverr   >/dev/null 2>&1 || true
        systemctl --user daemon-reload
        systemctl --user enable --now flaresolverr.service >/dev/null 2>&1 \
            && ok "FlareSolverr will auto-start on boot (systemd --user)"
    fi
}

install_flaresolverr() {
    if curl -fsS --max-time 2 http://127.0.0.1:8191/ >/dev/null 2>&1; then
        ok "FlareSolverr already running on :8191"
        return 0
    fi
    log "Set up FlareSolverr to auto-solve Cloudflare (~1 GB image) ?"
    read -rp "  [y/N] " ans
    [[ ! "${ans:-N}" =~ ^[Yy] ]] && return 0

    RT=""
    if command -v podman >/dev/null 2>&1; then RT="podman"
    elif command -v docker >/dev/null 2>&1; then RT="docker"
    else
        log "No Podman/Docker found. Installing Podman (rootless, recommended)…"
        case "$DISTRO" in
            fedora|rhel|centos|rocky|alma) sudo dnf install -y podman ;;
            debian|ubuntu|linuxmint|pop)   sudo apt-get install -y podman ;;
            arch|manjaro|endeavouros)      sudo pacman -S --needed --noconfirm podman ;;
            opensuse*|suse|sles)           sudo zypper install -y podman ;;
            alpine)                        sudo apk add podman ;;
        esac
        command -v podman >/dev/null 2>&1 && RT="podman"
    fi
    [[ -z "$RT" ]] && { warn "No container runtime — FlareSolverr skipped."; return 0; }

    log "Starting FlareSolverr via $RT (first run downloads the image)…"
    "$RT" start flaresolverr >/dev/null 2>&1 || \
        "$RT" run -d --name flaresolverr --restart unless-stopped \
            -p 8191:8191 "$FS_IMAGE" || \
        { warn "Could not start FlareSolverr — start it manually later."; return 0; }

    [[ "$RT" == "podman" ]] && flaresolverr_persistent_podman
    ok "FlareSolverr set up (give it a moment to be ready)."
}
install_flaresolverr

echo
ok "Installation complete. Run :  ${GREEN}freeflix${NC}"
log "Icons: if you installed the Nerd Font, set it as your terminal font, then"
log "in FreeFlix go to Settings > Icon Style > nerd (emoji is the default)."
