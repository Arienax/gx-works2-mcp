"""PyInstaller entry point for the local, single-worker Web workbench."""

from integrations.web.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
