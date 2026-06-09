#!/bin/sh
# Wondershot installer/updater for Linux (Tauri AppImage path).
#
#   curl -fsSL https://raw.githubusercontent.com/jackmusick/wondershot/main/install.sh | sh
#
# Downloads the latest Wondershot AppImage from GitHub Releases into
# ~/.local/share/wondershot, links a `wondershot` launcher in ~/.local/bin, and
# installs a .desktop entry. User-local, no sudo. Re-run to update in place.
# The Flatpak (install via wondershot's flatpak bundle) remains the recommended
# end-user install; this AppImage path is the convenient one-liner.
#
# System packages the AppImage relies on are CHECKED, not installed — a piped
# script can't sudo safely; you get the exact command to run.
set -eu

REPO="jackmusick/wondershot"
HOME_DIR="${WONDERSHOT_HOME:-$HOME/.local/share/wondershot}"
BIN_DIR="${WONDERSHOT_BIN:-$HOME/.local/bin}"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
APPIMAGE="$HOME_DIR/Wondershot.AppImage"

say() { printf '\033[1m[wondershot]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[wondershot]\033[0m %s\n' "$*" >&2; exit 1; }

# -- dependency checks ---------------------------------------------------------

missing=""
command -v ffmpeg >/dev/null 2>&1 || missing="$missing ffmpeg"
gst-inspect-1.0 pipewiresrc >/dev/null 2>&1 || missing="$missing gst-pipewire"
# Wayland-only: wl-copy holds the image selection without a focused window,
# which the toolkit cannot do — without it, copy-after-capture fails.
if [ -n "${WAYLAND_DISPLAY:-}" ] && ! command -v wl-copy >/dev/null 2>&1; then
    missing="$missing wl-clipboard"
fi

if [ -n "$missing" ]; then
    say "missing system packages:$missing"
    if command -v dnf >/dev/null 2>&1; then
        say "install them with:"
        say "  sudo dnf install ffmpeg gstreamer1-plugin-pipewire wl-clipboard"
    elif command -v apt-get >/dev/null 2>&1; then
        say "install them with:"
        say "  sudo apt install ffmpeg gstreamer1.0-pipewire wl-clipboard"
    else
        say "install ffmpeg, the GStreamer PipeWire plugin, and wl-clipboard"
        say "with your distro's package manager."
    fi
    fail "re-run this script once they're installed"
fi
# onnxruntime is optional (only AI background removal needs it); not required.

# -- locate + download the AppImage --------------------------------------------

mkdir -p "$HOME_DIR" "$BIN_DIR" "$APP_DIR"

say "looking up the latest release..."
api="https://api.github.com/repos/$REPO/releases/latest"
url=$(curl -fsSL "$api" \
    | grep -o '"browser_download_url": *"[^"]*\.AppImage"' \
    | head -n1 | cut -d'"' -f4)
[ -n "$url" ] || fail "no .AppImage asset in the latest release of $REPO"

tmp=$(mktemp --suffix=.AppImage)
trap 'rm -f "$tmp"' EXIT
say "downloading $url"
curl -fsSL "$url" -o "$tmp"
chmod +x "$tmp"
mv "$tmp" "$APPIMAGE"
trap - EXIT

ln -sf "$APPIMAGE" "$BIN_DIR/wondershot"

# -- desktop entry -------------------------------------------------------------

cat > "$APP_DIR/io.github.jackmusick.wondershot.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Wondershot
Comment=Screenshot & screen-recording with annotation
Exec=$BIN_DIR/wondershot
Icon=io.github.jackmusick.wondershot
Terminal=false
Categories=Utility;Graphics;
StartupNotify=true
EOF

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) say "NOTE: $BIN_DIR is not on your PATH — add it to use 'wondershot'" ;;
esac

say "done. Run: wondershot"
say "  update later: re-run this same command"
