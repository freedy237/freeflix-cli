#Requires -Version 5.1
# FreeFlix CLI - Windows bootstrap
#
# Usage (no Python required):
#   powershell -c "iwr -useb https://raw.githubusercontent.com/freedy237/freeflix-cli/main/scripts/install.ps1 | iex"
#
# Installs uv (standalone, no pre-requisites), then installs freeflix-cli
# and yt-dlp via uv.  Non-interactive.

$ErrorActionPreference = "Stop"

function Log($m)  { Write-Host "[*]  $m" -ForegroundColor Blue }
function Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Err($m)  { Write-Host "[X]  $m" -ForegroundColor Red }

try { chcp 65001 > $null } catch {}
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

Write-Host ""
Log "FreeFlix CLI - Windows Bootstrap"
Write-Host ""

$localBin = "$env:USERPROFILE\.local\bin"
$uvExe    = "$localBin\uv.exe"

# ---- 1. Install uv (standalone binary — no execution-policy issues) ---
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Ok "uv already installed"
} elseif (Test-Path $uvExe) {
    $env:PATH = "$localBin;$env:PATH"
    Ok "uv already installed (was on disk, added to PATH)"
} else {
    Log "Downloading uv ..."
    $uvUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
    $tmp   = "$env:TEMP\freeflix-uv"
    $null = New-Item -ItemType Directory -Path $tmp -Force
    try {
        $zip = "$tmp\uv.zip"
        Write-Host "       (≈10 MiB — no progress bar, please wait)"
        [Net.WebClient]::new().DownloadFile($uvUrl, $zip)
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $bin = Get-ChildItem -Recurse -Filter "uv.exe" -Path $tmp | Select-Object -First 1
        if (-not $bin) { throw "uv.exe not found in archive" }
        $null = New-Item -ItemType Directory -Path $localBin -Force
        Copy-Item -Path $bin.FullName -Destination $uvExe -Force
        $env:PATH = "$localBin;$env:PATH"
    } catch {
        Err "uv download/extract failed: $_"
        exit 1
    } finally {
        Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
        Err "uv still not found after install."
        exit 1
    }
    Ok "uv installed"
}

# ---- 2. Install freeflix-cli + yt-dlp via uv -------------------------
Log "Installing freeflix-cli ..."
uv tool install freeflix-cli --force
if ($LASTEXITCODE -ne 0) {
    Err "freeflix-cli install failed (exit $LASTEXITCODE)"
    exit 1
}
Ok "freeflix-cli installed"

Log "Installing yt-dlp ..."
uv tool install yt-dlp --force
if ($LASTEXITCODE -ne 0) {
    Err "yt-dlp install failed (exit $LASTEXITCODE)"
    exit 1
}
Ok "yt-dlp installed"

# ---- 3. Add ~\.local\bin to user PATH --------------------------------
$userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -and $userPath -like "*$localBin*") {
    Ok "$localBin already in user PATH"
} else {
    try {
        $newPath = if ($userPath) { "$localBin;$userPath" } else { $localBin }
        [System.Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        Ok "$localBin added to user PATH (new terminal recommended)"
    } catch {
        Warn "Could not update user PATH: $_"
    }
}

Write-Host ""
Ok "Installation complete!"
Log "Open a NEW terminal tab and run:  freeflix"
Write-Host ""
