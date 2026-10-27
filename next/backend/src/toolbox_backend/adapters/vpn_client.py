"""Narrow, fixed-argv controller for the selected VPN application."""

import asyncio
import os
import plistlib
import shutil
import signal
from dataclasses import dataclass
from pathlib import Path

from toolbox_backend.adapters.ai_process import child_environment
from toolbox_backend.domain.errors import SettingsError


@dataclass(frozen=True)
class ClientApp:
    bundle_id: str
    app_path: Path
    app_name: str
    executable: str
    version: str | None = None


class ClientController:
    def __init__(self, *, app_roots=None, path_extras=None, command_runner=None, term=os.kill):
        self.app_roots = [
            Path(p) for p in (app_roots or ["/Applications", Path.home() / "Applications"])
        ]
        self.path_extras = path_extras
        self.command_runner = command_runner or self._run
        self.term = term

    async def _run(self, argv, *, timeout_s=5, limit=1 << 20):
        env = child_environment(path_extras=self.path_extras)
        executable = shutil.which(argv[0], path=env["PATH"])
        if not executable:
            raise FileNotFoundError
        proc = await asyncio.create_subprocess_exec(
            executable,
            *argv[1:],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        async def read_bounded(stream):
            parts, size = [], 0
            while chunk := await stream.read(16384):
                size += len(chunk)
                if size > limit:
                    raise ValueError("client_output_limit")
                parts.append(chunk)
            return b"".join(parts)

        readers = [
            asyncio.create_task(read_bounded(proc.stdout)),
            asyncio.create_task(read_bounded(proc.stderr)),
        ]
        waiter = asyncio.create_task(proc.wait())
        try:
            async with asyncio.timeout(timeout_s):
                out, err, _ = await asyncio.gather(*readers, waiter)
            if len(out) + len(err) > limit:
                raise ValueError("client_output_limit")
            return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")
        except BaseException:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 1)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
            for task in [*readers, waiter]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*readers, waiter, return_exceptions=True)
            raise

    def resolve(self, bundle_id: str) -> ClientApp | None:
        for root in self.app_roots:
            if not root.is_dir():
                continue
            for info_path in root.glob("*.app/Contents/Info.plist"):
                try:
                    with info_path.open("rb") as stream:
                        info = plistlib.load(stream)
                    if info.get("CFBundleIdentifier") != bundle_id:
                        continue
                    app_path = info_path.parents[2]
                    executable = info.get("CFBundleExecutable")
                    if not isinstance(executable, str) or not executable:
                        continue
                    return ClientApp(
                        bundle_id,
                        app_path,
                        str(
                            info.get("CFBundleDisplayName")
                            or info.get("CFBundleName")
                            or app_path.stem
                        ),
                        executable,
                        info.get("CFBundleShortVersionString"),
                    )
                except OSError, ValueError, plistlib.InvalidFileException:
                    continue
        return None

    async def processes(self, app: ClientApp) -> list[tuple[int, str, str]]:
        code, out, _ = await self.command_runner(["ps", "-axo", "pid,lstart,command"], timeout_s=3)
        if code:
            return []
        prefix = str(app.app_path / "Contents/MacOS") + "/"
        rows = []
        for line in out.splitlines()[1:]:
            parts = line.strip().split(None, 6)
            if len(parts) < 7:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            lstart, command = " ".join(parts[1:6]), parts[6]
            if command.startswith(prefix) and "/Helpers/" not in command:
                rows.append((pid, lstart, command))
        return rows

    async def status(self, bundle_id: str) -> dict:
        app = self.resolve(bundle_id)
        if not app:
            return {"installed": False, "running": False, "app_name": None, "version": None}
        return {
            "installed": True,
            "running": bool(await self.processes(app)),
            "app_name": app.app_name,
            "version": app.version,
        }

    async def open(self, bundle_id: str) -> None:
        if not self.resolve(bundle_id):
            raise SettingsError("vpn_client_missing", "VPN 客户端未安装", 409)
        code, _, _ = await self.command_runner(["open", "-b", bundle_id], timeout_s=8)
        if code:
            raise SettingsError("vpn_client_missing", "无法打开 VPN 客户端", 409)

    async def restart(self, bundle_id: str, *, allow_term: bool = True) -> None:
        app = self.resolve(bundle_id)
        if not app:
            raise SettingsError("vpn_client_missing", "VPN 客户端未安装", 409)
        before = await self.processes(app)
        code, _, _ = await self.command_runner(
            ["osascript", "-e", f'tell application id "{bundle_id}" to quit'], timeout_s=5
        )
        if code == 0:
            deadline = asyncio.get_running_loop().time() + 1.0
            while asyncio.get_running_loop().time() < deadline and await self.processes(app):  # noqa: ASYNC110
                await asyncio.sleep(0.1)
        remaining = await self.processes(app)
        if remaining and allow_term:
            previous = {pid: started for pid, started, _ in before}
            for pid, started, _ in remaining:
                if previous.get(pid) == started:
                    try:
                        self.term(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        continue
                    break  # exactly one identity-checked TERM
            deadline = asyncio.get_running_loop().time() + 3.0
            while asyncio.get_running_loop().time() < deadline and await self.processes(app):  # noqa: ASYNC110
                await asyncio.sleep(0.1)
            remaining = await self.processes(app)
        if remaining:
            raise SettingsError("client_stuck", "VPN 客户端未能退出", 409)
