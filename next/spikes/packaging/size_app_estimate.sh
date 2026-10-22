#!/usr/bin/env bash
# Estimate full .app size = unsigned Tauri shell .app + runtime copied into Contents/Resources (no signing).
# Prints JSON lines; merged into results by hand-run python in README step. Only touches next/.local/spike/appest.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"
SHELL_APP="$REPO/.local/cargo-target/release/bundle/macos/TOOLBOX.app"
W="$SPIKE/appest"
rm -rf "$W"; mkdir -p "$W"
echo "shell_app_kib $(du -sk "$SHELL_APP" | cut -f1)"
echo "shell_binary_kib $(du -sk "$REPO/.local/cargo-target/release/toolbox-desktop" | cut -f1)"
ditto -c -k --sequesterRsrc --keepParent "$SHELL_APP" "$W/shell.zip"; echo "shell_app_zip_kib $(( ($(stat -f %z "$W/shell.zip")+1023)/1024 ))"
for v in pbs pyi; do
  rm -rf "$W/$v"; mkdir -p "$W/$v"; cp -R "$SHELL_APP" "$W/$v/TOOLBOX.app"
  if [ "$v" = pbs ]; then cp -R "$PBS_APP" "$W/$v/TOOLBOX.app/Contents/Resources/backend"; else cp -R "$PYI_APP" "$W/$v/TOOLBOX.app/Contents/Resources/backend"; fi
  echo "app_${v}_kib $(du -sk "$W/$v/TOOLBOX.app" | cut -f1)"
  ditto -c -k --sequesterRsrc --keepParent "$W/$v/TOOLBOX.app" "$W/$v.zip"; echo "app_${v}_zip_kib $(( ($(stat -f %z "$W/$v.zip")+1023)/1024 ))"
done
rm -rf "$W"
