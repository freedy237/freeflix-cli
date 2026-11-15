#!/usr/bin/env bash
# FreeFlix CLI — Linux installer
# Supports : Fedora/RHEL (dnf), Debian/Ubuntu (apt), Arch/Manjaro (pacman),
#            openSUSE (zypper), Alpine (apk).
# Installs system dependencies (mpv, yt-dlp, ffmpeg, aria2, libnotify)
# then installs the freeflix package via uv.
#
# Re-runnable by design : every step checks what is already installed and
# only touches what is missing. Running it twice must not reinstall packages,
# re-download the shaders, or overwrite a tuned mpv.conf.
#
# Non-interactive use (curl | bash, CI, provisioning) is supported: prompts
# are skipped instead of aborting on EOF.

set -euo pipefail

BLUE="\033[1;34m"; GREEN="\033[1;32m"; YELLOW="\033[1;33m"; RED="\033[1;31m"; NC="\033[0m"
log()   { echo -e "${BLUE}»${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}!${NC} $*"; }
err()   { echo -e "${RED}✗${NC} $*" >&2; }

# Interactive prompt helper : returns 0 (yes) for the default on a TTY,
# and takes the default when stdin is not a terminal (piped installer).
ask() {
    local prompt="$1" default="$2" ans
    if [[ ! -t 0 ]]; then
        [[ "$default" == "y" ]]
        return
    fi
    read -rp "$prompt" ans
    ans="${ans:-$default}"
    [[ "$ans" =~ ^[Yy] ]]
}

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ─── 1. Detect distro ────────────────────────────────────────────────
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        echo "${ID:-unknown}"
    else
        echo "unknown"
    fi
}

DISTRO=$(detect_distro)
log "Detected distro : ${DISTRO}"
log "Project root : $PROJECT_ROOT"

# root / minimal containers have no sudo: prefixing commands with it then
# failed with a confusing "sudo: command not found".
SUDO=""
if [[ ${EUID:-0} -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
fi

# ─── 2. Install system packages (only the missing ones) ──────────────
# chafa renders anime posters inline in the terminal ; vlc is the alt player.
# `libnotify` is the Fedora/openSUSE name, `libnotify-bin` the Debian one.
SYSTEM_PKGS_FEDORA="mpv vlc yt-dlp ffmpeg aria2 libnotify chafa python3 python3-pip curl"
SYSTEM_PKGS_DEBIAN="mpv vlc yt-dlp ffmpeg aria2 libnotify-bin chafa python3 python3-pip python3-venv curl"
SYSTEM_PKGS_ARCH="mpv vlc yt-dlp ffmpeg aria2 libnotify chafa python python-pip curl"
SYSTEM_PKGS_OPENSUSE="mpv vlc yt-dlp ffmpeg aria2 libnotify-tools chafa python3 python3-pip curl"
SYSTEM_PKGS_ALPINE="mpv vlc yt-dlp ffmpeg aria2 libnotify chafa python3 py3-pip curl"

# A player installed via Flatpak is already usable by FreeFlix; trying to
# `dnf install vlc` on top of it fails (no RPM Fusion) and printed errors on
# an otherwise perfectly fine machine.
flatpak_installed() {
    local app_id="$1"
    if command -v flatpak >/dev/null 2>&1; then
        flatpak info "$app_id" >/dev/null 2>&1 && return 0
    fi
    [[ -d "/var/lib/flatpak/app/$app_id" ]] && return 0
    [[ -d "$HOME/.local/share/flatpak/app/$app_id" ]] && return 0
    return 1
}

# `pkg_installed` asks the distro database — much cheaper and quieter than
# calling `dnf/apt install` again for a package that is already there (the
# old loop printed a wall of "already installed / nothing to do" every run).
pkg_installed() {
    local p="$1"
    case "$p" in
        mpv) flatpak_installed io.mpv.Mpv && return 0 ;;
        vlc) flatpak_installed org.videolan.VLC && return 0 ;;
    esac
    case "$DISTRO" in
        fedora|rhel|centos|rocky|alma)
            rpm -q "$p" >/dev/null 2>&1 || rpm -q --whatprovides "$p" >/dev/null 2>&1 ;;
        debian|ubuntu|linuxmint|pop)
            dpkg -s "$p" >/dev/null 2>&1 ;;
        arch|manjaro|endeavouros)
            pacman -Q "$p" >/dev/null 2>&1 ;;
        opensuse*|suse|sles)
            rpm -q "$p" >/dev/null 2>&1 ;;
        alpine)
            apk info -e "$p" >/dev/null 2>&1 ;;
        *)
            return 1 ;;
    esac
}

install_system_pkgs() {
    local pkgs=()
    case "$DISTRO" in
        fedora|rhel|centos|rocky|alma) read -r -a pkgs <<< "$SYSTEM_PKGS_FEDORA" ;;
        debian|ubuntu|linuxmint|pop)   read -r -a pkgs <<< "$SYSTEM_PKGS_DEBIAN" ;;
        arch|manjaro|endeavouros)      read -r -a pkgs <<< "$SYSTEM_PKGS_ARCH" ;;
        opensuse*|suse|sles)           read -r -a pkgs <<< "$SYSTEM_PKGS_OPENSUSE" ;;
        alpine)                        read -r -a pkgs <<< "$SYSTEM_PKGS_ALPINE" ;;
        *)
            warn "Unsupported distro : ${DISTRO} — skipping system packages."
            warn "Install these manually : mpv yt-dlp ffmpeg aria2 libnotify python3 pip"
            return 0
            ;;
    esac

    # One package at a time: vlc (or any optional package) being unavailable
    # in the enabled repos must not abort the whole install (Fedora without
    # RPM Fusion, Alpine has no vlc, …).
    local failed=()
    local skipped=0
    for p in "${pkgs[@]}"; do
        if pkg_installed "$p"; then
            skipped=$((skipped + 1))
            continue
        fi
        log "Installing ${p} …"
        case "$DISTRO" in
            fedora|rhel|centos|rocky|alma) $SUDO dnf install -y "$p" || failed+=("$p") ;;
            debian|ubuntu|linuxmint|pop)   $SUDO apt-get install -y "$p" || failed+=("$p") ;;
            arch|manjaro|endeavouros)      $SUDO pacman -S --needed --noconfirm "$p" || failed+=("$p") ;;
            opensuse*|suse|sles)           $SUDO zypper install -y "$p" || failed+=("$p") ;;
            alpine)                        $SUDO apk add "$p" || failed+=("$p") ;;
        esac
    done
    if ((${#failed[@]})); then
        warn "Optional packages not installed: ${failed[*]}"
        warn "FreeFlix can still run; install them later if a feature needs them."
    elif ((skipped > 0)); then
        ok "System packages ready (${skipped} already installed)"
    else
        ok "System packages installed"
    fi
}

# ─── 3. Install freeflix-cli (skip when already at this version) ─────
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

project_version() {
    sed -n 's/^version = "\(.*\)"/\1/p' "$PROJECT_ROOT/pyproject.toml" | head -n 1
}

install_freeflix() {
    install_uv_if_missing
    local want have
    want="$(project_version)"
    have="$(uv tool list 2>/dev/null | awk '/^freeflix-cli /{print $2; exit}' | sed 's/^v//')"
    # Reinstalling the very same version only re-downloads the wheel for
    # nothing: skip it unless the user explicitly asks for a rebuild.
    if [[ -n "$have" && -n "$want" && "$have" == "$want" \
          && "${FREEFLIX_FORCE_REINSTALL:-0}" != "1" ]]; then
        ok "freeflix-cli ${have} already installed (no reinstall)"
        return 0
    fi
    log "Installing freeflix-cli${want:+ ${want}} via uv…"
    uv tool install --force "$PROJECT_ROOT"
    ok "freeflix command installed"
}

ensure_permanent_path() {
    local bin_dir="$HOME/.local/bin"
    mkdir -p "$bin_dir"
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

# ─── 4. Wire the shared mpv config (idempotent, never overwrites) ────
# Copy a file only when the destination is missing/empty: a re-run used to
# resurrect the stock mpv.conf over the user's tuning.
install_file_once() {
    local src="$1" dest="$2"
    if [[ -s "$dest" ]]; then
        return 0
    fi
    cp "$src" "$dest"
}

# Download a shader only when it isn't there yet (atomic .part + size check).
download_shader_once() {
    local dest="$1" url="$2"
    if [[ -s "$dest" ]]; then
        return 0
    fi
    if curl -fsSL -o "$dest.part" "$url" && [[ -s "$dest.part" ]]; then
        mv "$dest.part" "$dest"
    else
        rm -f "$dest.part"
        warn "Could not download $(basename "$dest") — anime upscaling may be limited."
    fi
}

install_mpv_config() {
    local cfg="$HOME/.config/freeflix/mpv"
    if [[ -s "$cfg/mpv.conf" && -s "$cfg/input.conf" \
          && -s "$cfg/scripts/freeflix_position.lua" ]]; then
        ok "mpv config already installed (kept)"
    else
        if ask "Installing default mpv config (Anime4K toggle, anti-crash) ? [Y/n] " y; then
            mkdir -p "$cfg/scripts" "$cfg/shaders"
            install_file_once "$PROJECT_ROOT/config/mpv.conf" "$cfg/mpv.conf"
            install_file_once "$PROJECT_ROOT/config/input.conf" "$cfg/input.conf"
            install_file_once "$PROJECT_ROOT/config/freeflix_position.lua" \
                "$cfg/scripts/freeflix_position.lua"
            ok "mpv config installed (CTRL+1 toggles Anime4K)"
        fi
    fi

    # The wizard already installed these in most cases — only fetch the
    # missing ones instead of re-downloading all five on every run.
    if [[ -d "$cfg/shaders" ]]; then
        local base="https://raw.githubusercontent.com/bloc97/Anime4K/master/glsl"
        download_shader_once "$cfg/shaders/Anime4K_Clamp_Highlights.glsl" \
            "$base/Restore/Anime4K_Clamp_Highlights.glsl"
        download_shader_once "$cfg/shaders/Anime4K_Restore_CNN_S.glsl" \
            "$base/Restore/Anime4K_Restore_CNN_S.glsl"
        download_shader_once "$cfg/shaders/Anime4K_Upscale_CNN_x2_S.glsl" \
            "$base/Upscale/Anime4K_Upscale_CNN_x2_S.glsl"
        download_shader_once "$cfg/shaders/Anime4K_Restore_CNN_VL.glsl" \
            "$base/Restore/Anime4K_Restore_CNN_VL.glsl"
        download_shader_once "$cfg/shaders/Anime4K_Upscale_CNN_x2_VL.glsl" \
            "$base/Upscale/Anime4K_Upscale_CNN_x2_VL.glsl"
    fi
}

# ─── Nerd Font (crisp TUI icons) — idempotent, best-effort ──────────
nerd_font_installed() {
    local fontdir="$HOME/.local/share/fonts"
    if fc-list 2>/dev/null | grep -qiE "CaskaydiaCove|Nerd Font"; then
        return 0
    fi
    # fc-list may be missing/lagging right after fc-cache: also look on disk.
    compgen -G "$fontdir/*Caskaydia*" >/dev/null 2>&1 && return 0
    compgen -G "$fontdir/*Nerd*" >/dev/null 2>&1 && return 0
    return 1
}

install_nerd_font() {
    if nerd_font_installed; then
        ok "Nerd Font already installed"
        return 0
    fi
    if ! ask "Install a Nerd Font for crisp TUI icons ? [Y/n] " y; then
        return 0
    fi
    if ! command -v unzip >/dev/null 2>&1; then
        warn "unzip not found — skipping Nerd Font (emoji icons still work)."
        return 0
    fi
    local dest tmp url
    dest="$HOME/.local/share/fonts"
    tmp="$(mktemp -d)"
    url="https://github.com/ryanoasis/nerd-fonts/releases/latest/download/CascadiaCode.zip"
    log "Downloading CaskaydiaCove Nerd Font…"
    if curl -fsSL -o "$tmp/CascadiaCode.zip" "$url" \
        && unzip -oq "$tmp/CascadiaCode.zip" -d "$tmp/nf"; then
        mkdir -p "$dest"
        cp "$tmp"/nf/*.ttf "$dest/" 2>/dev/null || true
        fc-cache -f "$dest" >/dev/null 2>&1 || true
        ok "Nerd Font installed (select 'CaskaydiaCove Nerd Font' in your terminal)"
    else
        warn "Could not download the Nerd Font — emoji icons still work."
    fi
    rm -rf "$tmp"
}

# ─── 5. Optional : Nvidia PRIME wrappers for hybrid laptops ─────────
install_nvidia_wrappers() {
    local target="$HOME/.local/bin/mpv"
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        return 0  # No Nvidia GPU → nothing to do
    fi
    # Never clobber a wrapper that isn't ours, never rewrite ours needlessly.
    if [[ -f "$target" ]] \
        && ! grep -q "FreeFlix PRIME wrapper" "$target" 2>/dev/null; then
        warn "$target already exists and is not a FreeFlix wrapper — kept."
        return 0
    fi
    if cmp -s "$PROJECT_ROOT/scripts/wrappers/mpv" "$target"; then
        ok "Nvidia PRIME wrapper already installed"
        return 0
    fi
    if ! ask "Install the Nvidia PRIME wrapper so mpv uses the dGPU ? [Y/n] " y; then
        return 0
    fi
    mkdir -p "$HOME/.local/bin"
    cp "$PROJECT_ROOT/scripts/wrappers/mpv" "$target"
    chmod +x "$target"

    if ! echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
        warn "$HOME/.local/bin is NOT in PATH — add it to ~/.bashrc / ~/.zshrc :"
        warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
    ok "Nvidia PRIME wrappers installed"
}

# ─── 6. Optional : FlareSolverr (auto-solve Cloudflare) ──────────────
# Podman (rootless, no sudo) is preferred ; Docker is the fallback. On
# Podman we also register a systemd --user service so it survives reboots.
FS_IMAGE="ghcr.io/flaresolverr/flaresolverr:latest"

flaresolverr_running() {
    curl -fsS --max-time 2 http://127.0.0.1:8191/health >/dev/null 2>&1 \
        || curl -fsS --max-time 2 http://127.0.0.1:8191/ >/dev/null 2>&1
}

flaresolverr_persistent_podman() {
    loginctl enable-linger "${USER:-$(id -un)}" >/dev/null 2>&1 || true
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
    if flaresolverr_running; then
        ok "FlareSolverr already running on :8191"
        return 0
    fi
    if ! ask "Set up FlareSolverr to auto-solve Cloudflare (~1 GB image) ? [y/N] " n; then
        return 0
    fi

    RT=""
    if command -v podman >/dev/null 2>&1; then RT="podman"
    elif command -v docker >/dev/null 2>&1; then RT="docker"
    else
        log "No Podman/Docker found. Installing Podman (rootless, recommended)…"
        case "$DISTRO" in
            fedora|rhel|centos|rocky|alma) $SUDO dnf install -y podman ;;
            debian|ubuntu|linuxmint|pop)   $SUDO apt-get install -y podman ;;
            arch|manjaro|endeavouros)      $SUDO pacman -S --needed --noconfirm podman ;;
            opensuse*|suse|sles)           $SUDO zypper install -y podman ;;
            alpine)                        $SUDO apk add podman ;;
        esac
        command -v podman >/dev/null 2>&1 && RT="podman"
    fi
    [[ -z "$RT" ]] && { warn "No container runtime — FlareSolverr skipped."; return 0; }

    log "Starting FlareSolverr via $RT (first run downloads the image)…"
    if ! "$RT" start flaresolverr >/dev/null 2>&1; then
        # Re-running `run --name flaresolverr` printed "name already in use"
        # and looked like a failure: only create it when absent.
        if "$RT" container inspect flaresolverr >/dev/null 2>&1; then
            warn "FlareSolverr container exists but could not be started."
        elif ! "$RT" run -d --name flaresolverr --restart unless-stopped \
                -p 8191:8191 "$FS_IMAGE"; then
            warn "Could not start FlareSolverr — start it manually later."
            return 0
        fi
    fi

    [[ "$RT" == "podman" ]] && flaresolverr_persistent_podman
    ok "FlareSolverr set up (give it a moment to be ready)."
}

# ─── Main ────────────────────────────────────────────────────────────
install_system_pkgs
install_freeflix
ensure_permanent_path
install_mpv_config
install_nerd_font
install_nvidia_wrappers
install_flaresolverr

echo
ok "Installation complete. Run :  ${GREEN}freeflix${NC}"
log "Icons: if you installed the Nerd Font, set it as your terminal font, then"
log "in FreeFlix go to Settings > Icon Style > nerd (emoji is the default)."
