#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/wondershot-install-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/home/.local/bin" "$TMP/home/.local/share/applications"
cat >"$TMP/bin/curl" <<'CURL'
#!/bin/sh
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o) printf '[Flatpak Ref]\n' > "$2"; exit 0 ;;
        *) shift ;;
    esac
done
exit 1
CURL
cat >"$TMP/bin/flatpak" <<'FLATPAK'
#!/bin/sh
printf '%s\n' "$*" >> "$WONDERSHOT_TEST_LOG"
case "$1" in
    remote-add|install) exit 0 ;;
    run)
        [ "${WONDERSHOT_TEST_BAD_APP:-0}" = 0 ] || exit 2
        printf 'wondershot self check 0.2.1\n'
        ;;
    *) exit 1 ;;
esac
FLATPAK
for helper in gtk-update-icon-cache kbuildsycoca6 update-desktop-database; do
    printf '#!/bin/sh\nexit 0\n' > "$TMP/bin/$helper"
done
chmod +x "$TMP/bin/"*
export HOME="$TMP/home" XDG_DATA_HOME="$TMP/home/.local/share"
export PATH="$TMP/bin:$PATH" WONDERSHOT_TEST_LOG="$TMP/calls"
printf '#!/bin/sh\necho old-native\n' > "$HOME/.local/bin/wondershot"
printf '[Desktop Entry]\nExec=old-native\n' > "$XDG_DATA_HOME/applications/io.github.jackmusick.wondershot.desktop"
cp "$HOME/.local/bin/wondershot" "$TMP/old-native"
icons="$XDG_DATA_HOME/icons/hicolor/512x512/apps"
mkdir -p "$icons"
printf 'old icon\n' > "$icons/io.github.jackmusick.wondershot.png"
if WONDERSHOT_TEST_BAD_APP=1 sh "$ROOT/install.sh"; then
    echo 'Broken app unexpectedly accepted' >&2; exit 1
fi
cmp "$TMP/old-native" "$HOME/.local/bin/wondershot"
test -f "$XDG_DATA_HOME/applications/io.github.jackmusick.wondershot.desktop"
test -f "$icons/io.github.jackmusick.wondershot.png"
sh "$ROOT/install.sh"
test -x "$HOME/.local/bin/wondershot"
backup=$(find "$HOME/.local/bin" -name 'wondershot.before-flatpak.*' -print -quit)
cmp "$TMP/old-native" "$backup"
test ! -e "$XDG_DATA_HOME/applications/io.github.jackmusick.wondershot.desktop"
test ! -e "$icons/io.github.jackmusick.wondershot.png"
test "$(find "$icons" -name '*.before-flatpak.*' | wc -l)" -eq 1
"$HOME/.local/bin/wondershot" --capture 'two words'
grep -q '^run io.github.jackmusick.wondershot --capture two words$' "$TMP/calls"
grep -q '^install --user -y --noninteractive --or-update --from ' "$TMP/calls"
sh "$ROOT/install.sh"
test "$(find "$HOME/.local/bin" -name 'wondershot.before-flatpak.*' | wc -l)" -eq 1
echo 'Repository installation, migration, repeat update, and failed-app preservation passed'
