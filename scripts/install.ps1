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

# ---- 1. Install uv (standalone binary — no execution-policy issues) ---
if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Log "Installing uv ..."
    $uvUrl  = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
    $tmpDir = "$env:TEMP\freeflix-uv"
    $null = New-Item -ItemType Directory -Path $tmpDir -Force
    $zip    = "$tmpDir\uv.zip"
    try {
        [Net.WebClient]::new().DownloadFile($uvUrl, $zip)
        Expand-Archive -Path $zip -DestinationPath $tmpDir -Force
        $uvBin = Get-ChildItem -Recurse -Filter "uv.exe" -Path $tmpDir | Select-Object -First 1
        if (-not $uvBin) { throw "uv.exe not found in archive" }
        $localBin = "$env:USERPROFILE\.local\bin"
        $null = New-Item -ItemType Directory -Path $localBin -Force
        Copy-Item -Path $uvBin.FullName -Destination "$localBin\uv.exe" -Force
        $env:PATH = "$localBin;$env:PATH"
    } catch {
        Err "uv download/extract failed: $_"
        Err "Visit https://docs.astral.sh/uv/#getting-started"
        exit 1
    } finally {
        Remove-Item -Path $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
        Err "uv not found on PATH after install."
        exit 1
    }
    Ok "uv installed"
} else {
    Ok "uv already installed"
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
$localBin = "$env:USERPROFILE\.local\bin"
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
