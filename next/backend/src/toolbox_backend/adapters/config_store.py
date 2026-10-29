"""Single file store: async serialization, bounded flock, validated atomic replacement."""

import asyncio
import contextlib
import copy
import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.models import utcnow
from toolbox_backend.domain.settings import Config, config_v6_to_v7, config_v7_to_v8
from toolbox_backend.logging_setup import contains_secret

T = TypeVar("T")
MigrationStep = Callable[[dict], dict]
CURRENT_SCHEMA_VERSION = 8


def stamp() -> str:
    return utcnow().isoformat()


def private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Transaction:
    def __init__(self, store: ConfigStore, config: Config):
        self.store = store
        self.config = config
        self.revisions: list[int] = []

    def commit(self, mutate: Callable[[Config], None]) -> Config:
        candidate = self.config.model_copy(deep=True)
        mutate(candidate)
        candidate.revision = self.config.revision + 1
        candidate.updated_at = stamp()
        try:
            candidate = Config.model_validate(candidate.model_dump(by_alias=True))
        except ValidationError:
            raise SettingsError("validation_error", "配置校验失败", 422) from None
        if self.store.before_commit:
            self.store.before_commit(self.config, candidate)
        self.store._write(candidate)
        self.config = candidate
        self.revisions.append(candidate.revision)
        return candidate.model_copy(deep=True)


class ConfigStore:
    def __init__(
        self,
        data_dir: Path,
        on_change: Callable[[int], None] | None = None,
        *,
        migrations: dict[int, MigrationStep] | None = None,
    ):
        self.data_dir = data_dir
        self.path = data_dir / "config.json"
        self.lock_timeout_s = 5.0
        self._lock = asyncio.Lock()
        self.on_change = on_change
        self.before_commit = None
        # v1 is the first production version. Only explicitly registered, pure steps
        # may upgrade an older version; no guessed v0 data shape or implicit reset.
        from toolbox_backend.domain.ai import config_v2_to_v3
        from toolbox_backend.domain.mcp import config_v3_to_v4
        from toolbox_backend.domain.services import config_v4_to_v5
        from toolbox_backend.domain.telegram import config_v1_to_v2
        from toolbox_backend.domain.vpn import config_v5_to_v6

        self.migrations = {
            1: config_v1_to_v2,
            2: config_v2_to_v3,
            3: config_v3_to_v4,
            4: config_v4_to_v5,
            5: config_v5_to_v6,
            6: config_v6_to_v7,
            7: config_v7_to_v8,
            **(migrations or {}),
        }
        self.readonly_error: str | None = None
        # Fault injection only: no runtime/environment hook.
        self.checkpoint: Callable[[str], None] = lambda _: None

    @staticmethod
    def _validate(raw: dict) -> Config:
        required = {
            "schema_version",
            "revision",
            "updated_at",
            "ado",
            "tasks",
            "imported",
            "import",
            "credentials",
        }
        if (
            not isinstance(raw, dict)
            or type(raw.get("schema_version")) is not int
            or raw["schema_version"] != CURRENT_SCHEMA_VERSION
            or not required.issubset(raw)
            or type(raw.get("revision")) is not int
            or raw["revision"] < 1
        ):
            raise ValueError
        return Config.model_validate(raw)

    def _read(self) -> Config:
        try:
            with self.path.open("rb") as stream:
                raw = json.load(stream)
            result = self._validate(raw)
            self.readonly_error = None
            return result
        except FileNotFoundError:
            if self.readonly_error:
                raise SettingsError("store_unavailable", self.readonly_error, 503) from None
            return Config()
        except OSError, ValueError, RecursionError:
            self.readonly_error = "存储版本不支持或文件损坏；请检查 config.json"
            raise SettingsError("store_unavailable", self.readonly_error, 503) from None

    async def read(self) -> Config:
        return await asyncio.to_thread(self._read)

    def _backup(self, original: bytes, version: int) -> None:
        target = self.data_dir / "migrations" if version in (1, 2, 3, 4, 5, 6, 7) else self.data_dir
        private_dir(target)
        prefix = (
            f"config-v{version}-{stamp().replace(':', '-')}"
            if version in (1, 2, 3, 4, 5, 6, 7)
            else (f"config.json.bak-v{version}-{stamp().replace(':', '-')}-")
        )
        fd, filename = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=target)
        complete = False
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            complete = True
            sync_dir(target)
            sync_dir(self.data_dir)
        finally:
            if not complete:
                os.unlink(filename)

    def _initialize(self) -> Config:
        from toolbox_backend.domain.ai import config_v2_to_v3
        from toolbox_backend.domain.mcp import config_v3_to_v4
        from toolbox_backend.domain.services import config_v4_to_v5
        from toolbox_backend.domain.telegram import config_v1_to_v2
        from toolbox_backend.domain.vpn import config_v5_to_v6

        migrations = {
            1: config_v1_to_v2,
            2: config_v2_to_v3,
            3: config_v3_to_v4,
            4: config_v4_to_v5,
            5: config_v5_to_v6,
            6: config_v6_to_v7,
            7: config_v7_to_v8,
            **self.migrations,
        }
        try:
            # No infrastructure files for an empty/current/unsupported store. Migration
            # is explicit startup work; ordinary read() never upgrades or writes.
            raw = json.loads(self.path.read_bytes())
            version = raw.get("schema_version") if isinstance(raw, dict) else None
            if type(version) is not int or not 0 <= version < CURRENT_SCHEMA_VERSION:
                return self._read()
            if any(v not in migrations for v in range(version, CURRENT_SCHEMA_VERSION)):
                return self._read()
            with self._file_lock():
                # Another process may have migrated while this one waited for flock.
                original = self.path.read_bytes()
                raw = json.loads(original)
                version = raw.get("schema_version") if isinstance(raw, dict) else None
                if version == CURRENT_SCHEMA_VERSION:
                    return self._read()
                if type(version) is not int or not 0 <= version < CURRENT_SCHEMA_VERSION:
                    raise ValueError
                candidate = copy.deepcopy(raw)
                for current in range(version, CURRENT_SCHEMA_VERSION):
                    candidate = migrations[current](candidate)
                    if (
                        not isinstance(candidate, dict)
                        or type(candidate.get("schema_version")) is not int
                        or candidate["schema_version"] != current + 1
                    ):
                        raise ValueError
                if type(raw.get("revision")) is not int or raw["revision"] < 0:
                    raise ValueError
                candidate["revision"] = raw["revision"] + 1
                candidate["updated_at"] = stamp()
                config = self._validate(candidate)
                if contains_secret(original.decode("utf-8")) or contains_secret(
                    config.model_dump_json(by_alias=True)
                ):
                    raise ValueError
                # Backup must be durable before replacement can start. Any failure before
                # replace preserves the original; a complete backup is retained for repair.
                self._backup(original, version)
                self._write(config)
                self.readonly_error = None
                if self.on_change:
                    self._loop.call_soon_threadsafe(self.on_change, config.revision)
                return config
        except FileNotFoundError:
            return self._read()
        except Exception:
            self.readonly_error = "存储迁移失败或版本不支持；原件与已完成备份保留"
            raise SettingsError("store_unavailable", self.readonly_error, 503) from None

    async def initialize(self) -> Config:
        return await self._serialized(self._initialize)

    def _write(self, config: Config) -> None:
        if contains_secret(config.model_dump_json(by_alias=True)):
            raise SettingsError("validation_error", "配置包含凭据值，拒绝写入", 422)
        fd, filename = tempfile.mkstemp(prefix=".config-", dir=self.data_dir)
        replaced = False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(config.model_dump_json(by_alias=True))
                stream.flush()
                os.fsync(stream.fileno())
            self.checkpoint("before_replace")
            os.replace(filename, self.path)
            replaced = True
            sync_dir(self.data_dir)
            self.checkpoint("after_replace")
        except Exception:
            if not replaced:
                raise SettingsError("store_unavailable", "存储写入失败", 503) from None
            # replace is the commit point. A post-replace fsync/fault cannot be reported as
            # an uncommitted write: readers already observe the complete new revision.
            # Verify the committed bytes before reporting success.
            if self._read() != config:
                raise SettingsError("store_unavailable", "存储提交状态无法确认", 503) from None
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(filename)

    @contextlib.contextmanager
    def _file_lock(self):
        private_dir(self.data_dir)
        fd = os.open(self.data_dir / "config.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(fd, 0o600)
            deadline = time.monotonic() + self.lock_timeout_s
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise SettingsError("store_busy", "存储忙，请稍后重试", 503) from None
                    time.sleep(0.01)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _run(self, expected: int | None, operation: Callable[[Transaction], T]):
        # Validate before touching disk: a damaged store must never be reset by a write.
        self._read()
        with self._file_lock():
            tx = Transaction(self, self._read())
            if expected is not None and tx.config.revision != expected:
                raise SettingsError(
                    "revision_conflict", "配置已被其他写者更新", revision=tx.config.revision
                )
            try:
                return operation(tx)
            finally:
                # The callback runs on the owning event loop, including commits followed by
                # a later operation error. Never publish uncommitted revisions.
                if self.on_change:
                    for revision in tx.revisions:
                        self._loop.call_soon_threadsafe(self.on_change, revision)

    async def _serialized(self, operation: Callable[[], T]) -> T:
        try:
            await asyncio.wait_for(self._lock.acquire(), self.lock_timeout_s)
        except TimeoutError:
            raise SettingsError("store_busy", "存储忙，请稍后重试", 503) from None
        try:
            self._loop = asyncio.get_running_loop()
            task = asyncio.create_task(asyncio.to_thread(operation))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # A thread cannot be cancelled. Keep ownership until it releases flock.
                await task
                raise
        finally:
            self._lock.release()

    async def run(self, expected_revision: int | None, operation: Callable[[Transaction], T]) -> T:
        return await self._serialized(lambda: self._run(expected_revision, operation))

    async def update(self, expected_revision: int, mutate_fn: Callable[[Config], None]) -> Config:
        return await self.run(expected_revision, lambda tx: tx.commit(mutate_fn))
