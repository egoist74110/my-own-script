#!/usr/bin/env bash
# Build relocatable python-build-standalone runtime + locked backend deps into next/build/app-resources/backend.
# Never downloads Python or packages from the network.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BACKEND="${TOOLBOX_BACKEND_DIR:-$REPO/next/backend}"
BUILD_DIR="${TOOLBOX_BUILD_DIR:-$REPO/next/build}"
RUNTIME_OUT="${TOOLBOX_RUNTIME_OUT:-$BUILD_DIR/app-resources/backend}"

if [ -z "${TOOLBOX_PBS_PYTHON_HOME:-}" ]; then
  echo "error: TOOLBOX_PBS_PYTHON_HOME is not set." >&2
  echo "hint: prepare the interpreter outside the build script first:" >&2
  echo "  UV_PYTHON_INSTALL_DIR=<dir> uv python install 3.14" >&2
  echo "  export TOOLBOX_PBS_PYTHON_HOME=<installed-interpreter-root>" >&2
  exit 2
fi

if [ ! -x "$TOOLBOX_PBS_PYTHON_HOME/bin/python3.14" ]; then
  echo "error: $TOOLBOX_PBS_PYTHON_HOME/bin/python3.14 not found or not executable." >&2
  echo "hint: run UV_PYTHON_INSTALL_DIR=... uv python install 3.14 by hand and point TOOLBOX_PBS_PYTHON_HOME to the interpreter root." >&2
  exit 2
fi

SRC_ROOT="$(cd "$TOOLBOX_PBS_PYTHON_HOME" && pwd -P)"
echo "[build_runtime] source interpreter: $SRC_ROOT"

# Guard the destructive rm: RUNTIME_OUT must be absolute, strictly inside BUILD_DIR, and not a protected dir.
if ! python3 - "$RUNTIME_OUT" "$BUILD_DIR" "$HOME" "$REPO" <<'PYEOF'
import os
import sys

out, build, home, repo = sys.argv[1:5]
if not out or not build or not os.path.isabs(out) or not os.path.isabs(build):
    sys.exit(1)
out_r, build_r = os.path.realpath(out), os.path.realpath(build)
protected = {os.path.realpath(p) for p in ("/", home, repo) if p}
if out_r in protected:
    sys.exit(1)
if not out_r.startswith(build_r.rstrip("/") + "/"):
    sys.exit(1)
sys.exit(0)
PYEOF
then
  echo "error: refusing to rm -rf RUNTIME_OUT='$RUNTIME_OUT': must be non-empty, absolute, strictly under BUILD_DIR='$BUILD_DIR', and not /, \$HOME or the repo root." >&2
  exit 2
fi
rm -rf "$RUNTIME_OUT"
mkdir -p "$(dirname "$RUNTIME_OUT")"
cp -R "$SRC_ROOT" "$RUNTIME_OUT"
rm -f "$RUNTIME_OUT/lib/python3.14/EXTERNALLY-MANAGED"

PY="$RUNTIME_OUT/bin/python3.14"
SP="$RUNTIME_OUT/lib/python3.14/site-packages"
mkdir -p "$SP" "$BUILD_DIR"

REQ="$BUILD_DIR/requirements.txt"
echo "[build_runtime] exporting locked dependencies (offline/frozen)..."
(
  cd "$BACKEND"
  UV_PYTHON_DOWNLOADS=never uv export --frozen --no-dev --no-emit-project --no-hashes -o "$REQ" >/dev/null
)

echo "[build_runtime] installing locked dependencies and backend package (--offline --no-deps)..."
UV_PYTHON_DOWNLOADS=never uv pip install --offline --python "$PY" --target "$SP" --no-deps -r "$REQ"
UV_PYTHON_DOWNLOADS=never uv pip install --offline --python "$PY" --target "$SP" --no-deps "$BACKEND"

# Copy MCP resources into wheel install layout:
# Backend resolves Path(__file__).resolve().parents[3] / "resources/mcp", which in site-packages/toolbox_backend/...
# lands at Resources/backend/lib/python3.14/resources/mcp.
MCP_SRC="$BACKEND/resources/mcp"
MCP_DST="$RUNTIME_OUT/lib/python3.14/resources/mcp"
rm -rf "$MCP_DST"
mkdir -p "$MCP_DST"
for fname in figma_mcp_concurrency.js lark_mcp_patches.js package.json package-lock.json; do
  if [ ! -f "$MCP_SRC/$fname" ]; then
    echo "error: missing MCP resource $MCP_SRC/$fname" >&2
    exit 1
  fi
  cp "$MCP_SRC/$fname" "$MCP_DST/$fname"
done

# `uv pip install --target` writes console scripts with absolute shebangs; the backend is started with -m, so drop them.
rm -rf "$SP/bin"

echo "[build_runtime] pruning runtime per prune-list-pbs.txt..."
for p in \
  lib/python3.14/test lib/python3.14/idlelib lib/python3.14/tkinter lib/python3.14/turtledemo \
  lib/python3.14/ensurepip lib/python3.14/lib2to3 lib/python3.14/pydoc_data lib/python3.14/turtle.py \
  lib/python3.14/config-3.14-darwin lib/python3.14/site-packages/pip \
  lib/python3.14/site-packages/PyObjCTest \
  lib/python3.14/lib-dynload/_tkinter.cpython-314-darwin.so \
  lib/tcl9.0 lib/tk9.0 lib/tcl9 lib/tk9 lib/itcl4.3.4 lib/thread3.0.1 lib/tdbc1.1.10 \
  lib/libtcl9.0.dylib lib/libtcl9tk9.0.dylib lib/libpython3.14.a \
  lib/libpython3.14.dylib lib/itcl4.3.8 lib/thread3.0.6 lib/pkgconfig \
  include share bin/idle3 bin/idle3.14 bin/pydoc3 bin/pydoc3.14 bin/pip bin/pip3 bin/pip3.14 \
  bin/python3.14-config bin/python3-config; do
  if [ -e "$RUNTIME_OUT/$p" ] || [ -L "$RUNTIME_OUT/$p" ]; then
    rm -rf "${RUNTIME_OUT:?}/$p"
  fi
done

find "$RUNTIME_OUT/lib/python3.14" -type d \( -name tests -o -name test -o -name __pycache__ \) \
  -prune -exec rm -rf {} +
# Debug symbols shipped inside wheels (pyobjc); never loaded at runtime.
find "$RUNTIME_OUT" -type d -name '*.dSYM' -prune -exec rm -rf {} +

echo "[build_runtime] precompiling bytecode (--invalidation-mode unchecked-hash)..."
"$PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$RUNTIME_OUT/lib/python3.14"

echo "[build_runtime] running isolated import self-check..."
env -i HOME=/nonexistent PATH=/usr/bin:/bin "$PY" -I -c \
  'import toolbox_backend, uvicorn, fastapi, websockets, pydantic; print("import ok", toolbox_backend.__file__)'

echo "[build_runtime] done: $RUNTIME_OUT"
