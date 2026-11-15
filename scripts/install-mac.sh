#!/usr/bin/env bash
# FreeFlix CLI — macOS installer (Homebrew based)
#
# Re-runnable by design : already-installed brew packages are skipped, an
# existing tuned mpv.conf is never overwritten, shaders are only downloaded
# when missing, and prompts are skipped when stdin is not a terminal.

set -euo pipefail

BLUE="\033[1;34m"; GREEN="\033[1;32m"; YELLOW="\033[1;33m"; RED="\033[1;31m"; NC="\033[0m"
log()   { echo -e "${BLUE}»${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}!${NC} $*"; }
err()   { echo -e "${RED}✗${NC} $*" >&2; }

# Take the default instead of hanging/aborting when piped (no TTY).
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

# ─── 1. Ensure Homebrew ──────────────────────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
    log "Homebrew not found, installing it…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for this session (Apple Silicon vs Intel default paths)
    if [[ -x /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi
ok "Homebrew available"

# ─── 2. Install system packages (only the missing ones) ──────────────
# `brew list --versions` is a cheap local check ; calling `brew install`
# again for present packages re-ran the whole dependency resolution and
# printed upgrade noise on every re-run.
brew_installed() {
    brew list --versions "$1" >/dev/null 2>&1 \
        || brew list --cask --versions "$1" >/dev/null 2>&1
}

log "Installing system deps via brew (missing only)…"
for pkg in python yt-dlp ffmpeg aria2 mpv chafa; do
    if brew_installed "$pkg"; then
        continue
    fi
    brew install --quiet "$pkg" || warn "Could not install $pkg — continuing."
done
if ! brew_installed vlc; then
    brew install --quiet --cask vlc 2>/dev/null \
        || brew install --quiet vlc 2>/dev/null \
        || warn "VLC unavailable — mpv alone is enough to watch."
fi
ok "System packages ready"

# ─── 2b. Nerd Font (crisp TUI icons) — idempotent ────────────────────
if brew_installed font-caskaydia-cove-nerd-font; then
    ok "Nerd Font already installed"
elif brew install --quiet --cask font-caskaydia-cove-nerd-font 2>/dev/null; then
    ok "Nerd Font installed (set your terminal font to 'CaskaydiaCove Nerd Font')"
else
    warn "Nerd Font cask unavailable — emoji icons still work out of the box."
fi

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

install_uv_if_missing
want="$(project_version)"
have="$(uv tool list 2>/dev/null | awk '/^freeflix-cli /{print $2; exit}' | sed 's/^v//')"
if [[ -n "$have" && -n "$want" && "$have" == "$want" \
      && "${FREEFLIX_FORCE_REINSTALL:-0}" != "1" ]]; then
    ok "freeflix-cli ${have} already installed (no reinstall)"
else
    log "Installing freeflix-cli${want:+ ${want}} via uv…"
    uv tool install --force "$PROJECT_ROOT"
    ok "freeflix command installed"
fi

ensure_permanent_path() {
    local bin_dir="$HOME/.local/bin"
    mkdir -p "$bin_dir"
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
ensure_permanent_path

# ─── 4. Optional : mpv config + Anime4K (never overwrites) ──────────
MPV_CFG="$HOME/.config/freeflix/mpv"

install_file_once() {
    local src="$1" dest="$2"
    if [[ -s "$dest" ]]; then
        return 0
    fi
    cp "$src" "$dest"
}

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

if [[ -s "$MPV_CFG/mpv.conf" && -s "$MPV_CFG/input.conf" \
      && -s "$MPV_CFG/scripts/freeflix_position.lua" ]]; then
    ok "mpv config already installed (kept)"
elif ask "Install default mpv config (Anime4K toggle, anti-crash) ? [Y/n] " y; then
    # FreeFlix launches mpv with --config-dir ~/.config/freeflix/mpv: writing
    # the global ~/.config/mpv made Anime4K invisible to the app.
    mkdir -p "$MPV_CFG/scripts" "$MPV_CFG/shaders"
    install_file_once "$PROJECT_ROOT/config/mpv.conf" "$MPV_CFG/mpv.conf"
    install_file_once "$PROJECT_ROOT/config/input.conf" "$MPV_CFG/input.conf"
    install_file_once "$PROJECT_ROOT/config/freeflix_position.lua" \
        "$MPV_CFG/scripts/freeflix_position.lua"
    ok "mpv config installed (CTRL+1 toggles Anime4K)"
fi

if [[ -d "$MPV_CFG/shaders" ]]; then
    BASE="https://raw.githubusercontent.com/bloc97/Anime4K/master/glsl"
    download_shader_once "$MPV_CFG/shaders/Anime4K_Clamp_Highlights.glsl" \
        "$BASE/Restore/Anime4K_Clamp_Highlights.glsl"
    # mpv.conf loads the S variant by default; CTRL+1 switches to VL.
    download_shader_once "$MPV_CFG/shaders/Anime4K_Restore_CNN_S.glsl" \
        "$BASE/Restore/Anime4K_Restore_CNN_S.glsl"
    download_shader_once "$MPV_CFG/shaders/Anime4K_Upscale_CNN_x2_S.glsl" \
        "$BASE/Upscale/Anime4K_Upscale_CNN_x2_S.glsl"
    download_shader_once "$MPV_CFG/shaders/Anime4K_Restore_CNN_VL.glsl" \
        "$BASE/Restore/Anime4K_Restore_CNN_VL.glsl"
    download_shader_once "$MPV_CFG/shaders/Anime4K_Upscale_CNN_x2_VL.glsl" \
        "$BASE/Upscale/Anime4K_Upscale_CNN_x2_VL.glsl"
fi

# ─── 5. Optional : FlareSolverr (auto-solve Cloudflare) via Docker ───
flaresolverr_running() {
    curl -fsS --max-time 2 http://127.0.0.1:8191/health >/dev/null 2>&1 \
        || curl -fsS --max-time 2 http://127.0.0.1:8191/ >/dev/null 2>&1
}

if flaresolverr_running; then
    ok "FlareSolverr already running on :8191"
elif ask "Set up FlareSolverr to auto-solve Cloudflare (needs Docker) ? [y/N] " n; then
    if command -v docker >/dev/null 2>&1; then
        if ! docker start flaresolverr >/dev/null 2>&1; then
            if docker container inspect flaresolverr >/dev/null 2>&1; then
                warn "FlareSolverr container exists but could not be started."
            elif ! docker run -d --name flaresolverr --restart unless-stopped \
                    -p 8191:8191 ghcr.io/flaresolverr/flaresolverr:latest; then
                warn "Could not start FlareSolverr — start it manually later."
            fi
        fi
        ok "FlareSolverr requested (give it a moment to be ready)."
    else
        warn "Docker not found. Install Docker, then run the flaresolverr container."
    fi
fi

echo
ok "Installation complete. Run :  ${GREEN}freeflix${NC}"
log "Icons: set your terminal font to 'CaskaydiaCove Nerd Font', then in"
log "FreeFlix go to Settings > Icon Style > nerd (emoji is the default)."
