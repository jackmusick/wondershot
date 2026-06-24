#!/bin/sh
# Wondershot installer/updater for Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/jackmusick/wondershot/main/install.sh | sh
#
# Installs the latest Wondershot from GitHub Releases. Prefers an AppImage asset
# (user-local, no sudo) when a release ships one; otherwise installs the Flatpak
# bundle (the current recommended Linux artifact) as a --user Flatpak. Re-run to
# update in place.
set -eu

REPO="jackmusick/wondershot"
APPID="io.github.jackmusick.wondershot"
HOME_DIR="${WONDERSHOT_HOME:-$HOME/.local/share/wondershot}"
BIN_DIR="${WONDERSHOT_BIN:-$HOME/.local/bin}"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
APPIMAGE="$HOME_DIR/Wondershot.AppImage"

say()  { printf '\033[1m[wondershot]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[wondershot]\033[0m %s\n' "$*" >&2; exit 1; }

# -- pick the best asset from the latest release -------------------------------

say "looking up the latest release..."
assets=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
    | grep -o '"browser_download_url": *"[^"]*"' | cut -d'"' -f4)
appimage_url=$(printf '%s\n' "$assets" | grep -i '\.AppImage$' | head -n1 || true)
flatpak_url=$(printf  '%s\n' "$assets" | grep -i '\.flatpak$'  | head -n1 || true)

if [ -n "$appimage_url" ]; then
    # ---- AppImage path: runs against host libs, so check them ----------------
    missing=""
    command -v ffmpeg >/dev/null 2>&1 || missing="$missing ffmpeg"
    gst-inspect-1.0 pipewiresrc >/dev/null 2>&1 || missing="$missing gst-pipewire"
    if [ -n "${WAYLAND_DISPLAY:-}" ] && ! command -v wl-copy >/dev/null 2>&1; then
        missing="$missing wl-clipboard"   # holds the image selection on Wayland
    fi
    if [ -n "$missing" ]; then
        say "missing system packages:$missing"
        if command -v dnf >/dev/null 2>&1; then
            say "  sudo dnf install ffmpeg gstreamer1-plugin-pipewire wl-clipboard"
        elif command -v apt-get >/dev/null 2>&1; then
            say "  sudo apt install ffmpeg gstreamer1.0-pipewire wl-clipboard"
        else
            say "  install ffmpeg, the GStreamer PipeWire plugin, and wl-clipboard"
        fi
        fail "re-run this script once they're installed"
    fi

    mkdir -p "$HOME_DIR" "$BIN_DIR" "$APP_DIR"
    [ -d "$HOME_DIR/venv" ] && { say "removing the old Python install"; rm -rf "$HOME_DIR/venv"; }

    tmp=$(mktemp "${TMPDIR:-/tmp}/wondershot.XXXXXX.AppImage")
    trap 'rm -f "$tmp"' EXIT
    say "downloading $appimage_url"
    curl -fsSL "$appimage_url" -o "$tmp"
    chmod +x "$tmp"; mv "$tmp" "$APPIMAGE"; trap - EXIT
    ln -sf "$APPIMAGE" "$BIN_DIR/wondershot"

    cat > "$APP_DIR/$APPID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Wondershot
Comment=Screenshot & screen-recording with annotation
Exec=$BIN_DIR/wondershot
Icon=$APPID
Terminal=false
Categories=Utility;Graphics;
StartupNotify=true
EOF
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) say "NOTE: $BIN_DIR is not on your PATH — add it to use 'wondershot'" ;;
    esac
    say "done. Run: wondershot   (update later: re-run this command)"

elif [ -n "$flatpak_url" ]; then
    # ---- Flatpak path: the bundle carries its own runtime/deps ---------------
    command -v flatpak >/dev/null 2>&1 || fail "flatpak not found — install flatpak, then re-run"
    # the bundle references runtimes from Flathub; ensure a user remote exists
    flatpak remote-add --user --if-not-exists flathub \
        https://dl.flathub.org/repo/flathub.flatpakrepo

    tmp=$(mktemp "${TMPDIR:-/tmp}/wondershot.XXXXXX.flatpak")
    trap 'rm -f "$tmp"' EXIT
    say "downloading $flatpak_url"
    curl -fsSL "$flatpak_url" -o "$tmp"
    say "installing the Flatpak bundle (user)..."
    flatpak install --user -y --noninteractive "$tmp"
    rm -f "$tmp"; trap - EXIT
    say "done. Launch 'Wondershot' from your menu, or: flatpak run $APPID"

else
    fail "latest release of $REPO ships no .AppImage or .flatpak asset"
fi
