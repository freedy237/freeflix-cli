from __future__ import annotations

import shutil
import platform
import os
import re
import subprocess
import tempfile
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
    print_warning,
    console,
    _suppress_print,
)
from .scraping import player
from . import proxy
from typing import Dict
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

    origin_base = referer or out.get("Referer", "")
    if origin_base and "Origin" not in out:
        out["Origin"] = "/".join(origin_base.split("/")[:3])

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


def _probe_stream(stream_url: str, headers: dict,
                  session=None) -> dict:
    """
    One fetch of the resolved stream that serves two purposes :
      1. detect an upstream block (Cloudflare 403, etc.) so we can warn
         the user clearly instead of letting mpv fail cryptically ;
      2. parse HLS quality variants for the quality-selection menu.

    If *session* is provided (a curl_cffi Session), it is used instead of
    creating a new one — needed when a CDN expects cookies or TLS state
    from the extractor session (e.g. ``cdn.montmyoboku.net``).

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

        if session is None:
            sess = _rq.Session(impersonate="chrome")
            try:
                sess.curl_options.update(proxy.DNS_OPTIONS)
            except Exception:
                pass
        else:
            sess = session
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


def _ffprobe_quality(url: str, headers: dict, timeout: int = 12):
    """
    Fallback for single-quality / non-master streams (media playlist or
    direct mp4) : use ffprobe to read the actual resolution + bitrate.
    Returns {"height":h, "mbps":m} or None.
    """
    ff = shutil.which("ffprobe")
    if not ff:
        return None
    hdr = ""
    referer = headers.get("Referer", "")
    if referer:
        hdr += f"Referer: {referer}\r\n"
        origin = "/".join(referer.split("/")[:3])
        hdr += f"Origin: {origin}\r\n"
    ua = headers.get("User-Agent") or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    hdr += f"User-Agent: {ua}\r\n"
    cmd = [ff, "-v", "quiet", "-print_format", "json",
           "-show_entries", "stream=width,height,bit_rate:format=bit_rate"]
    if hdr:
        cmd += ["-headers", hdr]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        data = json.loads(r.stdout or "{}")
    except Exception:
        return None
    height, bitrate = None, 0
    for s in data.get("streams", []):
        if s.get("height"):
            height = s["height"]
            try:
                bitrate = int(s.get("bit_rate") or 0)
            except (TypeError, ValueError):
                bitrate = 0
            break
    if not bitrate:
        try:
            bitrate = int((data.get("format") or {}).get("bit_rate") or 0)
        except (TypeError, ValueError):
            bitrate = 0
    if height:
        return {"height": height, "mbps": round(bitrate / 1_000_000, 1) if bitrate else 0}
    return None


def analyze_stream_quality(url: str, headers: dict = None, timeout: int = 9) -> dict:
    """
    Resolve a player URL and probe its HLS master, to know — BEFORE playing —
    which resolutions it offers and the bitrate needed for stable playback.

    Returns {"ok": bool, "qualities": [{"height":1080,"mbps":5.0}, …],
             "blocked": bool}. Each quality carries ITS OWN minimum bitrate
             (the HLS variant bandwidth), never a sum. Network-bound : meant
             to be run in a thread pool.
    """
    out = {"ok": False, "qualities": [], "blocked": False}
    headers = headers or {}
    try:
        u = url
        if hasattr(player, "new_url") and isinstance(player.new_url, dict):
            for old, new in player.new_url.items():
                u = u.replace(old, new)

        player_config = {}
        for pname, cfg in player.players.items():
            if pname in u.lower():
                player_config = cfg
                break

        # GoldenAnime & co pass DIRECT stream URLs (m3u8/mp4), not player
        # embeds — use them as-is. Detect by the URL shape (a resolved
        # stream URL may itself contain a player name, so is_supported is not
        # reliable here ; player embeds are /embed-…html, /e/… etc.).
        low = u.split("?")[0].lower()
        is_direct_stream = (
            low.endswith((".m3u8", ".mp4", ".mkv", ".txt"))
            or ".m3u8" in low
            or "master" in low
            or "/api/streams" in low
        )
        if is_direct_stream:
            stream_url = u
            probe_headers = headers
        else:
            stream_url = player.get_hls_link(u, headers)
            if stream_url and stream_url.startswith("/"):
                stream_url = "https://" + u.split("/")[2] + stream_url
            if not stream_url:
                return out
            probe_headers = _proxy_request_headers(u, player_config, False, headers)
        probe = _probe_stream(stream_url, probe_headers)
        blocked = probe.get("blocked")
        if blocked == "cloudflare":
            out["blocked"] = True
            return out

        variants = probe.get("variants", [])
        # One bitrate PER resolution (variants are already de-duped per
        # resolution by _probe_stream). Each variant's bandwidth is the
        # minimum link speed to play THAT quality — never summed.
        best = {}
        for v in variants:
            h, bw = v.get("height"), v.get("bandwidth") or 0
            if h and (h not in best or bw > best[h]):
                best[h] = bw
        out["qualities"] = [
            {"height": h, "mbps": round(best[h] / 1_000_000, 1)}
            for h in sorted(best, reverse=True)
        ]
        # Single-quality / direct stream (no HLS master variants) : ask
        # ffprobe for the real resolution + bitrate. Skip it when the master
        # was access-blocked (e.g. vidmoly's CDN 403 anti-leech) — ffprobe
        # would 403 too, so don't burn the timeout.
        if not out["qualities"] and not blocked:
            q = _ffprobe_quality(stream_url, probe_headers, timeout=12)
            if q:
                out["qualities"] = [q]
        # Keep what's needed to estimate episode duration later (one media
        # playlist holds the same EXTINF total for every variant), so the
        # batch-download menu can show an approximate size per episode without
        # re-resolving the player.
        out["stream_url"] = stream_url
        out["probe_headers"] = probe_headers
        if variants:
            out["variant_uri"] = variants[0].get("uri")
        out["ok"] = True
    except Exception:
        return out
    return out


def estimate_episode_seconds(info: dict) -> float | None:
    """
    Best-effort episode duration (seconds) from an HLS media playlist : sum its
    ``#EXTINF`` segment durations. One small text fetch, no ffprobe. Returns
    None for direct (non-HLS) files or on any failure.
    """
    if not info:
        return None
    media_url = info.get("variant_uri") or info.get("stream_url")
    if not media_url:
        return None
    low = media_url.split("?")[0].lower()
    if low.endswith((".mp4", ".mkv", ".avi", ".webm", ".mov")):
        return None  # would need ffprobe; not worth it for a size estimate
    try:
        from curl_cffi import requests as _rq
        import m3u8 as _m3u8

        sess = _rq.Session(impersonate="chrome")
        try:
            sess.curl_options.update(proxy.DNS_OPTIONS)
        except Exception:
            pass
        headers = info.get("probe_headers") or {}
        text = sess.get(media_url, headers=headers, timeout=10).text or ""
        # If we landed on a master, descend into its first media playlist.
        if "#EXT-X-STREAM-INF" in text:
            obj = _m3u8.loads(text, uri=media_url)
            if obj.playlists:
                media_url = obj.playlists[0].absolute_uri
                text = sess.get(media_url, headers=headers, timeout=10).text or ""
        total = 0.0
        for line in text.splitlines():
            if line.startswith("#EXTINF:"):
                try:
                    total += float(line[8:].split(",", 1)[0])
                except ValueError:
                    pass
        return total or None
    except Exception:
        return None


def format_quality_label(info: dict) -> str:
    """
    Each quality with ITS OWN minimum bitrate, e.g.
    '1080p ~5.0 · 720p ~2.5 · 480p ~0.8 Mbps'. Not a sum.
    '✗' = unresolved, '🔒' = Cloudflare, 'direct' = single/non-HLS.
    """
    if not info or not info.get("ok"):
        return "✗" if not (info or {}).get("blocked") else "🔒"
    qs = info.get("qualities") or []
    if not qs:
        return "✓"  # resolves, but resolution/bitrate couldn't be read
    any_mbps = any(q.get("mbps") for q in qs)
    parts = [
        f"{q['height']}p ~{q['mbps']:.1f}" if q.get("mbps") else f"{q['height']}p"
        for q in qs[:4]
    ]
    return " · ".join(parts) + (" Mbps" if any_mbps else "")


PLAYERS: Dict[str, Dict[str, str]] = {
    "mpv": {"display": "mpv"},
    "vlc": {"display": "vlc"},
    "browser": {"display": "browser"},
    "download": {"display": "download"},
    "manual": {"display": "manual"},
}

DOWNLOAD_DIR = os.path.expanduser("~/Downloads/FreeFlix")
TEMP_DIR = os.path.join(DOWNLOAD_DIR, ".temp")


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


def get_mpv_path():
    """
    Find the mpv executable. On Windows the package most people install
    is mpv.net, whose binary is `mpvnet.exe` (not `mpv.exe`), so a plain
    shutil.which("mpv") misses it. Resolve PATH names then known install
    locations.

    Returns the executable path, or None if not found.
    """
    # PATH : try mpv first, then mpv.net's binary name.
    for name in ("mpv", "mpvnet"):
        p = shutil.which(name)
        if p:
            return p

    if platform.system() == "Windows":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\mpv.net\mpvnet.exe"),
            os.path.expandvars(r"%ProgramFiles%\mpv\mpv.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\mpv.net\mpvnet.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\mpvnet.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\mpv.exe"),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p

    return None


def _resolve_or_install(player_name: str):
    """
    Resolve a player's executable. If it's missing, offer to install it
    (mpv / vlc) via the OS package manager, then re-resolve. Returns the
    path or None.
    """
    def _resolve():
        if player_name == "vlc":
            return get_vlc_path()
        if player_name == "mpv":
            return get_mpv_path()
        return shutil.which(player_name)

    exe = _resolve()
    if exe:
        return exe

    if player_name in ("mpv", "vlc"):
        print_warning(f"{player_name} is not installed.")
        try:
            from . import setup_assistant
            if setup_assistant.install_media_player(player_name):
                exe = _resolve()
        except Exception:
            pass
    return exe


def _run_with_data_meter(cmd, env=None, quiet=False):
    """
    Launch the player (proxy mode) and report the TOTAL data consumed once
    it exits. We deliberately do NOT print a live counter during playback :
    mpv writes its own status lines to the same terminal, and a competing
    \\r line garbles both. So the player's output stays clean, and we print
    the total on a fresh line afterwards.

    `quiet` hides the player's console spam (VLC floods stderr with libav /
    libva / codec chatter the user doesn't want).
    """
    from .icons import icon

    proxy.reset_bytes_counter()
    out = subprocess.DEVNULL if quiet else None
    rc = subprocess.run(cmd, env=env, stdout=out, stderr=out).returncode

    total = proxy.get_bytes_served() / (1024 * 1024)
    if total > 0:
        print_info(f"{icon('stats')} {t('Data used')}: {total:.1f} MB")
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)
    return rc


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


def _stable_temp_dir(safe_title: str) -> str:
    """
    Return a *deterministic* temp dir for download fragments, enabling
    yt-dlp resume on re-launch. The directory is **hidden** (``.temp/``)
    so it never shows up in My Downloads.
    """
    d = os.path.join(TEMP_DIR, safe_title)
    os.makedirs(d, exist_ok=True)
    return d


_RESUME_META = ".freeflix-resume.json"


def _write_resume_meta(frag_tmp: str, **fields) -> None:
    """Persist what's needed to resume this download later (kept in .temp/,
    deleted with the dir on success)."""
    try:
        with open(os.path.join(frag_tmp, _RESUME_META), "w", encoding="utf-8") as f:
            json.dump(fields, f)
    except Exception:
        pass


def _partial_size_mb(d: str) -> float:
    """MB already on disk for a temp dir (its largest file)."""
    best = 0
    try:
        for n in os.listdir(d):
            if n == _RESUME_META:
                continue
            p = os.path.join(d, n)
            if os.path.isfile(p):
                best = max(best, os.path.getsize(p))
    except OSError:
        pass
    return best / (1024 * 1024)


def _hls_percent(d: str):
    """For yt-dlp HLS, derive % from the .ytdl resume state (fragment index)."""
    try:
        for n in os.listdir(d):
            if n.endswith(".ytdl"):
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    data = json.load(f)
                dl = data.get("downloader", {}) or {}
                cur = (dl.get("current_fragment", {}) or {}).get("index")
                total = dl.get("fragment_count")
                if cur and total:
                    return min(99, int(cur / total * 100))
    except Exception:
        pass
    return None


def list_interrupted_downloads() -> list:
    """
    Scan the hidden .temp/ for interrupted downloads (a partial file + a stored
    resume-meta). Returns dicts: {title, percent|None, size_mb, dir, meta}.
    """
    out = []
    if not os.path.isdir(TEMP_DIR):
        return out
    try:
        for name in sorted(os.listdir(TEMP_DIR)):
            d = os.path.join(TEMP_DIR, name)
            meta_p = os.path.join(d, _RESUME_META)
            if not os.path.isdir(d) or not os.path.isfile(meta_p):
                continue
            try:
                with open(meta_p, encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
            out.append({
                "title": meta.get("title", name),
                "percent": _hls_percent(d),
                "size_mb": _partial_size_mb(d),
                "dir": d,
                "meta": meta,
            })
    except OSError:
        pass
    return out


def resume_download(meta: dict) -> bool:
    """Re-run a download from stored resume-meta. The stable .temp dir + aria2
    --continue / yt-dlp .ytdl make it pick up where it stopped (works while the
    stream URL is still valid). Returns True on completion."""
    if not meta or not meta.get("stream_url"):
        return False
    return _download_stream(
        stream_url=meta["stream_url"],
        referer=meta.get("referer", ""),
        user_agent=meta.get("user_agent", ""),
        title=meta.get("title", "video"),
        is_mp4=meta.get("is_mp4", False),
        quality=meta.get("quality"),
        subfolder=meta.get("subfolder"),
    )


def _dedupe_title_segments(title: str) -> str:
    """
    Collapse repeated ' - ' segments in a title, so a movie that arrives as
    ``"Meilleurs ennemis - Movie - Meilleurs ennemis"`` becomes
    ``"Meilleurs ennemis - Movie"``. Keeps the first occurrence of each segment
    (case-insensitive), preserving order.
    """
    if " - " not in title:
        return title
    seen = set()
    out = []
    for seg in title.split(" - "):
        key = seg.strip().lower()
        if key and key in seen:
            continue
        seen.add(key)
        out.append(seg)
    return " - ".join(out)


def _sanitize_filename(name: str, max_len: int = 200) -> str:
    """Make a string safe to use as a filename across filesystems."""
    name = _dedupe_title_segments(name)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    if not cleaned:
        cleaned = "video"
    return cleaned[:max_len]


def clean_season_title(series_title: str, season_title: str) -> str:
    """
    Remove *series_title* from the start of *season_title* when the season
    title already embeds the series name (e.g. Coflix), avoiding duplicate
    names like  ``"FROM - FROM - Saison 4"`` → ``"FROM - Saison 4"``.
    """
    cleaned = season_title.replace(series_title, "", 1).strip(" -")
    return cleaned if cleaned else season_title


def clean_episode_title(series_title: str, season_title: str, episode_title: str) -> str:
    """
    Remove *series_title* and *season_title* from the start of *episode_title*
    when the episode title already embeds the full path (e.g. Coflix returns
    ``"FROM - Saison 4 - Episode 7"`` instead of just ``"Episode 7"``).

    Strips series first, then the (already-cleaned) season part.
    """
    ep = episode_title
    if ep.lower().startswith(series_title.lower()):
        ep = ep[len(series_title):].strip(" -")
    clean_season = clean_season_title(series_title, season_title)
    if ep.lower().startswith(clean_season.lower()):
        ep = ep[len(clean_season):].strip(" -")
    return ep if ep else episode_title


def _episode_window_title(series_title, season_title, episode_title) -> str:
    """The exact title used for the player window AND the resume/watched key —
    the single source of truth so badges match what playback stores."""
    cs = clean_season_title(series_title, season_title or "")
    ce = clean_episode_title(series_title, season_title or "", episode_title or "")
    return f"{series_title} - {cs} - {ce}"


def episode_badges(series_title, season_title, episode_title) -> str:
    """
    Trailing badges for an episode row in the lists:
      ⬇ downloaded · ▸NN% resume · ✓ watched
    Returns "" when there's nothing to show. Cheap (a hash + a couple lookups).
    """
    import hashlib
    wt = _episode_window_title(series_title, season_title, episode_title)
    key = hashlib.md5(wt.encode("utf-8")).hexdigest()
    tags = []
    if is_already_downloaded(wt) or is_already_downloaded(
        clean_episode_title(series_title, season_title or "", episode_title or ""),
        f"{series_title} - {clean_season_title(series_title, season_title or '')}",
    ):
        tags.append("⬇")
    pos = tracker.get_episode_position(key)
    if pos and pos > 30:
        tags.append(f"▸{int(pos // 60)}m")
    elif tracker.is_episode_watched(key):
        tags.append("✓")
    return ("  " + " ".join(tags)) if tags else ""


def _mpv_position_args(title: str):
    """
    Return extra CLI args for mpv to enable position tracking via the
    autoflix_position.lua script, plus the out-file path and key the
    Python side will read back after mpv exits.

    Returns (args_list, position_file_path, key) or ([], None, None)
    if no saved position needs restoring AND no key can be built.
    """
    import hashlib
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


def _sweep_download_litter():
    """Remove leftover HLS fragment / temp clutter (the `*-Frag*`, `*.aria2`,
    `*.frag.urls` files the old aria2c-per-fragment path left behind) so the
    download folder stays clean. These patterns are never a finished file."""
    import glob
    try:
        for pat in ("*-Frag*", "*.aria2", "*.frag.urls"):
            for p in glob.glob(os.path.join(DOWNLOAD_DIR, pat)):
                try:
                    os.remove(p)
                except OSError:
                    pass
    except Exception:
        pass


def _download_stream(
    stream_url: str,
    referer: str,
    user_agent: str,
    title: str,
    is_mp4: bool = False,
    local_subtitle_path: str = None,
    quality: int = None,
    _with_ui: bool = True,
    batch_view=None,
    subfolder: str = None,
    batch_label: str = None,
) -> bool:
    """
    Download a resolved stream to ~/Downloads/FreeFlix/ (or a `subfolder` of it,
    e.g. one folder per season for batch downloads).

    Routing:
      - HLS (.m3u8)     -> yt-dlp (handles segments via ffmpeg)
      - Direct mp4      -> aria2c (multi-connection, resumable)
                           falls back to yt-dlp if aria2c is missing.

    Subtitles, if previously downloaded, are copied next to the video.
    """
    safe_title = _sanitize_filename(title)
    out_dir = (os.path.join(DOWNLOAD_DIR, _sanitize_filename(subfolder))
               if subfolder else DOWNLOAD_DIR)
    os.makedirs(out_dir, exist_ok=True)
    _sweep_download_litter()  # clear any old fragment clutter up front

    url_lower = stream_url.lower()
    is_hls = ".m3u8" in url_lower or (not is_mp4 and ".mp4" not in url_lower)

    backend_name = None
    cmd = None
    frag_tmp = None  # temp dir for fragments / partial file (kept out of Downloads)
    needs_move = False  # True when the finished file must be moved temp → out_dir

    # Use user-selected quality from probe, or fall back to tracker default
    quality_str = str(quality) if quality else tracker.get_download_quality()
    format_arg = None
    if quality_str in ("1080", "720", "480"):
        format_arg = (
            f"bv*[height<={quality_str}]+ba/b[height<={quality_str}]/bv*+ba/b"
        )

    if is_hls:
        ytdlp = shutil.which("yt-dlp")
        if not ytdlp:
            print_error(
                "yt-dlp is required for HLS streams but is not installed. "
                "Install with: sudo dnf install yt-dlp"
            )
            return False
        # For HLS we MUST use yt-dlp's NATIVE downloader with parallel fragments,
        # not aria2c. Two reasons:
        #   1. real-time progress — native prints "[download] X% (frag a/b)"
        #      continuously, so the bar climbs live. Handing fragments to aria2c
        #      makes yt-dlp report only at the very end (bar stuck on "starting").
        #   2. it's just as fast for HLS — 16 fragments download in parallel,
        #      which already saturates the link (aria2c's per-connection split
        #      doesn't help small segments), and it leaves no fragment files.
        # Fragments + the .part go to a STABLE hidden temp dir that
        # survives interruptions — yt-dlp finds its .ytdl state on
        # re-launch and resumes where it left off.
        frag_tmp = _stable_temp_dir(safe_title)
        backend_name = "yt-dlp (16 fragments)"
        cmd = [
            ytdlp,
            "--no-warnings",
            "--newline",
            "--no-overwrites",
            "--concurrent-fragments", "16",
            "--add-header", f"Referer:{referer}",
            "--add-header", f"User-Agent:{user_agent}",
            "--merge-output-format", "mp4",
            "-P", f"home:{out_dir}",
            "-P", f"temp:{frag_tmp}",
            "-o", f"{safe_title}.%(ext)s",
        ]
        if format_arg:
            cmd.extend(["-f", format_arg])
        cmd.append(stream_url)
    else:
        aria = shutil.which("aria2c")
        if aria:
            backend_name = "aria2c"
            # Download into the hidden temp dir, NOT straight into Downloads, so a
            # dropped connection never leaves a half-finished .mp4 in the user's
            # folder. The finished file is moved to out_dir only on success
            # (--continue=true + the .aria2 control file resume the same partial).
            frag_tmp = _stable_temp_dir(safe_title)
            needs_move = True
            cmd = [
                aria,
                "--continue=true",
                "--max-connection-per-server=16",
                "--split=16",
                "--min-split-size=1M",
                "--auto-file-renaming=false",
                "--summary-interval=1",
                "--console-log-level=notice",
                f"--header=Referer: {referer}",
                f"--header=User-Agent: {user_agent}",
                f"--dir={frag_tmp}",
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
            # Same idea: the .part lives in temp, the final file lands in out_dir
            # only when complete (yt-dlp renames atomically on success).
            frag_tmp = _stable_temp_dir(safe_title)
            cmd = [
                ytdlp,
                "--no-warnings",
                "--newline",
                "--no-overwrites",
                "--add-header", f"Referer:{referer}",
                "--add-header", f"User-Agent:{user_agent}",
                "-P", f"home:{out_dir}",
                "-P", f"temp:{frag_tmp}",
                "-o", f"{safe_title}.%(ext)s",
            ]
            if format_arg:
                cmd.extend(["-f", format_arg])
            cmd.append(stream_url)

    # Remember how to resume this exact download if the connection drops.
    if frag_tmp:
        _write_resume_meta(
            frag_tmp,
            stream_url=stream_url, referer=referer, user_agent=user_agent,
            title=title, is_mp4=is_mp4, quality=quality, subfolder=subfolder,
        )

    output_suppressed = getattr(_suppress_print, "active", False)

    if not output_suppressed:
        print_info(
            f"Downloading [bold cyan]{safe_title}[/bold cyan] via "
            f"[bold cyan]{backend_name}[/bold cyan]"
        )
        print_info(f"Output: [cyan]{out_dir}[/cyan]")

    dl_ok = False
    try:
        from . import progress as _progress
        if _with_ui:
            # The BatchView is keyed by the DISPLAY label ("[i/total] title"),
            # which differs from `title` once a clean per-episode filename is
            # used — so update by `batch_label` to keep the bar moving.
            label = batch_label or title
            cb = (lambda _safe, info: batch_view.update(label, info)) if batch_view else None
            cancel = batch_view.is_cancelled if batch_view else None
            rc = _progress.run_download_with_bar(
                cmd, safe_title, batch_callback=cb, cancel_check=cancel
            )
            dl_ok = rc == 0
        else:
            import subprocess as _sp
            rc = _sp.run(cmd, env=None).returncode
            dl_ok = rc == 0
        if not dl_ok and not output_suppressed:
            print_error(f"Download failed (exit code {rc}).")
    except KeyboardInterrupt:
        if not output_suppressed:
            print_info("\nDownload interrupted by user.")
    except Exception as e:
        if not output_suppressed:
            print_error(f"Download error: {e}")
    finally:
        _sweep_download_litter()

    # Only a TRULY complete download leaves .temp for the user's folder. aria2c
    # wrote the .mp4 into frag_tmp — move it to out_dir now that it finished.
    if dl_ok and needs_move:
        try:
            src = os.path.join(frag_tmp, f"{safe_title}.mp4")
            if os.path.exists(src):
                os.makedirs(out_dir, exist_ok=True)
                shutil.move(src, os.path.join(out_dir, f"{safe_title}.mp4"))
            else:
                dl_ok = False  # nothing to move → treat as incomplete
        except Exception as e:
            if not output_suppressed:
                print_error(f"Could not finalize download: {e}")
            dl_ok = False

    # Clean the temp dir ONLY on success; keep it on failure/interrupt so the
    # next attempt resumes the partial instead of restarting from zero.
    if dl_ok and frag_tmp:
        shutil.rmtree(frag_tmp, ignore_errors=True)

    if not dl_ok:
        return False

    if local_subtitle_path and os.path.exists(local_subtitle_path):
        sub_ext = os.path.splitext(local_subtitle_path)[1] or ".srt"
        final_sub = os.path.join(out_dir, f"{safe_title}{sub_ext}")
        try:
            shutil.copy2(local_subtitle_path, final_sub)
            print_success(f"Subtitle saved: {final_sub}")
        except Exception as e:
            print_info(f"Could not save subtitle next to video: {e}")

    print_success(f"Download completed in {out_dir}")
    return True


def is_already_downloaded(title: str, subfolder: str = None) -> bool:
    """
    True if a completed download for `title` already exists on disk (so a batch
    can skip it). Mirrors the path `_download_stream` writes to.
    """
    out_dir = (os.path.join(DOWNLOAD_DIR, _sanitize_filename(subfolder))
               if subfolder else DOWNLOAD_DIR)
    base = _sanitize_filename(title)
    for ext in (".mp4", ".mkv", ".webm"):
        if os.path.isfile(os.path.join(out_dir, base + ext)):
            return True
    return False


def play_video(
    url: str,
    headers: dict,
    title: str = "FreeFlix Stream",
    subtitle_url: str = None,
    is_direct: bool = False,
    is_mp4: bool = False,
    force_player: str = None,
    _with_ui: bool = True,
    batch_view=None,
    subfolder: str = None,
    batch_label: str = None,
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

    output_suppressed = getattr(_suppress_print, "active", False)

    if not output_suppressed:
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
            if output_suppressed:
                stream_url = player.get_hls_link(url, headers)
            else:
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
            if not output_suppressed:
                print_error(f"Error resolving stream URL: {e}")
            return False

    if not stream_url:
        if not output_suppressed:
            print_error("Could not resolve stream URL.")
        return False

    if not output_suppressed:
        print_success(f"Stream URL: [cyan]{stream_url}[/cyan]")

    local_subtitle_path = subtitle_url
    if subtitle_url and subtitle_url.startswith("http"):
        print_info("Downloading subtitle file for compatibility...")
        try:
            from curl_cffi import requests

            r = requests.get(subtitle_url, timeout=10, impersonate="chrome")
            content = r.content
            sub_ext = ".vtt" if "vtt" in subtitle_url.lower() else ".srt"
            # Many subtitle hosts (OpenSubtitles & co, used by GoldenAnime)
            # serve the .srt GZIPPED or inside a ZIP — writing the raw bytes
            # as .srt gives mpv an unreadable file. Decompress first.
            if content[:2] == b"\x1f\x8b":  # gzip
                import gzip
                content = gzip.decompress(content)
            elif content[:2] == b"PK":  # zip
                import zipfile
                import io
                try:
                    z = zipfile.ZipFile(io.BytesIO(content))
                    names = [
                        n for n in z.namelist()
                        if n.lower().endswith((".srt", ".vtt", ".ass", ".ssa"))
                    ]
                    if names:
                        content = z.read(names[0])
                        sub_ext = os.path.splitext(names[0])[1] or ".srt"
                except Exception:
                    pass
            fd, temp_sub = tempfile.mkstemp(suffix=sub_ext, prefix="freeflix_sub_")
            with os.fdopen(fd, "wb") as f:
                f.write(content)
            local_subtitle_path = temp_sub
            print_success("Subtitles downloaded locally.")
        except Exception as e:
            print_error(f"Failed to download subtitles: {e}")

    # Fallback: if no subtitle and the user has configured an OpenSubtitles key,
    # try to fetch one automatically by title.
    if not local_subtitle_path and tracker.get_opensubtitles_key():
        try:
            from . import subtitles as os_subs
            # Subtitles follow the chosen *content* (anime) language : pick
            # English → English subs, French → French subs. Fall back to the
            # interface language, then English.
            sub_lang = (
                tracker.get_anime_language()
                or tracker.get_language()
                or "en"
            )
            print_info(f"No source subtitles; trying OpenSubtitles fallback ({sub_lang})…")
            fetched = os_subs.fetch_best_subtitle(title, languages=sub_lang)
            if fetched:
                local_subtitle_path = fetched
                print_success(f"OpenSubtitles match downloaded: {fetched}")
            else:
                print_info("No OpenSubtitles match found.")
        except Exception as e:
            print_info(f"OpenSubtitles lookup skipped: {e}")

    # Quality selection : if the resolved stream is a multi-variant HLS
    # master (e.g. vidmoly 1080p/480p, anizone 1080p…360p), let the user
    # pick. We apply the choice via mpv's --hls-bitrate on the MASTER
    # rather than swapping stream_url to a single variant playlist :
    # masters with a SEPARATE audio rendition (EXT-X-MEDIA TYPE=AUDIO,
    # e.g. anizone) would otherwise lose their audio track when reduced
    # to a video-only variant. Keeping the master preserves audio for
    # both muxed and split-audio streams.
    # Also doubles as a Cloudflare-block probe. Skipped for batch.
    selected_hls_bitrate = None
    selected_quality = None  # height for yt-dlp download (e.g. 1080)
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
                if chosen and chosen.get("bandwidth"):
                    selected_hls_bitrate = chosen["bandwidth"]
                    selected_quality = chosen.get("height")
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
                # Separate display labels from the internal values so the
                # "(recommended)" tag on mpv doesn't leak into player_name.
                player_values = ["mpv", "vlc", "browser", "download"]
                player_labels = [
                    f"mpv ({t('recommended')})",
                    "vlc",
                    "browser",
                    "download",
                    t("← Back"),
                ]
                player_choice = select_from_list(
                    player_labels, t("🎮 Select video player:")
                )

                if player_choice == len(player_values):  # Back
                    return False

                player_name = player_values[player_choice]
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
                referer = headers.get("Referer", "")
        else:
            referer = headers.get("Referer", "")

        user_agent = headers.get("User-Agent", DEFAULT_USER_AGENT)

        if player_name in ("browser", "download"):
            pass  # No specific executable needed at this stage
        elif player_name == "vlc":
            # Resolve VLC, offering to install it if missing.
            player_executable = _resolve_or_install("vlc")
            if not player_executable:
                print_error("VLC not found. Please install it or add it to your PATH.")
                retry = handle_player_error("VLC")
                if retry == 1:  # Back
                    return False
                force_manual_mode = True
                continue
        else:
            # mpv (Windows-aware: mpv.net → mpvnet.exe) and others, with an
            # install offer when the binary is missing.
            player_executable = _resolve_or_install(player_name)
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
                quality=selected_quality,
                _with_ui=_with_ui,
                batch_view=batch_view,
                subfolder=subfolder,
                batch_label=batch_label,
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
            print_info("Launching [bold cyan]Browser[/bold cyan] Player...")

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
            # /video is for direct MP4 (range seeking). But if the resolved
            # stream is actually an HLS playlist (e.g. uqload now returns
            # m3u8 despite an ext:mp4 config), force /stream so segments get
            # proxied/rewritten.
            is_hls_stream = ".m3u8" in stream_url.lower() or ".txt" in stream_url.lower()
            if not is_hls_stream and (
                ("ext" in player_config and player_config["ext"] == "mp4") or is_mp4
            ):
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
            # /video is for direct MP4 (range seeking). But if the resolved
            # stream is actually an HLS playlist (e.g. uqload now returns
            # m3u8 despite an ext:mp4 config), force /stream so segments get
            # proxied/rewritten.
            is_hls_stream = ".m3u8" in stream_url.lower() or ".txt" in stream_url.lower()
            if not is_hls_stream and (
                ("ext" in player_config and player_config["ext"] == "mp4") or is_mp4
            ):
                endpoint = "video"

            local_stream_url = f"{proxy.PROXY_URL}/{endpoint}?url={encoded_url}&headers={encoded_headers}"

            try:
                cmd = [player_executable, local_stream_url]
                if player_name == "vlc":
                    # Quiet the libav/libva/codec flood, and cap the adaptive
                    # (HLS) ladder to the chosen resolution so VLC doesn't ramp
                    # up to the highest variant, ignoring the picked quality.
                    cmd.append("--quiet")
                    if selected_quality:
                        cmd.append(f"--adaptive-maxheight={selected_quality}")
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
                    if selected_hls_bitrate:
                        # Cap to the chosen variant ; mpv keeps the master's
                        # audio rendition.
                        cmd.append(f"--hls-bitrate={selected_hls_bitrate}")
                    if local_subtitle_path:
                        cmd.append(f"--sub-files={local_subtitle_path}")

                pos_args, pos_file, pos_key = ([], None, None)
                if player_name == "mpv":
                    pos_args, pos_file, pos_key = _mpv_position_args(title)
                    cmd.extend(pos_args)

                run_env = _nvidia_env() if player_name == "mpv" else None
                # Proxy mode : show live data usage and the total at the end.
                _run_with_data_meter(cmd, env=run_env, quiet=(player_name == "vlc"))
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
                    # VLC Command construction (quiet + capped adaptive quality)
                    cmd = [
                        player_executable,
                        "--quiet",
                        stream_url,
                        f":http-referrer={referer}",
                        f":http-user-agent={user_agent}",
                        f"--meta-title={title}",
                    ]
                    if selected_quality:
                        cmd.append(f"--adaptive-maxheight={selected_quality}")
                    if local_subtitle_path:
                        print_warning(
                            "Note: VLC natively struggles to sync external subtitles on HLS/M3U8 streams (subtitles may flash). Strongly recommend using MPV instead."
                        )
                        cmd.append(f"--sub-file={local_subtitle_path}")
                    subprocess.run(cmd, check=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    # MPV Command construction
                    origin_domain = referer.split('/')[2] if referer else ""
                    headers_mpv = f"Origin: https://{origin_domain}" if origin_domain else ""
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
                    if selected_hls_bitrate:
                        cmd.append(f"--hls-bitrate={selected_hls_bitrate}")
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
