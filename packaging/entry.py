"""PyInstaller entry point (see README, "Standalone executable")."""

from musixporter.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
