import os
from ..config_loader import load_remote_jsonc, load_local_jsonc
from ..defaults import DEFAULT_SOURCE_PORTAL

# Remote config now points at OUR fork's repo (not PaulExplorer's) so we
# control the authoritative source URLs. When a site moves, we push a new
# data/source_portal.jsonc and every user picks it up on next launch.
REMOTE_CONFIG_URL = (
    "https://raw.githubusercontent.com/freedy237/freeflix-cli/main/"
    "data/source_portal.jsonc"
)

# The bundled override file can live in a few places depending on how the
# package was installed (editable checkout, hatchling shared-data, etc.).
# Try each candidate ; the first that exists wins.
# NOTE: never count `..` levels from __file__ to reach the env root —
# POSIX (lib/pythonX.Y/site-packages) and Windows (Lib/site-packages) nest
# differently, and the miscount silently dropped the bundled file on
# Windows (updates never arrived there). Anchor on sys.prefix / sysconfig.
_HERE = os.path.dirname(__file__)


def _local_candidates() -> list:
    cands = [
        # editable / source checkout : .../src/freeflix_cli/scraping/ -> ../../../data
        os.path.join(_HERE, "..", "..", "..", "data", "source_portal.jsonc"),
    ]
    # installed wheel shared-data : <env>/share/freeflix-cli/data/ on every
    # OS (venv root, not relative navigation).
    try:
        import sys as _sys
        import sysconfig as _sc
        for _base in dict.fromkeys([_sc.get_path("data"), _sys.prefix]):
            if _base:
                cands.append(os.path.join(
                    _base, "share", "freeflix-cli", "data", "source_portal.jsonc"))
    except Exception:
        pass
    # legacy relative fallback (POSIX lib/pythonX.Y layout only)
    cands.append(os.path.join(_HERE, "..", "..", "..", "..", "..", "share",
                              "freeflix-cli", "data", "source_portal.jsonc"))
    # user-level override : ~/.config/freeflix/source_portal.jsonc
    cands.append(os.path.expanduser("~/.config/freeflix/source_portal.jsonc"))
    return [os.path.normpath(p) for p in cands]


_LOCAL_CANDIDATES = _local_candidates()


_local_portal_path: str = ""


def _find_local_override():
    global _local_portal_path
    for path in _LOCAL_CANDIDATES:
        if os.path.exists(path):
            data = load_local_jsonc(path)
            if data:
                _local_portal_path = path
                return data
    return {}


# Priority (lowest → highest) :
#   1. DEFAULT_SOURCE_PORTAL  (hardcoded fallback, always correct at ship time)
#   2. remote config          (our repo — lets us patch URLs without a release)
#   3. local override         (user / bundled file — final word)
#
# Start from the bundled defaults + local override SYNCHRONOUSLY (no network),
# so importing this module — and therefore launching `freeflix` — is instant.
# The optional remote patch is fetched in the BACKGROUND and merged in; it is
# ready long before the user actually resolves a source. `portals` is mutated
# IN PLACE (never reassigned) so importers keep seeing the live dict.
portals = dict(DEFAULT_SOURCE_PORTAL)
portal_origins = {k: "default" for k in portals}
_local_portals = _find_local_override()
if _local_portals:
    portals.update(_local_portals)
    for k in _local_portals:
        portal_origins[k] = "local"


import threading as _threading  # noqa: E402 (deliberate late import — order matters)

_portals_lock = _threading.Lock()


def _refresh_remote_portals():
    try:
        remote = load_remote_jsonc(REMOTE_CONFIG_URL, None)
    except Exception:
        return
    if not remote:
        return
    merged = dict(DEFAULT_SOURCE_PORTAL)
    origins = {k: "default" for k in merged}
    merged.update(remote)
    for k in remote:
        origins[k] = "remote"
    if _local_portals:
        merged.update(_local_portals)  # local stays the final word
        for k in _local_portals:
            origins[k] = "local"
    # Jamais de dict vu vide par un lecteur concurrent (KeyError transitoire).
    with _portals_lock:
        portals.clear()
        portals.update(merged)
        portal_origins.clear()
        portal_origins.update(origins)


_threading.Thread(target=_refresh_remote_portals, daemon=True).start()

# Hot-patchable extractor selectors are fetched the same way (background,
# best-effort) so a broken source can be repaired without a release.
from . import resilient  # noqa: E402

resilient.start_background_refresh()
