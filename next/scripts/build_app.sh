#!/usr/bin/env bash
# End-to-end offline build pipeline for TOOLBOX.app:
#   1. sync_version.py --check
#   2. frontend: pnpm install --frozen-lockfile --offline + pnpm build (or --skip-frontend if dist exists)
#   3. build_runtime.sh
#   4. pnpm tauri build --bundles app --config src-tauri/tauri.bundle.conf.json
#   5. copy bundle to next/build/out/代码工具箱.app
#   6. optional: --sign adhoc | --sign identity
#   7. verify_app.sh next/build/out/代码工具箱.app
# Updater artifacts are NOT taken from the cargo bundle dir; see make_update_artifact.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
DESKTOP="${TOOLBOX_DESKTOP_DIR:-$REPO/next/desktop}"
BUILD_DIR="${TOOLBOX_BUILD_DIR:-$REPO/next/build}"
OUT_DIR="${TOOLBOX_OUT_DIR:-$BUILD_DIR/out}"

SKIP_FRONTEND=0
SIGN_MODE=""
UPDATER_CONFIG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-frontend)
      SKIP_FRONTEND=1
      shift
      ;;
    --sign)
      if [ $# -lt 2 ]; then
        echo "error: --sign requires an argument (adhoc | identity)" >&2
        exit 2
      fi
      case "$2" in
        adhoc|identity)
          SIGN_MODE="$2"
          ;;
        *)
          echo "error: invalid --sign mode '$2' (expected adhoc or identity)" >&2
          exit 2
          ;;
      esac
      shift 2
      ;;
    --sign=*)
      val="${1#--sign=}"
      case "$val" in
        adhoc|identity)
          SIGN_MODE="$val"
          ;;
        *)
          echo "error: invalid --sign mode '$val' (expected adhoc or identity)" >&2
          exit 2
          ;;
      esac
      shift
      ;;
    --updater-config)
      if [ $# -lt 2 ] || [ -z "$2" ]; then
        echo "error: --updater-config requires a file path" >&2
        exit 2
      fi
      UPDATER_CONFIG="$2"
      shift 2
      ;;
    --updater-config=*)
      UPDATER_CONFIG="${1#--updater-config=}"
      if [ -z "$UPDATER_CONFIG" ]; then
        echo "error: --updater-config requires a file path" >&2
        exit 2
      fi
      shift
      ;;
    -h|--help)
      echo "usage: build_app.sh [--skip-frontend] [--sign adhoc|identity] [--updater-config <file>]" >&2
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [ -n "$UPDATER_CONFIG" ] && [ ! -f "$UPDATER_CONFIG" ]; then
  echo "error: updater config file not found: $UPDATER_CONFIG" >&2
  exit 2
fi
if [ -n "$UPDATER_CONFIG" ]; then
  # Reject insecure/placeholder updater configs before any build work (exit 2).
  python3 "$HERE/validate_updater_config.py" "$UPDATER_CONFIG"
fi

# Preflight: name the missing piece in seconds instead of failing mid-build.
# Non-interactive shells (agents, cron) skip ~/.zshrc, so locate nvm's node and cargo ourselves.
if ! command -v pnpm >/dev/null 2>&1; then
  NVM_BIN="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)"
  [ -n "$NVM_BIN" ] && PATH="$NVM_BIN:$PATH"
fi
# rustup's shims must win over any other cargo, or rust-toolchain.toml is bypassed.
[ -d "$HOME/.cargo/bin" ] && PATH="$HOME/.cargo/bin:$PATH"
for d in "$HOME/.local/bin" /opt/homebrew/bin; do
  case ":$PATH:" in *":$d:"*) ;; *) [ -d "$d" ] && PATH="$PATH:$d" ;; esac
done
export PATH
export TOOLBOX_PBS_PYTHON_HOME="${TOOLBOX_PBS_PYTHON_HOME:-$REPO/next/.local/spike/python/cpython-3.14.8-macos-aarch64-none}"

preflight_fail=0
preflight_need() {
  command -v "$1" >/dev/null 2>&1 || { echo "preflight: '$1' not found ($2)" >&2; preflight_fail=1; }
}
preflight_need pnpm "install node via nvm, then 'npm i -g pnpm'"
preflight_need uv "brew install uv"
preflight_need cargo "install rustup"
preflight_need rustup "install rustup"
if [ ! -x "$TOOLBOX_PBS_PYTHON_HOME/bin/python3.14" ]; then
  echo "preflight: no Python runtime at $TOOLBOX_PBS_PYTHON_HOME" >&2
  echo "  fix: UV_PYTHON_INSTALL_DIR=$REPO/next/.local/spike/python uv python install 3.14" >&2
  preflight_fail=1
fi
# rust-toolchain.toml pins the compiler: rustc 1.95 + the macOS 27 linker emits proc-macro
# dylibs that dyld refuses to load ("mis-aligned LINKEDIT"), failing the build mid-way.
RUST_WANT="$(sed -n 's/^channel *= *"\(.*\)".*/\1/p' "$REPO/rust-toolchain.toml" 2>/dev/null || true)"
if [ -n "$RUST_WANT" ] && command -v rustup >/dev/null 2>&1; then
  rustup toolchain list | grep -q "^$RUST_WANT" \
    || { echo "preflight: Rust toolchain $RUST_WANT not installed (fix: rustup toolchain install $RUST_WANT)" >&2; preflight_fail=1; }
fi
[ "$preflight_fail" -eq 0 ] || exit 1
echo "[build_app] preflight ok: $(cd "$DESKTOP/src-tauri" && rustc --version), node $(node --version)"

echo "[build_app] step 1/6: checking version consistency..."
python3 "$HERE/sync_version.py" --root "$REPO" --check

echo "[build_app] step 2/6: preparing frontend dist..."
if [ "$SKIP_FRONTEND" -eq 1 ]; then
  if [ ! -f "$DESKTOP/dist/index.html" ]; then
    echo "error: --skip-frontend specified, but $DESKTOP/dist/index.html does not exist." >&2
    exit 1
  fi
  echo "[build_app] skipping frontend build (reusing existing $DESKTOP/dist)"
else
  (
    cd "$DESKTOP"
    pnpm install --frozen-lockfile --offline
    pnpm build
  )
fi

# The Tauri bundle embeds dist/ verbatim; an empty or stub page ships as a white window and
# verify_app.sh (backend-only) cannot catch it, so refuse such a dist here.
if ! grep -q '<script' "$DESKTOP/dist/index.html" 2>/dev/null \
  || ! find "$DESKTOP/dist/assets" -name '*.js' -type f 2>/dev/null | grep -q .; then
  echo "error: $DESKTOP/dist is not a real frontend build (index.html without <script> or no assets/*.js); run 'pnpm build' first." >&2
  exit 1
fi

echo "[build_app] step 3/6: building relocatable Python runtime..."
bash "$HERE/build_runtime.sh"

echo "[build_app] step 4/6: building Tauri .app bundle (offline)..."
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$REPO/.local/cargo-target}"
export CARGO_NET_OFFLINE=true

# Blank beforeBuildCommand via merged overlay so Tauri reuses the already-built dist/ without re-running pnpm build
OVERLAY_JSON="$BUILD_DIR/tauri.build.overlay.json"
RUNTIME_OUT="${TOOLBOX_RUNTIME_OUT:-$BUILD_DIR/app-resources/backend}"
mkdir -p "$BUILD_DIR"
python3 - "$DESKTOP/src-tauri/tauri.bundle.conf.json" "$OVERLAY_JSON" "$UPDATER_CONFIG" "$RUNTIME_OUT" <<'PYEOF'
import json
import os
import sys
from pathlib import Path


def deep_merge(base: dict, extra: dict) -> dict:
    for key, val in extra.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], val)
        else:
            base[key] = val
    return base


bundle_conf = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
bundle_conf.setdefault("build", {})["beforeBuildCommand"] = ""
# Point the "backend" resource at the actual runtime dir (honours TOOLBOX_BUILD_DIR/TOOLBOX_RUNTIME_OUT);
# resource keys are relative to the directory holding tauri.bundle.conf.json.
resources = bundle_conf.setdefault("bundle", {}).setdefault("resources", {})
for key in [k for k, v in resources.items() if v == "backend"]:
    del resources[key]
resources[os.path.relpath(os.path.abspath(sys.argv[4]), os.path.dirname(os.path.abspath(sys.argv[1])))] = "backend"
updater_path = sys.argv[3]
if updater_path:
    updater_conf = json.loads(Path(updater_path).read_text(encoding="utf-8"))
    if not isinstance(updater_conf, dict):
        raise SystemExit("error: updater config must be a JSON object")
    deep_merge(bundle_conf, updater_conf)
Path(sys.argv[2]).write_text(json.dumps(bundle_conf, indent=2) + "\n", encoding="utf-8")
PYEOF

(
  cd "$DESKTOP"
  pnpm tauri build --bundles app --config "$OVERLAY_JSON"
)

BUILT_APP="$CARGO_TARGET_DIR/release/bundle/macos/代码工具箱.app"
if [ ! -d "$BUILT_APP" ]; then
  echo "error: expected Tauri bundle output not found at $BUILT_APP" >&2
  exit 1
fi

echo "[build_app] step 5/6: copying bundle to $OUT_DIR/代码工具箱.app..."
mkdir -p "$OUT_DIR"
OUT_APP="$OUT_DIR/代码工具箱.app"
rm -rf "$OUT_APP"
cp -R "$BUILT_APP" "$OUT_APP"

if [ -n "$SIGN_MODE" ]; then
  echo "[build_app] signing $OUT_APP (--$SIGN_MODE)..."
  bash "$HERE/sign_app.sh" "--$SIGN_MODE" "$OUT_APP"
fi

echo "[build_app] step 6/6: verifying $OUT_APP..."
bash "$HERE/verify_app.sh" "$OUT_APP"

echo "[build_app] complete: $OUT_APP"
if [ -n "$UPDATER_CONFIG" ]; then
  echo "[build_app] NOTE: any .app.tar.gz/.sig under $CARGO_TARGET_DIR/release/bundle are from the UNSIGNED bundle; do not publish them." >&2
  echo "[build_app] NOTE: after signing/notarizing run: bash next/scripts/make_update_artifact.sh $OUT_APP  (ad-hoc builds yield no distributable update)." >&2
fi
