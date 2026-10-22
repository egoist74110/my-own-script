#!/usr/bin/env bash
# Build the (unsigned) Tauri shell .app WITHOUT a bundled runtime, to size the shell. Does not modify formal config.
# beforeBuildCommand is blanked by the overlay so next/desktop/dist (already built) is used as-is.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"
export CARGO_TARGET_DIR="$REPO/.local/cargo-target"
cd "$REPO/next/desktop"
[ -f dist/index.html ] || { echo "next/desktop/dist missing; build the frontend first (not done by this spike)" >&2; exit 2; }
pnpm tauri build --bundles app --config "$HERE/tauri-empty.overlay.json"
APP="$CARGO_TARGET_DIR/release/bundle/macos/TOOLBOX.app"
echo "binary KiB: $(du -sk "$CARGO_TARGET_DIR/release/toolbox-desktop" 2>/dev/null | cut -f1)"
du -sk "$APP"
