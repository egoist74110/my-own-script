#!/usr/bin/env bash
set -euo pipefail

APP_NAME="代码工具箱"
REPO_DIR="${REPO_DIR:-$HOME/my-own-script}"
OUT_DIR="${OUT_DIR:-$REPO_DIR/dist}"

# Version source: app_version.py (preferred), else fallback to date-based.
VERSION="${VERSION:-}"
if [ -z "$VERSION" ]; then
  if [ -f "$REPO_DIR/app_version.py" ]; then
    if [ -x "$REPO_DIR/.venv/bin/python" ]; then
      VERSION=$(cd "$REPO_DIR" && "$REPO_DIR/.venv/bin/python" -c 'import app_version; print(app_version.__version__)')
    else
      VERSION=$(cd "$REPO_DIR" && python3 -c 'import app_version; print(app_version.__version__)')
    fi
  else
    VERSION=$(date +"%Y.%m.%d.%H%M")
  fi
fi

TAG="v$VERSION"
DMG_PATH="$OUT_DIR/$APP_NAME-$VERSION-mac.dmg"

cd "$REPO_DIR"

# Ensure app_version matches the release version to avoid always-prompting updates.
if [ -f "$REPO_DIR/app_version.py" ]; then
  echo "==> Sync app_version.py -> $VERSION"
  cat > "$REPO_DIR/app_version.py" <<PY
"""Single source of truth for the app version.

Keep this in sync with release notes / packaging.
"""

__version__ = "$VERSION"
PY
  # Commit version bump if needed
  if ! git diff --quiet -- app_version.py; then
    git add app_version.py
    git commit -m "chore: bump version to $VERSION" || true
    git push || true
  fi
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "[ERR] gh CLI not found. Install it first: https://cli.github.com/"
  exit 1
fi

# Ensure logged in (non-interactive check)
if ! gh auth status >/dev/null 2>&1; then
  echo "[ERR] gh is not authenticated. Run: gh auth login"
  exit 1
fi

echo "==> Build .app/.dmg"
bash pack_mac_app.sh
bash pack_mac_dmg.sh

if [ ! -f "$DMG_PATH" ]; then
  echo "[ERR] DMG not found: $DMG_PATH"
  exit 1
fi

echo "==> Create or update GitHub Release: $TAG"
if gh release view "$TAG" >/dev/null 2>&1; then
  echo "Release exists, uploading asset (clobber)…"
  gh release upload "$TAG" "$DMG_PATH" --clobber
else
  echo "Creating release and uploading asset…"
  gh release create "$TAG" "$DMG_PATH" \
    --title "$APP_NAME $VERSION" \
    --generate-notes
fi

echo "OK: uploaded $DMG_PATH to release $TAG"
