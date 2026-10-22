#!/usr/bin/env bash
# Plan A: python-build-standalone runtime + locked backend deps -> relocatable directory.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"

mkdir -p "$PBS_PY_DIR" "$PBS_OUT"
# The single allowed interpreter download of this spike.
UV_PYTHON_INSTALL_DIR="$PBS_PY_DIR" uv python install 3.14
SRC="$(UV_PYTHON_INSTALL_DIR="$PBS_PY_DIR" UV_PYTHON_DOWNLOADS=never uv python find --no-project 3.14)"
SRC_ROOT="$(cd "$(dirname "$SRC")/.." && pwd -P)"
echo "pbs source: $SRC_ROOT"

rm -rf "$PBS_APP"
cp -R "$SRC_ROOT" "$PBS_APP"
rm -f "$PBS_APP/lib/python3.14/EXTERNALLY-MANAGED"
PY="$PBS_APP/bin/python3.14"
SP="$PBS_APP/lib/python3.14/site-packages"

REQ="$PBS_OUT/requirements.txt"
(cd "$BACKEND" && UV_PYTHON_DOWNLOADS=never uv export --frozen --no-dev --no-emit-project --no-hashes -o "$REQ" >/dev/null)
# locked deps + the project itself (wheel build, non-editable) into the runtime's own site-packages
UV_PYTHON_DOWNLOADS=never uv pip install --python "$PY" --target "$SP" --no-deps -r "$REQ"
UV_PYTHON_DOWNLOADS=never uv pip install --python "$PY" --target "$SP" --no-deps "$BACKEND"

echo "size before prune (KiB): $(du -sk "$PBS_APP" | cut -f1)" | tee "$PBS_OUT/prune.log"
{
  echo "# prune list (relative to runtime/)"
  for p in \
    lib/python3.14/test lib/python3.14/idlelib lib/python3.14/tkinter lib/python3.14/turtledemo \
    lib/python3.14/ensurepip lib/python3.14/lib2to3 lib/python3.14/pydoc_data lib/python3.14/turtle.py \
    lib/python3.14/config-3.14-darwin lib/python3.14/site-packages/pip \
    lib/python3.14/lib-dynload/_tkinter.cpython-314-darwin.so \
    lib/tcl9.0 lib/tk9.0 lib/tcl9 lib/tk9 lib/itcl4.3.4 lib/thread3.0.1 lib/tdbc1.1.10 \
    lib/libtcl9.0.dylib lib/libtcl9tk9.0.dylib lib/libpython3.14.a \
    lib/libpython3.14.dylib lib/itcl4.3.8 lib/thread3.0.6 lib/pkgconfig \
    include share bin/idle3 bin/idle3.14 bin/pydoc3 bin/pydoc3.14 bin/pip bin/pip3 bin/pip3.14 \
    bin/python3.14-config bin/python3-config; do
    if [ -e "$PBS_APP/$p" ]; then rm -rf "${PBS_APP:?}/$p"; echo "removed $p"; fi
  done
  # tests / caches inside installed deps and stdlib
  find "$PBS_APP/lib/python3.14" -type d \( -name tests -o -name test -o -name __pycache__ \) \
    -prune -print -exec rm -rf {} + | sed 's|^'"$PBS_APP"'/|removed (dir) |'
  find "$SP" -maxdepth 1 -name '*.dist-info' -print0 | xargs -0 -I{} true
} > "$PBS_OUT/prune-list.txt"
echo "size after prune, no pyc (KiB): $(du -sk "$PBS_APP" | cut -f1)" | tee -a "$PBS_OUT/prune.log"

# precompile (a signed .app is read-only: pyc must ship). unchecked-hash keeps relocation safe.
"$PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$PBS_APP/lib/python3.14" || true
echo "size after compileall (KiB): $(du -sk "$PBS_APP" | cut -f1)" | tee -a "$PBS_OUT/prune.log"

env -i HOME=/nonexistent PATH=/usr/bin:/bin "$PY" -I -c 'import toolbox_backend, uvicorn, fastapi, websockets, pydantic; print("import ok", toolbox_backend.__file__)'
