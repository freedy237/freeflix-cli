"""
Lightweight diagnostics : a rotating log file + an optional --verbose console.

We spent a lot of time GUESSING why a source or playback failed. Now every run
writes to a rotating log (``freeflix.log`` in the user cache dir), an unhandled
exception is captured with its traceback, and ``freeflix --verbose`` mirrors
DEBUG output to the console. ``log()`` is a thin helper so call sites stay cheap.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

try:
    from platformdirs import user_cache_dir
    _LOG_DIR = Path(user_cache_dir("freeflix-cli", "PaulExplorer"))
except Exception:  # pragma: no cover
    _LOG_DIR = Path.home() / ".cache" / "freeflix-cli"

LOG_FILE = _LOG_DIR / "freeflix.log"

_logger = logging.getLogger("freeflix")
_configured = False


def setup(verbose: bool = False) -> logging.Logger:
    """Configure logging once. Always logs to the rotating file ; with
    *verbose* also prints DEBUG to stderr. Safe to call more than once."""
    global _configured
    if _configured:
        if verbose:
            _stderr_debug()
        return _logger

    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False

    # Rotating file handler (best-effort — never let logging break the app).
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
        _logger.addHandler(fh)
    except Exception:
        pass

    if verbose:
        _stderr_debug()

    # Capture unhandled exceptions with their traceback (KeyboardInterrupt stays
    # a clean exit, not a logged crash).
    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        _logger.error("Unhandled exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook
    _configured = True
    return _logger


def _stderr_debug():
    if any(getattr(h, "_ff_stderr", False) for h in _logger.handlers):
        return
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    sh._ff_stderr = True
    _logger.addHandler(sh)


def log(msg: str, level: int = logging.INFO):
    try:
        _logger.log(level, msg)
    except Exception:
        pass


def warning(msg):
    log(str(msg), logging.WARNING)


def error(msg):
    log(str(msg), logging.ERROR)
