"""AI configuration and session kernel. This service alone owns AI subprocesses."""

import asyncio
import contextlib
import json
import logging
import secrets
from pathlib import Path

from pydantic import ValidationError

from toolbox_backend.adapters.ai_process import SupervisedProcess, resolve_argv
from toolbox_backend.adapters.ai_store import TERMINAL, AIStore
from toolbox_backend.adapters.config_store import stamp
from toolbox_backend.adapters.pty_terminal import PTYTerminal
from toolbox_backend.api.ai_schemas import (
    AIJobData,
    AIJobEvent,
    AISessionData,
    AISessionEvent,
    SessionView,
)
from toolbox_backend.domain.ai import BUILTINS, AIProfile, validate_model, validate_profile
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.logging_setup import redact_exception

logger = logging.getLogger(__name__)


def invalid():
    return SettingsError("validation_error", "AI 配置校验失败", 422)


def parse_profile(value):
    try:
        profile = value if isinstance(value, AIProfile) else AIProfile.model_validate(value)
        validate_profile(profile)
        return profile
    except ValidationError, ValueError, TypeError:
        raise invalid() from None


def find_profile(ai, pid):
    values = [
        p
        for p in ai.profiles
        if (p.id if isinstance(p, AIProfile) else p.get("id") if isinstance(p, dict) else None)
        == pid
    ]
    if not values:
        raise SettingsError("not_found", "AI 配置不存在", 404)
    if len(values) != 1:
        raise invalid()
    return parse_profile(values[0])


class SessionLifecycle:
    """Exactly one cleanup owner for every startup, exit, close and cancellation branch."""

    def __init__(self, terminal):
        self.terminal = terminal
        self.process = None
        self.kill_failed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        try:
            if self.process:
                try:
                    await self.process.close()
                except TimeoutError, OSError:
                    self.kill_failed = True
                    logger.error("ai process cleanup kill_failed")
        finally:
            if self.terminal:
                # Final nonblocking drain precedes fd closure. The memory ring survives attach.
                if not self.terminal.closed:
                    self.terminal._read()
                self.terminal.close()


class AISessionService:
    def __init__(self, config_store, ai_store: AIStore, hub, *, path_extras=None, fake=False):
        self.config = config_store
        self.store = ai_store
        self.hub = hub
        self.path_extras = path_extras
        self.fake = fake
        self.accepting = True
        self._lock = asyncio.Lock()
        self._active = {}
        self.terminals = {}
        self._jobs = {}
        self._job_task = None
        self._aux = {}
        self._checks = set()

    async def initialize(self):
        await self.store.initialize()

    def require(self):
        self.store.require()
        if not self.accepting:
            raise SettingsError("ai_session_limit", "AI 服务正在关闭", 409)

    def _resolve(self, command):
        return resolve_argv(command, path_extras=self.path_extras)

    def _profile(self, ai, pid):
        profile = find_profile(ai, pid)
        if self.fake:
            import shlex
            import sys

            fixture = Path(__file__).resolve().parents[3] / "tests/fixtures/fake_cli/fake.py"
            profile = profile.model_copy(
                update={
                    "command": shlex.join([sys.executable, str(fixture), "--echo"]),
                    "upgrade_command": shlex.join([sys.executable, str(fixture), "--version"]),
                }
            )
        return profile

    async def settings(self):
        config = await self.config.read()
        profiles, warnings, seen = [], [], set()
        for value in config.ai.profiles:
            try:
                profile = parse_profile(value)
                if profile.id in seen:
                    raise invalid()
                seen.add(profile.id)
                profile = self._profile(config.ai, profile.id)
                try:
                    argv = self._resolve(profile.command)
                    resolved = dict(ok=True, path_hint=Path(argv[0]).name)
                except SettingsError:
                    resolved = dict(ok=False, path_hint=None)
                profiles.append({**profile.model_dump(), "resolved": resolved, "warnings": []})
            except SettingsError:
                warnings.append("旧 AI 配置无效或标识重复，不可运行")
                profiles.append(value.model_dump() if isinstance(value, AIProfile) else value)
        return dict(
            revision=config.revision,
            profiles=profiles,
            selected_profile_id=config.ai.selected_profile_id,
            defaults=config.ai.defaults,
            analysis=config.ai.analysis,
            model_presets=config.ai.model_presets,
            store_state="unavailable" if self.store.readonly_error else "ready",
            warnings=warnings,
        )

    async def save_profile(self, body, pid=None):
        def mutate(config):
            nonlocal pid
            if pid is None:
                pid = "custom:" + secrets.token_hex(16)
                profile = AIProfile(id=pid, **body.model_dump(exclude={"revision"}))
                validate_profile(profile)
                config.ai.profiles.append(profile)
            else:
                old = find_profile(config.ai, pid)
                patch = body.model_dump(exclude={"revision"}, exclude_unset=True)
                profile = old.model_copy(update=patch)
                validate_profile(profile)
                profile.builtin = pid in BUILTINS
                config.ai.profiles = [
                    profile
                    if (
                        p.id
                        if isinstance(p, AIProfile)
                        else p.get("id")
                        if isinstance(p, dict)
                        else None
                    )
                    == pid
                    else p
                    for p in config.ai.profiles
                ]

        try:
            result = await self.config.update(body.revision, mutate)
        except ValueError:
            raise invalid() from None
        return dict(revision=result.revision, id=pid)

    async def delete_profile(self, pid, revision):
        if pid in BUILTINS:
            raise SettingsError("builtin_profile", "内置 AI 配置不可删除", 409)

        def mutate(config):
            find_profile(config.ai, pid)
            config.ai.profiles = [
                p
                for p in config.ai.profiles
                if (
                    p.id
                    if isinstance(p, AIProfile)
                    else p.get("id")
                    if isinstance(p, dict)
                    else None
                )
                != pid
            ]
            if config.ai.selected_profile_id == pid:
                config.ai.selected_profile_id = "codex"

        result = await self.config.update(revision, mutate)
        return dict(revision=result.revision)

    async def patch_settings(self, body):
        def mutate(config):
            for key in ("selected_profile_id", "defaults", "analysis", "model_presets"):
                if key in body.model_fields_set:
                    value = getattr(body, key)
                    if value is None:
                        raise invalid()
                    setattr(config.ai, key, value)
            find_profile(config.ai, config.ai.selected_profile_id)

        result = await self.config.update(body.revision, mutate)
        return dict(revision=result.revision)

    def _reserve_cli(self, cli):
        count = sum(item["cli"] == cli for item in self._active.values())
        if count + self._aux.get(cli, 0) >= 4:
            raise SettingsError("ai_session_limit", "AI CLI 进程达到上限", 409)
        self._aux[cli] = self._aux.get(cli, 0) + 1

    def _release_cli(self, cli):
        self._aux[cli] -= 1
        if not self._aux[cli]:
            del self._aux[cli]

    async def _command(self, argv, budget_s, maximum, role):
        owner = None
        try:
            owner = await SupervisedProcess.start(
                argv, str(self.config.data_dir), path_extras=self.path_extras
            )
            await self.store.process(None, owner.identity, role)
            output = bytearray()
            async with asyncio.timeout(budget_s):
                while True:
                    data = await owner.proc.stdout.read(65536)
                    if not data:
                        break
                    output.extend(data[: max(0, maximum - len(output))])
                code = await owner.proc.wait()
            text = redact_exception(output.decode(errors="replace"))
            # Redaction can increase length: enforce the byte limit after it as well.
            text = text.encode()[:maximum].decode(errors="ignore")
            return dict(ok=code == 0, output=text, exit_code=code)
        finally:
            if owner:
                try:
                    await owner.close()
                finally:
                    await self.store.finish_process(owner.identity["pid"])

    async def check(self, pid):
        self.require()
        config = await self.config.read()
        profile = self._profile(config.ai, pid)
        argv = self._resolve(profile.command)
        self._reserve_cli(profile.cli)
        task = asyncio.current_task()
        self._checks.add(task)
        try:
            return (
                await self._command([argv[0], "--version"], 15, 4096, "check")
                if not self.fake
                else (
                    await self._command(self._resolve(profile.upgrade_command), 15, 4096, "check")
                )
            )
        except RuntimeError, TimeoutError, OSError:
            return dict(ok=False, output="AI CLI 检测失败", exit_code=None)
        finally:
            self._checks.discard(task)
            self._release_cli(profile.cli)

    def _publish_job(self, job):
        self.hub.publish(AIJobEvent, AIJobData(**job))

    async def upgrade(self, pid):
        self.require()
        config = await self.config.read()
        profile = self._profile(config.ai, pid)
        try:
            argv = self._resolve(profile.upgrade_command)
        except ValueError:
            raise invalid() from None
        async with self._lock:
            self.require()
            if self._job_task and not self._job_task.done():
                raise SettingsError("busy", "已有 AI 升级任务", 409)
            self._reserve_cli(profile.cli)
            jid = "aij_" + secrets.token_hex(16)
            job = dict(job_id=jid, state="running", output="", exit_code=None)
            self._jobs[jid] = job

            async def execute():
                try:
                    result = await self._command(argv, 600, 256 * 1024, "upgrade")
                    job.update(
                        state="succeeded" if result["ok"] else "failed",
                        output=result["output"],
                        exit_code=result["exit_code"],
                    )
                except asyncio.CancelledError:
                    job.update(state="cancelled")
                except OSError, RuntimeError, TimeoutError:
                    job.update(state="failed", output="AI CLI 升级失败")
                finally:
                    self._publish_job(job)

            self._job_task = asyncio.create_task(execute())

            def settled(task):
                self._release_cli(profile.cli)
                if task.cancelled():
                    job.update(state="cancelled")
                    self._publish_job(job)

            self._job_task.add_done_callback(settled)
            self._publish_job(job)
        return dict(job_id=jid)

    async def cancel_job(self, jid):
        job = self._jobs.get(jid)
        if job is None:
            raise SettingsError("not_found", "升级任务不存在", 404)
        if job["state"] == "running":
            self._job_task.cancel()
            await asyncio.gather(self._job_task, return_exceptions=True)
        return dict(job_id=jid)

    def _repo(self, config, rid):
        repo = next((r for r in config.ado.local_repos if r.id == rid), None)
        if repo is None:
            raise SettingsError("repo_missing", "本地仓库不存在", 409)
        path = Path(repo.path)
        if path.is_symlink() or not path.is_dir():
            raise SettingsError("repo_missing", "本地仓库不存在", 409)
        resolved = str(path.resolve())
        return repo, resolved

    def _options(self, cli, body, config):
        if cli == "other":
            if body.effort or body.permission:
                raise invalid()
            return body.model, None, None
        default = getattr(config.ai.defaults, cli)
        model = body.model if body.model is not None else default.model
        validate_model(model)
        effort = body.effort if body.effort is not None else getattr(default, "effort", None)
        permission = (
            body.permission
            if body.permission is not None
            else getattr(default, {"claude": "permission", "codex": "sandbox", "agy": "mode"}[cli])
        )
        allowed_effort = {
            "claude": {None, "low", "medium", "high", "xhigh", "max"},
            "codex": {"minimal", "low", "medium", "high"},
            "agy": {None},
        }
        allowed_permission = {
            "claude": {"default", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan"},
            "codex": {"read-only", "workspace-write", "danger-full-access"},
            "agy": {"sandbox", "auto"},
        }
        if effort not in allowed_effort[cli] or permission not in allowed_permission[cli]:
            raise invalid()
        if (
            permission in {"bypassPermissions", "danger-full-access", "auto"}
            and (cli != "claude" or permission == "bypassPermissions")
            and not body.ack_high_risk
        ):
            raise SettingsError("high_risk_ack_required", "高权限会话需要再次确认", 409)
        return model, effort, permission

    async def create(self, body):
        self.require()
        async with self._lock:
            self.require()
            previous = await self.store.get(request_id=str(body.request_id))
            if previous:
                return await self.view(previous)
            if body.kind != "terminal" or body.resume is not None:
                raise SettingsError("unsupported_cli", "结构化会话将在 S5-B 接入", 409)
            config = await self.config.read()
            profile = self._profile(config.ai, body.profile_id)
            repo, cwd = self._repo(config, body.repo_id)
            model, effort, permission = self._options(profile.cli, body, config)
            if (
                len(self._active) >= 6
                or sum(a["cli"] == profile.cli for a in self._active.values())
                + self._aux.get(profile.cli, 0)
                >= 4
            ):
                raise SettingsError("ai_session_limit", "AI 会话达到上限", 409)
            argv = self._resolve(profile.command)
            sid = "ais_" + secrets.token_hex(16)
            values = dict(
                id=sid,
                kind="terminal",
                cli=profile.cli,
                profile_id=profile.id,
                repo_id=repo.id,
                cwd_snapshot=cwd,
                model=model,
                effort=effort,
                permission=permission,
                purpose="general",
                work_item_ref_json=None,
                external_id=None,
                resume_of=None,
                origin_json='{"kind":"ui"}',
                state="starting",
                created_at=stamp(),
                usage_json="{}",
                request_id=str(body.request_id),
            )
            await self.store.create(values)
            ready = asyncio.get_running_loop().create_future()
            active = dict(cli=profile.cli, queue=asyncio.Queue(maxsize=10), ready=ready)
            self._active[sid] = active
            active["task"] = asyncio.create_task(self._session(sid, argv, cwd, body, active))
        await asyncio.shield(ready)
        return await self.get(sid)

    async def _state(self, sid, state, reason=None, exit_code=None):
        await self.store.transition(sid, state, reason, exit_code)
        row = await self.store.get(sid)
        self.hub.publish(
            AISessionEvent,
            AISessionData(
                session_id=sid, state=state, ended_reason=reason, last_seq=row["last_seq"]
            ),
        )

    async def _session(self, sid, argv, cwd, body, active):
        reason, state, code = "process_exited", "ended", None
        terminal = None
        waiter = command_task = initial_writer = None
        lifecycle = None
        try:
            terminal = PTYTerminal()
            self.terminals[sid] = terminal
            async with SessionLifecycle(terminal) as lifecycle:
                lifecycle.process = await SupervisedProcess.start(
                    argv, cwd, slave=terminal.slave, path_extras=self.path_extras
                )
                terminal.close_slave()
                await self.store.process(sid, lifecycle.process.identity)
                await self._state(sid, "idle")
                if not active["ready"].done():
                    active["ready"].set_result(None)
                if body.initial_prompt:
                    initial_writer = asyncio.create_task(
                        terminal.write(b"\x1b[200~" + body.initial_prompt.encode() + b"\x1b[201~\r")
                    )

                    def written(task):
                        if not task.cancelled() and task.exception() is not None:
                            logger.error("ai initial prompt write failed")
                            with contextlib.suppress(asyncio.QueueFull):
                                active["queue"].put_nowait(("close", "process_exited"))

                    initial_writer.add_done_callback(written)
                waiter = asyncio.create_task(lifecycle.process.proc.wait())
                while True:
                    command_task = asyncio.create_task(active["queue"].get())
                    done, _ = await asyncio.wait(
                        {waiter, command_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if command_task in done:
                        action, argument = command_task.result()
                        if action == "close":
                            reason = argument
                            await self._state(sid, "closing")
                            break
                        if action == "interrupt":
                            await terminal.write(b"\x03")
                    else:
                        command_task.cancel()
                        await asyncio.gather(command_task, return_exceptions=True)
                    if waiter in done:
                        code = waiter.result()
                        break
        except asyncio.CancelledError:
            reason = "interrupted_on_exit"
        except OSError, RuntimeError, SettingsError, ValueError:
            state, reason = "failed", "start_failed"
        finally:
            for task in (waiter, command_task, initial_writer):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(t for t in (waiter, command_task, initial_writer) if t), return_exceptions=True
            )
            if terminal:
                terminal.close()
            try:
                if lifecycle and lifecycle.kill_failed:
                    await self.store.record_cleanup_failure(sid)
                await self._state(sid, state, reason, code)
            except SettingsError:
                logger.error("ai session finalization store_unavailable")
            finally:
                while not active["queue"].empty():
                    active["queue"].get_nowait()
                self._active.pop(sid, None)
                if not active["ready"].done():
                    active["ready"].set_result(None)

    async def view(self, row):
        config = await self.config.read()
        repo = next((r for r in config.ado.local_repos if r.id == row["repo_id"]), None)
        return SessionView(
            id=row["id"],
            kind=row["kind"],
            cli=row["cli"],
            profile=row["profile_id"],
            repo=dict(id=row["repo_id"], name=repo.name if repo else "已删除仓库"),
            model=row["model"],
            effort=row["effort"],
            permission=row["permission"],
            purpose=row["purpose"],
            work_item_ref=json.loads(row["work_item_ref_json"] or "null"),
            state=row["state"],
            ended_reason=row["ended_reason"],
            exit_code=row["exit_code"],
            origin={"kind": json.loads(row["origin_json"])["kind"]},
            has_external_id=bool(row["external_id"]),
            usage=json.loads(row["usage_json"] or "{}"),
            created_at=row["created_at"],
            ended_at=row["ended_at"],
            last_seq=row["last_seq"],
            warnings=["kill_failed"] if await self.store.cleanup_failed(row["id"]) else [],
        )

    async def get(self, sid):
        return await self.view(await self.store.get(sid))

    async def list(self, state=None, limit=50):
        return dict(items=[await self.view(row) for row in await self.store.list(state, limit)])

    async def command(self, sid, action):
        row = await self.store.get(sid)
        active = self._active.get(sid)
        if row["state"] not in TERMINAL and active:
            try:
                active["queue"].put_nowait((action, "user_closed"))
            except asyncio.QueueFull:
                raise SettingsError("ai_queue_full", "AI 会话队列已满", 409) from None
            if action == "close":
                await asyncio.shield(active["task"])
        return await self.get(sid)

    async def delete(self, sid):
        await self.store.delete(sid)
        terminal = self.terminals.pop(sid, None)
        if terminal:
            terminal.close()
            terminal.buffer.clear()

    async def close(self):
        self.accepting = False
        tasks = []
        for task in tuple(self._checks):
            task.cancel()
            tasks.append(task)
        for active in tuple(self._active.values()):
            if not active["ready"].done():
                active["task"].cancel()
            # Reserved shutdown delivery never waits for a full user-command queue.
            while not active["queue"].empty():
                active["queue"].get_nowait()
            active["queue"].put_nowait(("close", "interrupted_on_exit"))
            tasks.append(active["task"])
        if self._job_task and not self._job_task.done():
            self._job_task.cancel()
            tasks.append(self._job_task)
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=4.9)
            for task in pending:
                task.cancel()
            if pending:
                logger.error("ai shutdown kill_failed")
            for task in done:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    task.result()
        await self.store.close()
