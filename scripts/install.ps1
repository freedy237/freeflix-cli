#Requires -Version 5.1
# FreeFlix CLI - Windows bootstrap
#
# Usage:
#   powershell -c "iwr -useb https://raw.githubusercontent.com/freedy237/freeflix-cli/main/scripts/install.ps1 | iex"
#
# Installs uv + Python (if missing), then freeflix-cli and yt-dlp via uv.
# No manual pre-requisites needed beyond a working internet connection.

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

# ===== 1. Install uv (standalone binary) =====
$uvExe = "$localBin\uv.exe"
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Ok "uv already installed"
} elseif (Test-Path $uvExe) {
    $env:PATH = "$localBin;$env:PATH"
    Ok "uv already installed (was on disk, added to PATH)"
} else {
    Log "Downloading uv ..."
    $tmp = "$env:TEMP\freeflix-uv"
    $null = New-Item -ItemType Directory -Path $tmp -Force
    try {
        $zip = "$tmp\uv.zip"
        Write-Host "       (~10 MiB - please wait)"
        [Net.WebClient]::new().DownloadFile(
            "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip",
            $zip
        )
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

# ===== 2. Ensure Python is on PATH (avoid uv downloading it) =====
$havePy = (Get-Command "python3" -ErrorAction SilentlyContinue) -or
          (Get-Command "python" -ErrorAction SilentlyContinue)

if (-not $havePy -and (Get-Command "winget" -ErrorAction SilentlyContinue)) {
    Log "Installing Python via winget ..."
    winget install --silent --accept-source-agreements --accept-package-agreements Python.Python.3.12 2>$null
    # winget installs Python; refresh PATH so uv can find it
    $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("PATH", "User") + ";" +
                "$env:USERPROFILE\AppData\Local\Programs\Python\Python312\Scripts;" +
                "$env:USERPROFILE\AppData\Local\Programs\Python\Python312"
    $havePy = (Get-Command "python3" -ErrorAction SilentlyContinue) -or
              (Get-Command "python" -ErrorAction SilentlyContinue)
    if ($havePy) { Ok "Python installed" }
}

# ===== 3. Install freeflix-cli + yt-dlp via uv =====
# Pin a stable, well-tested CPython 3.12 (the code supports 3.9+, but pinning
# avoids landing on the system's old/bleeding-edge Python - e.g. a system 3.9).
# --force so re-running the installer always upgrades to the latest. Falls back
# to whatever Python uv can use if the 3.12 fetch fails (offline / locked-down).
Log "Installing freeflix-cli ..."
uv tool install freeflix-cli --force --python 3.12
if ($LASTEXITCODE -ne 0) {
    Write-Host "       (retrying without Python pin)..."
    uv tool install freeflix-cli --force
}
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

# ===== 4. Add ~\.local\bin to user PATH =====
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -and $userPath -like "*$localBin*") {
    Ok "$localBin already in user PATH"
} else {
    try {
        $newPath = if ($userPath) { "$localBin;$userPath" } else { $localBin }
        [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        Ok "$localBin added to user PATH (new terminal recommended)"
    } catch {
        Err "Could not update user PATH: $_"
    }
}

Write-Host ""
Ok "Installation complete!"
Log "Open a NEW terminal tab and run:  freeflix"
Write-Host ""
