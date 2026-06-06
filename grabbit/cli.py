"""Command-line entry point and single-instance dispatch."""

from __future__ import annotations

import argparse
import os
import shutil
import sys

from . import __version__


def build_command(args) -> dict:
    if args.capture:
        return {"action": "capture"}
    if args.fullscreen:
        return {"action": "fullscreen"}
    if args.edit:
        return {"action": "edit", "path": os.path.abspath(args.edit)}
    if args.imports:
        return {"action": "import",
                "paths": [os.path.abspath(p) for p in args.imports]}
    if args.quit:
        return {"action": "quit"}
    return {"action": "show"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="grabbit",
        description="Snagit-style screenshot tool: capture, gallery, markup.")
    parser.add_argument("-c", "--capture", action="store_true",
                        help="capture a region")
    parser.add_argument("-f", "--fullscreen", action="store_true",
                        help="capture the full screen")
    parser.add_argument("-e", "--edit", metavar="FILE",
                        help="open FILE in the markup editor")
    parser.add_argument("-i", "--import", dest="imports", nargs="+",
                        metavar="FILE", help="copy FILEs into the library")
    parser.add_argument("--quit", action="store_true",
                        help="stop the running instance")
    parser.add_argument("--install-desktop", action="store_true",
                        help="install .desktop launcher and icon for this user")
    parser.add_argument("--selftest", metavar="DIR",
                        help="render UI screenshots into DIR and exit (dev tool)")
    parser.add_argument("--version", action="version",
                        version=f"grabbit {__version__}")
    args = parser.parse_args(argv)

    if args.install_desktop:
        return install_desktop()

    if args.selftest:
        from .selftest import run_selftest
        return run_selftest(args.selftest)

    from .app import GrabbitApp, send_to_running

    command = build_command(args)
    if send_to_running(command):
        return 0
    if args.quit:
        return 0  # nothing running

    from PySide6.QtWidgets import QApplication

    qapp = QApplication(sys.argv[:1])
    qapp.setApplicationName("grabbit")
    qapp.setOrganizationName("grabbit")
    qapp.setDesktopFileName("grabbit")
    qapp.setQuitOnLastWindowClosed(False)

    app = GrabbitApp(qapp)
    # Apply the launch command once the event loop is up.
    from PySide6.QtCore import QTimer
    if command["action"] != "show":
        QTimer.singleShot(0, lambda: app.handle_command(command))
    else:
        QTimer.singleShot(0, app.show_gallery)
    return qapp.exec()


def install_desktop() -> int:
    """Install launcher + icon into the user's XDG data dirs."""
    from importlib import resources

    exec_path = shutil.which("grabbit") or os.path.abspath(sys.argv[0])
    data_home = os.environ.get("XDG_DATA_HOME",
                               os.path.expanduser("~/.local/share"))
    apps = os.path.join(data_home, "applications")
    icons = os.path.join(data_home, "icons", "hicolor", "scalable", "apps")
    os.makedirs(apps, exist_ok=True)
    os.makedirs(icons, exist_ok=True)

    desktop = resources.files("grabbit").joinpath("data/grabbit.desktop").read_text()
    desktop = desktop.replace("Exec=grabbit", f"Exec={exec_path}")
    dest = os.path.join(apps, "grabbit.desktop")
    with open(dest, "w") as f:
        f.write(desktop)

    svg = resources.files("grabbit").joinpath("data/grabbit.svg").read_bytes()
    with open(os.path.join(icons, "grabbit.svg"), "wb") as f:
        f.write(svg)

    print(f"installed {dest}")
    print(f"installed {os.path.join(icons, 'grabbit.svg')}")
    print("Tip: bind a global shortcut to:  grabbit --capture")
    return 0


if __name__ == "__main__":
    sys.exit(main())
