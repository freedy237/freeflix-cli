#Requires -Version 5.1
# FreeFlix CLI - Windows bootstrap
#
# Usage (no Python required):
#   powershell -c "iwr -useb https://raw.githubusercontent.com/freedy237/freeflix-cli/main/scripts/install.ps1 | iex"
#
# Installs uv (standalone, no pre-requisites), then installs freeflix-cli
# and yt-dlp via uv.  Non-interactive.

# Override execution policy for this process only — no system change.
Set-ExecutionPolicy Bypass -Scope Process -Force 2>$null

$ErrorActionPreference = "Stop"

function Log($m)  { Write-Host "[*]  $m" -ForegroundColor Blue }
function Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Err($m)  { Write-Host "[X]  $m" -ForegroundColor Red }

try { chcp 65001 > $null } catch {}
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

Write-Host ""
Log "FreeFlix CLI - Windows Bootstrap"
Write-Host ""

# ---- 1. Install uv (standalone, no Python needed) --------------------
if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Log "Installing uv ..."
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
        $env:PATH += ";$env:USERPROFILE\.local\bin"
    }
    if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
        Err "uv did not install correctly."
        Err "Visit https://docs.astral.sh/uv/#getting-started"
        exit 1
    }
    Ok "uv installed"
} else {
    Ok "uv already installed"
}

# ---- 2. Install freeflix-cli + yt-dlp via uv -------------------------
Log "Installing freeflix-cli ..."
uv tool install freeflix-cli --force 2>&1 | Out-Null
Ok "freeflix-cli installed"

Log "Installing yt-dlp ..."
uv tool install yt-dlp --force 2>&1 | Out-Null
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
