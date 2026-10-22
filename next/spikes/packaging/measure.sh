#!/usr/bin/env bash
# Run all measurements -> results-2026-10-22.json. Needs build_pbs.sh and build_pyinstaller.sh run first.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"
[ -x "$PBS_APP/bin/python3.14" ] || { echo "run build_pbs.sh first" >&2; exit 2; }
[ -x "$PYI_APP/toolbox-backend" ] || { echo "run build_pyinstaller.sh first" >&2; exit 2; }
/usr/bin/python3 "$HERE/measure.py" "$@"
