#!/bin/sh
# Install once; subsequent stable releases arrive through Discover / flatpak update.
# curl -fsSL https://raw.githubusercontent.com/jackmusick/wondershot/main/install.sh | sh
set -eu

APPID="io.github.jackmusick.wondershot"
REPOSITORY="https://jackmusick.github.io/wondershot"
BIN_DIR="${WONDERSHOT_BIN:-$HOME/.local/bin}"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
say() { printf '[wondershot] %s\n' "$*"; }
fail() { say "$*" >&2; exit 1; }

command -v flatpak >/dev/null 2>&1 || fail 'Install Flatpak with your distribution package manager, then re-run.'
command -v curl >/dev/null 2>&1 || fail 'curl is required.'
case "$(uname -m)" in
    x86_64) ;;
    *) fail 'The Linux release currently supports x86_64 only.' ;;
esac

work=$(mktemp -d "${TMPDIR:-/tmp}/wondershot-install.XXXXXX")
trap 'rm -rf "$work"' EXIT
say 'Registering the signed Wondershot repository and installing the latest stable release...'
curl -fsSL "$REPOSITORY/wondershot.flatpakref" -o "$work/wondershot.flatpakref"
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user -y --noninteractive --or-update --from "$work/wondershot.flatpakref"

say 'Checking the installed app...'
if ! flatpak run "$APPID" --self-check >"$work/check" 2>&1 \
    || ! grep -q '^wondershot self check ' "$work/check"; then
    cat "$work/check" >&2
    fail 'Flatpak validation failed; existing command and desktop launchers were preserved.'
fi

# Keep custom capture shortcuts working while package management owns the app.
mkdir -p "$BIN_DIR" "$APP_DIR"
cat >"$work/wondershot" <<'LAUNCHER'
#!/bin/sh
# Wondershot Flatpak launcher
exec flatpak run io.github.jackmusick.wondershot "$@"
LAUNCHER
if [ -e "$BIN_DIR/wondershot" ] || [ -L "$BIN_DIR/wondershot" ]; then
    if ! grep -q '^# Wondershot Flatpak launcher$' "$BIN_DIR/wondershot"; then
        backup="$BIN_DIR/wondershot.before-flatpak.$(date +%s)"
        cp -Pp "$BIN_DIR/wondershot" "$backup"
        say "Previous command saved to $backup"
    fi
fi
# Rename on the same filesystem, including when the previous binary is running.
launcher=$(mktemp "$BIN_DIR/.wondershot.XXXXXX")
cp "$work/wondershot" "$launcher"
chmod 755 "$launcher"
mv -f "$launcher" "$BIN_DIR/wondershot"

# A native per-user desktop file would shadow Flatpak's exported launcher.
desktop="$APP_DIR/$APPID.desktop"
if [ -f "$desktop" ]; then
    mv "$desktop" "$desktop.before-flatpak.$(date +%s)"
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" || true
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) say "Add $BIN_DIR to PATH to use the wondershot command." ;;
esac
say 'Installed. Future releases arrive through your software manager or flatpak update.'
