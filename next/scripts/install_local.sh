#!/usr/bin/env bash
# One-command local dev install: build (ad-hoc) -> quit the running app gracefully -> replace
# /Applications/代码工具箱.app -> optionally relaunch. For this machine only (ad-hoc, not distributable).
# usage: install_local.sh [--skip-build] [--open] [--dest <dir>]
#   --skip-build  reuse next/build/out/代码工具箱.app as is
#   --open        launch the installed app afterwards
#   --dest <dir>  install directory (default /Applications)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUT_APP="${TOOLBOX_OUT_DIR:-$REPO/next/build/out}/代码工具箱.app"
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
DEST_APP="$DEST_DIR/代码工具箱.app"

# Quit the installed app: SIGTERM to its exact main-process PID(s) takes the app's own coordinated
# shutdown path (same as tray "退出": backend stopped first). Never pkill by name.
APP_BIN="$DEST_APP/Contents/MacOS/toolbox-desktop"
app_pids() { pgrep -f "$APP_BIN" 2>/dev/null || true; }
PIDS="$(app_pids)"
if [ -n "$PIDS" ]; then
  echo "[install_local] quitting running TOOLBOX (SIGTERM: $(echo $PIDS))..."
  for pid in $PIDS; do kill -TERM "$pid" 2>/dev/null || true; done
  for _ in $(seq 1 60); do
    [ -z "$(app_pids)" ] && break
    sleep 0.5
  done
  if [ -n "$(app_pids)" ]; then
    echo "error: TOOLBOX is still running after 30s; quit it manually (Cmd+Q) and re-run with --skip-build." >&2
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
