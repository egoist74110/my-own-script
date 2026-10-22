"""Contract drift checks, run only on temporary copies (repo contract files are never written)."""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from .harness import BACKEND_DIR

NEXT_DIR = BACKEND_DIR.parent
REPO_CONTRACTS = NEXT_DIR / "contracts"


def _copy_tree(tmp_path: Path) -> Path:
    root = tmp_path / "next"
    shutil.copytree(
        BACKEND_DIR / "src", root / "backend" / "src", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(REPO_CONTRACTS, root / "contracts")
    (root / "home").mkdir()
    return root


def _env(root: Path, hashseed: str = "0") -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join([str(root / "backend" / "src"), os.environ["PYTHONPATH"]]),
        "PYTHON_KEYRING_BACKEND": os.environ["PYTHON_KEYRING_BACKEND"],
        "TOOLBOX_TEST_GUARD_LOG": os.environ["TOOLBOX_TEST_GUARD_LOG"],
        "TOOLBOX_DATA_DIR": str(root / "data"),
        "TOOLBOX_LEGACY_CONFIG_DIR": str(root / "legacy"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": hashseed,
        "HOME": str(root / "home"),
    }


def _run(root: Path, *args: str, hashseed: str = "0") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "toolbox_backend.contracts", *args],
        cwd=root,
        env=_env(root, hashseed),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    root = _copy_tree(tmp_path)
    probe = subprocess.run(
        [sys.executable, "-c", "import toolbox_backend.contracts as c; print(c.CONTRACTS_DIR)"],
        cwd=root,
        env=_env(root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == str(root / "contracts"), (
        "must import the temp copy, not the repo"
    )
    return root


def test_untampered_copy_check_exits_zero(copy):
    r = _run(copy, "--check")
    assert r.returncode == 0, r.stderr


def test_check_is_read_only(copy):
    before = {p.name: _sha(p) for p in (copy / "contracts").iterdir()}
    mtimes = {p.name: p.stat().st_mtime_ns for p in (copy / "contracts").iterdir()}
    assert _run(copy, "--check").returncode == 0
    assert {p.name: _sha(p) for p in (copy / "contracts").iterdir()} == before
    assert {p.name: p.stat().st_mtime_ns for p in (copy / "contracts").iterdir()} == mtimes


def test_semantic_edit_to_openapi_is_detected(copy):
    f = copy / "contracts" / "openapi.json"
    f.write_text(f.read_text().replace("TOOLBOX backend", "TOOLBOX backend (edited)"))
    r = _run(copy, "--check")
    assert r.returncode == 1, (r.returncode, r.stderr)
    assert "contract drift: openapi.json" in r.stderr


def test_removed_trailing_newline_is_detected(copy):
    f = copy / "contracts" / "events.schema.json"
    f.write_text(f.read_text().rstrip("\n"))
    r = _run(copy, "--check")
    assert r.returncode == 1, (r.returncode, r.stderr)
    assert "events.schema.json" in r.stderr


def test_missing_contract_file_is_detected(copy):
    (copy / "contracts" / "events.schema.json").unlink()
    r = _run(copy, "--check")
    assert r.returncode == 1, (r.returncode, r.stderr)
    assert "events.schema.json" in r.stderr


def test_both_tampered_files_are_both_reported(copy):
    (copy / "contracts" / "openapi.json").write_text("{}\n")
    (copy / "contracts" / "events.schema.json").write_text("{}\n")
    r = _run(copy, "--check")
    assert r.returncode == 1
    assert "openapi.json" in r.stderr and "events.schema.json" in r.stderr


def test_regeneration_after_tamper_restores_passing_check(copy):
    (copy / "contracts" / "openapi.json").write_text("{}\n")
    assert _run(copy, "--check").returncode == 1
    assert _run(copy).returncode == 0
    assert _run(copy, "--check").returncode == 0
    assert _sha(copy / "contracts" / "openapi.json") == _sha(REPO_CONTRACTS / "openapi.json")
    assert _sha(copy / "contracts" / "events.schema.json") == _sha(
        REPO_CONTRACTS / "events.schema.json"
    )


def test_generation_is_independent_of_hash_seed(tmp_path):
    outputs = []
    for seed in ("0", "424242"):
        root = _copy_tree(tmp_path / f"seed-{seed}")
        shutil.rmtree(root / "contracts")
        assert _run(root, hashseed=seed).returncode == 0
        outputs.append({p.name: p.read_bytes() for p in (root / "contracts").iterdir()})
    assert outputs[0] == outputs[1]
    assert set(outputs[0]) == {"openapi.json", "events.schema.json"}
