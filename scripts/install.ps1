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
#
# Re-runnable by design: already-installed tools are detected and skipped, so
# a second run does not re-download and reinstall everything.

$ErrorActionPreference = "Stop"
# PS 7.3+: a native command writing to stderr must NOT become a terminating
# error (winget/uv write progress there). On 5.1 the variable is harmless and
# Invoke-Native below provides the same protection.
$PSNativeCommandUseErrorActionPreference = $false

function Log($m)  { Write-Host "[*]  $m" -ForegroundColor Blue }
function Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[!]  $m" -ForegroundColor Yellow }
function Err($m)  { Write-Host "[X]  $m" -ForegroundColor Red }

# Run a native command without letting its stderr trip $ErrorActionPreference
# (Windows PowerShell 5.1 turns native stderr into a terminating error under
# "Stop" - the cause of the old installer aborting mid-run during winget).
function Invoke-Native {
    param([scriptblock]$Action)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Action 2>&1 | Out-String
        return @{ Code = $LASTEXITCODE; Output = $output }
    } finally {
        $ErrorActionPreference = $prev
    }
}

try { chcp 65001 > $null } catch {}
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { $ProgressPreference = "SilentlyContinue" } catch {}
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
$wingetLinks = "$env:LOCALAPPDATA\Microsoft\WinGet\Links"

# winget portable packages expose their shims here; put it on PATH for this
# session so a player installed on a previous run is FOUND instead of being
# reinstalled (and reported as failing) on every run.
function Add-WingetLinks {
    if ((Test-Path $wingetLinks) -and
        -not (($env:PATH -split ';') -contains $wingetLinks)) {
        $env:PATH = "$wingetLinks;$env:PATH"
    }
}
function Refresh-PathFromRegistry {
    try {
        $machine = [Environment]::GetEnvironmentVariable("PATH", "Machine")
        $user = [Environment]::GetEnvironmentVariable("PATH", "User")
        $env:PATH = "$localBin;$wingetLinks;$machine;$user"
    } catch {}
}
Add-WingetLinks

# Already installed? Check PATH (Get-Command) AND well-known install locations.
function Test-Tool {
    param([string[]]$Names, [string[]]$Paths = @())
    Add-WingetLinks
    foreach ($n in $Names) {
        if (Get-Command $n -ErrorAction SilentlyContinue) { return $true }
    }
    foreach ($p in $Paths) {
        if ($p -and (Test-Path $p)) { return $true }
    }
    return $false
}

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
    $r = Invoke-Native { winget install --silent --accept-source-agreements --accept-package-agreements --id Python.Python.3.12 }
    if ($r.Code -eq 0) { Ok "Python installed" } else { Warn "Python install returned $($r.Code) - uv will fetch its own Python if needed." }
    # Refresh PATH from the registry (and the default per-user install dirs).
    Refresh-PathFromRegistry
    $env:PATH = $env:PATH + ";" +
                "$env:USERPROFILE\AppData\Local\Programs\Python\Python312\Scripts;" +
                "$env:USERPROFILE\AppData\Local\Programs\Python\Python312"
    $havePy = (Get-Command "python3" -ErrorAction SilentlyContinue) -or
              (Get-Command "python" -ErrorAction SilentlyContinue)
    if ($havePy) { Ok "Python ready" } else { Warn "Python not detected yet - uv will download one." }
}

# ===== 3. Install/upgrade freeflix-cli + yt-dlp via uv =====
# No --force: if the tool is already installed we run `uv tool upgrade`
# instead, which only downloads when a newer release exists. `--force` on
# every run was re-downloading both tools for nothing.
$uvList = (Invoke-Native { uv tool list }).Output
$ffInstalled = $uvList -match '(?m)^freeflix-cli\s'
if ($ffInstalled) {
    Log "Upgrading freeflix-cli (only downloads when a newer version exists) ..."
    $r = Invoke-Native { uv tool upgrade freeflix-cli }
    if ($r.Code -ne 0) {
        Warn "Could not upgrade (offline?) - keeping the installed version."
    }
    Ok "freeflix-cli ready"
} else {
    Log "Installing freeflix-cli ..."
    # Pin a stable, well-tested CPython 3.12 (the code supports 3.9+, but
    # pinning avoids landing on the system's old/bleeding-edge Python).
    $r = Invoke-Native { uv tool install freeflix-cli --python 3.12 }
    if ($r.Code -ne 0) {
        Write-Host "       (retrying without Python pin)..."
        $r = Invoke-Native { uv tool install freeflix-cli }
    }
    if ($r.Code -ne 0) {
        Err "freeflix-cli install failed (exit $($r.Code))"
        exit 1
    }
    Ok "freeflix-cli installed"
}

if (Test-Tool @("yt-dlp")) {
    Log "Upgrading yt-dlp (only downloads when a newer version exists) ..."
    $r = Invoke-Native { uv tool upgrade yt-dlp }
    if ($r.Code -ne 0) { Warn "Could not upgrade yt-dlp (offline?) - keeping the installed version." }
    Ok "yt-dlp ready"
} else {
    Log "Installing yt-dlp ..."
    $r = Invoke-Native { uv tool install yt-dlp }
    if ($r.Code -ne 0) {
        Err "yt-dlp install failed (exit $($r.Code))"
        exit 1
    }
    Ok "yt-dlp installed"
}

# ===== 3b. Media tools via winget (best-effort, never fatal) =====
# Linux install.sh ships mpv/vlc/ffmpeg/aria2/chafa ; Windows gets the same
# set here so playback, posters and downloads behave identically.
# Each install is independent: one failure never aborts the rest, and an
# already-present tool is never reinstalled.
if (Get-Command "winget" -ErrorAction SilentlyContinue) {
    $mediaPkgs = @(
        @{ Ids = @("shinchiro.mpv", "mpv-player.mpv-CI.MSVC", "mpv.net");
           Name = "mpv (player)";
           Cmds = @("mpv", "mpvnet");
           Paths = @("$wingetLinks\mpv.exe", "$env:ProgramFiles\mpv\mpv.exe",
                     "$env:LOCALAPPDATA\Programs\mpv\mpv.exe",
                     "$env:LOCALAPPDATA\Microsoft\WinGet\Links\mpvnet.exe") },
        @{ Ids = @("VideoLAN.VLC");     Name = "VLC (alt player)";
           Cmds = @("vlc");
           Paths = @("$env:ProgramFiles\VideoLAN\VLC\vlc.exe",
                     "$env:ProgramFiles (x86)\VideoLAN\VLC\vlc.exe") },
        @{ Ids = @("Gyan.FFmpeg");      Name = "ffmpeg";
           Cmds = @("ffmpeg"); Paths = @("$wingetLinks\ffmpeg.exe") },
        @{ Ids = @("aria2.aria2");      Name = "aria2c";
           Cmds = @("aria2c"); Paths = @("$wingetLinks\aria2c.exe") },
        @{ Ids = @("hpjansson.Chafa");  Name = "chafa (posters)";
           Cmds = @("chafa"); Paths = @("$wingetLinks\chafa.exe") }
    )
    foreach ($p in $mediaPkgs) {
        if (Test-Tool -Names $p.Cmds -Paths $p.Paths) {
            Ok "$($p.Name) already installed"
            continue
        }
        Log "Installing $($p.Name) ..."
        $done = $false
        foreach ($id in $p.Ids) {
            $r = Invoke-Native { winget install --silent --accept-source-agreements --accept-package-agreements --id $id }
            Add-WingetLinks
            if (($r.Code -eq 0) -or (Test-Tool -Names $p.Cmds -Paths $p.Paths)) {
                $done = $true
                break
            }
        }
        if ($done) { Ok "$($p.Name) installed" }
        elseif (Test-Tool -Names $p.Cmds -Paths $p.Paths) { Ok "$($p.Name) already present" }
        else { Warn "$($p.Name) skipped (not available via winget - install manually if needed)" }
    }
    Refresh-PathFromRegistry
} else {
    Log "winget not found - install mpv / VLC / ffmpeg manually if needed"
}

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
