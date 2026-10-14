#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/wondershot-install-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

FAKE_BIN="$TMP/bin"
FAKE_HOME="$TMP/home"
mkdir -p "$FAKE_BIN" "$FAKE_HOME"

cat >"$FAKE_BIN/current-app" <<'APP'
#!/bin/sh
case "$1" in
  --self-check)
    echo "wondershot self check 0.1.0"
    exit 0
    ;;
  --version)
    echo "wondershot 0.1.0"
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
APP
chmod +x "$FAKE_BIN/current-app"

cat >"$FAKE_BIN/curl" <<'CURL'
#!/bin/sh
out=
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o)
      out=$2
      shift 2
      ;;
    http*)
      url=$1
      shift
      ;;
    *)
      shift
      ;;
  esac
done

case "$url" in
  *api.github.com*)
    case "${WONDERSHOT_TEST_RELEASE:-appimage}" in
      appimage)
        printf '%s\n' '{"assets":[{"browser_download_url":"https://example.invalid/Wondershot.AppImage"}]}'
        ;;
      flatpak)
        printf '%s\n' '{"assets":[{"browser_download_url":"https://example.invalid/wondershot.flatpak"}]}'
        ;;
    esac
    ;;
  *Wondershot.AppImage)
    cp "$WONDERSHOT_TEST_CURRENT_APP" "$out"
    ;;
  *wondershot.flatpak)
    printf '%s\n' "fake flatpak bundle" >"$out"
    ;;
  *)
    echo "unexpected curl URL: $url" >&2
    exit 1
    ;;
esac
CURL
chmod +x "$FAKE_BIN/curl"

cat >"$FAKE_BIN/flatpak" <<'FLATPAK'
#!/bin/sh
case "$1" in
  remote-add|install)
    exit 0
    ;;
  run)
    case "${WONDERSHOT_TEST_FLATPAK_MODE:-legacy}" in
      current)
        echo "wondershot self check 0.1.0"
        exit 0
        ;;
      legacy)
        echo "usage: wondershot [-h] [-c] [-f] [--version]" >&2
        echo "wondershot: error: unrecognized arguments: $3" >&2
        exit 2
        ;;
    esac
    ;;
  *)
    echo "unexpected flatpak command: $*" >&2
    exit 1
    ;;
esac
FLATPAK
chmod +x "$FAKE_BIN/flatpak"

for name in ffmpeg gst-inspect-1.0 wl-copy; do
  cat >"$FAKE_BIN/$name" <<'TOOL'
#!/bin/sh
exit 0
TOOL
  chmod +x "$FAKE_BIN/$name"
done

run_installer() {
  HOME="$FAKE_HOME" \
  XDG_DATA_HOME="$FAKE_HOME/.local/share" \
  WONDERSHOT_HOME="$FAKE_HOME/.local/share/wondershot" \
  WONDERSHOT_BIN="$FAKE_HOME/.local/bin" \
  WONDERSHOT_TEST_CURRENT_APP="$FAKE_BIN/current-app" \
  PATH="$FAKE_BIN:$PATH" \
  sh "$ROOT/install.sh"
}

WONDERSHOT_TEST_RELEASE=appimage run_installer
test -x "$FAKE_HOME/.local/share/wondershot/Wondershot.AppImage"
test -L "$FAKE_HOME/.local/bin/wondershot"

if WONDERSHOT_TEST_RELEASE=flatpak WONDERSHOT_TEST_FLATPAK_MODE=legacy run_installer; then
  echo "legacy Flatpak validation unexpectedly passed" >&2
  exit 1
fi

WONDERSHOT_TEST_RELEASE=flatpak WONDERSHOT_TEST_FLATPAK_MODE=current run_installer

echo "install.sh smoke tests passed"
