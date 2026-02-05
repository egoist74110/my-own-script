#!/usr/bin/env bash
set -euo pipefail

APP_NAME="代码工具箱"
REPO_DIR="${REPO_DIR:-$HOME/my-own-script}"
OUT_DIR="${OUT_DIR:-$REPO_DIR/dist}"
APP_PATH="$OUT_DIR/$APP_NAME.app"

# Version from source (optional)
VERSION="0.1.0"
if [ -f "$REPO_DIR/app_version.py" ]; then
  if [ -x "$REPO_DIR/.venv/bin/python" ]; then
    VERSION=$(cd "$REPO_DIR" && "$REPO_DIR/.venv/bin/python" -c 'import app_version; print(app_version.__version__)' 2>/dev/null || echo "$VERSION")
  else
    VERSION=$(cd "$REPO_DIR" && python3 -c 'import app_version; print(app_version.__version__)' 2>/dev/null || echo "$VERSION")
  fi
fi

DMG_NAME="$APP_NAME-$VERSION-mac.dmg"
DMG_PATH="$OUT_DIR/$DMG_NAME"

if [ ! -d "$APP_PATH" ]; then
  echo "[ERR] .app not found: $APP_PATH"
  echo "Run: bash pack_mac_app.sh"
  exit 1
fi

TMP_DIR=$(mktemp -d "/tmp/${APP_NAME}.dmg.XXXX")
STAGE_DIR="$TMP_DIR/stage"
mkdir -p "$STAGE_DIR"

# Stage content: app + Applications shortcut
cp -R "$APP_PATH" "$STAGE_DIR/"
ln -s /Applications "$STAGE_DIR/Applications"

# Clean old dmg
rm -f "$DMG_PATH"

# Create DMG (simple, no fancy background)
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGE_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH" >/dev/null

echo "OK: $DMG_PATH"
