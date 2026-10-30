"""Saved preferences, read-only preview and explicitly authorized managed actions."""

import asyncio
import json
import plistlib
import shlex
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from toolbox_backend.adapters.vpn_bypass_privileged import ManagedBypass
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.vpn_bypass import BypassSweepResult
from toolbox_backend.vpn import bypass_daemon as runtime

RUNTIME_REQUIREMENT = (
    "需要 Python 3.9 及以上版本（助手仅使用标准库）。解释器、标准库、动态库及其所有父目录"
    "必须归 root 所有，且用户组和其他用户均不可写。请填写真实解释器文件路径，不使用符号链接。"
    "普通用户可写的 Homebrew、uv 或用户目录解释器不能用于此 root 常驻服务。"
    "运行时使用 -I -S 隔离参数；托管模式自动预检已有系统运行时并固定可信真实路径，"
    "缺失或不可信时停止。"
)


def export_bundle(config, python_path):
    try:
        runtime.safe_path(python_path)
    except ValueError:
        raise SettingsError("validation_error", "需要可信 Python 解释器的绝对路径", 422) from None
    root = str(runtime.ROOT)
    label = "com.toolbox.vpn-bypass"
    plist = {
        "Label": label,
        "ProgramArguments": [python_path, "-I", "-S", root + "/helper.py", "loop"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "Umask": 0o077,
        "WorkingDirectory": root,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }
    return {
        "config_json": json.dumps(config, indent=2, sort_keys=True) + "\n",
        "helper_source": Path(runtime.__file__).read_text(),
        "launchd_plist": plistlib.dumps(plist, sort_keys=True).decode(),
        "runtime_requirement": RUNTIME_REQUIREMENT,
        "instructions": [
            "这里只生成导出文件，尚未安装或应用规则；也可使用界面的管理员授权启用。",
            RUNTIME_REQUIREMENT,
            "将导出内容分别保存为 config.json、helper.py 和 com.toolbox.vpn-bypass.plist，"
            "放在仅自己可写的临时准备目录。提权前检查脚本与配置，下面命令中的 "
            "/ABSOLUTE/REVIEWED 必须替换为你已检查文件的实际绝对目录。",
            "确认 /Library、/Library/Application Support 和已有目标路径归 root 所有、不是符号链接，"
            "且用户组与其他用户均不可写；不满足时不要安装。",
            "sudo /usr/bin/install -d -o root -g wheel -m 755 " + shlex.quote(root),
            "sudo /usr/bin/install -o root -g wheel -m 600 /ABSOLUTE/REVIEWED/config.json "
            + shlex.quote(root + "/config.json"),
            "sudo /usr/bin/install -o root -g wheel -m 600 /ABSOLUTE/REVIEWED/helper.py "
            + shlex.quote(root + "/helper.py"),
            "sudo /usr/bin/install -o root -g wheel -m 644 "
            "/ABSOLUTE/REVIEWED/com.toolbox.vpn-bypass.plist "
            "/Library/LaunchDaemons/com.toolbox.vpn-bypass.plist",
            "单次修复（输出验证结果与冲突）：sudo "
            + shlex.quote(python_path)
            + " -I -S "
            + shlex.quote(root + "/helper.py")
            + " sweep",
            "启动周期修复：sudo /bin/launchctl bootstrap system "
            "/Library/LaunchDaemons/com.toolbox.vpn-bypass.plist",
            "更新规则时：先停止常驻服务，再重新导出、检查并安装配置快照和助手，然后重新启动。"
            "界面保存会同步已存在的托管安装；未安装时仍需显式启用。",
            "撤销前先停止服务：sudo /bin/launchctl bootout system/com.toolbox.vpn-bypass",
            "仅撤销确认属于本助手的路由：sudo "
            + shlex.quote(python_path)
            + " -I -S "
            + shlex.quote(root + "/helper.py")
            + " undo",
            "撤销成功且已核查全部冲突或待确认条目之前，不要删除 root 状态账本。"
            "归属不明的路由不会被自动删除。",
            "常驻服务不写持续增长的日志；诊断时运行单次修复。"
            "查看系统服务状态：launchctl print system/com.toolbox.vpn-bypass。",
        ],
    }


class VpnBypassService:
    def __init__(self, store, managed=None):
        self.store = store
        self.managed = managed if managed is not None else ManagedBypass()
        self._action_lock = asyncio.Lock()
        self._sync_error = None

    @asynccontextmanager
    async def action(self):
        if self._action_lock.locked():
            raise SettingsError("bypass_busy", "分流操作正在进行，请等待管理员操作完成后重试")
        await self._action_lock.acquire()
        try:
            yield
        finally:
            self._action_lock.release()

    async def _thread(self, operation, *args):
        # OS authorization/root work cannot be cancelled with an HTTP request.
        # Retain the action lock until the worker has actually finished.
        task = asyncio.create_task(asyncio.to_thread(operation, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def snapshot(self):
        config = await self.store.read()
        status = await self._thread(self.managed.status, config.vpn_bypass.model_dump())
        if status.state == "active":
            # A previously failed sweep may recover in the persistent daemon.
            # Do not mask fresh, independently verified health with an old UI error.
            self._sync_error = None
        elif self._sync_error:
            status.errors.append(self._sync_error)
        return {"revision": config.revision, "settings": config.vpn_bypass, "status": status}

    async def update(self, body):
        async with self.action():
            config = await self.store.update(
                body.revision, lambda config: setattr(config, "vpn_bypass", body.settings)
            )
            if await self._thread(self.managed.installed):
                try:
                    await self._thread(
                        self.managed.apply,
                        "activate" if config.vpn_bypass.enabled else "deactivate",
                        config.vpn_bypass.model_dump(),
                    )
                    observed = await self._thread(
                        self.managed.status, config.vpn_bypass.model_dump()
                    )
                    if observed.state == "error":
                        raise SettingsError("bypass_apply_failed", "后台快照或路由修复未通过检查")
                except (SettingsError, OSError, RuntimeError) as exc:
                    self._sync_error = (
                        "配置已保存，但助手更新或路由检查失败；请查看实际状态后重试。"
                    )
                    raise SettingsError(
                        "bypass_sync_failed",
                        self._sync_error,
                        409,
                        revision=config.revision,
                        cause=exc.code
                        if isinstance(exc, SettingsError)
                        else "bypass_operation_failed",
                    ) from None
            self._sync_error = None
            return config

    async def _check_revision(self, revision):
        config = await self.store.read()
        if config.revision != revision:
            raise SettingsError(
                "revision_conflict", "配置已被其他写者更新", revision=config.revision
            )
        return config

    async def activate(self, revision):
        async with self.action():
            config = await self._check_revision(revision)
            if not config.vpn_bypass.enabled:
                raise SettingsError("validation_error", "请先启用并保存分流配置", 422)
            await self._thread(self.managed.apply, "activate", config.vpn_bypass.model_dump())
            self._sync_error = None
            return await self.snapshot()

    async def deactivate(self, revision):
        async with self.action():
            config = await self._check_revision(revision)
            if await self._thread(self.managed.installed):
                await self._thread(self.managed.apply, "deactivate", config.vpn_bypass.model_dump())
            self._sync_error = None
            return await self.snapshot()

    async def sweep(self, apply=False):
        config = (await self.store.read()).vpn_bypass.model_dump()
        errors = []
        targets = []
        if not config["enabled"]:
            errors.append("已保存的配置尚未启用；已安装助手使用独立快照，其状态可能不同。")
        elif not config["gateway"] or not config["interface"]:
            errors.append("已保存的配置缺少物理网关或网卡；请补全后保存，再预览。")
        elif not config["targets"] and not any(app["enabled"] for app in config["apps"]):
            errors.append("尚未配置分流目标；请添加并启用应用规则，或填写目标地址后保存。")
        elif sys.platform != "darwin":
            errors.append("只读目标发现仅支持 macOS。")
        else:
            try:

                def inspect():
                    routes = runtime.route_table()
                    runtime.physical_gateway(config, routes)
                    discovered = runtime.discover(config, runtime.command, routes)
                    return sorted(set(config["targets"]) | set(discovered))

                targets = await asyncio.to_thread(inspect)
            except OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError:
                errors.append("预览失败：请检查物理网关、网卡和应用的精确路径。")
        return BypassSweepResult(
            requires_privilege=apply,
            targets=targets,
            gateway=config["gateway"],
            interface=config["interface"],
            errors=errors,
            message=(
                "未修改路由；请运行已检查并安装的 root 助手来执行修复。"
                if apply
                else "这是已保存配置的只读预览，未修改路由，也不代表后台助手正在运行。"
            ),
        )

    async def export(self, python_path):
        config = (await self.store.read()).vpn_bypass.model_dump()
        return export_bundle(config, python_path)
