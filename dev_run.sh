#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

git pull --ff-only

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -U pip >/dev/null
python -m pip install -r requirements.txt >/dev/null

python app_main.py
