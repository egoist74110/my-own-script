"""Tests for next/scripts/sync_version.py (stdlib only)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = HERE.parent
SYNC_SCRIPT = SCRIPTS_DIR / "sync_version.py"


def _make_fake_repo(
    root: Path,
    *,
    tauri_v: str = "1.0.0",
    cargo_v: str = "0.0.0",
    pkg_v: str = "0.0.0",
    pyproj_v: str = "0.1.0",
    init_v: str = "0.1.0",
) -> dict[str, Path]:
    tauri_conf = root / "next/desktop/src-tauri/tauri.conf.json"
    cargo_toml = root / "next/desktop/src-tauri/Cargo.toml"
    package_json = root / "next/desktop/package.json"
    pyproject_toml = root / "next/backend/pyproject.toml"

    tauri_conf.parent.mkdir(parents=True, exist_ok=True)
    pyproject_toml.parent.mkdir(parents=True, exist_ok=True)

    tauri_conf.write_text(
        json.dumps(
            {
                "productName": "TOOLBOX",
                "version": tauri_v,
                "identifier": "dev.toolbox.next",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    cargo_toml.write_text(
        '[package]\n'
        'name = "toolbox-desktop"\n'
        f'version = "{cargo_v}"\n'
        'description = "keep exact bytes"\n\n'
        '[dependencies]\n'
        'tauri = { version = "2", features = ["tray-icon"] }\n',
        encoding="utf-8",
    )

    package_json.write_text(
        '{\n'
        '  "name": "toolbox-desktop",\n'
        '  "private": true,\n'
        f'  "version": "{pkg_v}",\n'
        '  "dependencies": {\n'
        '    "vue": "^3.5.44"\n'
        '  }\n'
        '}\n',
        encoding="utf-8",
    )

    pyproject_toml.write_text(
        '[project]\n'
        'name = "toolbox-backend"\n'
        f'version = "{pyproj_v}"\n'
        'description = "TOOLBOX next"\n\n'
        '[tool.ruff]\n'
        'target-version = "py314"\n',
        encoding="utf-8",
    )

    backend_init = root / "next/backend/src/toolbox_backend/__init__.py"
    backend_init.parent.mkdir(parents=True, exist_ok=True)
    backend_init.write_text(
        '"""TOOLBOX next backend process."""\n\n' f'__version__ = "{init_v}"\n',
        encoding="utf-8",
    )

    return {
        "init": backend_init,
        "tauri": tauri_conf,
        "cargo": cargo_toml,
        "package": package_json,
        "pyproject": pyproject_toml,
    }


class TestSyncVersion(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SYNC_SCRIPT), *args],
            capture_output=True,
            text=True,
        )

    def test_check_fails_when_inconsistent_and_lists_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(
                root,
                tauri_v="1.0.0",
                cargo_v="0.0.0",
                pkg_v="0.0.0",
                pyproj_v="0.1.0",
            )
            res = self._run("--root", str(root), "--check")
            self.assertEqual(res.returncode, 1)
            combined = res.stdout + res.stderr
            self.assertIn("Cargo.toml", combined)
            self.assertIn("package.json", combined)
            self.assertIn("pyproject.toml", combined)
            self.assertIn("__init__.py", combined)
            self.assertIn("1.0.0", combined)

    def test_write_updates_only_target_versions_preserving_surrounding_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = _make_fake_repo(
                root,
                tauri_v="1.2.3",
                cargo_v="0.0.0",
                pkg_v="0.0.0",
                pyproj_v="0.1.0",
            )
            before_cargo = files["cargo"].read_bytes()
            before_pkg = files["package"].read_bytes()
            before_pyproj = files["pyproject"].read_bytes()
            before_init = files["init"].read_bytes()
            before_tauri = files["tauri"].read_bytes()

            res_write = self._run("--root", str(root), "--write")
            self.assertEqual(res_write.returncode, 0, msg=res_write.stderr)

            self.assertEqual(files["tauri"].read_bytes(), before_tauri)
            self.assertEqual(
                files["init"].read_bytes(),
                before_init.replace(b'"0.1.0"', b'"1.2.3"', 1),
            )
            self.assertEqual(
                files["cargo"].read_bytes(),
                before_cargo.replace(b'version = "0.0.0"', b'version = "1.2.3"', 1),
            )
            self.assertEqual(
                files["package"].read_bytes(),
                before_pkg.replace(b'"version": "0.0.0"', b'"version": "1.2.3"', 1),
            )
            self.assertEqual(
                files["pyproject"].read_bytes(),
                before_pyproj.replace(b'version = "0.1.0"', b'version = "1.2.3"', 1),
            )

            res_check = self._run("--root", str(root), "--check")
            self.assertEqual(res_check.returncode, 0, msg=res_check.stderr)

    def test_missing_file_exits_nonzero_with_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = _make_fake_repo(root)
            files["pyproject"].unlink()
            res = self._run("--root", str(root), "--check")
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("pyproject.toml", res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
