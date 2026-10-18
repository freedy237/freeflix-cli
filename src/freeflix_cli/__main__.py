"""Entry point for `python -m freeflix_cli` and the PyInstaller binary."""
from freeflix_cli.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
