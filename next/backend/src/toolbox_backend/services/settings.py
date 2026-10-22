"""The only S1 mutation owner. All filesystem/keyring/network IO runs off-loop."""

import asyncio
import json
import os
import shutil
import uuid
from pathlib import Path

from pydantic import ValidationError

from toolbox_backend import __version__
from toolbox_backend.adapters.ado_http import AdoHTTP
from toolbox_backend.adapters.config_store import (
    ConfigStore,
    Transaction,
    private_dir,
    stamp,
    sync_dir,
)
from toolbox_backend.adapters.credentials import CredentialStore, LegacyCredentialSource
from toolbox_backend.adapters.legacy_config import LegacyConfig
from toolbox_backend.api.settings_schemas import (
    ActiveRequest,
    AdoResponse,
    CredentialStatus,
    ImportPreview,
    LibraryCreate,
    LibraryPatch,
    MutationResponse,
    ProjectCreate,
    ProjectPatch,
    SettingsResponse,
    TestRequest,
)
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import (
    Ado,
    Config,
    CredentialMeta,
    ImportState,
    Library,
    Project,
    origin,
)
from toolbox_backend.logging_setup import contains_secret, register_secret


def account(lid: str) -> str:
    return f"ado_pat:{lid}"


def find(items, ident):
    for item in items:
        if item.id == ident:
            return item
    raise SettingsError("not_found", "条目不存在", 404)


def credential_error() -> SettingsError:
    return SettingsError("credential_backend_error", "凭据后端访问失败", 502)


def allowed(config: Config) -> None:
    if config.import_.state not in {"none", "failed"} or any(
        (
            config.ado.libraries,
            config.ado.projects,
            config.tasks.items,
        )
    ):
        raise SettingsError("import_not_allowed", "仅首次运行且未完成/跳过导入时允许导入")


class SettingsService:
    def __init__(
        self,
        store: ConfigStore,
        credentials: CredentialStore,
        legacy: LegacyCredentialSource,
        legacy_dir: Path,
        http: AdoHTTP,
    ):
        self.store = store
        self.credentials = credentials
        self.legacy = legacy
        self.legacy_config = LegacyConfig(legacy_dir)
        self.http = http

    def _get(self, key: str) -> str | None:
        try:
            value = self.credentials.get(key)
            if value:
                register_secret(value)
            return value
        except Exception:
            raise credential_error() from None

    def _set(self, key: str, value: str) -> None:
        register_secret(value)
        try:
            self.credentials.set(key, value)
        except Exception:
            raise credential_error() from None

    def _delete(self, key: str) -> None:
        try:
            self.credentials.delete(key)
        except Exception:
            raise credential_error() from None

    def _legacy_get(self, lid: str) -> str | None:
        value = self.legacy.get(f"azuredevops_pat:{lid}")
        if value:
            register_secret(value)
        return value

    async def settings(self) -> SettingsResponse:
        try:
            config = await self.store.read()
            state = "ok"
        except SettingsError:
            config, state = Config(), "readonly_error"
        return SettingsResponse(
            revision=config.revision,
            store_state=state,
            store_error=self.store.readonly_error,
            data_dir=str(self.store.data_dir),
            legacy_config_dir=str(self.legacy_config.directory),
            app_version=__version__,
            **{"import": config.import_},
        )

    def _statuses(self, config: Config) -> list[CredentialStatus]:
        libs = {lib.id: lib for lib in config.ado.libraries}
        keys = set(config.credentials) | {account(lid) for lid in libs}
        result = []
        for key in sorted(keys):
            meta = config.credentials.get(key)
            lid = meta.ref if meta else key.removeprefix("ado_pat:")
            try:
                present = bool(self._get(key))
                state = "present" if present else "missing"
            except SettingsError:
                present, state = None, "unreadable"
            if meta and (meta.state == "pending_delete" or lid not in libs):
                state = "pending_delete" if meta.state == "pending_delete" else "orphan"
            result.append(
                CredentialStatus(
                    account=key,
                    ref=lid,
                    ref_name=libs[lid].name if lid in libs else None,
                    present=present,
                    source=meta.source if meta else "unknown",
                    state=state,
                    updated_at=meta.updated_at if meta else None,
                )
            )
        return result

    async def statuses(self) -> list[CredentialStatus]:
        config = await self.store.read()
        return await asyncio.to_thread(self._statuses, config)

    async def ado(self) -> AdoResponse:
        config = await self.store.read()
        statuses = {s.ref: s for s in await asyncio.to_thread(self._statuses, config)}
        return AdoResponse(
            revision=config.revision,
            libraries=[
                {
                    **lib.model_dump(),
                    "credential": statuses[lib.id].model_dump(
                        include={"present", "source", "state"},
                    ),
                }
                for lib in config.ado.libraries
            ],
            **config.ado.model_dump(exclude={"libraries"}),
        )

    def _preview(self, config: Config):
        allowed(config)
        plan = self.legacy_config.read()
        for lib in plan.summary["libraries"]:
            try:
                lib["pat_status"] = "found" if self._legacy_get(lib["id"]) else "missing"
            except Exception:
                lib["pat_status"] = "unreadable"
        if contains_secret(json.dumps(plan.summary, ensure_ascii=False)) or any(
            contains_secret(raw.decode("utf-8", errors="replace"))
            for raw in plan.originals.values()
        ):
            # Raw snapshots and unknown fields must be preserved; reject instead of
            # silently editing a source file that contains a credential value.
            plan.summary["libraries"] = []
            plan.summary["projects"] = []
            plan.summary["errors"] = ["源文件包含凭据值，禁止导入或复制快照"]
        return plan

    async def preview(self) -> ImportPreview:
        config = await self.store.read()
        plan = await asyncio.to_thread(self._preview, config)
        return ImportPreview(fingerprint=plan.fingerprint, **plan.summary)

    def _snapshot(self, originals: dict[str, bytes]) -> Path:
        parent = self.store.data_dir / "import"
        private_dir(parent)
        target = parent / ("legacy-" + stamp().replace(":", "-") + "-" + uuid.uuid4().hex[:8])
        private_dir(target)
        try:
            for filename, raw in originals.items():
                with (target / filename).open("xb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            sync_dir(target)
            sync_dir(parent)
            return target
        except BaseException:
            shutil.rmtree(target)
            raise

    async def execute(self, fingerprint: str) -> MutationResponse:
        def operation(tx: Transaction):
            plan = self._preview(tx.config)
            if plan.fingerprint != fingerprint:
                raise SettingsError("import_source_changed", "源配置已变化，请重新预览")
            if plan.summary["errors"]:
                raise SettingsError("import_not_allowed", "预览存在阻断错误")
            planned = [account(lib.id) for lib in plan.config.ado.libraries]
            previous = list(tx.config.import_.written_credentials)

            def start(c):
                c.import_ = ImportState(
                    state="in_progress",
                    source_dir=str(self.legacy_config.directory),
                    fingerprint=fingerprint,
                    started_at=stamp(),
                    summary=plan.summary,
                    # Persist intent before touching Keychain: a crash can leave a value
                    # whose set() result wasn't recorded. Retry/decline safely owns it.
                    written_credentials=sorted(set(previous + planned)),
                )

            tx.commit(start)
            written = list(previous)
            snapshot = None
            try:
                for lib in plan.config.ado.libraries:
                    value = self._legacy_get(lib.id)
                    if value:
                        key = account(lib.id)
                        self._set(key, value)
                        if key not in written:
                            written.append(key)
                        tx.commit(
                            lambda c: setattr(c.import_, "written_credentials", list(written))
                        )
                    del value
                snapshot = self._snapshot(plan.originals)

                def finish(c):
                    c.ado, c.tasks, c.imported = (
                        plan.config.ado,
                        plan.config.tasks,
                        plan.config.imported,
                    )
                    c.credentials = {
                        key: CredentialMeta(
                            ref=key.removeprefix("ado_pat:"),
                            source="imported",
                            updated_at=stamp(),
                        )
                        for key in written
                    }
                    c.import_.state = "completed"
                    c.import_.written_credentials = written
                    c.import_.finished_at = stamp()
                    c.import_.error = None

                tx.commit(finish)
            except Exception:
                if snapshot:
                    shutil.rmtree(snapshot)

                def fail(c):
                    c.import_.state = "failed"
                    c.import_.error = "导入失败；可重试或放弃导入"
                    c.import_.written_credentials = sorted(set(written))
                    c.import_.finished_at = stamp()

                tx.commit(fail)
                raise SettingsError(
                    "import_failed", "导入失败；已写凭据保留，可重试或放弃"
                ) from None
            return MutationResponse(revision=tx.config.revision)

        return await self.store.run(None, operation)

    async def decline(self) -> MutationResponse:
        def operation(tx):
            allowed(tx.config)
            for key in tx.config.import_.written_credentials:
                self._delete(key)

            def mutate(c):
                c.import_.state = "declined"
                c.import_.finished_at = stamp()
                c.import_.written_credentials = []
                c.import_.error = None

            tx.commit(mutate)
            return MutationResponse(revision=tx.config.revision)

        return await self.store.run(None, operation)

    def _put_pat(self, tx: Transaction, lid: str, value: str, mutate=lambda c: None):
        # Commit the metadata intent first. A failed set remains observable as missing /
        # unreadable, and the account is always discoverable for retry or cleanup.
        def update(c):
            mutate(c)
            c.credentials[account(lid)] = CredentialMeta(
                ref=lid,
                source="manual",
                updated_at=stamp(),
            )

        register_secret(value)
        tx.commit(update)
        self._set(account(lid), value)

    async def create_library(self, body: LibraryCreate):
        def operation(tx):
            lib = Library(id="lib:" + str(uuid.uuid4()), name=body.name, base_url=body.base_url)

            def mutate(c):
                c.ado.libraries.append(lib)

            if body.pat:
                self._put_pat(tx, lib.id, body.pat.get_secret_value(), mutate)
            else:
                tx.commit(mutate)
            return MutationResponse(revision=tx.config.revision, id=lib.id)

        return await self.store.run(body.revision, operation)

    async def patch_library(self, lid: str, body: LibraryPatch):
        def operation(tx):
            lib = find(tx.config.ado.libraries, lid)
            if body.base_url and origin(lib.base_url) != origin(body.base_url):
                if not body.pat and not body.keep_pat and self._get(account(lid)):
                    raise SettingsError(
                        "pat_origin_change", "地址 origin 已变化，请替换或明确保留 PAT"
                    )

            def mutate(c):
                target = find(c.ado.libraries, lid)
                if body.name is not None:
                    target.name = body.name
                if body.base_url is not None:
                    target.base_url = body.base_url

            if body.pat:
                # Write the replacement credential before changing the destination. If
                # Keychain fails the old origin remains; no old PAT can reach a new origin.
                register_secret(body.pat.get_secret_value())
                candidate = tx.config.model_copy(deep=True)
                mutate(candidate)
                try:
                    Ado.model_validate(candidate.ado.model_dump())
                except ValidationError:
                    raise SettingsError("validation_error", "配置校验失败", 422) from None
                self._set(account(lid), body.pat.get_secret_value())

                def with_meta(c):
                    mutate(c)
                    c.credentials[account(lid)] = CredentialMeta(
                        ref=lid,
                        source="manual",
                        updated_at=stamp(),
                    )

                tx.commit(with_meta)
            else:
                tx.commit(mutate)
            return MutationResponse(revision=tx.config.revision)

        return await self.store.run(body.revision, operation)

    async def put_pat(self, lid: str, revision: int, value: str):
        def operation(tx):
            find(tx.config.ado.libraries, lid)
            self._put_pat(tx, lid, value)
            return MutationResponse(revision=tx.config.revision)

        return await self.store.run(revision, operation)

    def _remove_credential(self, tx, key):
        def pending(c):
            if key in c.credentials:
                c.credentials[key].state = "pending_delete"
            else:
                c.credentials[key] = CredentialMeta(
                    ref=key.removeprefix("ado_pat:"),
                    source="manual",
                    updated_at=stamp(),
                    state="pending_delete",
                )

        tx.commit(pending)
        try:
            self._delete(key)
        except SettingsError:
            return ["凭据删除失败，保留 pending_delete，可在凭据页重试"]
        tx.commit(lambda c: c.credentials.pop(key, None))
        return []

    async def delete_pat(self, lid, revision):
        def operation(tx):
            find(tx.config.ado.libraries, lid)
            warnings = self._remove_credential(tx, account(lid))
            return MutationResponse(revision=tx.config.revision, warnings=warnings)

        return await self.store.run(revision, operation)

    @staticmethod
    def _in_use(config, pids):
        tasks = [t.name or t.tg_command or t.id for t in config.tasks.items if t.project_id in pids]
        if tasks:
            raise SettingsError("in_use", "条目被任务引用", tasks=tasks)

    async def delete_library(self, lid, revision):
        def operation(tx):
            find(tx.config.ado.libraries, lid)
            pids = {p.id for p in tx.config.ado.projects if p.library_id == lid}
            self._in_use(tx.config, pids)

            def mutate(c):
                c.ado.libraries = [lib for lib in c.ado.libraries if lib.id != lid]
                c.ado.projects = [p for p in c.ado.projects if p.id not in pids]
                if c.ado.active_library_id == lid:
                    c.ado.active_library_id = None
                if c.ado.active_project_id in pids:
                    c.ado.active_project_id = None
                c.credentials[account(lid)] = CredentialMeta(
                    ref=lid,
                    source=c.credentials[account(lid)].source
                    if account(lid) in c.credentials
                    else "manual",
                    updated_at=stamp(),
                    state="pending_delete",
                )

            tx.commit(mutate)
            warnings = self._remove_credential(tx, account(lid))
            return MutationResponse(revision=tx.config.revision, warnings=warnings)

        return await self.store.run(revision, operation)

    async def delete_orphan(self, key, revision):
        def operation(tx):
            meta = tx.config.credentials.get(key)
            if not meta:
                raise SettingsError("not_found", "凭据索引不存在", 404)
            if meta.state != "pending_delete" and any(
                x.id == meta.ref for x in tx.config.ado.libraries
            ):
                raise SettingsError("in_use", "只能清理孤立或待删除凭据")
            warnings = self._remove_credential(tx, key)
            return MutationResponse(revision=tx.config.revision, warnings=warnings)

        return await self.store.run(revision, operation)

    async def project(self, body: ProjectCreate | ProjectPatch, pid: str | None = None):
        def operation(tx):
            ident = pid or "proj:" + str(uuid.uuid4())

            def mutate(c):
                if pid:
                    target = find(c.ado.projects, pid)
                    for key, value in body.model_dump(
                        exclude={"revision"}, exclude_none=True
                    ).items():
                        setattr(target, key, value)
                else:
                    c.ado.projects.append(
                        Project(id=ident, **body.model_dump(exclude={"revision"}))
                    )

            tx.commit(mutate)
            return MutationResponse(revision=tx.config.revision, id=ident)

        return await self.store.run(body.revision, operation)

    async def delete_project(self, pid, revision):
        def operation(tx):
            find(tx.config.ado.projects, pid)
            self._in_use(tx.config, {pid})

            def mutate(c):
                c.ado.projects = [p for p in c.ado.projects if p.id != pid]
                if c.ado.active_project_id == pid:
                    c.ado.active_project_id = None

            tx.commit(mutate)
            return MutationResponse(revision=tx.config.revision)

        return await self.store.run(revision, operation)

    async def active(self, body: ActiveRequest):
        def mutate(c):
            c.ado.active_library_id = body.library_id
            c.ado.active_project_id = body.project_id

        config = await self.store.update(body.revision, mutate)
        return MutationResponse(revision=config.revision)

    async def connection(self, lid: str, body: TestRequest, *, listing: bool = False):
        # Keep the same file lock while loading the saved origin and PAT. Origin edits
        # cannot race a request into sending the previous credential to a new host.
        def operation(tx):
            lib = find(tx.config.ado.libraries, lid)
            value = body.pat.get_secret_value() if body.pat else self._get(account(lid))
            result, projects = self.http.projects(lib, body.collection, value, listing=listing)
            if listing and not result.ok:
                if result.category == "no_credential":
                    raise SettingsError("no_credential", result.message, 409)
                raise SettingsError(
                    "ado_request_failed",
                    result.message,
                    502,
                    category=result.category,
                )
            return projects if listing else result

        return await self.store.run(None, operation)
