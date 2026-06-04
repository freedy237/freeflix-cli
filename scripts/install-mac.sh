#!/usr/bin/env bash
# FreeFlix CLI — macOS installer (Homebrew based)

set -euo pipefail

BLUE="\033[1;34m"; GREEN="\033[1;32m"; YELLOW="\033[1;33m"; RED="\033[1;31m"; NC="\033[0m"
log()   { echo -e "${BLUE}»${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}!${NC} $*"; }
err()   { echo -e "${RED}✗${NC} $*" >&2; }

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

# ─── 2. Install system packages ──────────────────────────────────────
log "Installing system deps via brew…"
brew install --quiet python yt-dlp ffmpeg aria2 mpv chafa
ok "System packages installed"

# ─── 3. Install freeflix-cli ─────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v uv >/dev/null 2>&1; then
    log "Installing freeflix-cli via uv…"
    uv tool install --force "$PROJECT_ROOT"
elif command -v pipx >/dev/null 2>&1; then
    log "Installing freeflix-cli via pipx…"
    pipx install --force "$PROJECT_ROOT"
else
    log "Installing pipx then freeflix-cli…"
    brew install --quiet pipx
    pipx ensurepath
    pipx install --force "$PROJECT_ROOT"
fi
ok "freeflix command installed"

# ─── 4. Optional : mpv config + Anime4K ──────────────────────────────
log "Install default mpv config (Anime4K toggle, anti-crash) ?"
read -rp "  [Y/n] " ans
if [[ ! "${ans:-Y}" =~ ^[Nn] ]]; then
    mkdir -p "$HOME/.config/mpv/scripts" "$HOME/.config/mpv/shaders"
    cp "$PROJECT_ROOT/config/mpv.conf"              "$HOME/.config/mpv/mpv.conf"
    cp "$PROJECT_ROOT/config/input.conf"            "$HOME/.config/mpv/input.conf"
    cp "$PROJECT_ROOT/config/freeflix_position.lua" "$HOME/.config/mpv/scripts/freeflix_position.lua"

    BASE="https://raw.githubusercontent.com/bloc97/Anime4K/master/glsl"
    curl -fsSL -o "$HOME/.config/mpv/shaders/Anime4K_Clamp_Highlights.glsl"  "$BASE/Restore/Anime4K_Clamp_Highlights.glsl"
    curl -fsSL -o "$HOME/.config/mpv/shaders/Anime4K_Restore_CNN_VL.glsl"    "$BASE/Restore/Anime4K_Restore_CNN_VL.glsl"
    curl -fsSL -o "$HOME/.config/mpv/shaders/Anime4K_Upscale_CNN_x2_VL.glsl" "$BASE/Upscale/Anime4K_Upscale_CNN_x2_VL.glsl"
    ok "mpv config installed (CTRL+1 toggles Anime4K)"
fi

echo
ok "Installation complete. Run :  ${GREEN}freeflix${NC}"
