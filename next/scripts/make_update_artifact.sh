#!/usr/bin/env bash
# Build the distributable updater artifact from the FINAL (signed [+ notarized/stapled]) app:
#   <dist>/TOOLBOX.app.tar.gz        re-tarred from the signed app (never from cargo target dir)
#   <dist>/TOOLBOX.app.tar.gz.sig    minisign signature (needs TAURI_SIGNING_PRIVATE_KEY[_PASSWORD] in env)
# The private key is only read from the environment by the tauri CLI; it never goes into argv or logs.
# usage: make_update_artifact.sh [--allow-unsigned] <path/to/TOOLBOX.app> [<dist-dir>]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
DESKTOP="$REPO/next/desktop"
BUILD_DIR="${TOOLBOX_BUILD_DIR:-$REPO/next/build}"

ALLOW_UNSIGNED=0
if [ "${1:-}" = "--allow-unsigned" ]; then
  ALLOW_UNSIGNED=1
  shift
fi
if [ $# -lt 1 ] || [ $# -gt 2 ] || [ -z "$1" ]; then
  echo "usage: make_update_artifact.sh [--allow-unsigned] <TOOLBOX.app> [<dist-dir>]" >&2
  exit 2
fi
APP="$1"
DIST_DIR="${2:-${TOOLBOX_DIST_DIR:-$BUILD_DIR/dist}}"
if [ ! -d "$APP" ]; then
  echo "error: app bundle not found: $APP" >&2
  exit 2
fi
APP_ABS="$(cd "$APP" && pwd)"
APP_NAME="$(basename "$APP_ABS")"

# Only a Developer ID signed app may become a distributable update.
CS_INFO="$(codesign -dv --verbose=2 "$APP_ABS" 2>&1 || true)"
if ! codesign -dv "$APP_ABS" >/dev/null 2>&1; then
  SIGN_STATE="unsigned"
elif printf '%s' "$CS_INFO" | grep -q 'Signature=adhoc'; then
  SIGN_STATE="adhoc"
else
  SIGN_STATE="identity"
fi
if [ "$SIGN_STATE" != "identity" ]; then
  echo "[make_update_artifact] app is $SIGN_STATE: ad-hoc/unsigned builds do NOT produce a distributable update package." >&2
  if [ "$ALLOW_UNSIGNED" -ne 1 ]; then
    echo "error: sign with --sign identity (and notarize) first, or pass --allow-unsigned for local testing only." >&2
    exit 2
  fi
  echo "[make_update_artifact] --allow-unsigned: continuing; DO NOT publish the result." >&2
fi

mkdir -p "$DIST_DIR"
TARBALL="$DIST_DIR/TOOLBOX.app.tar.gz"
TMP_TAR="$TARBALL.tmp.$$"
trap 'rm -f "$TMP_TAR"' EXIT
rm -f "$TARBALL" "$TARBALL.sig"
echo "[make_update_artifact] tarring signed app -> $TARBALL"
COPYFILE_DISABLE=1 tar -C "$(dirname "$APP_ABS")" -czf "$TMP_TAR" "$APP_NAME"
mv "$TMP_TAR" "$TARBALL"

if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]; then
  echo "[make_update_artifact] TAURI_SIGNING_PRIVATE_KEY not set: skipping minisign signature; $TARBALL is NOT publishable without a .sig." >&2
  exit 0
fi
echo "[make_update_artifact] signing tarball with minisign key from environment..."
(
  cd "$DESKTOP"
  pnpm tauri signer sign "$TARBALL"
)
if [ ! -s "$TARBALL.sig" ]; then
  echo "error: signer did not produce $TARBALL.sig" >&2
  exit 1
fi
echo "[make_update_artifact] done: $TARBALL and $TARBALL.sig"
