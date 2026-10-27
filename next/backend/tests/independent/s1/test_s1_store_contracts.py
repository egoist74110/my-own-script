import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import Config


async def test_two_process_writers_with_same_revision_leave_second_conflicted(tmp_path):
    data = tmp_path / "data"
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    worker = Path(__file__).resolve().parents[2] / "store_worker.py"  # noqa: ASYNC240
    children = []

    def start(role):
        process = subprocess.Popen(
            [sys.executable, str(worker), str(data), str(barrier), role],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
        )
        children.append(process)
        return process

    def wait_for(name):
        deadline = time.monotonic() + 8
        while not (barrier / name).exists():
            if time.monotonic() >= deadline:
                raise AssertionError(f"timed out waiting for {name}")
            time.sleep(0.01)

    try:
        owner = start("owner")
        wait_for("locked")
        contender = start("contender")
        wait_for("contending")
        (barrier / "release").touch()
        out1, err1 = owner.communicate(timeout=10)
        out2, err2 = contender.communicate(timeout=10)
        assert owner.returncode == contender.returncode == 0, (err1, err2)
        assert out1.strip() == b"committed"
        assert out2.strip() == b"revision_conflict"
        assert json.loads((data / "config.json").read_text())["revision"] == 1
        observer = ConfigStore(data)
        with pytest.raises(SettingsError) as stale:
            await observer.update(0, lambda config: None)
        assert stale.value.status == 409
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


async def test_cross_process_lock_timeout_maps_to_store_busy(tmp_path):
    store = ConfigStore(tmp_path / "data")
    store.lock_timeout_s = 0.03
    (tmp_path / "data").mkdir()
    with (tmp_path / "data/config.lock").open("wb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(SettingsError) as error:
            await store.update(0, lambda config: None)
    assert error.value.code == "store_busy"


@pytest.mark.parametrize("content", [b"{broken", b'{"schema_version":99}'])
async def test_corrupt_or_newer_schema_is_readonly_and_preserves_original(tmp_path, content):
    store = ConfigStore(tmp_path / "data")
    store.data_dir.mkdir()
    store.path.write_bytes(content)
    for operation in (store.read(), store.update(0, lambda config: None)):
        with pytest.raises(SettingsError) as error:
            await operation
        assert error.value.code == "store_unavailable"
    assert store.path.read_bytes() == content
    assert list(store.data_dir.iterdir()) == [store.path]


async def test_replace_failure_before_commit_preserves_original_bytes(tmp_path):
    store = ConfigStore(tmp_path / "data")
    await store.update(0, lambda config: None)
    original = store.path.read_bytes()

    def fail_before_replace(stage):
        if stage == "before_replace":
            raise OSError("injected replace boundary failure")

    store.checkpoint = fail_before_replace
    with pytest.raises(SettingsError) as error:
        await store.update(1, lambda config: None)
    assert error.value.code == "store_unavailable"
    assert store.path.read_bytes() == original
    assert not list(store.data_dir.glob(".config-*"))


async def test_unregistered_low_schema_version_is_readonly_and_untouched(tmp_path):
    store = ConfigStore(tmp_path / "data")
    store.data_dir.mkdir()
    raw = Config().model_dump(by_alias=True)
    raw.update(schema_version=0, revision=4, updated_at="2026-10-21T00:00:00Z")
    original = json.dumps(raw).encode()
    store.path.write_bytes(original)
    with pytest.raises(SettingsError) as error:
        await store.initialize()
    assert error.value.code == "store_unavailable"
    assert store.readonly_error
    assert store.path.read_bytes() == original
    assert list(store.data_dir.iterdir()) == [store.path]


async def test_registered_migration_keeps_backup_before_replacement(tmp_path):
    store = ConfigStore(tmp_path / "data")
    store.data_dir.mkdir()
    raw = Config().model_dump(by_alias=True)
    raw.update(schema_version=0, revision=4, updated_at="2026-10-21T00:00:00Z")
    original = json.dumps(raw, indent=2).encode()
    store.path.write_bytes(original)

    def migrate(previous):
        previous["schema_version"] = 1
        return previous

    store.migrations = {0: migrate}

    def inspect_before_replace(stage):
        backups = list(store.data_dir.glob("config.json.bak-v0-*"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original
        if stage == "before_replace":
            assert store.path.read_bytes() == original

    store.checkpoint = inspect_before_replace
    migrated = await store.initialize()
    assert migrated.schema_version == 6 and migrated.revision == 5
    assert store.path.read_bytes() != original
    assert len(list(store.data_dir.glob("config.json.bak-v0-*"))) == 1


async def test_fault_after_replace_reports_committed_revision(tmp_path):
    store = ConfigStore(tmp_path / "data")
    await store.update(0, lambda config: None)

    def fail_after_replace(stage):
        if stage == "after_replace":
            raise OSError("injected crash after atomic replace")

    store.checkpoint = fail_after_replace
    committed = await store.update(1, lambda config: None)
    assert committed.revision == 2
    assert json.loads(store.path.read_text())["revision"] == 2
    assert not list(store.data_dir.glob(".config-*"))
