"""Single source of truth for the app version.

The 4th segment is auto-bumped on every git commit by the pre-commit hook
(see .githooks/pre-commit + scripts/bump_version.py). Each segment carries at
9 -> 0 into the one to its left (1.0.0.9 -> 1.0.1.0). Manual releases may set
the first three segments explicitly via release_github.sh.
"""

__version__ = "1.0.3.8"
