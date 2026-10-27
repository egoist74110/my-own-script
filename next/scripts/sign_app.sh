#!/usr/bin/env bash
# Sign TOOLBOX.app in inside-out Mach-O order.
# Modes:
#   --identity  Uses $TOOLBOX_SIGN_IDENTITY (Developer ID Application name/hash; never reads private key/password)
#   --adhoc     Uses "-" ad-hoc signature (local verification only; prints prominent non-distributable warning)
# Exits 2 if neither --adhoc nor a valid $TOOLBOX_SIGN_IDENTITY is provided.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
ENTITLEMENTS="${TOOLBOX_ENTITLEMENTS_PLIST:-$REPO/next/desktop/src-tauri/entitlements.plist}"

MODE=""
APP_PATH=""

while [ $# -gt 0 ]; do
  case "$1" in
    --adhoc)
      MODE="adhoc"
      shift
      ;;
    --identity)
      MODE="identity"
      shift
      ;;
    -h|--help)
      echo "usage: sign_app.sh [--identity | --adhoc] <path-to-.app>" >&2
      exit 0
      ;;
    -*)
      echo "error: unknown flag: $1" >&2
      exit 2
      ;;
    *)
      if [ -z "$APP_PATH" ]; then
        APP_PATH="$1"
      else
        echo "error: unexpected extra argument: $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

if [ -z "$APP_PATH" ]; then
  echo "error: missing <path-to-.app> argument." >&2
  echo "usage: sign_app.sh [--identity | --adhoc] <path-to-.app>" >&2
  exit 2
fi

if [ -z "$MODE" ]; then
  if [ -n "${TOOLBOX_SIGN_IDENTITY:-}" ]; then
    MODE="identity"
  else
    echo "error: no signing mode specified and TOOLBOX_SIGN_IDENTITY is not set." >&2
    echo "hint: set TOOLBOX_SIGN_IDENTITY='<Developer ID Application: ...>' and pass --identity," >&2
    echo "      or pass --adhoc for local-only verification." >&2
    exit 2
  fi
fi

if [ "$MODE" = "identity" ] && [ -z "${TOOLBOX_SIGN_IDENTITY:-}" ]; then
  echo "error: --identity requires environment variable TOOLBOX_SIGN_IDENTITY to be set (certificate name or SHA-1 hash)." >&2
  exit 2
fi

if [ ! -d "$APP_PATH" ]; then
  echo "error: bundle directory not found: $APP_PATH" >&2
  exit 2
fi

if [ ! -f "$ENTITLEMENTS" ]; then
  echo "error: entitlements plist not found: $ENTITLEMENTS" >&2
  exit 2
fi

SIGN_ID="-"
COMMON_FLAGS=(-f)
if [ "$MODE" = "adhoc" ]; then
  echo "================================================================================" >&2
  echo "WARNING / 警告：当前使用 ad-hoc 签名（codesign -s -），仅限本机开发验证！" >&2
  echo "(无 hardened runtime：ad-hoc 无 Team ID，库验证会拒绝加载内置扩展)" >&2
  echo "不可分发，授权会随更新失效（TCC 屏幕录制/辅助功能授权绑定 cdhash，每次重签均会失效）。" >&2
  echo "================================================================================" >&2
else
  SIGN_ID="$TOOLBOX_SIGN_IDENTITY"
  # Hardened runtime enforces library validation (same Team ID); only meaningful with a real identity.
  COMMON_FLAGS+=(--options runtime --timestamp)
fi

BACKEND_DIR="$APP_PATH/Contents/Resources/backend"
PY_BIN="$BACKEND_DIR/bin/python3.14"
MAIN_BIN="$APP_PATH/Contents/MacOS/toolbox-desktop"

is_macho() {
  local f="$1"
  [ -f "$f" ] && [ ! -L "$f" ] || return 1
  local desc
  desc="$(file -b "$f" 2>/dev/null || true)"
  case "$desc" in
    *Mach-O*) return 0 ;;
    *) return 1 ;;
  esac
}

# 1. Sign all inner Mach-O files in Resources/backend (.so / .dylib / executables), excluding bin/python3.14
if [ -d "$BACKEND_DIR" ]; then
  while IFS= read -r -d '' candidate; do
    if [ "$candidate" = "$PY_BIN" ]; then
      continue
    fi
    if is_macho "$candidate"; then
      codesign "${COMMON_FLAGS[@]}" -s "$SIGN_ID" "$candidate"
    fi
  done < <(find "$BACKEND_DIR" -type f -print0 | sort -z)
fi

# 2. Sign Resources/backend/bin/python3.14
if [ -f "$PY_BIN" ] || [ -L "$PY_BIN" ]; then
  codesign "${COMMON_FLAGS[@]}" -s "$SIGN_ID" "$PY_BIN"
fi

# 3. Sign Contents/MacOS/toolbox-desktop
if [ -f "$MAIN_BIN" ]; then
  codesign "${COMMON_FLAGS[@]}" -s "$SIGN_ID" "$MAIN_BIN"
fi

# 4. Sign the outer .app bundle with entitlements
codesign "${COMMON_FLAGS[@]}" --entitlements "$ENTITLEMENTS" -s "$SIGN_ID" "$APP_PATH"
echo "[sign_app] signed ($MODE): $APP_PATH"
