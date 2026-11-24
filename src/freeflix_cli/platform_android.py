"""
Android / Termux integration.

FreeFlix runs on Android inside Termux (or a proot Debian userland). There's no
display for a subprocess mpv/vlc, so playback is delegated to an EXTERNAL
Android video player (mpv-android first, then VLC) via an ``am start`` intent.
The external player reads FreeFlix's local proxy over the shared Android
loopback, so header injection + m3u8 rewriting still work exactly as on desktop.

Everything degrades gracefully : on a non-Android box every function is a
cheap no-op / False, so importing this module is always safe.
"""

from __future__ import annotations

import os
import shutil
import subprocess

# mpv-android is the best target : it honours the "video/any" MIME (forces
# playback regardless of extension) and handles HLS + headers. VLC is the
# fallback. Order matters — first installed wins.
ANDROID_PLAYER_PACKAGES = [
    ("is.xyz.mpv", "mpv-android"),
    ("org.videolan.vlc", "VLC"),
]


def is_termux() -> bool:
    """True when running inside the Termux app itself."""
    if os.environ.get("TERMUX_VERSION"):
        return True
    return "com.termux" in (os.environ.get("PREFIX", "") or "")


def is_android() -> bool:
    """True on Android — Termux directly, or a proot distro on top of Android."""
    if is_termux():
        return True
    if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
        return True
    # proot Debian/Ubuntu : the Android system partition is still mounted.
    return os.path.exists("/system/build.prop") or os.path.exists("/system/bin/am")


def _am_binary() -> str | None:
    """Path to Android's `am` (activity manager) — on PATH in Termux, at
    /system/bin/am inside a proot distro."""
    found = shutil.which("am")
    if found:
        return found
    for cand in ("/system/bin/am", "/system/xbin/am"):
        if os.path.exists(cand):
            return cand
    return None


def is_proot() -> bool:
    """
    True when running under a proot distro (Debian/Ubuntu) ON Android — as
    opposed to Termux natively. This matters a lot : Android's `am` CANNOT run
    from inside proot (it needs app_process / the Android linker, which proot
    can't provide), so playback must be launched from Termux instead.
    """
    return is_android() and not is_termux()


def _android_env() -> dict:
    """Env with the Android system lib paths so `am`/app_process can link when
    invoked from a bare shell. (Still won't help under proot, but it's correct
    and harmless in Termux.)"""
    env = dict(os.environ)
    env.setdefault("ANDROID_DATA", "/data")
    env.setdefault("ANDROID_ROOT", "/system")
    extra = "/system/lib64:/system/lib:/apex/com.android.runtime/lib64:/apex/com.android.art/lib64"
    cur = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = extra + ((":" + cur) if cur else "")
    return env


def available() -> bool:
    """True if a launch method exists at all (am or termux-open)."""
    return is_android() and (_am_binary() is not None or shutil.which("termux-open") is not None)


def _looks_like_error(output: str) -> bool:
    low = (output or "").lower()
    return (
        "error" in low
        or "does not exist" in low
        or "unable to resolve" in low
        or "no activities found" in low
        or "permission denial" in low
    )


def _is_linker_failure(output: str) -> bool:
    """The signature of `am` failing under proot (app_process can't be linked)."""
    low = (output or "").lower()
    return (
        "cannot link executable" in low
        or "app_process" in low
        or "libnativeloader" in low
        or "no such file or directory" in low
    )


def _run(cmd: list) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20,
                           env=_android_env(),
                           encoding="utf-8", errors="replace")
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return 1, str(e)


def launch_player(url: str, title: str | None = None) -> tuple[bool, str, str]:
    """
    Hand *url* to an Android video player. Returns (ok, player_label, diag).
    Tries mpv-android, then VLC, then termux-open, then a generic chooser —
    and NEVER reports success unless the launch was actually accepted (the old
    generic fallback lied, so "Playing…" showed but nothing opened).
    """
    am = _am_binary()
    termux_open = shutil.which("termux-open")

    methods: list[tuple[str, list, bool]] = []  # (label, cmd, needs_starting)
    if am:
        for pkg, label in ANDROID_PLAYER_PACKAGES:
            methods.append((label, [
                am, "start", "-a", "android.intent.action.VIEW",
                "-t", "video/any", "-d", url, "-p", pkg,
            ], True))
    if termux_open:
        methods.append(("termux-open", [termux_open, "--content-type", "video/*", url], False))
    if am:
        methods.append(("Android", [
            am, "start", "-a", "android.intent.action.VIEW",
            "-t", "video/any", "-d", url,
        ], True))

    if not methods:
        return False, "", "no launcher (am / termux-open) found"

    diags = []
    for label, cmd, needs_starting in methods:
        rc, out = _run(cmd)
        if _is_linker_failure(out):
            # am is broken here (proot) — no point trying its other variants.
            diags.append(f"[{label}] {out[:200]}")
            if am and cmd[0] == am:
                # skip remaining am-based methods
                methods = [m for m in methods if m[0] == "termux-open"]
            continue
        ok = rc == 0 and not _looks_like_error(out)
        if needs_starting:
            ok = ok and "starting" in out.lower()
        if ok:
            return True, label, ""
        diags.append(f"[{label}] rc={rc} {out[:200]}")

    return False, "", "\n".join(diags)


def diagnose() -> str:
    """One-line environment summary for troubleshooting playback launch."""
    kind = "Termux" if is_termux() else ("proot/Android" if is_proot() else "not-android")
    am = _am_binary() or "—"
    to = shutil.which("termux-open") or "—"
    return f"env={kind}  am={am}  termux-open={to}"
