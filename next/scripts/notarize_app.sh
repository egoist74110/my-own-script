#!/usr/bin/env bash
# Submit signed TOOLBOX.app to Apple notary service and staple ticket.
# Reads only $TOOLBOX_NOTARY_PROFILE (notarytool keychain profile name).
# Never invoked automatically by other scripts; must be run manually when authorized.
set -euo pipefail

if [ $# -ne 1 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  echo "usage: notarize_app.sh <path-to-.app>" >&2
  [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && exit 0
  exit 2
fi

APP_PATH="$1"

if [ -z "${TOOLBOX_NOTARY_PROFILE:-}" ]; then
  echo "error: TOOLBOX_NOTARY_PROFILE is not set." >&2
  echo "hint: store credentials via 'xcrun notarytool store-credentials <profile>' and export TOOLBOX_NOTARY_PROFILE=<profile>." >&2
  exit 2
fi

if [ ! -d "$APP_PATH" ]; then
  echo "error: bundle directory not found: $APP_PATH" >&2
  exit 2
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/toolbox-notarize.XXXXXX")"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

ZIP_PATH="$TMP_DIR/$(basename "$APP_PATH").zip"
echo "[notarize_app] compressing $APP_PATH -> $ZIP_PATH"
ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

echo "[notarize_app] submitting to notarytool with keychain profile '$TOOLBOX_NOTARY_PROFILE'..."
xcrun notarytool submit "$ZIP_PATH" --keychain-profile "$TOOLBOX_NOTARY_PROFILE" --wait

echo "[notarize_app] stapling ticket to $APP_PATH..."
xcrun stapler staple "$APP_PATH"

echo "[notarize_app] done: $APP_PATH"
