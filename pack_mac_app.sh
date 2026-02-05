#!/usr/bin/env bash
set -euo pipefail

APP_NAME="代码工具箱"
REPO_DIR="${REPO_DIR:-$HOME/my-own-script}"
OUT_DIR="${OUT_DIR:-$REPO_DIR/dist}"

# Version from source
VERSION="0.1.0"
if [ -x "$REPO_DIR/.venv/bin/python" ]; then
  VERSION=$(
    cd "$REPO_DIR" && "$REPO_DIR/.venv/bin/python" -c 'import app_version; print(app_version.__version__)' 2>/dev/null || echo "0.1.0"
  )
else
  VERSION=$(cd "$REPO_DIR" && python3 -c 'import app_version; print(app_version.__version__)' 2>/dev/null || echo "0.1.0")
fi

APP_DIR="$OUT_DIR/$APP_NAME.app"

# Use repo logo.png as the icon source (1024 preferred)
ICON_SRC="$REPO_DIR/logo.png"
ICONSET_DIR="$OUT_DIR/AppIcon.iconset"
ICNS_OUT="$OUT_DIR/AppIcon.icns"

mkdir -p "$OUT_DIR"
rm -rf "$APP_DIR" "$ICONSET_DIR" "$ICNS_OUT"

# --- build icns ---
if [ -f "$ICON_SRC" ]; then
  mkdir -p "$ICONSET_DIR"
  BASE_PNG="$OUT_DIR/_icon_base.png"
  sips -s format png "$ICON_SRC" --out "$BASE_PNG" >/dev/null

  # generate pngs from a real png to keep iconutil happy
  sips -z 16 16   "$BASE_PNG" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
  sips -z 32 32   "$BASE_PNG" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
  sips -z 32 32   "$BASE_PNG" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
  sips -z 64 64   "$BASE_PNG" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$BASE_PNG" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
  sips -z 256 256 "$BASE_PNG" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$BASE_PNG" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
  sips -z 512 512 "$BASE_PNG" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$BASE_PNG" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$BASE_PNG" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null

  iconutil -c icns "$ICONSET_DIR" -o "$ICNS_OUT"
else
  echo "[WARN] icon source not found: $ICON_SRC"
fi

# --- create app bundle ---
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>zh_CN</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIdentifier</key><string>com.egoist.toolsbox</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><false/>
PLIST

if [ -f "$ICNS_OUT" ]; then
cat >> "$APP_DIR/Contents/Info.plist" <<PLIST
  <key>CFBundleIconFile</key><string>AppIcon</string>
PLIST
  cp "$ICNS_OUT" "$APP_DIR/Contents/Resources/AppIcon.icns"
fi

cat >> "$APP_DIR/Contents/Info.plist" <<'PLIST'
</dict>
</plist>
PLIST

cat > "$APP_DIR/Contents/MacOS/launcher" <<'LAUNCH'
#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="__REPO_DIR__"
PY="$REPO_DIR/.venv/bin/python"
APP="$REPO_DIR/app_main.py"

if [ ! -x "$PY" ]; then
  /usr/bin/osascript -e 'display alert "代码工具箱" message "找不到 Python 虚拟环境：请先在仓库目录运行一次 bash dev_run.sh"'
  exit 1
fi

# When launched from .app, pass icon path so Qt uses the masked icns (Dock looks correct)
APP_RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
export TOOLBOX_APP_ICON="$APP_RES/AppIcon.icns"

exec "$PY" "$APP"
LAUNCH

# inject repo dir
sed -i '' "s|__REPO_DIR__|${REPO_DIR}|g" "$APP_DIR/Contents/MacOS/launcher"

chmod +x "$APP_DIR/Contents/MacOS/launcher"

echo "OK: $APP_DIR"
