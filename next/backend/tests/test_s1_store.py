import asyncio
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import Config


async def test_read_does_not_create_and_atomic_writes_are_private(tmp_path):
    data = tmp_path / "data"
    store = ConfigStore(data)
    assert (await store.read()).revision == 0
    assert not data.exists()
    await store.update(0, lambda c: None)
    assert (await store.read()).revision == 1
    assert stat.S_IMODE(data.stat().st_mode) == 0o700
    for path in data.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    before = store.path.stat().st_mtime_ns
    await store.read()
    assert store.path.stat().st_mtime_ns == before


@pytest.mark.parametrize("stage", ["before_replace", "after_replace"])
async def test_faults_never_leave_partial_json(tmp_path, stage):
    store = ConfigStore(tmp_path / "data")
    await store.update(0, lambda c: None)
    before = store.path.read_bytes()

    def fail(current):
        if current == stage:
            raise OSError("injected fault")

    store.checkpoint = fail
    if stage == "before_replace":
        with pytest.raises(SettingsError):
            await store.update(1, lambda c: None)
        assert store.path.read_bytes() == before
    else:
        # replace committed: post-replace exception must not fabricate a rollback.
        assert (await store.update(1, lambda c: None)).revision == 2
    assert json.loads(store.path.read_bytes())["revision"] in {1, 2}
    assert not list(store.data_dir.glob(".config-*"))


@pytest.mark.parametrize(
    "content", ['{"schema_version": 99}', "{bad", '{"schema_version":1,"ado":42}']
)
async def test_bad_store_stays_readonly_and_untouched(tmp_path, content):
    store = ConfigStore(tmp_path)
    store.path.write_text(content)
    for op in (store.read(), store.update(0, lambda c: None)):
        with pytest.raises(SettingsError) as exc:
            await op
        assert exc.value.code == "store_unavailable"
    assert store.path.read_text() == content
    assert list(tmp_path.iterdir()) == [store.path]


async def test_two_coroutines_compare_revision_under_lock(tmp_path):
    store = ConfigStore(tmp_path)
    values = await asyncio.gather(
        store.update(0, lambda c: None),
        store.update(0, lambda c: None),
        return_exceptions=True,
    )
    assert sum(isinstance(v, SettingsError) and v.code == "revision_conflict" for v in values) == 1
    assert (await store.read()).revision == 1


def test_two_processes_flock_and_stale_revision(tmp_path):
    data, barrier = tmp_path / "data", tmp_path / "barrier"
    barrier.mkdir()
    worker = Path(__file__).with_name("store_worker.py")
    processes = []

    def launch(role):
        proc = subprocess.Popen(
            [sys.executable, str(worker), str(data), str(barrier), role],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
        )
        processes.append(proc)
        return proc

    def wait_file(name):
        deadline = time.monotonic() + 5
        while not (barrier / name).exists():
            assert time.monotonic() < deadline, name
            time.sleep(0.01)

    try:
        first = launch("owner")
        wait_file("locked")
        second = launch("contender")
        wait_file("contending")
        (barrier / "release").touch()
        out1, err1 = first.communicate(timeout=10)
        out2, err2 = second.communicate(timeout=10)
        assert first.returncode == second.returncode == 0, (err1, err2)
        assert out1.strip() == b"committed"
        assert out2.strip() == b"revision_conflict"
        assert json.loads((data / "config.json").read_bytes())["revision"] == 1
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=5)


async def test_store_busy_has_bounded_wait(tmp_path):
    import fcntl

    store = ConfigStore(tmp_path)
    store.lock_timeout_s = 0.03
    with (tmp_path / "config.lock").open("wb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(SettingsError) as exc:
            await store.update(0, lambda c: None)
        assert exc.value.code == "store_busy"


async def test_cancelled_writer_waits_for_thread_and_releases_lock(tmp_path):
    import threading

    entered, release = threading.Event(), threading.Event()
    revisions = []
    store = ConfigStore(tmp_path, revisions.append)

    def pause(stage):
        if stage == "before_replace":
            entered.set()
            assert release.wait(timeout=3)

    store.checkpoint = pause
    task = asyncio.create_task(store.update(0, lambda c: None))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    store.checkpoint = lambda _: None
    assert (await store.update(1, lambda c: None)).revision == 2
    await asyncio.sleep(0)
    assert revisions == [1, 2]


def synthetic_v0(directory):
    raw = Config().model_dump(by_alias=True)
    raw.update(schema_version=0, revision=3, updated_at="2026-10-21T00:00:00Z")
    raw["old_library_name"] = "Synthetic library"
    original = (json.dumps(raw, indent=2) + "\n").encode()
    (directory / "config.json").write_bytes(original)
    return original


def v0_to_v1(raw):
    raw["ado"]["libraries"] = [
        {
            "id": "lib:synthetic",
            "name": raw.pop("old_library_name"),
            "base_url": "https://synthetic.example.test",
        }
    ]
    raw["schema_version"] = 1
    return raw


async def test_registered_migration_backs_up_original_before_atomic_replace(tmp_path):
    original = synthetic_v0(tmp_path)
    revisions = []
    store = ConfigStore(tmp_path, revisions.append, migrations={0: v0_to_v1})
    stages = []

    def checkpoint(stage):
        stages.append(stage)
        backups = list(tmp_path.glob("config.json.bak-v0-*"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
        if stage == "before_replace":
            assert store.path.read_bytes() == original

    store.checkpoint = checkpoint
    config = await store.initialize()
    assert config.schema_version == 2 and config.revision == 4
    assert config.ado.libraries[0].name == "Synthetic library"
    assert config.updated_at != "2026-10-21T00:00:00Z"
    assert stages == ["before_replace", "after_replace"]
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    await asyncio.sleep(0)
    assert revisions == [4]
    before = store.path.stat().st_mtime_ns
    await store.initialize()
    assert store.path.stat().st_mtime_ns == before
    assert len(list(tmp_path.glob("config.json.bak-*"))) == 1
    assert not list(tmp_path.glob(".config-*"))


async def test_read_never_migrates_even_with_registered_step(tmp_path):
    original = synthetic_v0(tmp_path)
    store = ConfigStore(tmp_path, migrations={0: v0_to_v1})
    with pytest.raises(SettingsError):
        await store.read()
    assert store.path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [store.path]
    assert (await store.initialize()).revision == 4


async def test_unknown_low_version_is_readonly_without_backup_or_reset(tmp_path):
    original = synthetic_v0(tmp_path)
    store = ConfigStore(tmp_path)
    with pytest.raises(SettingsError) as exc:
        await store.initialize()
    assert exc.value.code == "store_unavailable" and store.readonly_error
    with pytest.raises(SettingsError):
        await store.update(3, lambda c: None)
    assert store.path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [store.path]


@pytest.mark.parametrize(
    "failure",
    ["step", "invalid_version", "invalid_data", "backup", "backup_directory_sync", "replace"],
)
async def test_migration_failures_preserve_original_and_release_lock(
    tmp_path, monkeypatch, failure
):
    original = synthetic_v0(tmp_path)
    store = ConfigStore(tmp_path, migrations={0: v0_to_v1})
    if failure == "step":

        def fail_step(raw):
            raw.clear()
            raise RuntimeError("injected migration failure")

        store.migrations[0] = fail_step
    elif failure == "invalid_version":
        store.migrations[0] = lambda raw: {**raw, "schema_version": 9}
    elif failure == "invalid_data":
        store.migrations[0] = lambda raw: {**v0_to_v1(raw), "ado": None}
    elif failure == "backup":

        def fail_fsync(fd):
            raise OSError("injected backup fsync failure")

        monkeypatch.setattr(os, "fsync", fail_fsync)
    elif failure == "backup_directory_sync":

        def fail_sync_dir(directory):
            raise OSError("injected backup directory fsync failure")

        monkeypatch.setattr("toolbox_backend.adapters.config_store.sync_dir", fail_sync_dir)
    else:

        def fail(stage):
            if stage == "before_replace":
                raise OSError("injected replacement failure")

        store.checkpoint = fail
    with pytest.raises(SettingsError) as exc:
        await store.initialize()
    assert exc.value.code == "store_unavailable" and store.readonly_error
    assert store.path.read_bytes() == original
    assert not list(tmp_path.glob(".config-*"))
    backups = list(tmp_path.glob("config.json.bak-v0-*"))
    assert len(backups) == (1 if failure in {"replace", "backup_directory_sync"} else 0)
    for backup in backups:
        assert backup.read_bytes() == original
    monkeypatch.undo()
    # A separate owner can acquire flock after every failure path.
    repaired = ConfigStore(tmp_path, migrations={0: v0_to_v1})
    repaired.lock_timeout_s = 0.1
    assert (await repaired.initialize()).revision == 4


async def test_two_migration_owners_do_not_migrate_twice(tmp_path):
    original = synthetic_v0(tmp_path)
    first = ConfigStore(tmp_path, migrations={0: v0_to_v1})
    second = ConfigStore(tmp_path, migrations={0: v0_to_v1})
    configs = await asyncio.gather(first.initialize(), second.initialize())
    assert [c.revision for c in configs] == [4, 4]
    backups = list(tmp_path.glob("config.json.bak-v0-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
