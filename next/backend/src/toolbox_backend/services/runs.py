"""Execution lifecycle owner. Adapters journal intentions before crossing write boundaries."""

import asyncio
import contextlib
import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from toolbox_backend.adapters.ado_read import AdoFailure
from toolbox_backend.adapters.run_store import TERMINAL
from toolbox_backend.adapters.task_git import GitFailure
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.task_execution import EffectIntent, ExecutionOutcome, JournalCheckpoint
from toolbox_backend.services.tasks import execution_fields, find_task, validate_fields

logger = logging.getLogger(__name__)
LOST_WORKER_DIAGNOSTIC = "运行收尾未落盘；保留预约，等待只读恢复"


class ExecutionContext:
    def __init__(self, service, run, cancelled, *, readonly=False):
        self.service, self.store = service, service.store
        self.run_id = run["run_id"]
        self.operation = run["operation"]
        self.deadline_at = run["deadline_at"]
        self.snapshot = run["task_snapshot"]
        self.cancelled = cancelled
        self.readonly = readonly
        self.step_no = 0

    async def checkpoint(self, kind, data):
        if self.readonly:
            raise RuntimeError("read-only recovery")
        try:
            payload = JournalCheckpoint.model_validate({**data, "kind": kind}).model_dump(
                mode="json", exclude_none=True
            )
        except ValidationError:
            raise SettingsError("validation_error", "检查点字段无效", 422) from None
        await self.store.record(self.run_id, self.step_no, "checkpoint", payload)

    async def intent(self, kind, data):
        if self.readonly:
            raise RuntimeError("read-only recovery")
        if kind not in {"git_push", "build_create", "build_cancel", "release_create", "env_deploy"}:
            raise ValueError("invalid effect kind")
        effect = str(uuid.uuid4())
        try:
            payload = EffectIntent.model_validate({**data, "kind": kind}).model_dump(
                mode="json", exclude_none=True
            )
        except ValidationError:
            raise SettingsError("validation_error", "副作用意图字段无效", 422) from None
        await self.store.record(self.run_id, self.step_no, "intent", payload, effect_id=effect)
        return effect

    async def receipt(self, effect, state, *, remote_id=None, owned=False):
        if state not in {"confirmed", "rejected", "unknown"}:
            raise RuntimeError("invalid receipt")
        await self.store.record(
            self.run_id,
            self.step_no,
            "receipt",
            dict(remote_id=str(remote_id) if remote_id is not None else None, owned=owned),
            effect_id=effect,
            state=state,
        )

    async def log(self, text, *, raw_bytes=None):
        await self.store.log(self.run_id, text, raw_bytes=raw_bytes)

    async def complete_step(self, status="succeeded", **checkpoint):
        await self.store.record(
            self.run_id, self.step_no, "step_finished", {"status": status, **checkpoint}
        )

    async def current(self):
        return await self.store.get(self.run_id)

    async def request_stop(self, reason="user"):
        if self.readonly or reason not in {"user", "timeout", "shutdown"}:
            raise RuntimeError("invalid stop request")
        result = await self.store.cancel(self.run_id, reason)
        self.cancelled.set()
        return result


class RunService:
    def __init__(self, tasks, store, executor=None):
        self.tasks, self.store, self.executor = tasks, store, executor
        self.plans = {}
        self.workers = {}
        self.lost_workers = {}
        self.cancellations = {}
        self.reconciliations = {}
        self.acceptances = set()
        self._semaphore = asyncio.Semaphore(4)
        self.closing = False
        self._recovery_task = None

    async def initialize(self):
        await self.store.initialize()
        if not self.store.readonly_error:
            await self.store.recover()
            if self.executor is not None:
                self._recovery_task = asyncio.create_task(self._recovery_loop())

    async def _recovery_loop(self):
        while True:
            await asyncio.sleep(30)
            try:
                await self._recovery_round()
            except SettingsError:
                pass  # A failed journal is exposed by HTTP; never resume writes.

    async def _recovery_round(self):
        # Only exited workers may be recovered in-process; never disturb live workers.
        for rid in list(self.lost_workers):
            try:
                await self.store.recover(run_ids=(rid,), reason_code="worker_lost")
            except SettingsError:
                continue  # No durable transition: retain both diagnosis and reservation.
            self.lost_workers.pop(rid, None)
        cursor = None
        while True:
            page = await self.store.list(status="unknown", cursor=cursor, limit=100)
            for run in page["items"]:
                if run["recovery_state"] == "manual_required":
                    continue
                started = datetime.fromisoformat(await self.store.recovery_started(run["run_id"]))
                if (datetime.now(UTC) - started).total_seconds() >= 900:
                    await self.store.transition(
                        run["run_id"],
                        run["state_version"],
                        "unknown",
                        reason_code=run["reason_code"],
                        recovery_state="manual_required",
                        summary="无法核实远端结果；预约保留，请人工核实",
                    )
                else:
                    await self.reconcile(run["run_id"])
            cursor = page["cursor"]
            if cursor is None:
                return

    def supported(self):
        if self.executor is None:
            raise SettingsError("unsupported_task", "S3-B 执行适配器尚未接入，禁止启动真实链路")

    async def preflight(self, tid, body):
        self.supported()
        config = await self.tasks.store.read()
        if config.revision != body.revision:
            raise SettingsError("revision_conflict", "配置已变化", revision=config.revision)
        task = find_task(config, tid)
        dto = await asyncio.to_thread(self.tasks.dto, task, config)
        if not dto["validation"]["valid"] or not task.enabled:
            raise SettingsError("validation_error", "任务不可执行", 422)
        validate_fields(task.model_dump())
        project = next(p for p in config.ado.projects if p.id == task.project_id)
        library = next(lib for lib in config.ado.libraries if lib.id == project.library_id)
        # Explicit whitelist; extra legacy fields are never adapter execution parameters.
        snapshot = execution_fields(task)
        snapshot["id"] = tid
        snapshot["source"] = dict(
            project_id=project.id,
            library_id=library.id,
            base_url=library.base_url,
            collection=project.collection,
            project=project.project,
        )
        try:
            prepared = await self.executor.prepare(snapshot, body.operation, body.rollback_offset)
        except AdoFailure as exc:
            raise SettingsError(
                "ado_request_failed", exc.message, 502, category=exc.category
            ) from None
        snapshot["prepared"] = prepared.frozen
        resources = list(prepared.resources)
        if snapshot["local_repo_path"] and body.operation == "sync_build_release":
            info = await self.tasks.git.preflight(snapshot["local_repo_path"])
            resources.extend("git:" + key for key in info["lock_keys"])
        for target in snapshot["targets"]:
            if target["enabled"] and target["release_id"]:
                resources.append(
                    "release:"
                    + json.dumps(
                        [
                            library.base_url,
                            project.collection,
                            project.project,
                            target["release_id"],
                        ]
                    )
                )
        now = time.monotonic()
        self.plans = {key: value for key, value in self.plans.items() if value["expires"] > now}
        if len(self.plans) >= 128:
            raise SettingsError("busy", "预检计划已满", 503)
        plan_id = str(uuid.uuid4())
        expiry = datetime.now(UTC) + timedelta(minutes=5)
        plan = dict(
            task_id=tid,
            operation=body.operation,
            snapshot=snapshot,
            revision=config.revision,
            expires=now + 300,
            steps=prepared.steps,
            resources=resources,
            budget=prepared.budget_seconds,
        )
        self.plans[plan_id] = plan
        return dict(
            plan_id=plan_id,
            expires_at=expiry.isoformat(),
            revision=config.revision,
            task_summary={"id": tid, "name": task.name},
            steps=prepared.steps,
            targets=prepared.targets,
            warnings=prepared.warnings,
        )

    async def start(self, tid, body, *, origin=None, authorize=None):
        self.supported()
        if self.closing:
            raise SettingsError("busy", "后端正在关闭", 503)
        rid = str(body.request_id)
        digest = hashlib.sha256(
            json.dumps({"task_id": tid, **body.model_dump(mode="json")}, sort_keys=True).encode()
        ).hexdigest()
        if origin is not None:
            digest = hashlib.sha256(
                (digest + json.dumps(origin, sort_keys=True)).encode()
            ).hexdigest()
        prior = await self.store.lookup(rid)
        if prior:
            if prior["request_hash"] != digest:
                raise SettingsError("idempotency_conflict", "请求标识已用于不同请求")
            return {"run_id": prior["run_id"]}
        plan = self.plans.get(str(body.plan_id))
        if plan is None or plan["expires"] <= time.monotonic():
            raise SettingsError("plan_expired", "执行计划已过期")

        def create(tx):
            if authorize is not None and not authorize(tx.config):
                raise SettingsError("validation_error", "权限已变化", 422)
            if plan["task_id"] != tid or tx.config.revision != plan["revision"]:
                raise SettingsError("plan_changed", "任务或来源已变化，请重新预检")
            find_task(tx.config, tid)
            # The ConfigStore lock also serializes settings writes against reservation.
            return self.store._call(
                self.store._create,
                (),
                dict(
                    task_id=tid,
                    origin=origin,
                    operation=plan["operation"],
                    request_id=rid,
                    request_hash=digest,
                    config_revision=plan["revision"],
                    snapshot=plan["snapshot"],
                    resources=plan["resources"],
                    steps=plan["steps"],
                    deadline_at=(datetime.now(UTC) + timedelta(seconds=plan["budget"])).isoformat(),
                ),
            )

        async def accept():
            run = await self.tasks.store.run(None, create)
            if run["run_id"] not in self.workers and run["status"] == "queued":
                cancel = self.cancellations[run["run_id"]] = asyncio.Event()
                self.workers[run["run_id"]] = asyncio.create_task(
                    self._execute(run["run_id"], cancel)
                )
            return {"run_id": run["run_id"]}

        if self.closing:
            raise SettingsError("busy", "后端正在关闭", 503)
        # Once acceptance begins, HTTP cancellation must not strand a durable queued run.
        acceptance = asyncio.create_task(accept())
        self.acceptances.add(acceptance)

        def accepted(task):
            self.acceptances.discard(task)
            if not task.cancelled():
                task.exception()  # Observe errors even if the requesting client disconnected.

        acceptance.add_done_callback(accepted)
        return await asyncio.shield(acceptance)

    async def _finish(self, rid, outcome):
        for _ in range(3):
            run = await self.store.get(rid)
            if run["status"] in TERMINAL:
                return
            try:
                await self.store.transition(
                    rid,
                    run["state_version"],
                    outcome.status,
                    reason_code=outcome.reason_code,
                    summary=outcome.summary,
                    recovery_state="pending" if outcome.status == "unknown" else "none",
                )
                return
            except SettingsError as exc:
                if exc.code != "state_conflict":
                    raise
        raise SettingsError("busy", "状态持续变化，稍后重新核实", 503)

    async def _execute(self, rid, cancel):
        try:
            await self._execute_worker(rid, cancel)
        except Exception, asyncio.CancelledError:
            # Do not leak adapter/DB exception text or pretend unknown was committed.
            self.lost_workers[rid] = LOST_WORKER_DIAGNOSTIC
            logger.error("%s run_id=%s", LOST_WORKER_DIAGNOSTIC, rid)
        finally:
            self.workers.pop(rid, None)
            self.cancellations.pop(rid, None)

    async def _execute_worker(self, rid, cancel):
        try:
            async with self._slot(cancel):
                run = await self.store.get(rid)
                if run["status"] != "queued":
                    return
                await self.store.transition(rid, run["state_version"], "running")
                remaining = (
                    datetime.fromisoformat(run["deadline_at"]) - datetime.now(UTC)
                ).total_seconds()
                context = ExecutionContext(self, run, cancel)
                async with asyncio.timeout(max(0, remaining)):
                    outcome = await self.executor.execute(context)
                await self._finish(rid, outcome)
        except GitFailure as exc:
            if exc.code == "cancelled":
                await self.store.cancel(rid)
            await self._finish(
                rid,
                ExecutionOutcome(
                    "unknown"
                    if exc.unknown
                    else ("cancelled" if exc.code == "cancelled" else "failed"),
                    exc.code,
                ),
            )
        except TimeoutError, asyncio.CancelledError:
            cancel.set()
            await self.store.cancel(rid, "shutdown" if self.closing else "timeout")
            await self._failure_outcome(rid, stopped=True, reason="interrupted")
        except Exception:
            await self._failure_outcome(rid, stopped=False, reason="remote_unknown")

    async def _failure_outcome(self, rid, *, stopped, reason):
        run = await self.store.get(rid)
        # An unowned reused Build is an observation even without a create effect.
        remote = bool(run["effects"]) or any(
            any(
                step["checkpoint"].get(k) is not None
                for k in ("build_id", "pipeline_run_id", "release_id")
            )
            for step in run["steps"]
        )
        await self._finish(
            rid,
            ExecutionOutcome(
                "unknown" if remote else "cancelled" if stopped else "failed",
                reason if remote else "interrupted" if stopped else "local_failed",
            ),
        )

    @contextlib.asynccontextmanager
    async def _slot(self, cancelled):
        acquire = asyncio.create_task(self._semaphore.acquire())
        stop = asyncio.create_task(cancelled.wait())
        try:
            done, _ = await asyncio.wait(
                {acquire, stop}, timeout=300, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                raise GitFailure("busy")
            if stop in done:
                raise GitFailure("cancelled")
            yield
        finally:
            for task in (acquire, stop):
                if not task.done():
                    task.cancel()
            await asyncio.gather(acquire, stop, return_exceptions=True)
            if not acquire.cancelled() and acquire.exception() is None:
                self._semaphore.release()

    async def cancel(self, rid, *, authorize=None):
        if authorize is None:
            result = await self.store.cancel(rid)
        else:

            def guarded(tx):
                def cancel():
                    run = self.store._get(rid)
                    if not authorize(tx.config, run):
                        raise SettingsError("validation_error", "权限已变化", 422)
                    return self.store._cancel(rid)

                return self.store._call(cancel, (), {})

            result = await self.tasks.store.run(None, guarded)
        if signal := self.cancellations.get(rid):
            signal.set()
        return result

    async def reconcile(self, rid):
        run = await self.store.get(rid)
        if run["status"] != "unknown" or rid in self.reconciliations:
            return run
        self.supported()

        async def observe():
            try:
                async with asyncio.timeout(30):
                    context = ExecutionContext(self, run, asyncio.Event(), readonly=True)
                    outcome = await self.executor.reconcile(context)
                    await self._finish(rid, outcome)
            except TimeoutError, SettingsError, GitFailure:
                pass  # Keep unknown and its reservations; no remote write retry.
            except Exception:
                with contextlib.suppress(SettingsError):
                    await self._finish(
                        rid,
                        ExecutionOutcome("unknown", "remote_unknown", "核实失败；远端结果仍未知"),
                    )
            finally:
                self.reconciliations.pop(rid, None)

        self.reconciliations[rid] = asyncio.create_task(observe())
        return run

    async def close(self):
        self.closing = True
        try:
            if self.acceptances:
                await asyncio.gather(*self.acceptances, return_exceptions=True)
            if self._recovery_task:
                self._recovery_task.cancel()
                await asyncio.gather(self._recovery_task, return_exceptions=True)
            for rid in list(self.workers):
                try:
                    await self.store.cancel(rid, "shutdown")
                except Exception:
                    logger.error("运行取消意图写入失败；保留记录供重启核实")
                finally:
                    if cancelled := self.cancellations.get(rid):
                        cancelled.set()
            tasks = list(self.workers.values()) + list(self.reconciliations.values())
            if tasks:
                _, pending = await asyncio.wait(tasks, timeout=5)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self.store.close()
