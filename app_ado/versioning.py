"""Version bump logic — pure, importable, and unit-tested.

The version is a base-10 odometer of (up to) 4 segments. Bumping increments the
last segment; segments 2..4 carry at 9 -> 0 into the segment on their left. The
major (1st) segment is never capped.

    1.0.0   -> 1.0.0.1
    1.0.0.9 -> 1.0.1.0
    1.0.9.9 -> 1.1.0.0
    1.9.9.9 -> 2.0.0.0
"""

from __future__ import annotations

import re
from pathlib import Path

_VERSION_RE = re.compile(r"""__version__\s*=\s*["']([^"']+)["']""")

_FILE_TEMPLATE = '''\
"""Single source of truth for the app version.

The 4th segment is auto-bumped on every git commit by the pre-commit hook
(see .githooks/pre-commit + scripts/bump_version.py). Each segment carries at
9 -> 0 into the one to its left (1.0.0.9 -> 1.0.1.0). Manual releases may set
the first three segments explicitly via release_github.sh.
"""

__version__ = "{version}"
'''


def bump_version(v: str) -> str:
    """Increment the last segment of *v* with 0-9 carry into higher segments.

    Input is normalized to 4 segments before bumping ("1.0.0" -> "1.0.0.0").
    """
    parts = [int(x) for x in v.strip().split(".")]
    while len(parts) < 4:
        parts.append(0)
    parts = parts[:4]

    parts[3] += 1
    for i in (3, 2, 1):  # carry from the lowest segment up; major (index 0) is uncapped
        if parts[i] > 9:
            carry, parts[i] = divmod(parts[i], 10)
            parts[i - 1] += carry
    return ".".join(str(x) for x in parts)


def read_version(path: Path) -> str:
    """Extract __version__ from an app_version.py-style file."""
    text = Path(path).read_text(encoding="utf-8")
    m = _VERSION_RE.search(text)
    if not m:
        raise ValueError(f"无法在 {path} 中解析 __version__")
    return m.group(1)


def write_version(path: Path, version: str) -> None:
    """Rewrite an app_version.py-style file with *version*, preserving the docstring."""
    Path(path).write_text(_FILE_TEMPLATE.format(version=version), encoding="utf-8")
