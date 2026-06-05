#Requires -Version 5.1
# FreeFlix CLI - Windows installer (idempotent / resumable)
#
# Run from PowerShell (regular user is fine):
#   powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
#
# Re-runnable: every step checks what's already there and only installs what
# is missing, so if a previous run failed half-way you can just run it again
# and it continues. A completion marker is written so FreeFlix knows the
# system dependencies are in place.
#
# NOTE: this file is intentionally 100% ASCII. Windows PowerShell 5.1 reads
# scripts in the legacy ANSI code page, so any fancy Unicode glyph (arrows,
# check marks, box-drawing) gets mangled and breaks the parser. Keep it ASCII.

$ErrorActionPreference = "Continue"   # never hard-stop on one optional failure

function Log($m)  { Write-Host "[*]  $m" -ForegroundColor Blue }
function Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[!]  $m" -ForegroundColor Yellow }
function Err($m)  { Write-Host "[X]  $m" -ForegroundColor Red }

$Script:Failures = @()
function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

# Make THIS console UTF-8 so output renders while the script runs.
try { chcp 65001 > $null } catch {}
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

Write-Host ""
Log "FreeFlix CLI - Windows setup"
Write-Host ""

# ---- 1. winget --------------------------------------------------------
if (-not (Have "winget")) {
    Err "winget not found. Install 'App Installer' from the Microsoft Store,"
    Err "then run this script again."
    exit 1
}
Ok "winget available"

# ---- 2. System packages (install only the missing ones) ---------------
# id              : winget package id
# name            : friendly label
# bins            : command(s) that prove it is already installed
$packages = @(
    @{ id = "Python.Python.3.12";        name = "Python 3.12";      bins = @("python", "py") },
    @{ id = "Microsoft.WindowsTerminal"; name = "Windows Terminal"; bins = @("wt") },
    @{ id = "mpv.net";                   name = "mpv.net";          bins = @("mpvnet", "mpv") },
    @{ id = "VideoLAN.VLC";              name = "VLC";              bins = @("vlc") },
    @{ id = "yt-dlp.yt-dlp";             name = "yt-dlp";           bins = @("yt-dlp") },
    @{ id = "Gyan.FFmpeg";               name = "FFmpeg";           bins = @("ffmpeg") },
    @{ id = "aria2.aria2";               name = "aria2";            bins = @("aria2c") },
    @{ id = "hpjansson.Chafa";           name = "chafa (posters)";  bins = @("chafa") }
)

function Test-Pkg($pkg) {
    foreach ($b in $pkg.bins) { if (Have $b) { return $true } }
    return $false
}

function Install-Pkg($pkg) {
    if (Test-Pkg $pkg) { Ok "$($pkg.name) already present"; return }
    Log "Installing $($pkg.name) ..."
    winget install --silent --accept-source-agreements --accept-package-agreements --id $pkg.id | Out-Null
    $code = $LASTEXITCODE
    Start-Sleep -Milliseconds 250
    # 0 = installed ; -1978335189 = no applicable upgrade (already installed)
    if ((Test-Pkg $pkg) -or $code -eq 0 -or $code -eq -1978335189) {
        Ok "$($pkg.name) installed"
    } else {
        Warn "$($pkg.name) did not install cleanly (exit $code) - will retry on next run"
        $Script:Failures += $pkg.name
    }
}

foreach ($p in $packages) { Install-Pkg $p }

# Refresh PATH for the rest of THIS session so freshly-installed tools resolve.
$machine = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
$user    = [System.Environment]::GetEnvironmentVariable("PATH", "User")
$env:PATH = "$machine;$user;$env:USERPROFILE\.local\bin"

# ---- 3. Nerd Font (so the TUI icons render as crisp glyphs) -----------
function Install-NerdFont {
    $userFonts = "$env:LOCALAPPDATA\Microsoft\Windows\Fonts"
    $already = (Test-Path "$userFonts\CaskaydiaCoveNerdFont-Regular.ttf") -or
               (Test-Path "$env:WINDIR\Fonts\CaskaydiaCoveNerdFont-Regular.ttf")
    if ($already) { Ok "Nerd Font already installed (CaskaydiaCove)"; return $true }

    Log "Installing CaskaydiaCove Nerd Font (per-user, no admin needed) ..."
    $zip = "$env:TEMP\CascadiaCodeNF.zip"
    $dir = "$env:TEMP\CascadiaCodeNF"
    $url = "https://github.com/ryanoasis/nerd-fonts/releases/latest/download/CascadiaCode.zip"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
        if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
        Expand-Archive -Path $zip -DestinationPath $dir -Force
        New-Item -ItemType Directory -Force -Path $userFonts | Out-Null
        $reg = "HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
        $n = 0
        Get-ChildItem -Path $dir -Filter "*.ttf" -Recurse | ForEach-Object {
            $dest = Join-Path $userFonts $_.Name
            Copy-Item $_.FullName $dest -Force
            New-ItemProperty -Path $reg -Name "$($_.BaseName) (TrueType)" -PropertyType String -Value $dest -Force | Out-Null
            $n++
        }
        Remove-Item -Force $zip -ErrorAction SilentlyContinue
        Ok "Nerd Font installed ($n styles). Face name: 'CaskaydiaCove Nerd Font'"
        return $true
    } catch {
        Warn "Could not install the Nerd Font automatically: $($_.Exception.Message)"
        Warn "FreeFlix will still work with emoji icons. You can install a Nerd"
        Warn "Font later from https://www.nerdfonts.com and switch icons in Settings."
        $Script:Failures += "Nerd Font"
        return $false
    }
}
$fontOk = Install-NerdFont

# ---- 4. pipx + freeflix-cli ------------------------------------------
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Log "Project root: $ProjectRoot"

if (-not (Have "pipx")) {
    Log "Installing pipx ..."
    python -m pip install --user --upgrade pipx | Out-Null
    python -m pipx ensurepath | Out-Null
    $env:PATH += ";$env:USERPROFILE\.local\bin"
}

Log "Installing freeflix-cli (pipx) ..."
pipx install --force "$ProjectRoot" | Out-Null
if (Have "freeflix") { Ok "freeflix command installed" }
else { Warn "freeflix not on PATH yet - open a NEW terminal after this finishes"; $Script:Failures += "freeflix command" }

# ---- 5. mpv config (Anime4K toggle, anti-crash) - idempotent ----------
$mpvDir = "$env:APPDATA\mpv"
if (Test-Path "$mpvDir\mpv.conf") {
    Ok "mpv config already present"
} else {
    Log "Installing default mpv config + Anime4K shaders ..."
    try {
        New-Item -ItemType Directory -Force -Path "$mpvDir\scripts" | Out-Null
        New-Item -ItemType Directory -Force -Path "$mpvDir\shaders" | Out-Null
        Copy-Item "$ProjectRoot\config\mpv.conf"              "$mpvDir\mpv.conf"   -Force
        Copy-Item "$ProjectRoot\config\input.conf"            "$mpvDir\input.conf" -Force
        Copy-Item "$ProjectRoot\config\freeflix_position.lua" "$mpvDir\scripts\freeflix_position.lua" -Force
        $base = "https://raw.githubusercontent.com/bloc97/Anime4K/master/glsl"
        Invoke-WebRequest -UseBasicParsing "$base/Restore/Anime4K_Clamp_Highlights.glsl"  -OutFile "$mpvDir\shaders\Anime4K_Clamp_Highlights.glsl"
        Invoke-WebRequest -UseBasicParsing "$base/Restore/Anime4K_Restore_CNN_VL.glsl"    -OutFile "$mpvDir\shaders\Anime4K_Restore_CNN_VL.glsl"
        Invoke-WebRequest -UseBasicParsing "$base/Upscale/Anime4K_Upscale_CNN_x2_VL.glsl" -OutFile "$mpvDir\shaders\Anime4K_Upscale_CNN_x2_VL.glsl"
        Ok "mpv config installed (CTRL+1 toggles Anime4K)"
    } catch {
        Warn "mpv config step failed: $($_.Exception.Message) - will retry on next run"
    }
}

# ---- 6. FlareSolverr (optional, auto-solve Cloudflare) ----------------
$fsRunning = $false
try { $fsRunning = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:8191/").StatusCode -eq 200 } catch {}
if ($fsRunning) {
    Ok "FlareSolverr already running on :8191"
} else {
    Log "Set up FlareSolverr to auto-solve Cloudflare (Coflix/Anime-Sama)? Needs Docker Desktop. [y/N]"
    $a = Read-Host "  Answer"
    if ($a -match "^[Yy]") {
        if (Have "docker") {
            docker start flaresolverr 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) {
                docker run -d --name flaresolverr --restart unless-stopped -p 8191:8191 ghcr.io/flaresolverr/flaresolverr:latest | Out-Null
            }
            Ok "FlareSolverr requested (give it a moment to be ready)."
        } else {
            Warn "Docker not found. Install Docker Desktop, then run:"
            Warn "  docker run -d --name flaresolverr --restart unless-stopped -p 8191:8191 ghcr.io/flaresolverr/flaresolverr:latest"
        }
    }
}

# ---- 7. Write completion marker (so FreeFlix can skip re-checking) ----
$cfgDir = "$env:LOCALAPPDATA\PaulExplorer\AutoFlixCLI"
try {
    New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
    $marker = [ordered]@{
        system_deps_ok = ($Script:Failures.Count -eq 0)
        failures       = $Script:Failures
        nerd_font      = $fontOk
        installed_at   = (Get-Date).ToString("o")
    }
    ($marker | ConvertTo-Json) | Set-Content -Path "$cfgDir\install_status.json" -Encoding UTF8
} catch {}

# ---- 8. Summary -------------------------------------------------------
Write-Host ""
if ($Script:Failures.Count -eq 0) {
    Ok "Installation complete."
} else {
    Warn "Installation finished with some items pending: $($Script:Failures -join ', ')"
    Warn "Just run this script again - it will only retry what is missing."
}
Write-Host ""
Log "IMPORTANT - for the icons to show correctly:"
Log "  1. Use 'Windows Terminal' (installed above), NOT the old cmd.exe window."
Log "  2. In Windows Terminal: Settings > Defaults > Appearance > Font face"
Log "       -> choose 'CaskaydiaCove Nerd Font'."
Log "  3. Open a NEW Windows Terminal tab and run:  freeflix"
Log "If glyphs still look odd, run 'freeflix' and pick emoji icons in Settings."
Write-Host ""
