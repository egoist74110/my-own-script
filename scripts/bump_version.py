#!/usr/bin/env python3
"""Bump app_version.py by one (called from the pre-commit hook).

Reads the current version, increments the last segment (with 0-9 carry), writes
it back, and prints the new version. Pure logic lives in app_ado.versioning so
it stays unit-testable.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_ado.versioning import bump_version, read_version, write_version  # noqa: E402

VERSION_FILE = ROOT / "app_version.py"


def main() -> int:
    cur = read_version(VERSION_FILE)
    new = bump_version(cur)
    write_version(VERSION_FILE, new)
    print(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
