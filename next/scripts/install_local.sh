#!/usr/bin/env bash
# One-command local dev install: build (ad-hoc) -> quit the running app gracefully -> replace
# /Applications/TOOLBOX.app -> optionally relaunch. For this machine only (ad-hoc, not distributable).
# usage: install_local.sh [--skip-build] [--open] [--dest <dir>]
#   --skip-build  reuse next/build/out/TOOLBOX.app as is
#   --open        launch the installed app afterwards
#   --dest <dir>  install directory (default /Applications)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUT_APP="${TOOLBOX_OUT_DIR:-$REPO/next/build/out}/TOOLBOX.app"
DEST_DIR="/Applications"
SKIP_BUILD=0
OPEN_AFTER=0

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-build) SKIP_BUILD=1 ;;
    --open) OPEN_AFTER=1 ;;
    --dest)
      [ $# -ge 2 ] || { echo "error: --dest needs a directory" >&2; exit 2; }
      DEST_DIR="$2"; shift ;;
    *) echo "usage: install_local.sh [--skip-build] [--open] [--dest <dir>]" >&2; exit 2 ;;
  esac
  shift
done

if [ "$SKIP_BUILD" -eq 0 ]; then
  # Full build (incl. frontend) so the installed app never carries a stale dist.
  : "${TOOLBOX_PBS_PYTHON_HOME:=$REPO/next/.local/spike/python/cpython-3.14.8-macos-aarch64-none}"
  export TOOLBOX_PBS_PYTHON_HOME
  bash "$HERE/build_app.sh" --sign adhoc
fi
[ -d "$OUT_APP" ] || { echo "error: $OUT_APP not found (run without --skip-build)" >&2; exit 1; }
[ -d "$DEST_DIR" ] || { echo "error: install dir not found: $DEST_DIR" >&2; exit 1; }
DEST_APP="$DEST_DIR/TOOLBOX.app"

# Quit the installed app via its own quit event (coordinated backend shutdown); never pkill.
if pgrep -f "$DEST_APP/Contents/MacOS/toolbox-desktop" >/dev/null 2>&1; then
  echo "[install_local] quitting running TOOLBOX..."
  osascript -e 'tell application id "dev.toolbox.next" to quit' >/dev/null 2>&1 || true
  for _ in $(seq 1 40); do
    pgrep -f "$DEST_APP/Contents/MacOS/toolbox-desktop" >/dev/null 2>&1 || break
    sleep 0.5
  done
  if pgrep -f "$DEST_APP/Contents/MacOS/toolbox-desktop" >/dev/null 2>&1; then
    echo "error: TOOLBOX is still running after 20s; quit it manually (Cmd+Q) and re-run with --skip-build." >&2
    exit 1
  fi
fi

echo "[install_local] installing -> $DEST_APP"
rm -rf "${DEST_APP:?}"
ditto "$OUT_APP" "$DEST_APP"
codesign --verify --deep --strict "$DEST_APP"
echo "[install_local] done: $DEST_APP"

if [ "$OPEN_AFTER" -eq 1 ]; then
  open "$DEST_APP"
fi
