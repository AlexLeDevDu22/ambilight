#!/bin/bash
# Construit ~/Applications/Ambilight.app (lanceur natif + icône).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CLIENT="$(cd "$HERE/.." && pwd)"
APP="$HOME/Applications/Ambilight.app"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/Ambilight.app/Contents/MacOS" "$TMP/Ambilight.app/Contents/Resources"
cp "$HERE/Info.plist" "$TMP/Ambilight.app/Contents/Info.plist"
# Python embarqué : même Python que le venv du projet
PY="$CLIENT/.venv/bin/python"
BASE="$("$PY" -c 'import sys; print(sys.base_prefix)')"
VER="$("$PY" -c 'import sysconfig; print(sysconfig.get_config_var("LDVERSION"))')"
SITE="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
clang -O2 -Wall \
  -DCLIENT_DIR="\"$CLIENT\"" -DSITE_PACKAGES="\"$SITE\"" \
  -I"$BASE/include/python$VER" "$BASE/Python" \
  -o "$TMP/Ambilight.app/Contents/MacOS/Ambilight" "$HERE/launcher.c"

# Icône à partir de Icon.png
ICONSET="$TMP/Ambilight.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$CLIENT/Icon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$CLIENT/Icon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$TMP/Ambilight.app/Contents/Resources/Ambilight.icns"

# Signature ad hoc : identité stable pour les permissions macOS
codesign --force --sign - "$TMP/Ambilight.app" >/dev/null 2>&1

mkdir -p "$HOME/Applications"
rm -rf "$APP"
mv "$TMP/Ambilight.app" "$APP"
touch "$APP"
echo "✓ $APP"
