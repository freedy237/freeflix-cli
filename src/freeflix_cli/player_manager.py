import shutil
import platform
import os
import re
import subprocess
import sys
import json
import urllib.parse
import time
import webbrowser
from rich.progress import Progress, SpinnerColumn, TextColumn
from .cli_utils import (
    select_from_list,
    print_info,
    print_error,
    print_success,
    console,
)
from .scraping import player
from . import proxy
from typing import Dict, Any
from .tracker import tracker
from .i18n import t


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0"
)

# ─── Optimus / PRIME : detect dGPU and offload mpv onto it ──────────
# On hybrid Linux laptops (iGPU + dGPU), launching mpv with the right
# env vars routes rendering to the dedicated card :
#   - Nvidia : __NV_PRIME_RENDER_OFFLOAD + __GLX_VENDOR_LIBRARY_NAME
#   - AMD    : DRI_PRIME=1
# Both give 5-10× shader headroom for Anime4K. Results are cached for
# the process to avoid shelling out repeatedly.
_gpu_cache = {"nvidia": None, "amd": None}


def _has_nvidia_dgpu() -> bool:
    if _gpu_cache["nvidia"] is not None:
        return _gpu_cache["nvidia"]
    nv = shutil.which("nvidia-smi")
    if not nv:
        _gpu_cache["nvidia"] = False
        return False
    try:
        r = subprocess.run([nv, "-L"], capture_output=True, text=True, timeout=2)
        _gpu_cache["nvidia"] = r.returncode == 0 and "GPU" in r.stdout
    except Exception:
        _gpu_cache["nvidia"] = False
    return _gpu_cache["nvidia"]


def _has_amd_dgpu() -> bool:
    """
    True if lspci sees an AMD/ATI/Radeon graphics device. We don't
    distinguish iGPU vs dGPU here ; DRI_PRIME=1 on a system with
    only one AMD GPU is a no-op anyway.
    """
    if _gpu_cache["amd"] is not None:
        return _gpu_cache["amd"]
    if not sys.platform.startswith("linux"):
        _gpu_cache["amd"] = False
        return False
    if not shutil.which("lspci"):
        _gpu_cache["amd"] = False
        return False
    try:
        r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=2)
        out = (r.stdout or "").lower()
        _gpu_cache["amd"] = (
            r.returncode == 0
            and ("amd" in out or "ati " in out or "radeon" in out)
            and ("vga" in out or "3d controller" in out or "display" in out)
        )
    except Exception:
        _gpu_cache["amd"] = False
    return _gpu_cache["amd"]


def _gpu_offload_env(base_env=None) -> dict:
    """
    Return an env dict augmented with PRIME offload variables when the
    user setting is auto + a dGPU is detected (Nvidia preferred over AMD
    if both are present), or 'on'. PRIME is Linux-only ; on macOS and
    Windows the OS picks the GPU automatically and we return env as-is.
    """
    env = dict(base_env if base_env is not None else os.environ)
    if not sys.platform.startswith("linux"):
        return env

    setting = tracker.get_nvidia_offload()  # "auto" | "on" | "off"
    if setting == "off":
        return env

    # 'auto' / 'on' : prefer Nvidia (richer feature set), fall back to AMD
    if _has_nvidia_dgpu():
        env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
        env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
        env["__VK_LAYER_NV_optimus"] = "NVIDIA_only"
    elif _has_amd_dgpu():
        env["DRI_PRIME"] = "1"
    return env


# Backwards-compat alias — older code paths still call _nvidia_env().
_nvidia_env = _gpu_offload_env


def get_freeflix_mpv_config_dir() -> str:
    """
    Dedicated mpv config dir for FreeFlix, so our tuned config (Anime4K,
    big cache, position-resume hook) applies ONLY when mpv is launched by
    FreeFlix — never to the user's normal `mpv file.mkv` usage.

    Linux/macOS : ~/.config/freeflix/mpv
    Windows     : %APPDATA%/freeflix/mpv
    """
    if sys.platform in ("win32", "cygwin"):
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "freeflix", "mpv")
    return os.path.expanduser("~/.config/freeflix/mpv")


def _mpv_config_args() -> list:
    """Return ['--config-dir=...'] if the FreeFlix mpv config dir exists."""
    cfg = get_freeflix_mpv_config_dir()
    if os.path.isdir(cfg) and os.path.isfile(os.path.join(cfg, "mpv.conf")):
        return [f"--config-dir={cfg}"]
    return []


def _proxy_request_headers(url: str, player_config: dict, is_direct: bool,
                           headers: dict) -> dict:
    """
    Build the exact header set the proxy uses to fetch a stream from a
    given player host : the per-host Referer (most CDNs reject a fetch
    without their own embed domain as referer), plus Alt-Used and any
    sec_headers from the player config. Used by the quality/block probe
    so it sees the SAME thing the proxy will — otherwise hosts like
    embed4me / minochinos reject the probe (wrong referer) and the
    quality menu never appears for them.
    """
    out = dict(headers) if headers else {}
    # Referer (same logic as the proxy-mode block)
    if not is_direct:
        try:
            domain = url.split("/")[2].lower()
            referer = f"https://{domain}"
            rc = player_config.get("referrer")
            if rc == "full":
                referer = url
            elif rc == "path":
                referer = f"https://{domain}/"
            elif isinstance(rc, str):
                referer = rc
            referer = f"{referer}/"
        except IndexError:
            referer = ""
    else:
        referer = (headers or {}).get("Referer", "")
    if referer:
        out["Referer"] = referer

    if player_config.get("alt-used") is True:
        try:
            out["Alt-Used"] = url.split("/")[2].lower()
        except Exception:
            pass

    sec_headers = player_config.get("sec_headers")
    if isinstance(sec_headers, str):
        for part in sec_headers.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                out[k.strip()] = v.strip()
    return out


def _probe_stream(stream_url: str, headers: dict) -> dict:
    """
    One fetch of the resolved stream that serves two purposes :
      1. detect an upstream block (Cloudflare 403, etc.) so we can warn
         the user clearly instead of letting mpv fail cryptically ;
      2. parse HLS quality variants for the quality-selection menu.

    Returns {"variants": [...], "blocked": "cloudflare" | "httpNNN" | None}.
    Each variant : {"label","bandwidth","height","uri"}.
    """
    result = {"variants": [], "blocked": None}
    if not stream_url:
        return result
    # Skip obvious direct video files (no HLS master to parse). We do NOT
    # gate on ".m3u8" : some CDNs serve the master with a .txt / extension-
    # less / .urlset name (e.g. Smoothpre's '…/master.txt'), so we detect
    # HLS by content (#EXTM3U) instead.
    path_lower = stream_url.split("?")[0].lower()
    if path_lower.endswith((".mp4", ".mkv", ".avi", ".webm", ".mov")):
        return result
    try:
        import m3u8 as _m3u8
        from curl_cffi import requests as _rq

        sess = _rq.Session(impersonate="chrome")
        try:
            sess.curl_options.update(proxy.DNS_OPTIONS)
        except Exception:
            pass
        # Plain GET (HLS playlists — incl. .txt / .urlset masters — are
        # small text files ; we already skipped obvious direct video files
        # by extension above). A non-stream GET is reliable ; curl_cffi's
        # stream=True + early break can hang.
        r = sess.get(stream_url, headers=headers or {}, timeout=12)
        text = r.text or ""

        if r.status_code != 200:
            hl = text[:1500].lower()
            if r.status_code == 403 and (
                "cloudflare" in hl
                or "attention required" in hl
                or "cf-ray" in hl
                or "/cdn-cgi/" in hl
            ):
                result["blocked"] = "cloudflare"
            else:
                result["blocked"] = f"http{r.status_code}"
            return result

        if "#EXTM3U" not in text[:256]:
            return result  # not an HLS playlist (direct video, etc.)

        obj = _m3u8.loads(text, uri=stream_url)
        if not obj.playlists:
            return result  # media playlist → single quality, nothing to choose

        variants = []
        for p in obj.playlists:
            si = p.stream_info
            bw = si.bandwidth or 0
            res = si.resolution
            height = res[1] if res else None
            if height:
                label = f"{height}p"
            elif bw:
                label = f"{bw // 1000} kbps"
            else:
                label = "?"
            try:
                uri = p.absolute_uri
            except Exception:
                uri = p.uri
            variants.append({
                "label": label, "bandwidth": bw, "height": height, "uri": uri,
            })

        seen = {}
        for v in variants:
            key = v["label"]
            if key not in seen or v["bandwidth"] > seen[key]["bandwidth"]:
                seen[key] = v
        result["variants"] = sorted(
            seen.values(), key=lambda v: v["bandwidth"], reverse=True
        )
        return result
    except Exception:
        return result


def _prompt_hls_quality(variants: list):
    """
    Show a quality menu for a multi-variant HLS stream.
    Returns the chosen variant dict (with its 'uri'), or None for
    'Auto (best)' which keeps the original master playlist.
    """
    opts = []
    for v in variants:
        mbps = v["bandwidth"] / 1_000_000 if v["bandwidth"] else 0
        opts.append(f"{v['label']}  ({mbps:.1f} Mbps)" if mbps else v["label"])
    opts.append(t("Auto (best)"))
    idx = select_from_list(opts, t("📺 Choisis la qualité :"))
    if idx == len(variants):  # Auto
        return None
    return variants[idx]


PLAYERS: Dict[str, Dict[str, str]] = {
    "mpv": {"display": "mpv"},
    "vlc": {"display": "vlc"},
    "browser": {"display": "browser"},
    "download": {"display": "download"},
    "manual": {"display": "manual"},
}

DOWNLOAD_DIR = os.path.expanduser("~/Downloads/FreeFlix")


def get_player_display(code: str, default: str = "manual") -> str:

    return PLAYERS.get(code, {}).get("display", default)


def get_all_players():

    return [(code, f"{player['display']}") for code, player in PLAYERS.items()]


def get_vlc_path():
    """
    Find the VLC executable path.

    Returns:
        Path to VLC executable if found, None otherwise
    """
    # Check PATH first
    path = shutil.which("vlc")
    if path:
        return path

    if platform.system() == "Windows":
        # Check Registry
        try:
            import winreg

            for key_path in [
                r"SOFTWARE\VideoLAN\VLC",
                r"SOFTWARE\WOW6432Node\VideoLAN\VLC",
            ]:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                        install_dir = winreg.QueryValueEx(key, "InstallDir")[0]
                        exe_path = os.path.join(install_dir, "vlc.exe")
                        if os.path.exists(exe_path):
                            return exe_path
                except FileNotFoundError:
                    continue
        except Exception:
            pass

        # Check common paths
        common_paths = [
            os.path.expandvars(r"%ProgramFiles%\VideoLAN\VLC\vlc.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\VideoLAN\VLC\vlc.exe"),
        ]
        for p in common_paths:
            if os.path.exists(p):
                return p

    return None


def handle_player_error(context: str = "player") -> int:
    """
    Handle player errors and ask user what they want to do.

    Args:
        context: Context of the error (default: "player")

    Returns:
        User's choice index: 0 = try another, 1 = back
    """
    return select_from_list(
        ["Try another player", "← Back"],
        f"The {context} failed. What would you like to do?",
    )


def _sanitize_filename(name: str, max_len: int = 200) -> str:
    """Make a string safe to use as a filename across filesystems."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    if not cleaned:
        cleaned = "video"
    return cleaned[:max_len]


def _mpv_position_args(title: str):
    """
    Return extra CLI args for mpv to enable position tracking via the
    autoflix_position.lua script, plus the out-file path and key the
    Python side will read back after mpv exits.

    Returns (args_list, position_file_path, key) or ([], None, None)
    if no saved position needs restoring AND no key can be built.
    """
    import hashlib
    import tempfile
    import uuid

    if not title or title == "FreeFlix Stream":
        return [], None, None

    key = hashlib.md5(title.encode("utf-8")).hexdigest()
    out_path = os.path.join(
        tempfile.gettempdir(), f"freeflix-pos-{uuid.uuid4().hex}.txt"
    )

    args = [f"--script-opts=freeflix-key={key},freeflix-out={out_path}"]

    saved = tracker.get_episode_position(key)
    if saved and saved > 30:
        args.append(f"--start={saved:.2f}")
        print_info(f"Resuming at {int(saved // 60)}m{int(saved % 60):02d}s")

    return args, out_path, key


def _save_mpv_position(out_path: str, key: str, completion_threshold: float = 0.95):
    """
    Read the position file written by autoflix_position.lua and update
    tracker. If the episode was watched past `completion_threshold` of
    its duration, clear the saved position (treated as fully watched).
    """
    if not out_path or not key or not os.path.exists(out_path):
        return

    pos = None
    dur = None
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("pos="):
                    try:
                        pos = float(line[4:])
                    except ValueError:
                        pass
                elif line.startswith("dur="):
                    try:
                        dur = float(line[4:])
                    except ValueError:
                        pass
    except OSError:
        pass
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass

    if pos is None:
        return

    if dur and dur > 0 and (pos / dur) >= completion_threshold:
        tracker.clear_episode_position(key)
    elif pos > 30:
        tracker.set_episode_position(key, pos)


def _download_stream(
    stream_url: str,
    referer: str,
    user_agent: str,
    title: str,
    is_mp4: bool = False,
    local_subtitle_path: str = None,
) -> bool:
    """
    Download a resolved stream to ~/Downloads/FreeFlix/.

    Routing:
      - HLS (.m3u8)     -> yt-dlp (handles segments via ffmpeg)
      - Direct mp4      -> aria2c (multi-connection, resumable)
                           falls back to yt-dlp if aria2c is missing.

    Subtitles, if previously downloaded, are copied next to the video.
    """
    safe_title = _sanitize_filename(title)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    url_lower = stream_url.lower()
    is_hls = ".m3u8" in url_lower or (not is_mp4 and ".mp4" not in url_lower)

    backend_name = None
    cmd = None

    quality = tracker.get_download_quality()
    format_arg = None
    if quality in ("1080", "720", "480"):
        format_arg = (
            f"bv*[height<={quality}]+ba/b[height<={quality}]/bv*+ba/b"
        )

    if is_hls:
        ytdlp = shutil.which("yt-dlp")
        if not ytdlp:
            print_error(
                "yt-dlp is required for HLS streams but is not installed. "
                "Install with: sudo dnf install yt-dlp"
            )
            return False
        backend_name = "yt-dlp"
        cmd = [
            ytdlp,
            "--no-warnings",
            "--no-overwrites",
            "--add-header", f"Referer:{referer}",
            "--add-header", f"User-Agent:{user_agent}",
            "--merge-output-format", "mp4",
            "-o", os.path.join(DOWNLOAD_DIR, f"{safe_title}.%(ext)s"),
        ]
        if format_arg:
            cmd.extend(["-f", format_arg])
        cmd.append(stream_url)
    else:
        aria = shutil.which("aria2c")
        if aria:
            backend_name = "aria2c"
            cmd = [
                aria,
                "--continue=true",
                "--max-connection-per-server=16",
                "--split=16",
                "--min-split-size=1M",
                "--auto-file-renaming=true",
                "--summary-interval=1",
                "--console-log-level=warn",
                f"--header=Referer: {referer}",
                f"--header=User-Agent: {user_agent}",
                f"--dir={DOWNLOAD_DIR}",
                f"--out={safe_title}.mp4",
                stream_url,
            ]
        else:
            print_info("aria2c not found, falling back to yt-dlp.")
            ytdlp = shutil.which("yt-dlp")
            if not ytdlp:
                print_error(
                    "Neither aria2c nor yt-dlp is installed. "
                    "Install with: sudo dnf install aria2 yt-dlp"
                )
                return False
            backend_name = "yt-dlp"
            cmd = [
                ytdlp,
                "--no-warnings",
                "--no-overwrites",
                "--add-header", f"Referer:{referer}",
                "--add-header", f"User-Agent:{user_agent}",
                "-o", os.path.join(DOWNLOAD_DIR, f"{safe_title}.%(ext)s"),
            ]
            if format_arg:
                cmd.extend(["-f", format_arg])
            cmd.append(stream_url)

    print_info(
        f"Downloading [bold cyan]{safe_title}[/bold cyan] via "
        f"[bold cyan]{backend_name}[/bold cyan]"
    )
    print_info(f"Output: [cyan]{DOWNLOAD_DIR}[/cyan]")

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print_error(f"Download failed (exit code {e.returncode}).")
        return False
    except KeyboardInterrupt:
        print_info("\nDownload interrupted by user.")
        return False
    except Exception as e:
        print_error(f"Download error: {e}")
        return False

    if local_subtitle_path and os.path.exists(local_subtitle_path):
        sub_ext = os.path.splitext(local_subtitle_path)[1] or ".srt"
        final_sub = os.path.join(DOWNLOAD_DIR, f"{safe_title}{sub_ext}")
        try:
            shutil.copy2(local_subtitle_path, final_sub)
            print_success(f"Subtitle saved: {final_sub}")
        except Exception as e:
            print_info(f"Could not save subtitle next to video: {e}")

    print_success(f"Download completed in {DOWNLOAD_DIR}")
    return True


def play_video(
    url: str,
    headers: dict,
    title: str = "FreeFlix Stream",
    subtitle_url: str = None,
    is_direct: bool = False,
    is_mp4: bool = False,
    force_player: str = None,
) -> bool:
    """
    Attempt to play a video with the chosen player.

    Args:
        url: Video player URL
        headers: HTTP headers for the request
        title: Title of the video to display in the player

    Returns:
        True if playback succeeded, False otherwise
    """

    if hasattr(player, "new_url") and isinstance(player.new_url, dict):
        for old, new in player.new_url.items():
            url = url.replace(old, new)

    print_info(f"Resolving stream for: [cyan]{url}[/cyan]")

    # Determine player configuration
    player_config = {}
    for player_name, config in player.players.items():
        if player_name in url.lower():
            player_config = config
            break

    if is_direct:
        stream_url = url
    else:
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task(description="Getting stream URL...", total=None)
                stream_url = player.get_hls_link(url, headers)
                if stream_url and stream_url.startswith("/"):
                    stream_url = (
                        "https://"
                        + url.removeprefix("https://")
                        .removeprefix("http://")
                        .split("/")[0]
                        + stream_url
                    )
        except Exception as e:
            print_error(f"Error resolving stream URL: {e}")
            return False

    if not stream_url:
        print_error("Could not resolve stream URL.")
        return False

    print_success(f"Stream URL: [cyan]{stream_url}[/cyan]")

    local_subtitle_path = subtitle_url
    if subtitle_url and subtitle_url.startswith("http"):
        print_info("Downloading subtitle file for compatibility...")
        try:
            from curl_cffi import requests
            import tempfile

            r = requests.get(subtitle_url, timeout=10, impersonate="chrome")
            sub_ext = ".vtt" if "vtt" in subtitle_url.lower() else ".srt"
            fd, temp_sub = tempfile.mkstemp(suffix=sub_ext, prefix="freeflix_sub_")
            with os.fdopen(fd, "wb") as f:
                f.write(r.content)
            local_subtitle_path = temp_sub
            print_success("Subtitles downloaded locally.")
        except Exception as e:
            print_error(f"Failed to download subtitles: {e}")

    # Fallback: if no subtitle and the user has configured an OpenSubtitles key,
    # try to fetch one automatically by title.
    if not local_subtitle_path and tracker.get_opensubtitles_key():
        try:
            from . import subtitles as os_subs
            user_lang = tracker.get_language() or "en"
            print_info("No source subtitles; trying OpenSubtitles fallback…")
            fetched = os_subs.fetch_best_subtitle(title, languages=user_lang)
            if fetched:
                local_subtitle_path = fetched
                print_success(f"OpenSubtitles match downloaded: {fetched}")
            else:
                print_info("No OpenSubtitles match found.")
        except Exception as e:
            print_info(f"OpenSubtitles lookup skipped: {e}")

    # Quality selection : if the resolved stream is a multi-variant HLS
    # master (e.g. vidmoly's 1080p+480p), let the user pick a quality.
    # We swap stream_url to the chosen variant's own playlist URL, so the
    # selection works for EVERY player (mpv, vlc, download) — not just
    # mpv's --hls-bitrate. 'Auto (best)' keeps the master untouched.
    # Skipped for non-interactive callers (batch download).
    if not force_player:
        try:
            probe_headers = _proxy_request_headers(
                url, player_config, is_direct, headers
            )
            probe = _probe_stream(stream_url, probe_headers)
            if probe.get("blocked") == "cloudflare":
                print_error(t(
                    "This source is Cloudflare-protected and can't be played "
                    "from the terminal."
                ))
                print_info(t(
                    "→ Pick ANOTHER source from the list (e.g. Vidlink, another "
                    "server), or try again later."
                ))
                return False
            _variants = probe.get("variants", [])
            if len(_variants) > 1:
                chosen = _prompt_hls_quality(_variants)
                if chosen and chosen.get("uri"):
                    stream_url = chosen["uri"]
                    print_info(f"Quality: [cyan]{chosen['label']}[/cyan]")
        except Exception:
            pass

    force_manual_mode = False
    while True:  # Loop to allow retrying with another player
        if force_player:
            # Caller-imposed choice (e.g. batch download). No prompts, no fallbacks.
            player_name = force_player
            player_executable = None
        else:
            player_pref = tracker.get_player()
            if force_manual_mode or not player_pref or player_pref == "manual":
                players = ["mpv", "vlc", "browser", "download", t("← Back")]
                player_choice = select_from_list(players, t("🎮 Select video player:"))

                if players[player_choice] == t("← Back"):
                    return False

                player_name = players[player_choice]
                player_executable = None
            else:
                player_name = player_pref
                player_executable = None

        # --- 1. Preparation of Headers & Referer for both players ---
        # Calculate Referer
        if not is_direct:
            try:
                domain = url.split("/")[2].lower()
                referer = f"https://{domain}"
                if player_config.get("referrer") == "full":
                    referer = url
                elif player_config.get("referrer") == "path":
                    referer = f"https://{domain}/"
                elif isinstance(player_config.get("referrer"), str):
                    referer = player_config.get("referrer")

                referer = f"{referer}/"
            except IndexError:
                referer = ""
        else:
            referer = headers.get("Referer", "")

        user_agent = headers.get("User-Agent", DEFAULT_USER_AGENT)

        if player_name in ("browser", "download"):
            pass  # No specific executable needed at this stage
        elif player_name == "vlc":
            player_executable = get_vlc_path()
            if not player_executable:
                print_error("VLC not found. Please install it or add it to your PATH.")
                retry = handle_player_error("VLC")
                if retry == 1:  # Back
                    return False
                force_manual_mode = True
                continue
        else:
            player_executable = shutil.which(player_name)
            if not player_executable:
                print_error(f"{player_name} is not installed or not in PATH.")
                retry = handle_player_error(player_name)
                if retry == 1:  # Back
                    return False
                force_manual_mode = True
                continue

        if player_name == "download":
            success = _download_stream(
                stream_url=stream_url,
                referer=referer,
                user_agent=user_agent,
                title=title,
                is_mp4=is_mp4,
                local_subtitle_path=local_subtitle_path,
            )
            if success:
                return True
            if force_player:
                # Non-interactive caller (batch). Just report failure.
                return False
            retry = select_from_list(
                [
                    t("Try another player/backend"),
                    t("Retry download"),
                    t("← Back"),
                ],
                t("The download failed. What would you like to do?"),
            )
            if retry == 0:
                force_manual_mode = True
                continue
            elif retry == 1:
                continue
            else:
                return False

        if player_name == "browser":
            print_info(f"Launching [bold cyan]Browser[/bold cyan] Player...")

            # Construct Proxy URL
            proxy_headers = headers.copy()
            if referer:
                proxy_headers["Referer"] = referer

            if player_config.get("alt-used") is True:
                proxy_headers["Alt-Used"] = domain

            sec_headers = player_config.get("sec_headers")
            if sec_headers:
                if isinstance(sec_headers, str):
                    for part in sec_headers.split(";"):
                        if ":" in part:
                            k, v = part.split(":", 1)
                            proxy_headers[k.strip()] = v.strip()

            headers_json = json.dumps(proxy_headers)
            encoded_url = urllib.parse.quote(stream_url)
            encoded_headers = urllib.parse.quote(headers_json)

            if not proxy.PROXY_URL:
                print_error("Proxy server not initialized.")
                return False

            endpoint = "stream"
            if ("ext" in player_config and player_config["ext"] == "mp4") or is_mp4:
                endpoint = "video"

            local_stream_url = f"{proxy.PROXY_URL}/{endpoint}?url={encoded_url}&headers={encoded_headers}"

            encoded_local_stream_url = urllib.parse.quote(local_stream_url)
            browser_player_url = (
                f"{proxy.PROXY_URL}/player?url={encoded_local_stream_url}"
            )

            if local_subtitle_path:
                abs_sub_path = os.path.abspath(local_subtitle_path)
                encoded_sub = urllib.parse.quote(abs_sub_path)
                browser_player_url += f"&sub_path={encoded_sub}"

            # Reset heartbeat and event
            proxy.player_finished_event.clear()
            proxy.player_heartbeat_time = time.time()

            webbrowser.open(browser_player_url)
            print_info(
                "Waiting for playback to finish in browser... (Close the tab to continue)"
            )

            try:
                # Polling loop
                while True:
                    time.sleep(1)
                    if proxy.player_finished_event.is_set():
                        print_success(
                            "Playback finished (end of video or manually marked)."
                        )
                        return True

                    # Check heartbeat timeout (e.g., > 6 seconds without heartbeat)
                    if time.time() - proxy.player_heartbeat_time > 6.0:
                        print_success("Browser tab closed or playback stopped.")
                        return True
            except KeyboardInterrupt:
                print_info("\nPlayback interrupted by user.")
                return True
            except Exception as e:
                print_error(f"Error monitoring browser player: {e}")
                return False

        # Determine Launch Mode from config
        mode = player_config.get("mode", "proxy")  # Default to proxy

        if mode == "proxy":
            print_info(
                f"Launching [bold cyan]{player_name}[/bold cyan] via Proxy ({player_executable})..."
            )

            # Construct Proxy URL
            # We need to pass the headers to the proxy
            # Combine all necessary headers
            proxy_headers = headers.copy()
            if referer:
                proxy_headers["Referer"] = referer

            # Add specific headers from config
            if player_config.get("alt-used") is True:
                proxy_headers["Alt-Used"] = domain

            sec_headers = player_config.get("sec_headers")
            if sec_headers:
                # Parse sec_headers string if needed, or just add them
                if isinstance(sec_headers, str):
                    for part in sec_headers.split(";"):
                        if ":" in part:
                            k, v = part.split(":", 1)
                            proxy_headers[k.strip()] = v.strip()

            headers_json = json.dumps(proxy_headers)
            encoded_url = urllib.parse.quote(stream_url)
            encoded_headers = urllib.parse.quote(headers_json)

            if not proxy.PROXY_URL:
                print_error("Proxy server not initialized.")
                return False

            endpoint = "stream"
            if ("ext" in player_config and player_config["ext"] == "mp4") or is_mp4:
                endpoint = "video"

            local_stream_url = f"{proxy.PROXY_URL}/{endpoint}?url={encoded_url}&headers={encoded_headers}"

            try:
                cmd = [player_executable, local_stream_url]
                if player_name == "vlc":
                    if local_subtitle_path:
                        print_warning(
                            "Note: VLC natively struggles to sync external subtitles on HLS/M3U8 streams (subtitles may flash). Strongly recommend using MPV instead."
                        )
                    cmd.append(f"--meta-title={title}")
                    if local_subtitle_path:
                        cmd.append(f"--sub-file={local_subtitle_path}")
                elif player_name == "mpv":
                    cmd.extend(_mpv_config_args())  # FreeFlix-only mpv config
                    cmd.append(f"--title={title}")
                    if local_subtitle_path:
                        cmd.append(f"--sub-files={local_subtitle_path}")

                pos_args, pos_file, pos_key = ([], None, None)
                if player_name == "mpv":
                    pos_args, pos_file, pos_key = _mpv_position_args(title)
                    cmd.extend(pos_args)

                run_env = _nvidia_env() if player_name == "mpv" else None
                subprocess.run(cmd, check=True, env=run_env)
                if player_name == "mpv":
                    _save_mpv_position(pos_file, pos_key)
                print_success("Playback completed successfully!")
                return True
            except Exception as e:
                print_error(f"Error running player via proxy: {e}")

        elif mode == "direct":
            print_info(
                f"Launching [bold cyan]{player_name}[/bold cyan] directly ({player_executable})..."
            )
            try:
                if player_name == "vlc":
                    # VLC Command construction
                    cmd = [
                        player_executable,
                        stream_url,
                        f":http-referrer={referer}",
                        f":http-user-agent={user_agent}",
                        f"--meta-title={title}",
                    ]
                    if local_subtitle_path:
                        print_warning(
                            "Note: VLC natively struggles to sync external subtitles on HLS/M3U8 streams (subtitles may flash). Strongly recommend using MPV instead."
                        )
                        cmd.append(f"--sub-file={local_subtitle_path}")
                    subprocess.run(cmd, check=True)
                else:
                    # MPV Command construction
                    headers_mpv = f"Origin: {referer.split('/')[2]}"
                    add_default_sec_headers = False

                    if player_config.get("alt-used") is True:
                        headers_mpv = f"Alt-Used: {domain};" + headers_mpv

                    sec_headers = player_config.get("sec_headers")
                    if sec_headers:
                        if isinstance(sec_headers, str):
                            headers_mpv += ";" + sec_headers
                        elif isinstance(sec_headers, bool) and sec_headers is True:
                            add_default_sec_headers = True
                    else:
                        add_default_sec_headers = True

                    if add_default_sec_headers:
                        headers_mpv += ";Sec-Fetch-Dest: iframe;Sec-Fetch-Mode: navigate;Sec-Fetch-Site: same-origin"

                    if player_config.get("no-header") is True:
                        headers_mpv = ""

                    print_info(f"Headers: {headers_mpv}")

                    cmd = [
                        player_executable,
                        *_mpv_config_args(),  # FreeFlix-only mpv config
                        f'--referrer="{referer}"',
                        f'--user-agent="{user_agent}"',
                        f'--http-header-fields="{headers_mpv}"',
                        f'--title="{title}"',
                    ]
                    if local_subtitle_path:
                        cmd.append(f"--sub-files={local_subtitle_path}")
                    pos_args_d, pos_file_d, pos_key_d = _mpv_position_args(title)
                    cmd.extend(pos_args_d)
                    cmd.append(stream_url)
                    subprocess.run(cmd, check=True, env=_nvidia_env())
                    _save_mpv_position(pos_file_d, pos_key_d)

                print_success("Playback completed successfully!")
                return True

            except subprocess.CalledProcessError as e:
                print_error(f"Error running player: {e}")
                # Retry logic below
            except Exception as e:
                print_error(f"An unexpected error occurred: {e}")
                # Retry logic below

        # Common retry logic
        if force_player:
            # Non-interactive caller (batch). Don't prompt; just bail.
            return False
        retry = select_from_list(
            [
                t("Try another player"),
                t("Retry with same player"),
                t("← Back"),
            ],
            t("The player failed. What would you like to do?"),
        )
        if retry == 0:  # Try another player
            continue
        elif retry == 1:  # Retry with same player
            continue
        else:  # Back
            force_manual_mode = True
            return False


def select_and_play_player(
    supported_players: list, referer: str, title: str, subtitle_url: str = None
) -> bool:
    """
    Let user select a player and attempt playback with retry logic.

    Args:
        supported_players: List of supported player objects
        referer: HTTP Referer header value
        title: Title of the video

    Returns:
        True if playback succeeded, False otherwise
    """
    while True:
        player_idx = select_from_list(
            [p.name for p in supported_players] + [t("← Back")], t("🎮 Select Player:")
        )

        if player_idx == len(supported_players):  # Back
            return False

        success = play_video(
            supported_players[player_idx].url,
            headers={"Referer": referer},
            title=title,
            subtitle_url=subtitle_url,
        )

        if success:
            return True
        else:
            # Playback failed, ask if they want to retry
            retry = select_from_list(
                ["Try another server/player", "← Back to main menu"],
                "What would you like to do?",
            )
            if retry == 1:  # Back
                return False

            # Otherwise continue the loop to choose another player
