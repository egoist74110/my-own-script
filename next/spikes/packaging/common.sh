# shellcheck shell=bash
# Shared paths for the S0-D packaging spike. Source, do not execute.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKEND="$REPO/next/backend"
SPIKE_HERE="$REPO/next/spikes/packaging"
SPIKE="$REPO/next/.local/spike"
PBS_PY_DIR="$SPIKE/python"          # UV_PYTHON_INSTALL_DIR (only place uv may download an interpreter)
PBS_OUT="$SPIKE/pbs"                # plan A output
PBS_APP="$PBS_OUT/runtime"          # relocatable directory: interpreter + site-packages
PYI_ENV="$SPIKE/pyi-env"            # plan B own uv env (pyinstaller lives here, not in backend)
PYI_WORK="$SPIKE/pyi-work"
PYI_OUT="$SPIKE/pyinstaller"        # plan B output (onedir parent)
PYI_APP="$PYI_OUT/toolbox-backend"
