# FreeFlix CLI — Windows installer (winget + pipx)
# Run from PowerShell as a regular user :
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# Installs : mpv, yt-dlp, ffmpeg, aria2, Python ; then the freeflix command.

$ErrorActionPreference = "Stop"
function Log($m)   { Write-Host "» $m" -ForegroundColor Blue }
function Ok($m)    { Write-Host "✓ $m" -ForegroundColor Green }
function Warn($m)  { Write-Host "! $m" -ForegroundColor Yellow }
function Err($m)   { Write-Host "✗ $m" -ForegroundColor Red }

# ─── 1. Ensure winget is available ───────────────────────────────────
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Err "winget is not installed. Install 'App Installer' from the Microsoft Store, then re-run this script."
    exit 1
}
Ok "winget available"

# ─── 2. System dependencies via winget ───────────────────────────────
$packages = @(
    @{ id = "Python.Python.3.12"; name = "Python 3.12" },
    @{ id = "mpv.net";             name = "mpv.net (mpv for Windows)" },
    @{ id = "yt-dlp.yt-dlp";       name = "yt-dlp" },
    @{ id = "Gyan.FFmpeg";         name = "FFmpeg" },
    @{ id = "aria2.aria2";         name = "aria2" }
)

foreach ($pkg in $packages) {
    Log "Installing $($pkg.name)…"
    winget install --silent --accept-source-agreements --accept-package-agreements --id $pkg.id 2>$null
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {  # already installed
        Warn "$($pkg.name) install returned exit code $LASTEXITCODE — continuing"
    }
}
Ok "System packages installed"

# Refresh PATH for the rest of this session
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("PATH","User")

# ─── 3. Install pipx, then freeflix-cli ──────────────────────────────
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Log "Project root : $ProjectRoot"

Log "Installing pipx (if missing)…"
python -m pip install --user --upgrade pipx
python -m pipx ensurepath
$env:PATH += ";$env:USERPROFILE\.local\bin"

Log "Installing freeflix-cli via pipx…"
pipx install --force $ProjectRoot
Ok "freeflix command installed"

# ─── 4. Optional : mpv config + Anime4K ──────────────────────────────
$mpvDir = "$env:APPDATA\mpv"
Log "Install default mpv config (Anime4K toggle, anti-crash) ?"
$ans = Read-Host "  [Y/n]"
if ($ans -notmatch "^[Nn]") {
    New-Item -ItemType Directory -Force -Path "$mpvDir\scripts" | Out-Null
    New-Item -ItemType Directory -Force -Path "$mpvDir\shaders" | Out-Null

    Copy-Item "$ProjectRoot\config\mpv.conf"              "$mpvDir\mpv.conf"   -Force
    Copy-Item "$ProjectRoot\config\input.conf"            "$mpvDir\input.conf" -Force
    Copy-Item "$ProjectRoot\config\freeflix_position.lua" "$mpvDir\scripts\freeflix_position.lua" -Force

    $base = "https://raw.githubusercontent.com/bloc97/Anime4K/master/glsl"
    Invoke-WebRequest "$base/Restore/Anime4K_Clamp_Highlights.glsl"  -OutFile "$mpvDir\shaders\Anime4K_Clamp_Highlights.glsl"
    Invoke-WebRequest "$base/Restore/Anime4K_Restore_CNN_VL.glsl"    -OutFile "$mpvDir\shaders\Anime4K_Restore_CNN_VL.glsl"
    Invoke-WebRequest "$base/Upscale/Anime4K_Upscale_CNN_x2_VL.glsl" -OutFile "$mpvDir\shaders\Anime4K_Upscale_CNN_x2_VL.glsl"
    Ok "mpv config installed (CTRL+1 toggles Anime4K)"
}

Write-Host ""
Ok "Installation complete. Open a new terminal and run :  freeflix"
