"""VPN runtime owner: one run, bounded history, and injected OS/browser seams."""

import asyncio
import contextlib
import time
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError

from toolbox_backend.adapters.net_info import read_network
from toolbox_backend.adapters.vpn_log import VpnLog
from toolbox_backend.adapters.vpn_totp import parse_totp_import, totp
from toolbox_backend.api.vpn_schemas import VpnRunView, VpnSnapshot
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.logging_setup import register_secret


class ClientPort(Protocol):
    def resolve(self, bundle_id: str): ...
    async def status(self, bundle_id: str) -> dict: ...
    async def open(self, bundle_id: str) -> None: ...
    async def restart(self, bundle_id: str, *, allow_term: bool = True) -> None: ...


class LoginRunner(Protocol):
    async def run(
        self, config, password: str, seed: str | None, cancel: asyncio.Event, request_mfa
    ): ...


class WindowAutomation(Protocol):
    async def permissions(self) -> dict: ...
    async def connect(self, mode: str) -> str: ...


class UnimplementedLoginRunner:
    async def run(self, config, password, seed, cancel, request_mfa):
        raise SettingsError("vpn_not_implemented", "VPN 登录流程将在后续版本提供", 501)


class UnimplementedWindowAutomation:
    async def permissions(self):
        return {"screen_recording": "unknown", "accessibility": "unknown"}

    async def connect(self, mode):
        raise SettingsError("vpn_not_implemented", "窗口自动化将在后续版本提供", 501)


def now():
    return datetime.now(UTC)


class VpnService:
    def __init__(
        self,
        store,
        credentials,
        legacy,
        client: ClientPort,
        hub,
        *,
        login_runner=None,
        window_automation=None,
        network_reader=read_network,
        path_extras=None,
    ):
        self.store, self.credentials, self.legacy, self.client, self.hub = (
            store,
            credentials,
            legacy,
            client,
            hub,
        )
        self.login_runner = login_runner or UnimplementedLoginRunner()
        self.window_automation = window_automation or UnimplementedWindowAutomation()
        self.network_reader, self.path_extras = network_reader or read_network, path_extras
        self.log = VpnLog(store.data_dir)
        self.runs: list[dict] = []
        self._active: dict | None = None
        self._task: asyncio.Task | None = None
        self._gate = asyncio.Lock()
        self._requests: dict[str, str] = {}
        self._closing = False
        self.on_complete = None
        self._last_status = None

    @property
    def active(self):
        return self._active is not None

    def _credential(self, key):
        try:
            value = self.credentials.get(key)
        except Exception:
            raise SettingsError("credential_backend_error", "凭据后端访问失败", 502) from None
        return value

    async def snapshot(self):
        config = await self.store.read()
        info = await self.network_reader(
            cwd=self.store.data_dir,
            path_extras=self.path_extras,
            tunnel_prefix=config.vpn.tunnel_prefix,
        )
        client = await self.client.status(config.vpn.client.bundle_id)
        permissions = await self.window_automation.permissions()
        run = self._public(self._active) if self._active else None
        snapshot = VpnSnapshot(
            connected=bool(info.vpn_ip),
            ip=info.vpn_ip,
            client=client,
            credentials={
                "password": bool(self._credential("vpn_password")),
                "totp_secret": bool(self._credential("vpn_totp_secret")),
            },
            permissions=permissions,
            settings=config.vpn,
            current_run=run,
            revision=config.revision,
        )
        self._publish_status(snapshot.connected, snapshot.ip, snapshot.client, run)
        return snapshot

    def _publish_status(self, connected, ip, client=None, run=None):
        if not hasattr(self.hub, "publish_vpn"):
            return
        current = {
            "connected": bool(connected),
            "ip": ip,
            "client": client or {},
            "current_run": (
                {"run_id": run.run_id, "state": run.state, "rung": run.rung} if run else None
            ),
        }
        signature = repr(current)
        if signature == self._last_status:
            return
        self._last_status = signature
        self.hub.publish_vpn("vpn.status", current)

    async def update_settings(self, body):
        async with self._gate:
            if self._active:
                raise SettingsError("vpn_busy", "VPN 运行期间不能修改设置", 409)
            return await self.store.update(body.revision, lambda c: setattr(c, "vpn", body.vpn))

    def write_credential(self, kind, value):
        if self._active:
            raise SettingsError("vpn_busy", "VPN 运行期间不能修改凭据", 409)
        if kind not in {"vpn_password", "vpn_totp_secret"}:
            raise SettingsError("not_found", "凭据类型不存在", 404)
        register_secret(value)
        try:
            self.credentials.set(kind, value)
        except Exception:
            raise SettingsError("credential_backend_error", "凭据后端访问失败", 502) from None

    def delete_credential(self, kind):
        if self._active:
            raise SettingsError("vpn_busy", "VPN 运行期间不能修改凭据", 409)
        if kind not in {"vpn_password", "vpn_totp_secret"}:
            raise SettingsError("not_found", "凭据类型不存在", 404)
        try:
            self.credentials.delete(kind)
        except Exception:
            raise SettingsError("credential_backend_error", "凭据后端访问失败", 502) from None

    async def import_legacy(self, kinds, fields=False):
        imported = []
        for kind in dict.fromkeys(kinds):
            legacy_account = {
                "vpn_password": "harmony_vpn:password",
                "vpn_totp_secret": "harmony_vpn:totp_secret",
            }.get(kind)
            if legacy_account is None:
                raise SettingsError("validation_error", "凭据类型无效", 422)
            value = self.legacy.get(legacy_account)
            if value:
                self.write_credential(kind, value)
                imported.append(kind)
        if fields:
            config = await self.store.read()
            values = {}
            for field in ("workspace", "residency", "email", "totp_filter"):
                value = self.legacy.get(f"harmony_vpn:{field}")
                if value:
                    values[field] = value
            if values:
                from toolbox_backend.domain.vpn import VpnLogin

                try:
                    VpnLogin.model_validate({**config.vpn.login.model_dump(), **values})
                except ValidationError:
                    raise SettingsError("validation_error", "旧应用设置无法导入", 422) from None
            if values:

                def mutate(candidate):
                    candidate.vpn.login = VpnLogin.model_validate(
                        {**candidate.vpn.login.model_dump(), **values}
                    )

                updated = await self.store.update(config.revision, mutate)
                imported.extend(
                    f"field:{name}"
                    for name in values
                    if getattr(updated.vpn.login, name) == values[name]
                )
        return {"imported": imported}

    async def import_totp(self, text, index=None):
        config = await self.store.read()
        try:
            candidates = parse_totp_import(text, config.vpn.login.totp_filter)
        except ValueError as exc:
            code = str(exc)
            mapping = {
                "totp_unsupported": ("totp_unsupported", 422),
                "totp_not_found": ("totp_not_found", 422),
                "totp_import_too_large": ("totp_import_too_large", 413),
            }
            error, status = mapping.get(code, ("totp_not_found", 422))
            raise SettingsError(error, "未找到可导入的 TOTP 项目", status) from None
        if len(candidates) > 1 and index is None:
            raise SettingsError(
                "totp_ambiguous",
                "找到多个匹配项目，请选择一个",
                409,
                items=[
                    {"issuer": x["issuer"], "label": x["label"], "index": i}
                    for i, x in enumerate(candidates)
                ],
            )
        selected = index if index is not None else 0
        if selected >= len(candidates):
            raise SettingsError("validation_error", "TOTP 项目序号无效", 422)
        self.write_credential("vpn_totp_secret", candidates[selected]["secret"])
        return {"configured": True}

    async def request_mfa(self, record):
        seed = self._credential("vpn_totp_secret")
        if seed:
            return totp(seed, time.time())
        future = asyncio.get_running_loop().create_future()
        record["mfa_future"] = future
        if hasattr(self.hub, "publish_vpn"):
            self.hub.publish_vpn(
                "vpn.mfa_required",
                {"run_id": record["run_id"], "expires_in_s": 120},
            )
        try:
            return await asyncio.wait_for(future, timeout=120)
        except TimeoutError:
            raise SettingsError("vpn_mfa_timeout", "手动 MFA 输入超时", 408) from None
        finally:
            if record.get("mfa_future") is future:
                record.pop("mfa_future", None)

    async def submit_mfa(self, run_id, code):
        record = self._active
        future = record.get("mfa_future") if record else None
        if (
            record is None
            or record["run_id"] != run_id
            or record["state"] not in {"running", "cancelling"}
            or future is None
            or future.done()
        ):
            raise SettingsError("vpn_mfa_required", "当前没有等待中的 MFA", 409)
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            raise SettingsError("validation_error", "MFA 验证码格式无效", 422)
        register_secret(code)
        future.set_result(code)
        return {"accepted": True}

    @staticmethod
    def _public(record):
        return VpnRunView.model_validate(
            {
                key: record[key]
                for key in (
                    "run_id",
                    "request_id",
                    "state",
                    "rung",
                    "created_at",
                    "updated_at",
                    "ip",
                    "error_code",
                    "events",
                )
            }
        )

    def _emit(self, record, event=None, error_code=None, ip=None):
        record["run_seq"] += 1
        item = {
            "run_id": record["run_id"],
            "run_seq": record["run_seq"],
            "state": record["state"],
            "rung": record["rung"],
            "event": event,
            "error_code": error_code,
            "ip": ip,
        }
        record["events"].append(item)
        record["events"] = record["events"][-256:]
        record["updated_at"] = now()
        if hasattr(self.hub, "publish_vpn"):
            self.hub.publish_vpn("vpn.run", item)
            self._publish_status(bool(record["ip"]), record["ip"], run=self._public(record))
        self.log.write(
            f"run={record['run_id']} state={record['state']} rung={record['rung']} "
            f"event={event} error={error_code}"
        )

    async def start(self, *, request_id=None, relogin=False, allow_login=True, max_rung=None):
        key = str(request_id) if request_id else None
        async with self._gate:
            if key and key in self._requests:
                return self.get_run(self._requests[key])
            if self._active and self._active["state"] in {"queued", "running", "cancelling"}:
                raise SettingsError("vpn_busy", "VPN 运行正在进行", 409)
            config = await self.store.read()
            rid = str(uuid4())
            record = {
                "run_id": rid,
                "request_id": key,
                "state": "queued",
                "rung": 0,
                "created_at": now(),
                "updated_at": now(),
                "ip": None,
                "error_code": None,
                "events": [],
                "run_seq": 0,
                "cancel": asyncio.Event(),
                "relogin": relogin,
                "allow_login": allow_login,
                "max_rung": max_rung,
                "config": config.vpn,
            }
            self.runs.append(record)
            self.runs[:] = self.runs[-20:]
            self._active = record
            if key:
                self._requests[key] = rid
                while len(self._requests) > 1024:
                    self._requests.pop(next(iter(self._requests)))
            self._task = asyncio.create_task(self._run(record), name=f"vpn:{rid}")
            return self._public(record)

    async def _probe(self, config):
        return await self.network_reader(
            cwd=self.store.data_dir,
            path_extras=self.path_extras,
            tunnel_prefix=config.tunnel_prefix,
        )

    async def _wait_connected(self, record, deadline):
        while time.monotonic() < deadline:
            if record["cancel"].is_set():
                raise asyncio.CancelledError
            net = await self._probe(record["config"])
            if net.vpn_ip:
                return net.vpn_ip
            await asyncio.sleep(min(1.5, max(0, deadline - time.monotonic())))
        return None

    async def _stage(self, record, rung, name):
        record["rung"] = rung
        self._emit(record, name)

    async def _network_monitor(self, record):
        while record["state"] in {"queued", "running", "cancelling"}:
            if record["cancel"].is_set():
                return
            with contextlib.suppress(Exception):
                net = await self._probe(record["config"])
                if net.vpn_ip != record["ip"]:
                    record["ip"] = net.vpn_ip
                    self._publish_status(bool(net.vpn_ip), net.vpn_ip, run=self._public(record))
            try:
                await asyncio.wait_for(record["cancel"].wait(), timeout=1.5)
            except TimeoutError:
                pass

    async def _run(self, record):
        config = record["config"]
        deadline = time.monotonic() + config.max_run_s
        timeout_scope = asyncio.timeout(config.max_run_s)
        monitor = asyncio.create_task(
            self._network_monitor(record), name=f"vpn-net:{record['run_id']}"
        )
        record["state"] = "running"
        self._emit(record, "started")
        try:
            async with timeout_scope:
                net = await self._probe(config)
                if net.vpn_ip and not record["relogin"]:
                    record["ip"] = net.vpn_ip
                else:
                    max_rung = record["max_rung"] if record["max_rung"] is not None else 3
                    bundle = config.client.bundle_id
                    app = self.client.resolve(bundle)
                    if not app:
                        raise SettingsError("vpn_client_missing", "VPN 客户端未安装", 409)
                    if max_rung >= 1:
                        await self._stage(record, 1, "rungA_open")
                        await self.client.open(bundle)
                        ip = await self._wait_connected(
                            record, min(deadline, time.monotonic() + config.rung_timeout_s)
                        )
                        if ip:
                            record["ip"] = ip
                    if not record["ip"] and max_rung >= 2:
                        await self._stage(record, 2, "rungB_restart")
                        await self.client.restart(bundle, allow_term=True)
                        await self.client.open(bundle)
                        ip = await self._wait_connected(
                            record, min(deadline, time.monotonic() + config.rung_timeout_s)
                        )
                        if ip:
                            record["ip"] = ip
                    mode = config.window_automation
                    if not record["ip"] and mode == "off":
                        self._emit(
                            record, "window_connect", error_code="skipped:window_automation_off"
                        )
                    elif not record["ip"] and mode != "off" and max_rung >= 2:
                        perms = await self.window_automation.permissions()
                        if any(
                            value is not True and value != "granted" for value in perms.values()
                        ):
                            raise SettingsError(
                                "window_permission_missing", "窗口自动化所需权限未就绪", 409
                            )
                        outcome = await self.window_automation.connect(mode)
                        self._emit(
                            record, "window_update" if outcome == "update" else "window_connect"
                        )
                        if outcome == "update":
                            deadline = max(deadline, time.monotonic() + config.max_run_s)
                            timeout_scope.reschedule(
                                asyncio.get_running_loop().time() + config.max_run_s
                            )
                    if not record["ip"] and record["allow_login"] and max_rung >= 3:
                        await self._stage(record, 3, "rungC_login")
                        password = self._credential("vpn_password")
                        seed = self._credential("vpn_totp_secret")
                        if not password:
                            raise SettingsError(
                                "vpn_not_configured", "请先在桌面端配置 VPN 凭据", 409
                            )
                        await self.login_runner.run(
                            config,
                            password,
                            seed,
                            record["cancel"],
                            lambda: self.request_mfa(record),
                        )
                        record["ip"] = await self._wait_connected(record, deadline)
                    if not record["ip"]:
                        if time.monotonic() >= deadline:
                            raise SettingsError("max_run_exceeded", "VPN 运行超出时间预算", 408)
                        raise SettingsError("vpn_not_connected", "VPN 尚未连接", 409)
            record["state"] = "succeeded"
            self._emit(record, "done", ip=record["ip"])
        except asyncio.CancelledError:
            record["state"] = "cancelled"
            self._emit(record, "cancelled")
        except TimeoutError:
            record["state"], record["error_code"] = "failed", "max_run_exceeded"
            self._emit(record, "failed", error_code="max_run_exceeded")
        except SettingsError as exc:
            record["state"], record["error_code"] = "failed", exc.code
            self._emit(record, "failed", error_code=exc.code)
        except Exception:
            record["state"], record["error_code"] = "failed", "vpn_failed"
            self._emit(record, "failed", error_code="vpn_failed")
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
            if self.on_complete is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self.on_complete(self._public(record)), timeout=1.0)
            if self._active is record:
                self._active = None
            if self._task is asyncio.current_task():
                self._task = None

    async def cancel(self, run_id):
        record = next((r for r in self.runs if r["run_id"] == run_id), None)
        if record is None:
            raise SettingsError("not_found", "VPN 运行不存在", 404)
        if record["state"] in {"queued", "running"}:
            record["cancel"].set()
            task = self._task
            if record["state"] == "queued":
                record["state"] = "cancelled"
                self._emit(record, "cancelled")
                if self._active is record:
                    self._active = None
                self._task = None
            else:
                record["state"] = "cancelling"
                self._emit(record, "cancelling")
            if task and task is not asyncio.current_task():
                task.cancel()
        return self._public(record)

    def get_run(self, run_id):
        record = next((r for r in self.runs if r["run_id"] == run_id), None)
        if record is None:
            raise SettingsError("not_found", "VPN 运行不存在", 404)
        return self._public(record)

    def list_runs(self):
        return [self._public(row) for row in reversed(self.runs)]

    async def close(self):
        self._closing = True
        task = self._task
        if task and not task.done():
            if self._active:
                self._active["cancel"].set()
                if self._active["state"] == "queued":
                    self._active["state"] = "cancelled"
                    self._emit(self._active, "cancelled")
                    self._active = None
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, 4.5)
        self._task = None
