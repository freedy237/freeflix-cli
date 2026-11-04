"""Lightweight CLI entry point.

Handles the fast, non-TUI flags (--version / --help / --doctor) WITHOUT
importing the full application (handlers, players, scrapers…), then hands
off to `freeflix_cli.main` for the real run. This keeps those commands at
a few tens of milliseconds instead of paying the whole import tax.
"""

import sys


def _utf8_console() -> None:
    """Force UTF-8 on stdout/stderr when the console defaults to cp1252.

    The Windows standalone binary inherits a cp1252 console; --doctor (box
    drawing, arrows) then crashed with UnicodeEncodeError before printing
    anything. TUI output uses the same code path.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
            if enc not in ("utf8", "utf8mb4"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _version() -> str:
    try:
        import importlib.metadata as _im
        return _im.version("freeflix-cli")
    except Exception:
        return "dev"


def print_help():
    from .i18n import t
    print(t("freeflix — terminal streaming for movies / series / anime\n"))
    print(f"  freeflix           {t('launch the TUI')}")
    print(f"  freeflix --setup   {t('re-run setup : anime + interface language, then deps')}")
    print(f"  freeflix --doctor  {t('run system diagnostic')}")
    print(f"  freeflix --doctor --sources  {t('live-test every source (search + resolve)')}")
    print(f"  freeflix --doctor --upload  {t('diagnostic + upload to Gist')}")
    print(f"  freeflix --verbose {t('print DEBUG to the console (also always logged)')}")
    print(f"  freeflix --version {t('print the installed version')}")
    print(f"  freeflix --help    {t('this message')}")
    try:
        from .logsetup import LOG_FILE
        print(f"\n  {t('log file :')} {LOG_FILE}")
    except Exception:
        pass


def main():
    """Entry point: fast flags first, then the real application."""
    _utf8_console()
    args = set(sys.argv[1:])
    if args & {"--version", "-V"}:
        print(_version())
        return 0
    if args & {"--help", "-h"}:
        print_help()
        return 0
    if args & {"--doctor", "-D"}:
        from .doctor import cli_doctor
        return cli_doctor()

    # Everything else needs the app (TUI, setup, verbose logging…).
    from .main import main as run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
