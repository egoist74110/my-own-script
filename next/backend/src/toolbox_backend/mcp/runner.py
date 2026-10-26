"""Reusable bounded stdio handshake, with one owner for all cleanup paths."""

import asyncio
import contextlib
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from toolbox_backend.adapters.ai_process import SupervisedProcess, child_environment
from toolbox_backend.api.mcp_schemas import SelfTestResult
from toolbox_backend.logging_setup import redact_exception

LINE_LIMIT = 4 << 20
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")


def redact_mcp(value):
    text = redact_exception(value)
    text = re.sub(r'(?i)\bBearer\s+[^\s"\',;]+', "Bearer ***", text)
    text = re.sub(r"\b(?:ur|u)-[A-Za-z0-9._~-]+", "***", text)
    return re.sub(r'(?i)(\bcode\s*[=:]\s*)[^\s&"\',;]+', r"\1***", text)


def mcp_environment(*, path_extras=None):
    env = child_environment(path_extras=path_extras)
    return {
        k: v
        for k, v in env.items()
        if not (
            k.upper() in {"NODE_OPTIONS", "APP_ID", "APP_SECRET", "USER_ACCESS_TOKEN"}
            or k.upper().startswith(("LARK_", "FIGMA_"))
        )
    }


def validate_data_dir(path):
    path = Path(path).absolute()
    # Reject symlinks in every path component, including a symlink data-dir ancestor.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("unsafe data directory")
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("unsafe data directory")
    return path


def secure_directory(parent, *parts):
    """Create beneath an already trusted root; never chmod or follow a symlink."""
    current = Path(parent)
    for part in parts:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in {".", ".."}:
            raise ValueError("invalid directory segment")
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("unsafe directory")
    return current


def prepare_run_directory(data_dir, name):
    validate_data_dir(data_dir)
    path = secure_directory(data_dir, "mcp", "run", name)
    if any(path.iterdir()):
        raise ValueError("run directory must be empty")
    return path


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: list[str]
    path_extras: list[str] | None = None
    env_extras: dict[str, str] | None = None


async def run_self_test(spec: CommandSpec, data_dir: Path, *, timeout_s=15):
    if not 1 <= timeout_s <= 60:
        raise ValueError("invalid deadline")
    started = time.monotonic()
    result = SelfTestResult()
    owner = None
    tasks = []
    stderr = bytearray()
    # Only two replies are expected; flooding must not grow memory without bound.
    replies = asyncio.Queue(maxsize=8)

    async def read_stdout():
        buffer = bytearray()
        try:
            while chunk := await owner.stdout.read(65536):
                buffer.extend(chunk)
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    buffer[:] = rest
                    if len(line) > LINE_LIMIT:
                        raise ValueError("line_too_long")
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        raise ValueError("bad_response")
                    if "id" in payload:
                        replies.put_nowait(payload)
                if len(buffer) > LINE_LIMIT:
                    raise ValueError("line_too_long")
            raise ValueError("process_exited")
        except ValueError, asyncio.QueueFull:
            # Wake the protocol consumer; the reader never waits on it.
            with contextlib.suppress(asyncio.QueueFull):
                replies.put_nowait(None)

    async def read_stderr():
        while chunk := await owner.stderr.read(8192):
            stderr.extend(chunk)
            del stderr[:-65536]

    async def send(payload):
        owner.stdin.write(json.dumps(payload).encode() + b"\n")
        await owner.stdin.drain()

    async def reply(ident):
        payload = await replies.get()
        if (
            not payload
            or payload.get("jsonrpc") != "2.0"
            or payload.get("id") != ident
            or "error" in payload
            or not isinstance(payload.get("result"), dict)
        ):
            raise ValueError("bad_response")
        return payload["result"]

    async def cleanup():
        if owner is not None:
            try:
                await owner.close_stdin()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(owner.proc.wait()), 2)
                owner.close_control()
                await owner.close()
            except TimeoutError, OSError:
                result.ok = False
                result.error_code = "kill_failed"
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    try:
        cwd = prepare_run_directory(data_dir, spec.name)
        # Reserve the 2s EOF grace + supervisor's 3s TERM grace + wait margin.
        async with asyncio.timeout(max(0.05, timeout_s - 6.7)):
            env = mcp_environment(path_extras=spec.path_extras)
            if spec.env_extras:
                env.update(spec.env_extras)
            owner = await SupervisedProcess.start(
                spec.argv, str(cwd), stdio=True, env=env
            )
            tasks.extend([asyncio.create_task(read_stdout()), asyncio.create_task(read_stderr())])
            await send(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": PROTOCOLS[0],
                        "capabilities": {},
                        "clientInfo": {"name": "toolbox-self-test", "version": "1"},
                    },
                }
            )
            initialized = await reply(1)
            version = initialized.get("protocolVersion")
            name = initialized.get("serverInfo", {}).get("name")
            if version not in PROTOCOLS or not isinstance(name, str) or not name:
                raise ValueError("bad_response")
            await send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            await send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            tools = (await reply(2)).get("tools")
            if (
                not isinstance(tools, list)
                or len(tools) > 1000
                or any(not isinstance(t, dict) or not isinstance(t.get("name"), str) for t in tools)
            ):
                raise ValueError("bad_response")
            result.ok, result.protocol_version, result.server_name = True, version, redact_mcp(name)
            result.tools = [redact_mcp(t["name"]) for t in tools]
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        result.error_code = "timeout"
    except Exception:
        result.error_code = "mcp_self_test_failed"
    finally:
        closing = asyncio.create_task(cleanup())
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            await closing
            raise
        result.stderr_tail = redact_mcp(stderr.decode(errors="replace"))[-65536:]
        result.duration_ms = int((time.monotonic() - started) * 1000)
    return result
