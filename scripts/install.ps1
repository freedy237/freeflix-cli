#Requires -Version 5.1
# FreeFlix CLI - Windows bootstrap
#
# Usage (download, inspect, then run - avoid piping into iex, which triggers
# Defender's ML heuristics on unsigned installers):
#   irm https://raw.githubusercontent.com/freedy237/freeflix-cli/main/scripts/install.ps1 -OutFile install.ps1
#   Unblock-File .\install.ps1
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# Installs uv + Python (if missing), then freeflix-cli and yt-dlp via uv.
# No manual pre-requisites needed beyond a working internet connection.

$ErrorActionPreference = "Stop"

function Log($m)  { Write-Host "[*]  $m" -ForegroundColor Blue }
function Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Err($m)  { Write-Host "[X]  $m" -ForegroundColor Red }

try { chcp 65001 > $null } catch {}
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
# Windows PowerShell 5.1 may still default to TLS 1.0/1.1; GitHub rejects it.
try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
} catch {
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
}

# Native arm64 asset when running Windows-on-ARM (x64 would run under emulation).
$uvArch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") {
    "aarch64-pc-windows-msvc"
} else {
    "x86_64-pc-windows-msvc"
}

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
            "https://github.com/astral-sh/uv/releases/latest/download/uv-$uvArch.zip",
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

# ===== 3b. Media tools via winget (best-effort, never fatal) =====
# Linux install.sh ships mpv/vlc/ffmpeg/aria2/chafa ; Windows gets the same
# set here so playback, posters and downloads behave identically.
# Each install is independent: one failure never aborts the rest.
#
# mpv: prefer a REAL mpv.exe CLI build. mpv.net only ships mpvnet.exe (GUI
# wrapper) and is kept as a last resort because stdin playback / IPC flags
# used by FreeFlix are not guaranteed to work there.
if (Get-Command "winget" -ErrorAction SilentlyContinue) {
    $mediaPkgs = @(
        @{ Ids = @("shinchiro.mpv", "mpv-player.mpv-CI.MSVC", "mpv.net");
           Name = "mpv (player)" },
        @{ Ids = @("VideoLAN.VLC");     Name = "VLC (alt player)" },
        @{ Ids = @("Gyan.FFmpeg");      Name = "ffmpeg" },
        @{ Ids = @("aria2.aria2");      Name = "aria2c" },
        @{ Ids = @("hpjansson.Chafa");  Name = "chafa (posters)" }
    )
    foreach ($p in $mediaPkgs) {
        Log "Installing $($p.Name) ..."
        $done = $false
        foreach ($id in $p.Ids) {
            winget install --silent --accept-source-agreements --accept-package-agreements --id $id 2>$null
            if ($LASTEXITCODE -eq 0) { $done = $true; break }
        }
        if ($done) { Ok "$($p.Name) installed" }
        else { Log "$($p.Name) skipped (already present or unavailable)" }
    }
    # winget portable packages expose shims here; add it for this session and
    # for future ones (the user PATH update below handles the rest).
    $wingetLinks = "$env:LOCALAPPDATA\Microsoft\WinGet\Links"
    if (Test-Path $wingetLinks) {
        if (-not ($env:PATH -split ';' | Where-Object { $_ -eq $wingetLinks })) {
            $env:PATH = "$wingetLinks;$env:PATH"
        }
    }
} else {
    Log "winget not found - install mpv / VLC / ffmpeg manually if needed"
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
Log "Antivirus note: a 'Commando.*!ml' / 'Wacatac.*!ml' alert on this script"
Log "or on freeflix.exe is a known Defender ML false positive - see"
Log "docs/TROUBLESHOOTING.md (Windows / antivirus)."
Write-Host ""
