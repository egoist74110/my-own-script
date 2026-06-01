from __future__ import annotations

from pathlib import Path

import pytest

from app_ado.versioning import bump_version, read_version, write_version


@pytest.mark.parametrize(
    "cur,expected",
    [
        ("1.0.0", "1.0.0.1"),       # base 3-segment normalizes to 4 then +1
        ("1.0.0.1", "1.0.0.2"),
        ("1.0.0.9", "1.0.1.0"),     # 4th carries into 3rd
        ("1.0.9.9", "1.1.0.0"),     # carry ripples up two places
        ("1.9.9.9", "2.0.0.0"),     # carry bumps the major
        ("2.0.0", "2.0.0.1"),       # manual major release continues auto-bump
        ("1.0.0.10", "1.0.1.1"),    # non-canonical input normalizes via carry
    ],
)
def test_bump_version(cur: str, expected: str) -> None:
    assert bump_version(cur) == expected


def test_read_write_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "app_version.py"
    write_version(f, "1.2.3.4")
    assert read_version(f) == "1.2.3.4"
    # Bumping the file's value and writing it back stays parseable.
    write_version(f, bump_version(read_version(f)))
    assert read_version(f) == "1.2.3.5"


def test_write_preserves_module_shape(tmp_path: Path) -> None:
    f = tmp_path / "app_version.py"
    write_version(f, "9.9.9.9")
    text = f.read_text(encoding="utf-8")
    assert text.startswith('"""')
    assert '__version__ = "9.9.9.9"' in text
