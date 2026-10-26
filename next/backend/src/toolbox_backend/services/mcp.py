"""S6 MCP configuration, runtime installer, Lark managed supervisor, and self-test owner."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from uuid import UUID, uuid4

from toolbox_backend.adapters.ai_process import SupervisedProcess
from toolbox_backend.adapters.config_store import ConfigStore, stamp
from toolbox_backend.adapters.credentials import CredentialStore, LegacyCredentialSource
from toolbox_backend.api.mcp_schemas import (
    FigmaMcpView,
    LarkActionRequest,
    LarkMcpView,
    LarkOwnershipRequest,
    LarkPatchStatus,
    McpJobEvent,
    McpJobView,
    MCPSnapshot,
    McpStatusEvent,
    RuntimeInstallRequest,
    RuntimeView,
)
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.mcp import (
    MANAGED_NODE_VERSION,
    NODE_MIN_VERSION,
    LoginMetadata,
    NodeRuntime,
)
from toolbox_backend.domain.settings import CredentialMeta
from toolbox_backend.logging_setup import register_secret
from toolbox_backend.mcp.lark_logs import (
    LarkLogManager,
    infer_lark_token_status,
    is_port_in_use,
    parse_line_markers,
    probe_lark_http,
)
from toolbox_backend.mcp.runner import mcp_environment, prepare_run_directory, redact_mcp
from toolbox_backend.mcp.runtime import (
    INSTALL_TIMEOUT_S,
    RESOURCES_MCP_DIR,
    RuntimeFetcher,
    append_capped_output,
    default_runtime_fetcher,
    detect_node_runtime,
    inspect_packages,
    install_node_from_tarball,
    lark_cli_js_path,
    probe_node_executable,
    resolve_npm_executable,
    run_supervised_step,
    runtime_archive_stem,
    stage_locked_package_manifests,
)
from toolbox_backend.services.events import EventHub
from toolbox_backend.services.settings import SettingsService


class _SettingsShim:
    """Adapter when McpService is constructed directly with (store, credentials, legacy)."""

    def __init__(
        self,
        store: ConfigStore,
        credentials: CredentialStore,
        legacy: LegacyCredentialSource,
        legacy_config_dir: Path | None,
    ) -> None:
        self.store = store
        self.credentials = credentials
        self.legacy = legacy
        self.legacy_config = type(
            "_LegacyCfg",
            (),
            {"directory": legacy_config_dir or (store.data_dir.parent / "legacy")},
        )()

    def _get(self, account: str) -> str | None:
        return self.credentials.get(account)

    def _set(self, account: str, value: str) -> None:
        self.credentials.set(account, value)

    def _delete(self, account: str) -> None:
        self.credentials.delete(account)


class McpService:
    def __init__(
        self,
        settings_or_store: SettingsService | ConfigStore,
        credentials: CredentialStore | EventHub | None = None,
        legacy_credentials: LegacyCredentialSource | None = None,
        *,
        hub: EventHub | None = None,
        events: EventHub | None = None,
        path_extras: Sequence[str | Path] | None = None,
        legacy_config_dir: Path | None = None,
        lark_logs_dir: Path | None = None,
        runtime_fetcher: RuntimeFetcher | None = None,
    ) -> None:
        if isinstance(settings_or_store, ConfigStore):
            assert credentials is not None and not isinstance(credentials, EventHub)
            assert legacy_credentials is not None
            self.settings = _SettingsShim(
                settings_or_store,
                credentials,
                legacy_credentials,
                legacy_config_dir,
            )
            self.store = settings_or_store
            self.hub = events or hub
        else:
            self.settings = settings_or_store
            self.store = settings_or_store.store
            self.hub = (
                credentials
                if isinstance(credentials, EventHub)
                else (events or hub)
            )
        self.path_extras: Sequence[str | Path] | None = (
            list(path_extras) if path_extras is not None else None
        )
        self.legacy_config_dir: Path | None = legacy_config_dir or getattr(
            getattr(self.settings, "legacy_config", None), "directory", None
        )
        self.lark_logs_dir: Path | None = lark_logs_dir
        self.runtime_fetcher: RuntimeFetcher | None = runtime_fetcher
        self._tests: dict[str, asyncio.Task] = {}

        # Runtime install job state
        self._jobs: dict[str, McpJobView] = {}
        self._job_tasks: dict[str, asyncio.Task] = {}
        self._job_procs: dict[str, object] = {}
        self._active_job_id: str | None = None
        self._idempotency: dict[tuple[str, str], object] = {}

        # Lark managed state machine
        self.start_timeout_s: float = 15.0
        self.health_interval_s: float = 30.0
        self.health_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
        self.login_timeout_s: float = 300.0
        self.logout_timeout_s: float = 60.0
        self.lark_http_prober = probe_lark_http
        self._lark_op_lock = asyncio.Lock()
        self._lark_state: str = "stopped"
        self._lark_pid: int | None = None
        self._lark_owner: SupervisedProcess | None = None
        self._lark_log_tasks: list[asyncio.Task] = []
        self._lark_health_task: asyncio.Task | None = None
        self._lark_exit_task: asyncio.Task | None = None
        self._lark_login_owner: SupervisedProcess | None = None
        self._lark_login_task: asyncio.Task | None = None
        self._lark_login_cancelled: bool = False
        self._lark_patches = LarkPatchStatus()
        self._lark_keytar_available: bool = True
        self._lark_last_error: str | None = None
        self._lark_warnings: list[str] = []
        self._lark_logs = LarkLogManager(self.store.data_dir)

    @staticmethod
    def runtime_archive_stem() -> str:
        return runtime_archive_stem()

    def _compute_runtime_view(self, config) -> RuntimeView:
        node_rt, warnings = detect_node_runtime(
            self.store.data_dir,
            config.mcp.runtime.node,
            path_extras=self.path_extras,
            legacy_config_dir=self.legacy_config_dir,
        )
        lark_ok, figma_ok, keytar_ok = inspect_packages(self.store.data_dir)
        packages_installed = lark_ok and figma_ok
        node_ok = node_rt.source in ("managed", "detected") and bool(node_rt.path)
        ready = node_ok and packages_installed
        return RuntimeView(
            node=node_rt,
            packages=dict(config.mcp.runtime.packages),
            ready=ready,
            packages_installed=packages_installed,
            lark_package_ready=lark_ok,
            figma_package_ready=figma_ok,
            keytar_ready=keytar_ok,
            warnings=warnings,
        )

    def _compute_lark_view(self, config) -> LarkMcpView:
        lark = config.mcp.lark
        secret_key = f"lark_app_secret:{lark.app_id}" if lark.app_id else ""
        secret_configured = bool(
            secret_key
            and (
                secret_key in config.credentials
                or self.settings._get(secret_key) is not None
            )
        )
        warnings = list(self._lark_warnings)
        if not lark.login.logged_in_at:
            msg = "未在新端登录过（共享存储下可能已有旧端登录）"
            if msg not in warnings:
                warnings.append(msg)
        token_status = infer_lark_token_status(
            self.store.data_dir,
            lark.login.logged_in_at,
            self.lark_logs_dir,
        )
        return LarkMcpView(
            **lark.model_dump(),
            state=self._lark_state,
            secret_configured=secret_configured,
            pid=self._lark_pid,
            endpoint=f"http://localhost:{lark.port}/mcp",
            patches=self._lark_patches.model_copy(deep=True),
            keytar_available=self._lark_keytar_available,
            token_status=token_status,
            warnings=warnings,
            last_error=self._lark_last_error,
            log_tail=self._lark_logs.tail_text,
        )

    async def snapshot(self) -> MCPSnapshot:
        config = await self.store.read()
        runtime_view = await asyncio.to_thread(self._compute_runtime_view, config)
        lark_view = await asyncio.to_thread(self._compute_lark_view, config)
        figma_view = FigmaMcpView(
            **config.mcp.figma.model_dump(),
            token_configured="figma_token" in config.credentials,
        )
        active_job = (
            self._jobs.get(self._active_job_id) if self._active_job_id else None
        )
        return MCPSnapshot(
            revision=config.revision,
            ado=config.mcp.ado,
            lark=lark_view,
            figma=figma_view,
            runtime=runtime_view,
            node_min_version=NODE_MIN_VERSION,
            managed_node_version=MANAGED_NODE_VERSION,
            self_test_running=bool(self._tests),
            active_job=active_job.model_copy(deep=True) if active_job else None,
        )

    def _emit_job(self, job: McpJobView) -> None:
        if self.hub is not None:
            self.hub.publish_mcp(McpJobEvent, job.model_copy(deep=True))

    async def _emit_status(self) -> MCPSnapshot:
        snap = await self.snapshot()
        if self.hub is not None:
            self.hub.publish_mcp(McpStatusEvent, snap)
        return snap

    # ------------------------------------------------------------------
    # Lark Ownership & Managed State Machine
    # ------------------------------------------------------------------

    async def confirm_lark_ownership(
        self, body: LarkOwnershipRequest | None = None
    ) -> MCPSnapshot:
        req = body or LarkOwnershipRequest()
        if req.request_id is not None:
            cached = self._idempotency.get(("lark_ownership_confirm", str(req.request_id)))
            if isinstance(cached, MCPSnapshot):
                return cached
        if not req.ack_old_app_stopped:
            raise SettingsError(
                "lark_owner_unconfirmed", "请先确认已在旧应用中停止飞书 MCP", 409
            )
        config = await self.store.read()
        rev = req.revision if req.revision is not None else config.revision
        await self.store.update(
            rev,
            lambda c: setattr(c.mcp.lark, "owner_confirmed_at", stamp()),
        )
        snap = await self._emit_status()
        if req.request_id is not None:
            self._idempotency[("lark_ownership_confirm", str(req.request_id))] = snap
        return snap

    async def revoke_lark_ownership(
        self, revision: int | None = None
    ) -> MCPSnapshot:
        if self._lark_state != "stopped":
            raise SettingsError(
                "mcp_busy", "请先停止飞书 MCP 再撤销所有权确认", 409
            )
        config = await self.store.read()
        rev = revision if revision is not None else config.revision
        await self.store.update(
            rev,
            lambda c: setattr(c.mcp.lark, "owner_confirmed_at", None),
        )
        return await self._emit_status()

    async def _check_lark_gates(
        self, config, *, require_secret: bool = True
    ) -> tuple[NodeRuntime, Path, str | None]:
        if not config.mcp.lark.owner_confirmed_at:
            raise SettingsError(
                "lark_owner_unconfirmed", "请先确认已停止旧应用中的飞书 MCP", 409
            )
        app_id = config.mcp.lark.app_id
        secret: str | None = None
        if require_secret:
            if not app_id:
                raise SettingsError(
                    "lark_not_configured", "请先配置飞书 App ID 与 App Secret", 409
                )
            secret = await asyncio.to_thread(
                self.settings._get, f"lark_app_secret:{app_id}"
            )
            if not secret:
                raise SettingsError(
                    "lark_not_configured", "请先配置飞书 App Secret", 409
                )
            register_secret(secret)
        else:
            if not app_id:
                raise SettingsError(
                    "lark_not_configured", "请先配置飞书 App ID", 409
                )
            secret = await asyncio.to_thread(
                self.settings._get, f"lark_app_secret:{app_id}"
            )
            if secret:
                register_secret(secret)

        node_rt, _ = await asyncio.to_thread(
            detect_node_runtime,
            self.store.data_dir,
            config.mcp.runtime.node,
            path_extras=self.path_extras,
            legacy_config_dir=self.legacy_config_dir,
        )
        lark_ok, _, _ = await asyncio.to_thread(
            inspect_packages, self.store.data_dir
        )
        cli_js = lark_cli_js_path(self.store.data_dir)
        if (
            node_rt.source == "none"
            or not node_rt.path
            or not lark_ok
            or not cli_js.is_file()
        ):
            raise SettingsError(
                "mcp_runtime_missing", "飞书 MCP 运行组件未安装或不可用", 409
            )
        return node_rt, cli_js, secret

    def _ensure_lark_not_busy(self) -> None:
        if (
            self._lark_state in ("starting", "stopping", "logging_in")
            or self._lark_op_lock.locked()
        ):
            raise SettingsError("mcp_busy", "飞书 MCP 操作正在进行", 409)

    async def _pump_lark_stream(
        self, stream: asyncio.StreamReader | None
    ) -> None:
        if stream is None:
            return
        try:
            while raw := await stream.readline():
                line = raw.decode("utf-8", errors="replace")
                self._lark_logs.write_line(line)
                self._lark_patches, self._lark_keytar_available, _ = (
                    parse_line_markers(
                        line, self._lark_patches, self._lark_keytar_available
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    def _refresh_degraded_warnings(self) -> None:
        patch_warn = "刷新补丁未生效：过期后可能需要重登"
        keytar_warn = "令牌存储不可用，重启后需重登"
        if not self._lark_patches.all_applied:
            if patch_warn not in self._lark_warnings:
                self._lark_warnings.append(patch_warn)
        if not self._lark_keytar_available:
            if keytar_warn not in self._lark_warnings:
                self._lark_warnings.append(keytar_warn)

    async def _lark_health_loop(self, port: int) -> None:
        failures = 0
        try:
            while self._lark_state in ("running", "running_degraded", "unhealthy"):
                await self.health_sleep(self.health_interval_s)
                if self._lark_state not in ("running", "running_degraded", "unhealthy"):
                    break
                owner = self._lark_owner
                if owner is None or owner.proc.returncode is not None:
                    break
                ok = await self.lark_http_prober(port)
                if ok:
                    failures = 0
                    if self._lark_state == "unhealthy":
                        self._lark_state = (
                            "running"
                            if (
                                self._lark_patches.all_applied
                                and self._lark_keytar_available
                            )
                            else "running_degraded"
                        )
                        await self._emit_status()
                else:
                    failures += 1
                    if failures >= 3 and self._lark_state != "unhealthy":
                        self._lark_state = "unhealthy"
                        self._lark_last_error = "health_check_failed"
                        await self._emit_status()
        except asyncio.CancelledError:
            raise

    async def _lark_exit_watcher(self, owner: SupervisedProcess) -> None:
        try:
            await owner.proc.wait()
            if (
                self._lark_owner is owner
                and self._lark_state in ("running", "running_degraded", "unhealthy")
            ):
                self._lark_state = "failed"
                self._lark_last_error = "exited"
                self._lark_pid = None
                await self._emit_status()
        except asyncio.CancelledError:
            raise

    async def _teardown_lark_proc(self) -> None:
        for t in (self._lark_health_task, self._lark_exit_task):
            if t is not None and not t.done():
                t.cancel()
        await asyncio.gather(
            *(
                t
                for t in (self._lark_health_task, self._lark_exit_task)
                if t is not None
            ),
            return_exceptions=True,
        )
        self._lark_health_task = None
        self._lark_exit_task = None

        owner = self._lark_owner
        self._lark_owner = None
        self._lark_pid = None
        log_tasks = list(self._lark_log_tasks)
        self._lark_log_tasks.clear()

        if owner is not None:
            owner.close_control()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(owner.proc.wait()), timeout=3.5)
        for lt in log_tasks:
            if not lt.done():
                lt.cancel()
        await asyncio.gather(*log_tasks, return_exceptions=True)
        if owner is not None:
            await owner.close()

    async def _stop_lark_internal(self) -> None:
        if self._lark_owner is None and self._lark_state in ("stopped", "failed"):
            self._lark_state = "stopped"
            return
        self._lark_state = "stopping"
        await self._emit_status()
        await self._teardown_lark_proc()
        self._lark_state = "stopped"

    async def start_lark(
        self, body: LarkActionRequest | None = None
    ) -> MCPSnapshot:
        req = body or LarkActionRequest()
        if req.request_id is not None:
            cached = self._idempotency.get(("lark_start", str(req.request_id)))
            if isinstance(cached, MCPSnapshot):
                return await self.snapshot()

        config = await self.store.read()
        self._ensure_lark_not_busy()
        node_rt, cli_js, secret = await self._check_lark_gates(
            config, require_secret=True
        )
        assert secret is not None and node_rt.path is not None

        if self._lark_state in ("running", "running_degraded"):
            snap = await self.snapshot()
            if req.request_id is not None:
                self._idempotency[("lark_start", str(req.request_id))] = snap
            return snap

        lark = config.mcp.lark
        if await asyncio.to_thread(is_port_in_use, lark.port):
            raise SettingsError(
                "mcp_port_in_use", f"端口 {lark.port} 已被占用", 409
            )

        async with self._lark_op_lock:
            self._lark_state = "starting"
            self._lark_patches = LarkPatchStatus()
            self._lark_keytar_available = True
            self._lark_last_error = None
            self._lark_warnings = []
            self._lark_logs.clear_tail()
            await self._emit_status()

            node_path = Path(node_rt.path)
            extra_dirs: list[str | Path] = [node_path.parent]
            if self.path_extras:
                extra_dirs.extend(self.path_extras)
            env = mcp_environment(path_extras=extra_dirs)
            env["APP_SECRET"] = secret
            env["NODE_OPTIONS"] = (
                f"--require {RESOURCES_MCP_DIR / 'lark_mcp_patches.js'}"
            )

            run_cwd = await asyncio.to_thread(
                prepare_run_directory, self.store.data_dir, "lark"
            )
            argv = [
                str(node_path),
                str(cli_js),
                "mcp",
                "-a",
                lark.app_id,
                "-d",
                lark.domain,
                "-t",
                lark.tools,
                "-m",
                "streamable",
                "--host",
                "localhost",
                "-p",
                str(lark.port),
                "--oauth",
                "--token-mode",
                "user_access_token",
                "-l",
                lark.language,
                "--debug",
            ]
            owner = await SupervisedProcess.start(
                argv,
                str(run_cwd),
                env=env,
                path_extras=extra_dirs,
                stdio=True,
            )
            self._lark_owner = owner
            self._lark_pid = owner.identity.get("pid") or owner.proc.pid
            self._lark_log_tasks = [
                asyncio.create_task(self._pump_lark_stream(owner.stdout)),
                asyncio.create_task(self._pump_lark_stream(owner.stderr)),
            ]

            timeout_s = req.timeout_s or self.start_timeout_s
            deadline = asyncio.get_running_loop().time() + timeout_s
            listening = False
            while asyncio.get_running_loop().time() < deadline:
                if owner.proc.returncode is not None:
                    break
                if await self.lark_http_prober(lark.port, 0.25):
                    listening = True
                    break
                await asyncio.sleep(0.25)

            if not listening:
                exited_early = owner.proc.returncode is not None
                if exited_early:
                    await asyncio.gather(
                        *self._lark_log_tasks, return_exceptions=True
                    )
                await self._teardown_lark_proc()
                self._lark_state = "failed"
                self._lark_last_error = (
                    "exited" if exited_early else "start_timeout"
                )
                snap = await self._emit_status()
                if req.request_id is not None:
                    self._idempotency[("lark_start", str(req.request_id))] = snap
                return snap

            # Allow stderr patch markers a brief moment to flush
            for _ in range(5):
                if self._lark_patches.all_applied:
                    break
                await asyncio.sleep(0.02)

            self._refresh_degraded_warnings()
            self._lark_state = (
                "running"
                if (
                    self._lark_patches.all_applied
                    and self._lark_keytar_available
                )
                else "running_degraded"
            )
            self._lark_health_task = asyncio.create_task(
                self._lark_health_loop(lark.port)
            )
            self._lark_exit_task = asyncio.create_task(
                self._lark_exit_watcher(owner)
            )
            snap = await self._emit_status()
            if req.request_id is not None:
                self._idempotency[("lark_start", str(req.request_id))] = snap
            return snap

    async def stop_lark(
        self, body: LarkActionRequest | None = None
    ) -> MCPSnapshot:
        req = body or LarkActionRequest()
        if req.request_id is not None:
            cached = self._idempotency.get(("lark_stop", str(req.request_id)))
            if isinstance(cached, MCPSnapshot):
                return await self.snapshot()

        config = await self.store.read()
        if not config.mcp.lark.owner_confirmed_at:
            raise SettingsError(
                "lark_owner_unconfirmed", "请先确认已停止旧应用中的飞书 MCP", 409
            )
        self._ensure_lark_not_busy()
        async with self._lark_op_lock:
            await self._stop_lark_internal()
            snap = await self._emit_status()
            if req.request_id is not None:
                self._idempotency[("lark_stop", str(req.request_id))] = snap
            return snap

    async def login_lark(
        self, body: LarkActionRequest | None = None
    ) -> MCPSnapshot:
        req = body or LarkActionRequest()
        if req.request_id is not None:
            cached = self._idempotency.get(("lark_login", str(req.request_id)))
            if isinstance(cached, MCPSnapshot):
                return await self.snapshot()

        config = await self.store.read()
        self._ensure_lark_not_busy()
        node_rt, cli_js, secret = await self._check_lark_gates(
            config, require_secret=True
        )
        assert secret is not None and node_rt.path is not None

        was_running = self._lark_state in (
            "running",
            "running_degraded",
            "unhealthy",
        )
        self._lark_login_cancelled = False
        self._lark_login_task = asyncio.current_task()
        owner: SupervisedProcess | None = None
        pump_tasks: list[asyncio.Task] = []
        rc: int | None = None
        timed_out = False
        try:
            async with self._lark_op_lock:
                if was_running:
                    await self._stop_lark_internal()
                self._lark_state = "logging_in"
                self._lark_last_error = None
                await self._emit_status()

            node_path = Path(node_rt.path)
            extra_dirs: list[str | Path] = [node_path.parent]
            if self.path_extras:
                extra_dirs.extend(self.path_extras)
            env = mcp_environment(path_extras=extra_dirs)
            env["APP_SECRET"] = secret

            lark = config.mcp.lark
            run_cwd = await asyncio.to_thread(
                prepare_run_directory, self.store.data_dir, "lark"
            )
            argv = [
                str(node_path),
                str(cli_js),
                "login",
                "-a",
                lark.app_id,
                "-d",
                lark.domain,
                "--host",
                "localhost",
                "-p",
                str(lark.port),
            ]
            if lark.scope_hint.strip():
                for scope_item in lark.scope_hint.split():
                    argv.extend(["--scope", scope_item])

            owner = await SupervisedProcess.start(
                argv,
                str(run_cwd),
                env=env,
                path_extras=extra_dirs,
                stdio=True,
            )
            self._lark_login_owner = owner
            pump_tasks = [
                asyncio.create_task(self._pump_lark_stream(owner.stdout)),
                asyncio.create_task(self._pump_lark_stream(owner.stderr)),
            ]
            timeout_s = req.timeout_s or self.login_timeout_s
            async with asyncio.timeout(timeout_s):
                await asyncio.gather(*pump_tasks)
                rc = await owner.proc.wait()
        except TimeoutError:
            timed_out = True
        except asyncio.CancelledError:
            if not self._lark_login_cancelled:
                raise
        finally:
            self._lark_login_owner = None
            self._lark_login_task = None
            if owner is not None:
                owner.close_control()
            for pt in pump_tasks:
                if not pt.done():
                    pt.cancel()
            if pump_tasks:
                await asyncio.gather(*pump_tasks, return_exceptions=True)
            if owner is not None:
                await owner.close()

        if self._lark_login_cancelled:
            self._lark_state = "stopped"
            snap = await self._emit_status()
            if req.request_id is not None:
                self._idempotency[("lark_login", str(req.request_id))] = snap
            return snap

        if timed_out:
            self._lark_state = "failed"
            self._lark_last_error = "login_timeout"
            snap = await self._emit_status()
            if req.request_id is not None:
                self._idempotency[("lark_login", str(req.request_id))] = snap
            return snap

        if rc != 0:
            self._lark_state = "failed"
            self._lark_last_error = "login_failed"
            snap = await self._emit_status()
            if req.request_id is not None:
                self._idempotency[("lark_login", str(req.request_id))] = snap
            return snap

        latest = await self.store.read()
        await self.store.update(
            latest.revision,
            lambda c: setattr(
                c.mcp.lark,
                "login",
                LoginMetadata(
                    logged_in_at=stamp(),
                    scope=c.mcp.lark.scope_hint,
                ),
            ),
        )
        self._lark_state = "stopped"
        if was_running:
            snap = await self.start_lark()
        else:
            snap = await self._emit_status()
        if req.request_id is not None:
            self._idempotency[("lark_login", str(req.request_id))] = snap
        return snap

    async def cancel_lark_login(
        self, body: LarkActionRequest | None = None
    ) -> MCPSnapshot:
        req = body or LarkActionRequest()
        if req.request_id is not None:
            cached = self._idempotency.get(
                ("lark_login_cancel", str(req.request_id))
            )
            if isinstance(cached, MCPSnapshot):
                return await self.snapshot()

        self._lark_login_cancelled = True
        owner = self._lark_login_owner
        if owner is not None:
            owner.close_control()
        task = self._lark_login_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(asyncio.shield(task), timeout=4.0)
        self._lark_state = "stopped"
        snap = await self._emit_status()
        if req.request_id is not None:
            self._idempotency[("lark_login_cancel", str(req.request_id))] = snap
        return snap

    async def logout_lark(
        self, body: LarkActionRequest | None = None
    ) -> MCPSnapshot:
        req = body or LarkActionRequest()
        if req.request_id is not None:
            cached = self._idempotency.get(("lark_logout", str(req.request_id)))
            if isinstance(cached, MCPSnapshot):
                return await self.snapshot()

        config = await self.store.read()
        self._ensure_lark_not_busy()
        node_rt, cli_js, _ = await self._check_lark_gates(
            config, require_secret=False
        )
        assert node_rt.path is not None

        async with self._lark_op_lock:
            if self._lark_state in ("running", "running_degraded", "unhealthy"):
                await self._stop_lark_internal()

            node_path = Path(node_rt.path)
            extra_dirs: list[str | Path] = [node_path.parent]
            if self.path_extras:
                extra_dirs.extend(self.path_extras)
            env = mcp_environment(path_extras=extra_dirs)
            run_cwd = await asyncio.to_thread(
                prepare_run_directory, self.store.data_dir, "lark"
            )
            argv = [
                str(node_path),
                str(cli_js),
                "logout",
                "-a",
                config.mcp.lark.app_id,
            ]
            owner = await SupervisedProcess.start(
                argv,
                str(run_cwd),
                env=env,
                path_extras=extra_dirs,
                stdio=True,
            )
            pumps = [
                asyncio.create_task(self._pump_lark_stream(owner.stdout)),
                asyncio.create_task(self._pump_lark_stream(owner.stderr)),
            ]
            try:
                async with asyncio.timeout(req.timeout_s or self.logout_timeout_s):
                    await asyncio.gather(*pumps)
                    await owner.proc.wait()
            finally:
                owner.close_control()
                for pt in pumps:
                    if not pt.done():
                        pt.cancel()
                await asyncio.gather(*pumps, return_exceptions=True)
                await owner.close()

            latest = await self.store.read()
            await self.store.update(
                latest.revision,
                lambda c: setattr(
                    c.mcp.lark,
                    "login",
                    LoginMetadata(logged_in_at=None, scope=None),
                ),
            )
            self._lark_state = "stopped"
            bearer_warn = "已写入各 CLI 的旧 bearer（若有）随之失效，各客户端需重新授权"
            if bearer_warn not in self._lark_warnings:
                self._lark_warnings.append(bearer_warn)
            snap = await self._emit_status()
            if req.request_id is not None:
                self._idempotency[("lark_logout", str(req.request_id))] = snap
            return snap

    # ------------------------------------------------------------------
    # Runtime Install Job
    # ------------------------------------------------------------------

    async def install_runtime(
        self, body: RuntimeInstallRequest | None = None
    ) -> McpJobView:
        req = body or RuntimeInstallRequest()
        if req.request_id is not None:
            cached = self._idempotency.get(("runtime_install", str(req.request_id)))
            if isinstance(cached, McpJobView):
                return self._jobs.get(cached.job_id, cached)

        if self._active_job_id is not None:
            current = self._jobs.get(self._active_job_id)
            if current and current.state == "running":
                raise SettingsError("mcp_busy", "运行组件安装任务正在进行")

        job_id = f"mcpjob_{uuid4().hex[:16]}"
        job = McpJobView(
            job_id=job_id,
            kind="runtime_install",
            state="running",
            started_at=stamp(),
        )
        self._jobs[job_id] = job
        self._active_job_id = job_id
        if req.request_id is not None:
            self._idempotency[("runtime_install", str(req.request_id))] = job
        self._emit_job(job)

        task = asyncio.create_task(self._run_install_job(job_id, force_node=req.force_node))
        self._job_tasks[job_id] = task
        return job.model_copy(deep=True)

    async def _run_install_job(self, job_id: str, *, force_node: bool = False) -> None:
        job = self._jobs[job_id]

        def append_out(text: str) -> None:
            job.output = append_capped_output(job.output, text)
            self._emit_job(job)

        def set_proc(proc: object) -> None:
            if proc is None:
                self._job_procs.pop(job_id, None)
            else:
                self._job_procs[job_id] = proc

        try:
            async with asyncio.timeout(INSTALL_TIMEOUT_S):
                config = await self.store.read()
                detected_node, _ = await asyncio.to_thread(
                    detect_node_runtime,
                    self.store.data_dir,
                    config.mcp.runtime.node,
                    path_extras=self.path_extras,
                    legacy_config_dir=self.legacy_config_dir,
                )
                need_download = (
                    force_node
                    or self.runtime_fetcher is not None
                    or detected_node.source == "none"
                    or not detected_node.path
                )
                if need_download:
                    fetcher = self.runtime_fetcher or default_runtime_fetcher
                    stem = runtime_archive_stem()
                    archive_name = f"{stem}.tar.gz"
                    ver_tag = (
                        MANAGED_NODE_VERSION
                        if MANAGED_NODE_VERSION.startswith("v")
                        else f"v{MANAGED_NODE_VERSION}"
                    )
                    base_url = f"https://nodejs.org/dist/{ver_tag}"
                    append_out(f"Downloading {base_url}/SHASUMS256.txt ...\n")
                    shasums_bytes = await fetcher(f"{base_url}/SHASUMS256.txt")
                    append_out(f"Downloading {base_url}/{archive_name} ...\n")
                    tar_bytes = await fetcher(f"{base_url}/{archive_name}")
                    node_bin = await asyncio.to_thread(
                        install_node_from_tarball,
                        self.store.data_dir,
                        stem,
                        archive_name,
                        shasums_bytes,
                        tar_bytes,
                    )
                    ver = await asyncio.to_thread(probe_node_executable, node_bin)
                    if not ver:
                        raise RuntimeError("解压后的 Node 版本校验未通过 (>=20.20.0)")
                    latest_cfg = await self.store.read()
                    await self.store.update(
                        latest_cfg.revision,
                        lambda c: setattr(
                            c.mcp.runtime,
                            "node",
                            NodeRuntime(
                                source="managed",
                                path=str(node_bin),
                                version=ver,
                            ),
                        ),
                    )
                else:
                    node_bin = Path(detected_node.path)

                packages_dir = await asyncio.to_thread(
                    stage_locked_package_manifests, self.store.data_dir
                )
                npm_bin = await asyncio.to_thread(
                    resolve_npm_executable, node_bin, self.path_extras
                )
                extra_dirs: list[str | Path] = [node_bin.parent]
                if self.path_extras:
                    extra_dirs.extend(self.path_extras)
                env = mcp_environment(path_extras=extra_dirs)

                rc1 = await run_supervised_step(
                    [
                        str(npm_bin),
                        "ci",
                        "--ignore-scripts",
                        "--prefix",
                        str(packages_dir),
                    ],
                    cwd=packages_dir,
                    env=env,
                    path_extras=extra_dirs,
                    on_proc=set_proc,
                    on_output=append_out,
                )
                if rc1 != 0:
                    raise RuntimeError(f"npm ci 失败 (exit {rc1})")

                rc2 = await run_supervised_step(
                    [
                        str(npm_bin),
                        "rebuild",
                        "keytar",
                        "--prefix",
                        str(packages_dir),
                    ],
                    cwd=packages_dir,
                    env=env,
                    path_extras=extra_dirs,
                    on_proc=set_proc,
                    on_output=append_out,
                )
                if rc2 != 0:
                    append_out(f"warning: npm rebuild keytar exited with {rc2}\n")

                job.state = "completed"
                job.finished_at = stamp()
                self._emit_job(job)
                await self._emit_status()
        except asyncio.CancelledError:
            if job.state == "running":
                job.state = "cancelled"
                job.finished_at = stamp()
                self._emit_job(job)
                await self._emit_status()
            raise
        except TimeoutError:
            job.state = "failed"
            job.error = "运行组件安装超时 (600s)"
            job.finished_at = stamp()
            self._emit_job(job)
            await self._emit_status()
        except Exception as exc:
            if job.state == "running":
                job.state = "failed"
                job.error = redact_mcp(str(exc))
                job.finished_at = stamp()
                self._emit_job(job)
                await self._emit_status()
        finally:
            self._job_procs.pop(job_id, None)
            self._job_tasks.pop(job_id, None)
            if self._active_job_id == job_id:
                self._active_job_id = None

    async def cancel_job(
        self, job_id: str, *, request_id: UUID | None = None
    ) -> McpJobView:
        if request_id is not None:
            cached = self._idempotency.get(("job_cancel", str(request_id)))
            if isinstance(cached, McpJobView):
                return cached
        job = self._jobs.get(job_id)
        if job is None:
            raise SettingsError("not_found", "任务不存在", 404)
        task = self._job_tasks.get(job_id)
        proc = self._job_procs.get(job_id)
        if job.state == "running":
            job.state = "cancelled"
            job.finished_at = stamp()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            elif proc is not None and hasattr(proc, "close"):
                await proc.close()
            self._emit_job(job)
            await self._emit_status()
        res = job.model_copy(deep=True)
        if request_id is not None:
            self._idempotency[("job_cancel", str(request_id))] = res
        return res

    async def wait_job(self, job_id: str, timeout: float = 10.0) -> McpJobView:  # noqa: ASYNC109
        task = self._job_tasks.get(job_id)
        if task is not None:
            async with asyncio.timeout(timeout):
                await asyncio.shield(task)
        return self._jobs[job_id].model_copy(deep=True)

    # ------------------------------------------------------------------
    # S6-A Settings, Credentials, Policy, Client Config, Self-Test
    # ------------------------------------------------------------------

    async def patch(self, body):
        config = await self.store.read()
        new_lark = body.mcp.lark if body.mcp is not None else body.lark
        if new_lark is not None and self._lark_state not in ("stopped", "failed"):
            if (
                new_lark.port != config.mcp.lark.port
                or new_lark.app_id != config.mcp.lark.app_id
            ):
                raise SettingsError(
                    "mcp_busy", "请先停止飞书 MCP 再修改端口或 App ID", 409
                )

        def mutate(c):
            if body.mcp is not None:
                c.mcp = body.mcp
            for key in ("ado", "lark", "figma", "runtime"):
                value = getattr(body, key)
                if value is not None:
                    setattr(c.mcp, key, value)

        result = await self.store.update(body.revision, mutate)
        return {"revision": result.revision}

    @staticmethod
    def _account(kind, app_id, config):
        if kind == "figma_token":
            return "figma_token", "figma"
        app_id = app_id or config.mcp.lark.app_id
        if not app_id:
            raise SettingsError("validation_error", "请配置 Lark App ID", 422)
        return f"lark_app_secret:{app_id}", app_id

    async def credential(
        self,
        kind,
        revision,
        *,
        value=None,
        app_id=None,
        expiry_days=90,
        source="manual",
        login=None,
    ):
        def operation(tx):
            key, ref = self._account(kind, app_id, tx.config)
            previous = self.settings._get(key)

            def mutate(c):
                if value is None:
                    c.credentials.pop(key, None)
                else:
                    c.credentials[key] = CredentialMeta(
                        kind=kind, ref=ref, source=source, updated_at=stamp()
                    )
                if kind == "figma_token":
                    c.mcp.figma.token_set_at = stamp() if value else None
                    c.mcp.figma.expiry_days = expiry_days
                if login is not None:
                    c.mcp.lark.login = login

            # Validate the candidate before changing Keychain.
            candidate = tx.config.model_copy(deep=True)
            mutate(candidate)
            type(candidate).model_validate(candidate.model_dump(by_alias=True))
            if value is None:
                self.settings._delete(key)
            else:
                self.settings._set(key, value)
            try:
                tx.commit(mutate)
            except BaseException:
                # ConfigStore's commit point is replace; reconcile before rollback.
                disk = self.store._read()
                if disk.revision == tx.config.revision:
                    if previous is None:
                        self.settings._delete(key)
                    else:
                        self.settings._set(key, previous)
                raise
            return {"revision": tx.config.revision}

        return await self.store.run(revision, operation)

    async def import_credentials(self, body):
        config = await self.store.read()
        if config.revision != body.revision:
            raise SettingsError("revision_conflict", "配置已更新", revision=config.revision)
        # Prepare reads before writes, never hold flock while old Keychain may prompt.
        values = []
        for kind in dict.fromkeys(body.kinds):
            key, _ = self._account(kind, body.app_id, config)
            try:
                value = await asyncio.to_thread(self.settings.legacy.get, key)
            except Exception:
                raise SettingsError("credential_backend_error", "凭据后端访问失败", 502) from None
            if not value:
                raise SettingsError("legacy_missing", "旧凭据不存在", 404)
            values.append((kind, value))
        login = None
        if "lark_app_secret" in body.kinds:
            path = self.settings.legacy_config.directory / "lark_login_state.json"

            def read_metadata():
                if not path.exists():
                    return None
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as stream:
                    raw = stream.read(65537)
                if len(raw) > 65536:
                    raise ValueError
                data = json.loads(raw)
                return LoginMetadata.model_validate(
                    {k: data[k] for k in ("logged_in_at", "scope") if k in data}
                )

            try:
                login = await asyncio.to_thread(read_metadata)
            except OSError, ValueError:
                raise SettingsError("validation_error", "旧登录元数据无效", 422) from None
        revision = body.revision
        for kind, value in values:
            result = await self.credential(
                kind,
                revision,
                value=value,
                app_id=body.app_id,
                source="imported",
                login=login if kind == "lark_app_secret" else None,
            )
            revision = result["revision"]
        return {"revision": revision}

    async def client_config(self, server, cli):
        config = await self.store.read()
        name = {"ado": "toolbox_ado", "figma": "toolbox_figma", "lark": "lark"}[server]
        if server == "lark":
            entry = {"url": f"http://localhost:{config.mcp.lark.port}/mcp"}
        else:
            entry = {
                "command": sys.executable,
                "args": [
                    "-m",
                    f"toolbox_backend.mcp.{server}_" + ("server" if server == "ado" else "wrapper"),
                    "--data-dir",
                    str(self.store.data_dir),
                ],
            }
        if cli == "codex":
            import json as j

            snippet = (
                f"[mcp_servers.{name}]\n"
                + "\n".join(f"{k} = {j.dumps(v, ensure_ascii=False)}" for k, v in entry.items())
                + "\n"
            )
        else:
            snippet = json.dumps({"mcpServers": {name: entry}}, ensure_ascii=False, indent=2)
        return dict(server=server, cli=cli, name=name, config=entry, snippet=snippet)

    async def import_policy(self, body):
        from toolbox_backend.mcp.policy import import_policy

        def operation(tx):
            import_policy(Path(body.path), self.store.data_dir)
            # No configuration change is needed; revision guards the explicit operation.
            return {"revision": tx.config.revision}

        return await self.store.run(body.revision, operation)

    async def self_test(self, body, server: str = "ado"):
        from toolbox_backend.adapters.credentials import MemoryCredentials
        from toolbox_backend.mcp.runner import CommandSpec, run_self_test

        if server in self._tests:
            raise SettingsError("mcp_busy", "自检正在运行")
        task = asyncio.current_task()
        self._tests[server] = task
        module_name = (
            "toolbox_backend.mcp.ado_server"
            if server == "ado"
            else "toolbox_backend.mcp.figma_wrapper"
        )
        env_extras = None
        if server == "figma" and isinstance(
            getattr(self.settings, "credentials", None), MemoryCredentials
        ):
            env_extras = {"_MCP_MEM_FIGMA": self.settings._get("figma_token") or ""}
        try:
            return await run_self_test(
                CommandSpec(
                    name=server,
                    argv=[
                        sys.executable,
                        "-m",
                        module_name,
                        "--data-dir",
                        str(self.store.data_dir),
                    ],
                    path_extras=[str(p) for p in self.path_extras] if self.path_extras else None,
                    env_extras=env_extras,
                ),
                self.store.data_dir,
                timeout_s=body.timeout_s,
            )
        finally:
            self._tests.pop(server, None)

    async def close(self):
        self._lark_login_cancelled = True
        if self._lark_login_owner is not None:
            self._lark_login_owner.close_control()
        if self._lark_login_task is not None and not self._lark_login_task.done():
            self._lark_login_task.cancel()

        job_tasks = list(self._job_tasks.values())
        test_tasks = list(self._tests.values())
        for task in [*job_tasks, *test_tasks]:
            task.cancel()

        await asyncio.gather(
            self._teardown_lark_proc(),
            *(
                [self._lark_login_task]
                if self._lark_login_task is not None
                else []
            ),
            *job_tasks,
            *test_tasks,
            return_exceptions=True,
        )
        self._lark_state = "stopped"
