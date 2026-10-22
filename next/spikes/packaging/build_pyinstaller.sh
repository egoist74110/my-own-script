#!/usr/bin/env bash
# Plan B: PyInstaller onedir of toolbox_backend, using a spike-private uv env (not next/backend's deps).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"

mkdir -p "$SPIKE"
# interpreter for the env: the PBS 3.14 installed by build_pbs.sh (no new download)
BASE_PY="$(UV_PYTHON_INSTALL_DIR="$PBS_PY_DIR" UV_PYTHON_DOWNLOADS=never uv python find --no-project 3.14)"
rm -rf "$PYI_ENV" "$PYI_WORK" "$PYI_OUT"
UV_PYTHON_DOWNLOADS=never uv venv --python "$BASE_PY" "$PYI_ENV"
PY="$PYI_ENV/bin/python"
REQ="$SPIKE/pyi-requirements.txt"
(cd "$BACKEND" && UV_PYTHON_DOWNLOADS=never uv export --frozen --no-dev --no-emit-project --no-hashes -o "$REQ" >/dev/null)
UV_PYTHON_DOWNLOADS=never uv pip install --python "$PY" --no-deps -r "$REQ"
UV_PYTHON_DOWNLOADS=never uv pip install --python "$PY" --no-deps "$BACKEND"
UV_PYTHON_DOWNLOADS=never uv pip install --python "$PY" pyinstaller
"$PY" -m PyInstaller --version

# entry shim: same early-signal behaviour as `python -m toolbox_backend` via its __main__ module
ENTRY="$SPIKE/pyi-entry.py"
cat > "$ENTRY" <<'PYEOF'
import runpy
runpy.run_module("toolbox_backend", run_name="__main__", alter_sys=True)
PYEOF

"$PY" -m PyInstaller --noconfirm --clean --onedir --name toolbox-backend \
  --distpath "$PYI_OUT" --workpath "$PYI_WORK" --specpath "$PYI_WORK" \
  --collect-submodules toolbox_backend \
  --collect-submodules uvicorn \
  --collect-submodules websockets \
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on \
  --hidden-import uvicorn.protocols.websockets.websockets_sansio_impl \
  --exclude-module tkinter --exclude-module unittest --exclude-module pydoc_data \
  "$ENTRY"
echo "pyinstaller size (KiB): $(du -sk "$PYI_APP" | cut -f1)"
env -i HOME=/nonexistent PATH=/usr/bin:/bin "$PYI_APP/toolbox-backend" --help 2>&1 | head -5 || true
