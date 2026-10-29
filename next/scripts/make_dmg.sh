#!/usr/bin/env bash
# Package TOOLBOX.app into UDZO DMG (with Applications symlink) and zip archive:
#   <outdir>/TOOLBOX-<version>-arm64.dmg
#   <outdir>/TOOLBOX-<version>-arm64.zip
# Does NOT perform code signing, notarization, or release publishing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

if [ $# -ne 2 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  echo "usage: make_dmg.sh <path-to-.app> <outdir>" >&2
  [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && exit 0
  exit 2
fi

APP_PATH="$1"
OUT_DIR="$2"

if [ ! -d "$APP_PATH" ]; then
  echo "error: bundle directory not found: $APP_PATH" >&2
  exit 2
fi

TAURI_CONF="${TOOLBOX_TAURI_CONF:-$REPO/next/desktop/src-tauri/tauri.conf.json}"
VERSION="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' "$TAURI_CONF")"

mkdir -p "$OUT_DIR"
OUT_ABS="$(cd "$OUT_DIR" && pwd -P)"
DMG_PATH="$OUT_ABS/TOOLBOX-${VERSION}-arm64.dmg"
ZIP_PATH="$OUT_ABS/TOOLBOX-${VERSION}-arm64.zip"

STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/toolbox-dmg-stage.XXXXXX")"
cleanup() {
  rm -rf "$STAGE_DIR"
}
trap cleanup EXIT

APP_NAME="$(basename "$APP_PATH")"
cp -R "$APP_PATH" "$STAGE_DIR/$APP_NAME"
ln -s /Applications "$STAGE_DIR/Applications"

rm -f "$DMG_PATH" "$ZIP_PATH"

echo "[make_dmg] creating UDZO DMG: $DMG_PATH"
hdiutil create -volname "代码工具箱" -srcfolder "$STAGE_DIR" -ov -format UDZO "$DMG_PATH"

echo "[make_dmg] creating zip archive: $ZIP_PATH"
ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

echo "[make_dmg] done:"
echo "  $DMG_PATH"
echo "  $ZIP_PATH"
