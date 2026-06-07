"""Wondershot — Snagit-style screenshot tool for Linux/Wayland."""

import os
import shutil
import sys

__version__ = "0.1.0"


def launcher_command() -> str:
    """Absolute capture command for shortcut instructions.

    A bare name ("wondershot --capture", or worse the pre-rename
    "grabbit --capture") breaks when the venv's bin dir isn't on the
    desktop session's PATH — and Jack's KDE shortcut died exactly that
    way after the rename. Always show the full path.
    """
    exe = shutil.which("wondershot")
    if not exe:
        # running from a venv without the launcher on PATH
        cand = os.path.join(os.path.dirname(sys.executable), "wondershot")
        exe = cand if os.path.exists(cand) else "wondershot"
    return f"{exe} --capture"
