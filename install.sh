#!/bin/sh
# Wondershot installer/updater for Linux (from-source path).
#
#   curl -fsSL https://raw.githubusercontent.com/jackmusick/wondershot/main/install.sh | sh
#
# Everything is user-local (no sudo): a private venv under
# ~/.local/share/wondershot, a `wondershot` command in ~/.local/bin, and
# desktop entries. Re-running updates to latest main. Flatpak remains
# the recommended end-user install; this is the bleeding-edge path.
#
# Distro packages we depend on are CHECKED, not installed (a piped
# script can't sudo safely) — you get the exact command to run.
set -eu

REPO_TARBALL="https://github.com/jackmusick/wondershot/archive/refs/heads/main.tar.gz"
HOME_DIR="${WONDERSHOT_HOME:-$HOME/.local/share/wondershot}"
BIN_DIR="${WONDERSHOT_BIN:-$HOME/.local/bin}"
VENV="$HOME_DIR/venv"

say() { printf '\033[1m[wondershot]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[wondershot]\033[0m %s\n' "$*" >&2; exit 1; }

# -- dependency checks ---------------------------------------------------------

command -v python3 >/dev/null 2>&1 || fail "python3 is required"

missing=""
python3 -c "import gi" >/dev/null 2>&1 || missing="$missing gobject"
command -v ffmpeg >/dev/null 2>&1 || missing="$missing ffmpeg"
gst-inspect-1.0 pipewiresrc >/dev/null 2>&1 || missing="$missing gst-pipewire"
# Wayland-only: wl-copy holds the image selection without a focused window,
# which Qt cannot do — without it, copy-to-clipboard after a capture fails.
if [ -n "${WAYLAND_DISPLAY:-}" ] && ! command -v wl-copy >/dev/null 2>&1; then
    missing="$missing wl-clipboard"
fi

if [ -n "$missing" ]; then
    say "missing system packages:$missing"
    if command -v dnf >/dev/null 2>&1; then
        say "install them with:"
        say "  sudo dnf install python3-gobject ffmpeg gstreamer1-plugin-pipewire wl-clipboard"
    elif command -v apt-get >/dev/null 2>&1; then
        say "install them with:"
        say "  sudo apt install python3-gi ffmpeg gstreamer1.0-pipewire wl-clipboard"
    else
        say "install python3-gobject (gi), ffmpeg, the GStreamer PipeWire"
        say "plugin, and wl-clipboard with your distro's package manager."
    fi
    fail "re-run this script once they're installed"
fi

# -- venv + install ------------------------------------------------------------

mkdir -p "$HOME_DIR" "$BIN_DIR"
if [ ! -x "$VENV/bin/python" ]; then
    say "creating environment in $HOME_DIR"
    # --system-site-packages: the portal D-Bus layer needs the distro's
    # gi/GLib typed variants (pip cannot provide a matching PyGObject).
    python3 -m venv --system-site-packages "$VENV"
fi

say "installing latest wondershot"
"$VENV/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
# Two passes: the first resolves any new dependencies; the second
# force-reinstalls the app itself — main moves without version bumps,
# and pip treats a same-version direct URL as already satisfied.
"$VENV/bin/pip" install --quiet --upgrade "wondershot @ $REPO_TARBALL"
"$VENV/bin/pip" install --quiet --force-reinstall --no-deps \
    "wondershot @ $REPO_TARBALL"

ln -sf "$VENV/bin/wondershot" "$BIN_DIR/wondershot"
"$VENV/bin/wondershot" --install-desktop >/dev/null 2>&1 || true

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) say "NOTE: $BIN_DIR is not on your PATH — add it to use 'wondershot'" ;;
esac

say "done. Run: wondershot"
say "  capture hotkey: bind a shortcut to 'wondershot --capture'"
say "  update later:   re-run this same command"
