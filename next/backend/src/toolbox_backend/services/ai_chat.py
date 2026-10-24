"""Headless chat session (Claude / Codex / agy). One task owns every state transition.

External callers only post commands to `inbox` (or append to `pending` synchronously); reader
tasks only append normalized events, and hand control facts (result, approval request, exit)
to the owner through the same inbox. Readers are never blocked by downstream consumers.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import secrets
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from toolbox_backend.adapters.ai_cli import agy, claude, codex
from toolbox_backend.adapters.ai_cli.base import (
    MAX_LINE,
    LineSplitter,
    Noise,
    Ring,
    clip,
    tool_summary,
)
from toolbox_backend.adapters.ai_process import SupervisedProcess
from toolbox_backend.adapters.config_store import stamp
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.logging_setup import redact_exception

logger = logging.getLogger(__name__)

QUEUE_LIMIT = 10
PROMPT_LIMIT = 32 * 1024
MAX_PENDING_APPROVALS = 8
UNSAFE_SHELL = re.compile(r"[;&|`<>\n\r]|\$\(|\$\{")
WORD = re.compile(r"^[A-Za-z0-9._/\-]+$")
DENY_TEXT = {
    "user": "用户拒绝了此操作",
    "expired": "审批已过期，已自动拒绝",
    "interrupted": "会话已中断，操作未执行",
    "limit": "待决审批过多，已自动拒绝",
}


@dataclass
class Turn:
    number: int
    task: asyncio.Task | None = None
    interrupting: bool = False


@dataclass
class Outcome:
    """What one per-turn CLI process did (Codex / agy)."""

    code: int | None = None
    timeout: bool = False
    start_failed: bool = False
    objects: int = 0
    result: dict | None = None
    stderr_marker: bool = False
    assistant_seen: bool = False
    parser: object = None


@dataclass
class Approval:
    request_id: str
    tool: str
    input: dict
    timer: object = None


def bash_word(command):
    """First word of a plain command; None when the command is compound or unusual."""
    if not isinstance(command, str) or UNSAFE_SHELL.search(command):
        return None
    parts = command.strip().split(None, 1)
    return parts[0] if parts and WORD.fullmatch(parts[0]) else None


class ChatSession:
    def __init__(
        self, svc, sid, *, cli, exe, cwd, permission, model, effort, external_id, resume, prompts=()
    ):
        self.svc, self.sid, self.cli, self.exe, self.cwd = svc, sid, cli, exe, cwd
        self.permission, self.model, self.effort = permission, model, effort
        self.external_id, self.resume = external_id, resume
        self.inbox = asyncio.Queue()
        self.pending = deque(prompts)
        self.requests = OrderedDict()
        self.turn = None
        self.turn_count = 0
        self.state = "starting"
        self.closing = False
        self.finished = False
        self.approvals = {}
        self.rules = set()
        self.process = None
        self.tasks = set()
        self.noise = Noise(20)
        self.ring = Ring()
        self.usage = {"turns": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
        self.stale_results = 0
        self.agy_input = "stdin"
        self.init_emitted = False
        self.store_warned = False
        self.control_seq = 0
        self.flush_handle = None

    # ---- commands from other tasks (synchronous, no awaits) ---------------------------------

    @property
    def queue_len(self):
        return len(self.pending)

    @property
    def pending_approval(self):
        return bool(self.approvals)

    def submit(self, request_id, text):
        if request_id in self.requests:
            return self.requests[request_id]
        if self.closing or self.finished:
            raise SettingsError("session_ended", "会话已结束", 409)
        if len(self.pending) >= QUEUE_LIMIT:
            raise SettingsError("ai_queue_full", "AI 会话队列已满", 409)
        busy = self.turn is not None or bool(self.pending)
        self.pending.append(text)
        result = {
            "status": "queued" if busy else "sent",
            "position": len(self.pending) if busy else 0,
        }
        self.requests[request_id] = result
        while len(self.requests) > 256:
            self.requests.popitem(last=False)
        self.inbox.put_nowait(("wake", None))
        return result

    def decided(self, aid, decision, by):
        self.inbox.put_nowait(("approval_decided", (aid, decision, by)))

    # ---- events ------------------------------------------------------------------------------

    async def event(self, kind, payload):
        try:
            return await self.svc.store.append_event(self.sid, kind, payload)
        except SettingsError:
            if not self.store_warned:
                self.store_warned = True
                logger.error("ai event store unavailable")
            return None

    async def noisy(self, category, text=None, **extra):
        allowed, merged = self.noise.allow()
        if merged:
            await self.event("notice", {"reason": "suppressed", "count": merged})
        if not allowed and self.flush_handle is None:
            # Report the merged count even if nothing noisy follows.
            self.flush_handle = asyncio.get_running_loop().call_later(1.1, self._flush_noise)
        if allowed:
            payload = {"category": category, **extra}
            if text is not None:
                payload["text"] = text
            await self.event("error", payload)

    def _flush_noise(self):
        self.flush_handle = None
        if not self.finished:
            self._track(asyncio.create_task(self._emit_suppressed()))

    async def _emit_suppressed(self):
        merged = self.noise.drain()
        if merged:
            await self.event("notice", {"reason": "suppressed", "count": merged})

    async def _set_state(self):
        if self.closing:
            wanted = "closing"
        elif self.approvals:
            wanted = "awaiting_approval"
        elif self.turn is not None:
            wanted = "busy"
        else:
            wanted = "idle"
        if wanted != self.state:
            self.state = wanted
            await self.svc._state(self.sid, wanted)

    def _track(self, task):
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    # ---- stream readers ----------------------------------------------------------------------

    @staticmethod
    async def _lines(reader, limit):
        splitter = LineSplitter(limit)
        while True:
            chunk = await reader.read(65536)
            for line in splitter.feed(chunk) if chunk else splitter.flush():
                yield line
            if not chunk:
                return

    async def _pump_json(self, reader, on_object, outcome=None):
        async for line in self._lines(reader, MAX_LINE):
            if isinstance(line, int):
                await self.noisy("line_too_long", bytes=line)
                continue
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError, RecursionError:
                await self.noisy("bad_json", bytes=len(line))
                continue
            if outcome is not None:
                outcome.objects += 1
            await on_object(obj)

    async def _pump_stderr(self, reader, outcome=None):
        try:
            async for line in self._lines(reader, 64 * 1024):
                if isinstance(line, int):
                    continue
                text = redact_exception(line.decode(errors="replace").rstrip("\r"))
                self.ring.add((text[:2000] + "\n").encode())
                if outcome is not None and agy.TIMEOUT_MARKER in text:
                    outcome.stderr_marker = True
                if text.strip():
                    await self.noisy("stderr", clip(text, 2000))
        finally:
            merged = self.noise.drain()
            if merged:
                with contextlib.suppress(Exception):
                    await self.event("notice", {"reason": "suppressed", "count": merged})

    def _tail(self):
        return clip(redact_exception(self.ring.text()[-1500:]).strip(), 1000)

    async def _norm(self, norm, outcome=None):
        """Apply one normalized fact from a reader (events are written; control goes to owner)."""
        kind, payload = norm.kind, norm.payload
        if kind == "init":
            external = payload.get("external_id")
            if external and external != self.external_id:
                self.external_id = external
                await self.svc.store.set_external_id(self.sid, external)
                self.init_emitted = False
            if not self.init_emitted:
                self.init_emitted = True
                await self.event(
                    "init", {"cli": self.cli, **{k: v for k, v in payload.items() if v}}
                )
            return
        if kind == "result":
            if outcome is not None:
                outcome.result = payload
            else:
                self.inbox.put_nowait(("result", payload))
            return
        if kind == "can_use_tool":
            self.inbox.put_nowait(("approval_request", payload))
            return
        if kind == "assistant" and outcome is not None:
            outcome.assistant_seen = True
        await self.event(kind, payload)

    # ---- start / loop / finalize -------------------------------------------------------------

    async def start(self, lifecycle):
        if self.cli == "claude":
            argv = claude.build_argv(
                self.exe,
                permission=self.permission,
                session_id=None if self.resume else self.external_id,
                resume=self.external_id if self.resume else None,
                model=self.model,
                effort=self.effort,
            )
            lifecycle.process = self.process = await SupervisedProcess.start(
                argv, self.cwd, stdio=True, path_extras=self.svc.path_extras
            )
            await self.svc.store.process(self.sid, self.process.identity, "cli")
            readers = [
                self._track(
                    asyncio.create_task(self._pump_json(self.process.stdout, self._claude_obj))
                ),
                self._track(asyncio.create_task(self._pump_stderr(self.process.stderr))),
            ]
            self._track(asyncio.create_task(self._watch_exit(readers)))
        self.state = "idle"
        await self.svc._state(self.sid, "idle")

    async def _claude_obj(self, obj):
        for norm in claude.parse(obj):
            await self._norm(norm)

    async def _watch_exit(self, readers):
        code = await self.process.proc.wait()
        # Let readers drain what the CLI wrote before it exited (bounded: a grandchild may
        # keep the pipes open).
        await asyncio.wait(readers, timeout=2)
        self.inbox.put_nowait(("proc_exit", code))

    async def loop(self):
        """Returns (ended_reason, exit_code)."""
        await self._pump()
        while True:
            timeout = None
            if self.cli == "claude" and self.state == "idle" and not self.pending:
                timeout = self.svc.claude_idle_s
            try:
                action, argument = await asyncio.wait_for(self.inbox.get(), timeout)
            except TimeoutError:
                return "limit", None
            if action == "close":
                self.closing = True
                await self._set_state()
                await self._expire_all("interrupted")
                await self._fail_turn("interrupted", "会话已关闭", status="interrupted")
                return argument, None
            if action == "proc_exit":
                if self.cli == "claude":
                    tail = self._tail()
                    if tail:
                        await self.event(
                            "error",
                            {"category": "process_exited", "exit_code": argument, "text": tail},
                        )
                    await self._expire_all("interrupted")
                    await self._fail_turn("process_exited", "CLI 进程已退出", exit_code=argument)
                    return "process_exited", argument
                continue
            await self._handle(action, argument)
            await self._set_state()

    async def _handle(self, action, argument):
        if action == "wake":
            await self._pump()
        elif action == "interrupt":
            await self._interrupt()
        elif action == "result":
            await self._claude_result(argument)
        elif action == "turn_done":
            number, task = argument
            if self.turn is not None and self.turn.number == number:
                await self._process_turn_done(task)
        elif action == "approval_request":
            await self._approval_request(argument)
        elif action == "approval_decided":
            await self._approval_decided(*argument)
        elif action == "approval_expire":
            await self._approval_expire(argument)
        elif action == "interrupt_grace":
            if self.turn is not None and self.turn.number == argument and self.turn.interrupting:
                self.stale_results += 1  # the CLI never confirmed; swallow its late result
                await self._fail_turn("interrupted", "回合已中断", status="interrupted")
                await self._pump()

    async def finalize(self):
        self.finished = True
        self.closing = True
        if self.flush_handle is not None:
            self.flush_handle.cancel()
        for entry in self.approvals.values():
            if entry.timer:
                entry.timer.cancel()
        tasks = list(self.tasks)
        turn_task = self.turn.task if self.turn else None
        if turn_task is not None and turn_task not in tasks:
            tasks.append(turn_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.pending.clear()
        self.approvals.clear()

    # ---- turns -------------------------------------------------------------------------------

    async def _pump(self):
        if self.turn is not None or not self.pending or self.closing:
            return
        text = self.pending.popleft()
        self.turn_count += 1
        self.turn = Turn(self.turn_count)
        number = self.turn.number
        await self.event("turn_started", {"turn": number, "text": clip(text, 4000)})
        await self._set_state()
        if self.cli == "claude":
            if not await self._write(claude.encode_user(text)):
                logger.error("ai claude stdin write failed")
        else:
            task = asyncio.create_task(self._process_turn(text))
            self.turn.task = task
            task.add_done_callback(lambda t, n=number: self.inbox.put_nowait(("turn_done", (n, t))))

    async def _write(self, data):
        writer = self.process.stdin if self.process else None
        if writer is None:
            return False
        try:
            writer.write(data)
            await asyncio.wait_for(writer.drain(), 10)
            return True
        except OSError, TimeoutError, RuntimeError:
            return False

    def _add_usage(self, payload, cost=0.0):
        self.usage["turns"] += 1
        self.usage["cost_usd"] = round(self.usage["cost_usd"] + cost, 6)
        for key, value in payload.items():
            if (
                key.endswith("_tokens")
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            ):
                self.usage[key] = self.usage.get(key, 0) + value

    async def _finish_turn(self, kind, payload):
        """The only place a turn reaches a terminal event: exactly one per turn."""
        turn, self.turn = self.turn, None
        if turn is None:
            return
        await self.event(kind, {"turn": turn.number, **payload})
        with contextlib.suppress(SettingsError):
            await self.svc.store.update_usage(self.sid, self.usage)
        await self._set_state()

    async def _fail_turn(self, category, message, *, status="failed", exit_code=None):
        if self.turn is None:
            return
        payload = {"category": category, "status": status, "message": clip(message, 500)}
        if exit_code is not None:
            payload["exit_code"] = exit_code
        await self._finish_turn("turn_failed", payload)

    async def _claude_result(self, payload):
        if self.stale_results and self.turn is None:
            self.stale_results -= 1
            return
        if self.turn is None:
            return
        if self.turn.interrupting:
            await self._fail_turn("interrupted", "回合已中断", status="interrupted")
        elif payload.get("is_error"):
            self._add_usage(payload, payload.get("cost_usd", 0.0))
            await self._fail_turn("cli_error", payload.get("message") or "CLI 报告错误")
        else:
            self._add_usage(payload, payload.get("cost_usd", 0.0))
            await self._finish_turn(
                "turn_completed",
                {
                    "status": "completed",
                    **{
                        k: payload[k]
                        for k in ("duration_ms", "cost_usd", "input_tokens", "output_tokens")
                        if payload.get(k)
                    },
                },
            )
        await self._pump()

    async def _interrupt(self):
        self.pending.clear()  # an interrupt cancels everything queued behind the running turn
        await self._expire_all("interrupted")
        if self.turn is None:
            return
        if self.cli == "claude":
            if not self.turn.interrupting:
                self.turn.interrupting = True
                self.control_seq += 1
                await self._write(claude.encode_interrupt(f"int-{self.control_seq}"))
                loop = asyncio.get_running_loop()
                loop.call_later(
                    self.svc.interrupt_grace_s,
                    self.inbox.put_nowait,
                    ("interrupt_grace", self.turn.number),
                )
        else:
            task = self.turn.task
            self.turn.interrupting = True
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await self._fail_turn("interrupted", "回合已中断", status="interrupted")

    # ---- Codex / agy per-turn processes ------------------------------------------------------

    async def _process_turn(self, text):
        """Runs one CLI process for a turn. Returns a terminal description for the owner."""
        if self.cli == "codex":
            parse = codex.parse

            async def on_object(obj, outcome):
                for norm in parse(obj):
                    await self._norm(norm, outcome)

            argv = codex.build_argv(
                self.exe,
                cwd=self.cwd,
                sandbox=self.permission,
                effort=self.effort,
                model=self.model,
                resume=self.external_id,
                first_turn_danger=self.permission == "danger-full-access",
            )
            return await self._run_process(
                argv, codex.encode_prompt(text), on_object, self.svc.codex_turn_s
            )
        outcome = None
        for _ in range(2):
            stdin_mode = self.agy_input == "stdin"
            argv = agy.build_argv(
                self.exe,
                mode=self.permission,
                prompt=None if stdin_mode else text,
                model=self.model,
                effort=self.effort,
                conversation=self.external_id,
                timeout_s=self.svc.agy_print_timeout_s,
            )
            parser = agy.Parser()

            async def on_object(obj, outcome, parser=parser):
                for norm in parser.parse(obj):
                    await self._norm(norm, outcome)

            outcome = await self._run_process(
                argv,
                agy.encode_prompt(text) if stdin_mode else None,
                on_object,
                self.svc.agy_print_timeout_s + self.svc.agy_watchdog_extra_s,
                parser=parser,
            )
            failed_fast = (
                outcome.code not in (0, None) and not outcome.objects and not outcome.timeout
            )
            if stdin_mode and failed_fast and not outcome.start_failed:
                # stdin stream-json input is unchecked against the real CLI: fall back to argv.
                self.agy_input = "argv"
                with contextlib.suppress(SettingsError):
                    await self.svc.store.add_warning(self.sid, "prompt_visible_to_other_processes")
                continue
            break
        return outcome

    async def _run_process(self, argv, stdin_bytes, on_object, limit, parser=None):
        outcome = Outcome(parser=parser)
        owner = None
        tasks = []
        try:
            try:
                owner = await SupervisedProcess.start(
                    argv, self.cwd, stdio=True, path_extras=self.svc.path_extras
                )
            except RuntimeError, OSError, TimeoutError:
                outcome.start_failed = True
                return outcome
            await self.svc.store.process(self.sid, owner.identity, "turn")
            tasks = [
                asyncio.create_task(
                    self._pump_json(owner.stdout, lambda o: on_object(o, outcome), outcome)
                ),
                asyncio.create_task(self._pump_stderr(owner.stderr, outcome)),
            ]
            try:
                if stdin_bytes is not None and owner.stdin is not None:
                    owner.stdin.write(stdin_bytes)
                    await asyncio.wait_for(owner.stdin.drain(), 10)
            except OSError, TimeoutError, RuntimeError:
                pass  # a CLI that exits without reading stdin is judged by its exit
            await owner.close_stdin()
            try:
                async with asyncio.timeout(limit):
                    outcome.code = await owner.proc.wait()
            except TimeoutError:
                outcome.timeout = True
            if not outcome.timeout:
                await asyncio.wait(tasks, timeout=2)
            return outcome
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if owner is not None:
                try:
                    await owner.close()
                except TimeoutError, OSError:
                    logger.error("ai turn process cleanup kill_failed")
                finally:
                    with contextlib.suppress(SettingsError):
                        await self.svc.store.finish_process(owner.identity["pid"])

    async def _process_turn_done(self, task):
        if task.cancelled():
            await self._fail_turn("interrupted", "回合已中断", status="interrupted")
            return
        error = task.exception()
        if error is not None:
            logger.error("ai turn failed: %s", type(error).__name__)
            await self._fail_turn("internal", "回合内部错误")
            await self._pump()
            return
        outcome = task.result()
        tail = self._tail()
        if outcome.timeout or (self.cli == "agy" and outcome.stderr_marker):
            await self._fail_turn("timeout", "回合超时")
        elif outcome.start_failed:
            await self._fail_turn("start_failed", "CLI 无法启动")
        elif self.cli == "codex":
            result = outcome.result
            if result is not None and result.get("is_error"):
                await self._fail_turn("cli_error", result.get("message") or "CLI 报告错误")
            elif result is not None or outcome.code == 0:
                self._add_usage(result or {})
                await self._finish_turn(
                    "turn_completed",
                    {
                        "status": "completed",
                        **{k: v for k, v in (result or {}).items() if k.endswith("_tokens") and v},
                    },
                )
            else:
                await self._fail_turn("exit", tail or "CLI 异常退出", exit_code=outcome.code)
        else:
            await self._agy_done(outcome, tail)
        await self._pump()

    async def _agy_done(self, outcome, tail):
        parser, result = outcome.parser, outcome.result
        if outcome.code not in (0, None):
            await self._fail_turn("exit", tail or "CLI 异常退出", exit_code=outcome.code)
        elif result is not None and result.get("status") not in ("", "SUCCESS"):
            await self._fail_turn("cli_error", f"agy 状态 {result.get('status')}")
        elif not parser.agent_done:
            await self._fail_turn("timeout", "缺少最终回复，按超时处理")
        else:
            if not outcome.assistant_seen and result and result.get("response"):
                await self.event("assistant", {"text": result["response"]})
            self._add_usage(result or {})
            await self._finish_turn(
                "turn_completed",
                {
                    "status": "completed",
                    **{k: v for k, v in (result or {}).items() if k.endswith("_tokens") and v},
                },
            )

    # ---- Claude tool approvals ---------------------------------------------------------------

    def _rule_allows(self, tool, data):
        if tool == "Bash":
            word = bash_word(data.get("command"))
            return word is not None and ("Bash", word) in self.rules
        return ("tool", tool) in self.rules

    async def _respond(self, request_id, *, allow, data=None, reason="user"):
        await self._write(
            claude.encode_decision(
                request_id, allow=allow, updated_input=data, message=DENY_TEXT.get(reason, "")
            )
        )

    async def _approval_request(self, payload):
        tool, data = payload["tool"], payload["input"]
        digest = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()
        summary = clip(redact_exception(tool_summary(tool, data) or tool), 500)
        aid = "apr_" + secrets.token_hex(16)
        now = datetime.now(UTC)
        row = {
            "id": aid,
            "session_id": self.sid,
            "tool_name": tool,
            "summary": summary,
            "input_digest": digest,
            "state": "pending",
            "requested_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=self.svc.approval_ttl_s)).isoformat(),
            "scope": None,
        }
        reason = None
        if self._rule_allows(tool, data):
            row.update(
                state="allowed",
                scope="session",
                decided_at=stamp(),
                decided_by_json='{"kind":"rule"}',
            )
        elif len(self.approvals) >= MAX_PENDING_APPROVALS:
            row.update(state="denied", decided_at=stamp(), decided_by_json='{"kind":"system"}')
            reason = "limit"
        await self.svc.store.create_approval(row)
        base = {"approval_id": aid, "tool": tool, "summary": summary}
        if row["state"] == "pending":
            entry = Approval(payload["request_id"], tool, data)
            entry.timer = asyncio.get_running_loop().call_later(
                self.svc.approval_ttl_s, self.inbox.put_nowait, ("approval_expire", aid)
            )
            self.approvals[aid] = entry
            await self.event(
                "approval", {**base, "state": "pending", "expires_at": row["expires_at"]}
            )
        elif row["state"] == "allowed":
            await self.event(
                "approval", {**base, "state": "allowed", "scope": "session", "auto": True}
            )
            await self._respond(payload["request_id"], allow=True, data=data)
        else:
            await self.event("approval", {**base, "state": "denied", "auto": True})
            await self._respond(payload["request_id"], allow=False, reason=reason)

    async def _approval_decided(self, aid, decision, by):
        entry = self.approvals.pop(aid, None)
        if entry is None:
            return
        if entry.timer:
            entry.timer.cancel()
        allow = decision != "deny"
        scope = "session" if decision == "allow_session" else "once"
        if decision == "allow_session":
            if entry.tool == "Bash":
                word = bash_word(entry.input.get("command"))
                if word:
                    self.rules.add(("Bash", word))
            else:
                self.rules.add(("tool", entry.tool))
        await self.event(
            "approval",
            {
                "approval_id": aid,
                "tool": entry.tool,
                "state": "allowed" if allow else "denied",
                "scope": scope,
                "by": by.get("kind"),
            },
        )
        await self._respond(entry.request_id, allow=allow, data=entry.input, reason="user")

    async def _approval_expire(self, aid):
        entry = self.approvals.get(aid)
        if entry is None:
            return
        won = await self.svc.store.settle_approval(
            self.sid, aid, "expired", None, {"kind": "system"}, datetime.now(UTC).isoformat()
        )
        if not won:
            return  # a decision won first; its message is already queued
        self.approvals.pop(aid, None)
        await self.event("approval", {"approval_id": aid, "tool": entry.tool, "state": "expired"})
        await self._respond(entry.request_id, allow=False, reason="expired")

    async def _expire_all(self, reason):
        """Interrupt/close/exit: pending approvals become expired and the CLI is told no."""
        if not self.approvals:
            return
        ids = set(await self.svc.store.expire_pending(self.sid))
        for aid in list(self.approvals):
            if aid not in ids:
                continue  # already decided; its decision message is still in the inbox
            entry = self.approvals.pop(aid)
            if entry.timer:
                entry.timer.cancel()
            await self.event(
                "approval", {"approval_id": aid, "tool": entry.tool, "state": "expired"}
            )
            await self._respond(entry.request_id, allow=False, reason=reason)

    async def stop_input(self):
        """Claude only: EOF on stdin, then a short grace for a natural exit."""
        if self.process is None:
            return
        await self.process.close_stdin()
        with contextlib.suppress(TimeoutError, OSError):
            await asyncio.wait_for(asyncio.shield(self.process.proc.wait()), self.svc.stop_grace_s)
