"""Frozen-build entry point (PyInstaller analyzes from here)."""
import sys

from wondershot.cli import main

if __name__ == "__main__":
    sys.exit(main())
