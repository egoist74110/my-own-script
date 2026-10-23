"""Validated argv, isolated environment, and a pipe-controlled subprocess owner."""

import asyncio
import contextlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path

from toolbox_backend.domain.ai import profile_argv  # noqa: F401
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.logging_setup import register_secret


def child_environment(pty: bool = False, *, path_extras=None) -> dict[str, str]:
    env = {}
    for key, value in os.environ.items():
        upper = key.upper()
        safe_path = upper in {"PATH", "MANPATH", "INFOPATH", "FPATH"}
        sensitive = bool(
            set(upper.split("_"))
            & {
                "TOKEN",
                "TOKENS",
                "SECRET",
                "SECRETS",
                "PASSWORD",
                "PASSWD",
                "PAT",
                "COOKIE",
                "COOKIES",
            }
        ) or any(
            part in upper
            for part in (
                "API_KEY",
                "APIKEY",
                "ACCESS_KEY",
                "PRIVATE_KEY",
                "TOKEN",
                "SECRET",
                "PASSWORD",
            )
        )
        if not safe_path and (upper.startswith("TOOLBOX_") or upper == "CI" or sensitive):
            if sensitive:
                register_secret(value)
        else:
            env[key] = value
    parts = env.get("PATH", "").split(os.pathsep)
    if path_extras is None:
        path_extras = default_path_extras()
    for extra in path_extras:
        if extra not in parts and Path(extra).is_dir():
            parts.append(str(extra))
    env["PATH"] = os.pathsep.join(p for p in parts if p)
    env["TERM"] = "xterm-256color"
    if pty:
        env["COLORTERM"] = "truecolor"
    return env


def default_path_extras():
    return [
        "/usr/local/bin",
        "/opt/homebrew/bin",
        str(Path.home() / ".gemini/bin"),
        str(Path.home() / ".local/bin"),
        str(Path.home() / "bin"),
    ]


def resolve_argv(command: str, *, path_extras=None) -> list[str]:
    argv = profile_argv(command)
    found = shutil.which(argv[0], path=child_environment(path_extras=path_extras)["PATH"])
    if not found:
        raise SettingsError("cli_not_found", "AI CLI 不存在或不可执行", 409)
    path = Path(found).resolve()
    if not stat.S_ISREG(path.stat().st_mode) or not os.access(path, os.X_OK):
        raise SettingsError("cli_not_found", "AI CLI 不存在或不可执行", 409)
    argv[0] = str(path)
    return argv


class SupervisedProcess:
    """Own control/status descriptors and the reaped supervisor; no backend fork."""

    def __init__(self, proc, control, status):
        self.proc, self.control, self.status = proc, control, status
        self.identity = None

    @classmethod
    async def start(cls, argv, cwd, *, slave=None, path_extras=None):
        control_r = control_w = status_r = status_w = -1
        proc = None
        try:
            control_r, control_w = os.pipe()
            status_r, status_w = os.pipe()
            # Boot payload is read from stdin before PTY stdio is installed.
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "toolbox_backend.adapters.proc_supervisor",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE if slave is None else asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.STDOUT,
                pass_fds=tuple(fd for fd in (control_r, status_w, slave) if fd is not None),
                start_new_session=True,
            )
            payload = dict(
                argv=argv,
                cwd=cwd,
                env=child_environment(slave is not None, path_extras=path_extras),
                control=control_r,
                status=status_w,
                slave=slave,
            )
            proc.stdin.write(json.dumps(payload).encode() + b"\n")
            await proc.stdin.drain()
            proc.stdin.close()
            owner = cls(proc, control_w, status_r)
            os.close(control_r)
            control_r = -1
            os.close(status_w)
            status_w = -1

            # A fixed status pipe is independent of CLI output and contains no secrets.
            async def ready():
                os.set_blocking(status_r, False)
                data = bytearray()
                loop = asyncio.get_running_loop()
                while b"\n" not in data:
                    available = loop.create_future()
                    loop.add_reader(status_r, lambda f=available: f.done() or f.set_result(None))
                    try:
                        await available
                        block = os.read(status_r, 4096)
                    finally:
                        loop.remove_reader(status_r)
                    if not block:
                        raise RuntimeError("start_failed")
                    data.extend(block)
                return json.loads(data.split(b"\n")[0])

            owner.identity = await asyncio.wait_for(ready(), 5)
            if owner.identity.get("error"):
                raise RuntimeError(
                    "start_failed:"
                    + str(owner.identity.get("category"))
                    + ":"
                    + str(owner.identity.get("errno"))
                )
            return owner
        except BaseException:
            for fd in (control_w, status_r):
                if fd >= 0:
                    os.close(fd)
            if proc:
                # Drain discarded startup output so a full pipe cannot prevent reaping.
                async def reap():
                    if proc.stdout:
                        while await proc.stdout.read(65536):
                            pass
                    await proc.wait()

                await asyncio.wait_for(reap(), 4.8)
            raise
        finally:
            for fd in (control_r, status_w):
                if fd >= 0:
                    os.close(fd)

    def stop(self):
        if self.control is not None:
            with contextlib.suppress(BrokenPipeError):
                os.write(self.control, b"stop\n")

    def close_control(self):
        if self.control is not None:
            os.close(self.control)
            self.control = None

    async def close(self):
        self.stop()
        self.close_control()
        drain = None
        if self.proc.stdout:

            async def discard():
                while await self.proc.stdout.read(65536):
                    pass

            drain = asyncio.create_task(discard())
        try:
            await asyncio.wait_for(self.proc.wait(), 4.5)
            if drain:
                await asyncio.wait_for(drain, 0.2)
        finally:
            if drain and not drain.done():
                drain.cancel()
                await asyncio.gather(drain, return_exceptions=True)
            if self.status is not None:
                os.close(self.status)
                self.status = None
