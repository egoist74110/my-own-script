#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

git pull --ff-only

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -U pip >/dev/null
# Install deps; filter Windows-only packages on macOS
if [[ "$(uname)" == "Darwin" ]]; then
  python -m pip install -r requirements-mac.txt >/dev/null
else
  python -m pip install -r requirements.txt >/dev/null
fi

python app_main.py
