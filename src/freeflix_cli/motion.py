"""Motion preferences.

`FREEFLIX_REDUCED_MOTION=1` (or the Settings toggle) disables decorative
animation — comet, logo shine, marching bars — while keeping the UI fully
usable and styled. This is the terminal twin of the OS "reduce motion"
setting, and it also cuts CPU on very slow machines / remote SSH sessions.
"""

import os

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def reduced() -> bool:
    """True when decorative animation should be skipped."""
    val = (os.environ.get("FREEFLIX_REDUCED_MOTION") or "").strip().lower()
    if val in _TRUE:
        return True
    if val in _FALSE:
        return False
    try:
        from .tracker import tracker
        return bool(tracker.data.get("reduced_motion", False))
    except Exception:
        return False
