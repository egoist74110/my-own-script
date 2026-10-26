"""S7 service owner. Snapshots never acquire operation locks or spawn processes."""

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from toolbox_backend.adapters.ai_process import SupervisedProcess, child_environment
from toolbox_backend.adapters.net_info import read_network
from toolbox_backend.adapters.service_logs import ServiceLog
from toolbox_backend.adapters.service_runtime import (
    read_code_server_config,
    resolve_binary,
    validate_tunnel_target,
)
from toolbox_backend.api.services_schemas import (
    ActionRequest,
    BinariesView,
    BinaryInfo,
    CloudflaredView,
    LogsResult,
    NetworkInfo,
    ServicesSnapshot,
    ServicesStatusData,
    ServicesStatusEvent,
    ServiceView,
    SettingsResult,
)
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.services import ServicesConfig
from toolbox_backend.mcp.runner import secure_directory

DOMAIN = re.compile(r"https://[a-z0-9-]+(?:\.[a-z0-9-]+)*\.trycloudflare\.com", re.ASCII)
# cloudflared prints the URL either bare or boxed ("<ts> INF |  https://x.trycloudflare.com  |").
# Accept only those whole-line shapes so text embedded in other output never matches.
DOMAIN_LINE = re.compile(
    r"(?:\S+\s+(?:INF|INFO)\s+)?\|?\s*(" + DOMAIN.pattern + r")\s*\|?", re.ASCII
)


async def port_open(host, port):
    try:
        async with asyncio.timeout(0.2):
            _, writer = await asyncio.open_connection(host, port)
            writer.close()
            await writer.wait_closed()
        return True
    except OSError, TimeoutError:
        return False


@dataclass
class ServiceLifecycle:
    """One structural owner for process, stream readers, and health/exit monitor."""

    view: ServiceView = field(default_factory=ServiceView)
    owner: SupervisedProcess | None = None
    readers: list = field(default_factory=list)
    monitor: asyncio.Task | None = None
    operation: asyncio.Task | None = None
    log: ServiceLog | None = None
    protocol: str | None = None
    host: str = "127.0.0.1"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self):
        current = asyncio.current_task()
        monitor, self.monitor = self.monitor, None
        if monitor and monitor is not current:
            monitor.cancel()
        owner, self.owner = self.owner, None
        try:
            if owner:
                # The supervisor owns the process group and its identity; never discover PIDs.
                await owner.close()
        finally:
            for task in self.readers:
                task.cancel()
            await asyncio.gather(*self.readers, return_exceptions=True)
            self.readers.clear()
            if monitor and monitor is not current:
                await asyncio.gather(monitor, return_exceptions=True)
            self.view.owned = False


class ServicesService:
    def __init__(
        self,
        store,
        hub=None,
        *,
        code_server_config_path=None,
        path_extras=None,
        network_reader=read_network,
    ):
        self.store, self.hub = store, hub
        self.path_extras = path_extras
        # Tests never inspect the actual user's config, even via unrelated app lifespans.
        test_root = os.environ.get("TOOLBOX_TEST_ROOT")
        config_home = (
            Path(test_root) / ".config"
            if test_root
            else Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        )
        self.config_path = code_server_config_path or config_home / "code-server/config.yaml"
        self.network_reader = network_reader
        self.settings = ServicesConfig()
        self.revision = 0
        self._prior_change = store.on_change

        def config_changed(revision):
            self.revision = revision
            if self._prior_change:
                self._prior_change(revision)

        self._config_changed = config_changed
        store.on_change = config_changed
        self.network = NetworkInfo()
        self.binaries = BinariesView()
        self.code = ServiceLifecycle(log=ServiceLog(store.data_dir, "code-server"))
        self.global_tunnel = ServiceLifecycle(log=ServiceLog(store.data_dir, "cloudflared"))
        self.tunnels = {}
        self._requests = {}
        self._network_task = None
        self._closing = False
        self.health_interval_s = 30
        self.network_interval_s = 5

    async def _refresh(self):
        config = await self.store.read()
        self.settings, self.revision = config.services, config.revision
        for key, executable in [("code_server", "code-server"), ("cloudflared", "cloudflared")]:
            confirmed = getattr(self.settings.binaries, key)
            try:
                path = resolve_binary(executable, confirmed, path_extras=self.path_extras)
                info = BinaryInfo(found=True, path=path, confirmed=bool(confirmed))
            except SettingsError:
                info = BinaryInfo(confirmed=bool(confirmed))
            setattr(self.binaries, key, info)

    async def initialize(self):
        try:
            await self._refresh()
        except SettingsError:
            pass
        cfg = await asyncio.to_thread(read_code_server_config, self.config_path)
        self.code.view.port, self.code.host = cfg.port, cfg.host
        if cfg.bind_addr and await port_open(cfg.host, cfg.port):
            self.code.view.state = "external"
        # No service starts at initialization. The bounded ifconfig refresh starts lazily on the
        # first snapshot so an idle backend owns no child process.

    async def _network_loop(self):
        while True:
            # S6 uses the same explicit test path seam to avoid invoking installed tools.
            if self.path_extras is not None or "TOOLBOX_TEST_ROOT" not in os.environ:
                try:
                    value = await self.network_reader(
                        cwd=self.store.data_dir, path_extras=self.path_extras
                    )
                    if value != self.network:
                        self.network = value
                        self._emit()
                except OSError, ValueError, RuntimeError:
                    pass
            await asyncio.sleep(self.network_interval_s)

    def _snapshot(self):
        return ServicesSnapshot(
            code_server=self.code.view.model_copy(deep=True),
            cloudflared=CloudflaredView(
                **{
                    "global": self.global_tunnel.view.model_copy(deep=True),
                    "tunnels": [r.view.model_copy(deep=True) for r in self.tunnels.values()],
                }
            ),
            network=self.network.model_copy(),
            binaries=self.binaries.model_copy(deep=True),
            settings=self.settings.model_copy(deep=True),
            revision=self.revision,
        )

    async def snapshot(self):
        if self._network_task is None and not self._closing:
            self._network_task = asyncio.create_task(self._network_loop())
        return self._snapshot()

    def _emit(self):
        if self.hub:
            self.hub.publish_services(
                ServicesStatusEvent,
                ServicesStatusData(
                    services_seq=self.hub._state("services").last_seq + 1, snapshot=self._snapshot()
                ),
            )

    def _record(self, name):
        if name == "code-server":
            return self.code
        if name == "cloudflared":
            return self.global_tunnel
        if name in self.tunnels:
            return self.tunnels[name]
        raise SettingsError("not_found", "服务不存在", 404)

    def _claim(self, record):
        if self._closing or record.operation is not None:
            raise SettingsError("service_busy", "服务正在执行其他操作")
        record.operation = asyncio.current_task()

    def _cached(self, action, body):
        rid = getattr(body, "request_id", None)
        return self._requests.get((action, str(rid))) if rid else None

    def _remember(self, action, body, result):
        rid = getattr(body, "request_id", None)
        if rid:
            if len(self._requests) >= 1024:
                self._requests.pop(next(iter(self._requests)))
            self._requests[action, str(rid)] = result.model_copy(deep=True)
        return result

    async def start(self, name, body=None):
        body = body or ActionRequest()
        if cached := self._cached("start:" + name, body):
            return cached
        record = self._record(name)
        self._claim(record)
        try:
            await self._refresh()
            if record.view.state in {"running", "unhealthy"}:
                return self._remember("start:" + name, body, self._snapshot())
            key = "code_server" if name == "code-server" else "cloudflared"
            binary = resolve_binary(
                name, getattr(self.settings.binaries, key), path_extras=self.path_extras
            )
            if name == "code-server":
                cfg = await asyncio.to_thread(read_code_server_config, self.config_path)
                if not cfg.safe:
                    raise SettingsError(
                        "service_unsafe_config", "无法确认 code-server 密码认证配置安全"
                    )
                record.view.port, record.host = cfg.port, cfg.host
                if await port_open(cfg.host, cfg.port):
                    record.view.state = "external"
                    self._emit()
                    raise SettingsError("service_port_in_use", "服务端口已被外部进程占用")
                argv = [binary]
            else:
                cfg = await asyncio.to_thread(read_code_server_config, self.config_path)
                if not cfg.safe:
                    raise SettingsError(
                        "service_unsafe_config", "无法确认 code-server 密码认证配置安全"
                    )
                target = f"http://127.0.0.1:{cfg.port}"
                argv = self._tunnel_argv(binary, target)
                record.view.target_url = target
            await record.close()
            record.view.state, record.view.last_error, record.view.url = "starting", None, None
            record.protocol = self.settings.cloudflared.protocol
            record.operation = asyncio.create_task(
                self._launch(record, argv, name == "code-server")
            )
            self._emit()
            return self._remember("start:" + name, body, self._snapshot())
        finally:
            if record.operation is asyncio.current_task():
                record.operation = None

    def _tunnel_argv(self, binary, target):
        return [binary, "tunnel", "--url", target, "--protocol", self.settings.cloudflared.protocol]

    async def _pump(self, record, stream):
        # Consume bounded chunks rather than readline's unbounded-line failure mode.
        buffer = bytearray()
        dropping = False
        while chunk := await stream.read(16384):
            for part in chunk.splitlines(keepends=True):
                if not dropping:
                    buffer.extend(part)
                if len(buffer) > 65536:
                    buffer.clear()
                    dropping = True
                if part.endswith(b"\n"):
                    if not dropping:
                        await self._line(record, buffer.decode(errors="replace"))
                    buffer.clear()
                    dropping = False
        if buffer and not dropping:
            await self._line(record, buffer.decode(errors="replace"))

    async def _line(self, record, line):
        await asyncio.to_thread(record.log.write, line)
        record.view.log_tail_available = True
        # Match only an entire trimmed output line, never a token inside attacker text.
        found = DOMAIN_LINE.fullmatch(line.strip())
        candidate = found[1] if found else None
        if (
            candidate
            and candidate != "https://api.trycloudflare.com"
            and record.view.url != candidate
        ):
            record.view.url = candidate
            self._emit()

    async def _launch(self, record, argv, code_server):
        try:
            if not self.store.data_dir.exists():
                self.store.data_dir.mkdir(mode=0o700, parents=True)
            cwd = await asyncio.to_thread(secure_directory, self.store.data_dir, "services", "run")
            env = child_environment(
                path_extras=self.path_extras
                if self.path_extras is not None
                else ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
            )
            # Do not allow inherited Node options or service-specific environment overrides.
            for key in list(env):
                if key.upper() in {
                    "NODE_OPTIONS",
                    "CODE_SERVER_CONFIG",
                    "CS_DISABLE_GETTING_STARTED_OVERRIDE",
                }:
                    env.pop(key)
            record.owner = await SupervisedProcess.start(argv, str(cwd), stdio=True, env=env)
            record.readers = [
                asyncio.create_task(self._pump(record, stream))
                for stream in (record.owner.stdout, record.owner.stderr)
            ]
            deadline = asyncio.get_running_loop().time() + (
                self.settings.code_server.start_timeout_s if code_server else 15
            )
            while True:
                if record.owner.proc.returncode is not None:
                    raise RuntimeError("exited")
                if any(t.done() and t.exception() is not None for t in record.readers):
                    raise RuntimeError("log_failed")
                if code_server:
                    ready = await port_open(record.host, record.view.port)
                else:
                    ready = record.view.url is not None
                if ready or asyncio.get_running_loop().time() >= deadline:
                    if code_server and not ready:
                        raise RuntimeError("start_timeout")
                    break
                await asyncio.sleep(0.25)
            record.view.state = "running"
            record.view.owned = True
            record.monitor = asyncio.create_task(self._monitor(record, code_server))
        except asyncio.CancelledError:
            await record.close()
            record.view.state = "stopped"
            raise
        except Exception as exc:
            await record.close()
            record.view.state = "failed"
            record.view.last_error = (
                str(exc)
                if str(exc) in {"exited", "log_failed", "start_timeout"}
                else "start_failed"
            )
        finally:
            record.operation = None
            self._emit()

    async def _monitor(self, record, code_server):
        failures = 0
        owner = record.owner
        exited = asyncio.create_task(owner.proc.wait())
        try:
            while record.owner is owner:
                done, _ = await asyncio.wait({exited}, timeout=self.health_interval_s)
                if done:
                    record.view.state, record.view.last_error = "failed", "exited"
                    break
                if code_server:
                    host, port = record.host, record.view.port
                else:
                    target = urlsplit(record.view.target_url)
                    host = "127.0.0.1" if target.hostname == "localhost" else target.hostname
                    port = target.port
                ok = await port_open(host, port)
                failures = 0 if ok else failures + 1
                record.view.state = "unhealthy" if failures >= 3 else "running"
                record.view.last_error = "health_check_failed" if failures >= 3 else None
                self._emit()
        finally:
            exited.cancel()
            await asyncio.gather(exited, return_exceptions=True)
            if record.owner is owner:
                await record.close()
                self._emit()

    async def stop(self, name, body=None):
        body = body or ActionRequest()
        if cached := self._cached("stop:" + name, body):
            return cached
        record = self._record(name)
        self._claim(record)
        record.view.state = "stopping"
        record.operation = asyncio.create_task(self._stop(record))
        self._emit()
        return self._remember("stop:" + name, body, self._snapshot())

    async def _stop(self, record):
        try:
            await record.close()
            record.view.state, record.view.url = "stopped", None
        finally:
            record.operation = None
            self._emit()

    async def create_tunnel(self, body):
        if cached := self._cached("create_tunnel", body):
            return cached
        target = validate_tunnel_target(body.target_url, body.ack_public)
        await self._refresh()
        # No await from count check to registry reservation.
        if len(self.tunnels) >= self.settings.cloudflared.max_tunnels:
            raise SettingsError("tunnel_limit", "自定义隧道数量已达上限")
        binary = resolve_binary(
            "cloudflared", self.settings.binaries.cloudflared, path_extras=self.path_extras
        )
        if self._closing:
            raise SettingsError("service_busy", "服务正在关闭")
        identifier = str(uuid4())
        record = ServiceLifecycle(
            view=ServiceView(id=identifier, state="starting", target_url=target),
            log=ServiceLog(self.store.data_dir, "cloudflared-" + identifier),
            protocol=self.settings.cloudflared.protocol,
        )
        self.tunnels[identifier] = record
        record.operation = asyncio.create_task(
            self._launch(record, self._tunnel_argv(binary, target), False)
        )
        self._emit()
        return self._remember("create_tunnel", body, self._snapshot())

    async def delete_tunnel(self, identifier):
        if identifier not in self.tunnels:
            raise SettingsError("not_found", "隧道不存在", 404)
        record = self.tunnels[identifier]
        self._claim(record)
        try:
            await record.close()
            self.tunnels.pop(identifier, None)
            self._emit()
            return self._snapshot()
        finally:
            record.operation = None

    def _restart_required(self, new):
        return any(
            r.view.state in {"starting", "running", "unhealthy"}
            and r.protocol != new.cloudflared.protocol
            for r in [self.global_tunnel, *self.tunnels.values()]
        )

    async def patch_settings(self, body):
        def mutate(c):
            c.services = body.services

        result = await self.store.update(body.revision, mutate)
        await self._refresh()
        self._emit()
        return SettingsResult(
            revision=result.revision, restart_required=self._restart_required(body.services)
        )

    async def set_protocol(self, body):
        def mutate(c):
            c.services.cloudflared.protocol = body.protocol

        result = await self.store.update(body.revision, mutate)
        await self._refresh()
        self._emit()
        return SettingsResult(
            revision=result.revision, restart_required=self._restart_required(self.settings)
        )

    async def import_legacy(self, body):
        def read():
            with Path(body.path).open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError
            data = json.loads(raw)
            protocol = data.get("protocol")
            if protocol not in {"http2", "quic"}:
                raise ValueError
            return protocol

        try:
            protocol = await asyncio.to_thread(read)
        except OSError, ValueError, AttributeError:
            raise SettingsError("validation_error", "旧协议偏好文件不可用", 422) from None
        from toolbox_backend.api.services_schemas import ProtocolRequest

        return await self.set_protocol(ProtocolRequest(revision=body.revision, protocol=protocol))

    async def logs(self, name, tail=65536):
        if name.startswith("cloudflared-"):
            name = name.removeprefix("cloudflared-")
        record = self._record(name)
        try:
            text = await asyncio.to_thread(record.log.read_tail, min(max(tail, 1), 65536))
        except OSError, ValueError:
            raise SettingsError("store_unavailable", "服务日志不可用", 503) from None
        return LogsResult(text=text)

    async def close(self):
        self._closing = True
        if self.store.on_change is self._config_changed:
            self.store.on_change = self._prior_change
        records = [self.code, self.global_tunnel, *self.tunnels.values()]
        tasks = [r.operation for r in records if r.operation is not None]
        if self._network_task:
            self._network_task.cancel()
            tasks.append(self._network_task)
        for task in tasks:
            task.cancel()
        # Close control channels synchronously before waiting on cancelled starts.
        for record in records:
            if record.owner:
                record.owner.close_control()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(r.close() for r in records), return_exceptions=True)
        for record in records:
            record.view.state = "stopped"
