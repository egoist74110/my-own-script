"""Profile ownership, exact Chrome identity reclamation and in-memory URL delivery."""

import asyncio
import contextlib
import json
import os
import signal
import tempfile
from pathlib import Path

from toolbox_backend.adapters.ai_process import SupervisedProcess, child_environment
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.mcp.runner import secure_directory, validate_data_dir
from toolbox_backend.vpn.login_worker import ERRORS, MAX_LINE, encode_event


def vpn_directory(data_dir):
    root = Path(data_dir).absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    validate_data_dir(root)
    return secure_directory(root, "vpn")


def secure_profile(data_dir):
    profile = vpn_directory(data_dir) / "chrome-profile"
    if profile.is_symlink():
        raise ValueError("unsafe browser profile")
    profile.mkdir(mode=0o700, exist_ok=True)
    profile.chmod(0o700)
    return profile


async def process_rows():
    proc = await asyncio.create_subprocess_exec(
        "/bin/ps",
        "-axo",
        "pid,ppid,pgid,lstart,command",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 2)
        if len(out) > 8 << 20:
            return []
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    rows = []
    for line in out.decode(errors="replace").splitlines()[1:]:
        parts = line.strip().split(None, 8)
        if len(parts) == 9:
            with contextlib.suppress(ValueError):
                rows.append(
                    dict(
                        pid=int(parts[0]),
                        ppid=int(parts[1]),
                        pgid=int(parts[2]),
                        lstart=" ".join(parts[3:8]),
                        command=parts[8],
                    )
                )
    return rows


async def inspect_process(pid):
    return next((row for row in await process_rows() if row["pid"] == pid), None)


def has_profile(command, profile):
    marker = f"--user-data-dir={profile}"
    offset = command.find(marker)
    end = offset + len(marker)
    return (
        offset >= 0
        and (offset == 0 or command[offset - 1].isspace())
        and (end == len(command) or command[end].isspace())
    )


async def discover_chrome(worker_pid, profile):
    rows = await process_rows()
    descendants = {worker_pid}
    for _ in range(len(rows)):
        added = {r["pid"] for r in rows if r["ppid"] in descendants}
        if added <= descendants:
            break
        descendants |= added
    for row in rows:
        if (
            row["pid"] in descendants
            and row["pid"] == row["pgid"]
            and has_profile(row["command"], profile)
            and "--remote-debugging-pipe" in row["command"]
        ):
            return {key: row[key] for key in ("pid", "lstart")}
    return None


class ChromeRegistry:
    def __init__(self, data_dir, *, inspect=inspect_process, killpg=os.killpg, sleep=asyncio.sleep):
        self.data_dir = Path(data_dir)
        self.inspect, self.killpg, self.sleep = inspect, killpg, sleep
        self.records = []

    @property
    def path(self):
        return vpn_directory(self.data_dir) / "chrome-processes.json"

    def record(self, identity):
        pid, start = identity.get("pid"), identity.get("lstart")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
            raise ValueError("invalid chrome pid")
        if not isinstance(start, str) or not start or len(start) > 64:
            raise ValueError("invalid chrome start")
        if not self.records:
            self.load()
        self.records.append({"pid": pid, "lstart": start})
        self.save()

    def load(self):
        path = self.path
        if path.is_symlink():
            raise ValueError("unsafe chrome registry")
        if path.exists():
            if path.stat().st_size > MAX_LINE:
                raise ValueError("chrome registry too large")
            data = json.loads(path.read_text())
            if not isinstance(data, list) or len(data) > 32:
                raise ValueError("invalid chrome registry")
            self.records = data

    def save(self):
        path = self.path
        if path.is_symlink():
            raise ValueError("unsafe chrome registry")
        fd, temporary = tempfile.mkstemp(prefix=".chrome-processes.", dir=path.parent)
        temp = Path(temporary)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(self.records, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)

    async def cleanup(self):
        if not self.records:
            self.load()
        remaining = []
        for record in self.records:
            pid = record.get("pid")
            if not isinstance(pid, int) or pid <= 1:
                continue
            row = await self.inspect(pid)
            profile = str(self.data_dir.absolute() / "vpn/chrome-profile")

            def matches(current, record=record, pid=pid, profile=profile):
                return (
                    current
                    and current.get("lstart") == record.get("lstart")
                    and current.get("pgid") == pid
                    and has_profile(current.get("command", ""), profile)
                )

            if not matches(row):
                continue
            try:
                self.killpg(pid, signal.SIGTERM)
                await self.sleep(3)
                if matches(await self.inspect(pid)):
                    self.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                remaining.append(record)
        self.records = remaining
        self.save()


async def open_callback(url, app_path):
    """No argv/logging: NSURL is passed only to the selected application's NSWorkspace API."""
    if sys_platform() != "darwin":
        raise RuntimeError("NSWorkspace unavailable")
    from AppKit import NSWorkspace, NSWorkspaceOpenConfiguration
    from Foundation import NSURL

    loop = asyncio.get_running_loop()
    completed = loop.create_future()

    def result(_app, error):
        def finish():
            if not completed.done():
                if error:
                    completed.set_exception(RuntimeError("callback delivery failed"))
                else:
                    completed.set_result(None)

        loop.call_soon_threadsafe(finish)

    NSWorkspace.sharedWorkspace().openURLs_withApplicationAtURL_configuration_completionHandler_(
        [NSURL.URLWithString_(url)],
        NSURL.fileURLWithPath_(str(app_path)),
        NSWorkspaceOpenConfiguration.configuration(),
        result,
    )
    await asyncio.wait_for(completed, 8)


def sys_platform():
    import sys

    return sys.platform


class ProcessLoginRunner:
    def __init__(
        self,
        data_dir,
        client,
        *,
        process_factory=SupervisedProcess.start,
        path_extras=None,
        registry=None,
        on_event=None,
    ):
        self.data_dir, self.client = Path(data_dir), client
        self.process_factory, self.path_extras = process_factory, path_extras
        self.registry = registry or ChromeRegistry(data_dir)
        self.on_event = on_event

    async def initialize(self):
        await self.registry.cleanup()

    async def run(self, config, password, seed, cancel, request_mfa):
        import sys

        if cancel.is_set():
            raise asyncio.CancelledError
        app = self.client.resolve(config.client.bundle_id)
        if not app:
            raise SettingsError("vpn_client_missing", "VPN 客户端未安装", 409)
        secure_profile(self.data_dir)
        options = dict(
            data_dir=str(self.data_dir),
            scheme=config.client.url_scheme,
            app_path=str(app.app_path),
            headless=config.login.headless,
            has_seed=bool(seed),
            chrome_path=config.chrome_path,
            timeout_s=config.login_timeout_s,
            password=password,
            **config.login.model_dump(exclude={"headless", "totp_filter"}),
        )
        raw = (json.dumps(options) + "\n").encode()
        if len(raw) > MAX_LINE:
            raise SettingsError("login_timeout", "登录参数超出限制", 422)
        environment = child_environment(path_extras=self.path_extras)
        sensitive = [value for value in (password, seed) if value]
        environment = {
            key: value
            for key, value in environment.items()
            if not key.upper().startswith("PLAYWRIGHT_")
            and key.upper() not in {"NODE_OPTIONS", "DEBUG"}
            and not any(secret in value for secret in sensitive)
        }
        owner = await self.process_factory(
            [sys.executable, "-m", "toolbox_backend.vpn.login_worker"],
            str(self.data_dir),
            stdio=True,
            env=environment,
        )

        async def discard():
            # stderr is never reflected or persisted (third-party errors may contain secrets).
            while await owner.stderr.read(16384):
                pass

        async def exchange():
            owner.stdin.write(raw)
            await owner.stdin.drain()
            attempts = 0
            while True:
                line = await owner.stdout.readline()
                try:
                    if not line or len(line) > MAX_LINE or not line.endswith(b"\n"):
                        raise ValueError("invalid worker line")
                    event = json.loads(line)
                    kind = event.pop("event")
                    encode_event(kind, **event)  # never log raw worker output
                except ValueError, KeyError, TypeError, AttributeError:
                    raise SettingsError("login_timeout", "登录 worker 协议失败", 502) from None
                if kind == "chrome_started":
                    self.registry.record(event)
                elif kind == "need_mfa":
                    attempts += 1
                    if attempts > 3 or event.get("attempt") != attempts:
                        raise SettingsError("login_mfa_rejected", "MFA 重试次数超出限制", 409)
                    code = await request_mfa()
                    owner.stdin.write((json.dumps({"event": "mfa", "code": code}) + "\n").encode())
                    await owner.stdin.drain()
                elif kind == "error":
                    code = event.get("code")
                    raise SettingsError(
                        code if code in ERRORS else "login_timeout", "VPN 登录失败", 409
                    )
                elif kind == "done":
                    return
                if self.on_event:
                    self.on_event({"event": kind, **event})

        drain = asyncio.create_task(discard())
        exchange_task = asyncio.create_task(exchange())
        cancelled = asyncio.create_task(cancel.wait())
        try:
            done, _ = await asyncio.wait(
                [exchange_task, cancelled], return_when=asyncio.FIRST_COMPLETED
            )
            if cancelled in done:
                raise asyncio.CancelledError
            await exchange_task
        except ValueError, json.JSONDecodeError:
            raise SettingsError("login_timeout", "登录 worker 协议失败", 502) from None
        finally:
            try:
                for task in (exchange_task, cancelled):
                    task.cancel()
                await asyncio.gather(exchange_task, cancelled, return_exceptions=True)
                owner.stop()
                owner.close_control()
                results = await asyncio.gather(
                    owner.close(), self.registry.cleanup(), return_exceptions=True
                )
                for result in results:
                    if isinstance(result, BaseException):
                        raise result
            finally:
                drain.cancel()
                await asyncio.gather(drain, return_exceptions=True)
