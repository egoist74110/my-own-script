"""OS authorization and read-only verification of the fixed bypass installation."""

import base64
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.vpn_bypass import BypassStatus, BypassTargetStatus
from toolbox_backend.vpn import bypass_daemon as runtime
from toolbox_backend.vpn import bypass_installer as installer

MAX_AUTH_SCRIPT = 180_000
PYTHON = "/usr/bin/python3"


def authorization_script(action, config, python_path=PYTHON):
    if action not in {"activate", "deactivate"}:
        raise ValueError("invalid managed action")
    config = runtime.validate_config(config)
    source = Path(installer.__file__).read_text()
    helper = Path(runtime.__file__).read_text()
    # The only interpolation into executable code is JSON/base64 literal data.
    payload = source + "\nPYTHON = " + repr(python_path)
    payload += "\nexecute(" + repr(action) + ", " + repr(helper) + ", "
    payload += "json.loads(" + repr(json.dumps(config)) + "))\n"
    encoded = base64.b64encode(payload.encode()).decode("ascii")
    code = "import base64; exec(compile(base64.b64decode(" + repr(encoded)
    code += "), '<toolbox-reviewed-installer>', 'exec'))"
    shell = shlex.join([python_path, "-I", "-S", "-c", code])
    script = 'do shell script "' + shell.replace("\\", "\\\\").replace('"', '\\"')
    script += '" with administrator privileges'
    if len(script.encode()) > MAX_AUTH_SCRIPT:
        raise SettingsError("bypass_payload_too_large", "配置过大，无法安全传递管理员操作", 422)
    return "with timeout of 300 seconds\n" + script + "\nend timeout\n"


def verify_runtime_tree(executable):
    """App-side checks before trusting the selected interpreter's own probe."""
    if executable.parent.name != "bin":
        raise RuntimeError("unrecognized system runtime layout")
    prefix = executable.parent.parent
    pending, visited = [prefix], set()
    while pending:
        directory = pending.pop()
        if directory in visited:
            continue
        visited.add(directory)
        installer.protected(directory, directory=True)
        for path in directory.iterdir():
            if path.is_symlink():
                # CLT includes a root-owned include/python3.9 -> ../Headers
                # alias. Verify its canonical tree too, not just the link itself.
                if path.lstat().st_uid != 0:
                    raise RuntimeError("unprotected runtime link")
                path = path.resolve(strict=True)
                if not path.is_relative_to(prefix):
                    raise RuntimeError("runtime alias leaves its protected framework")
            if path.is_dir():
                pending.append(path)
            else:
                installer.protected(path)


def preflight():
    if sys.platform != "darwin":
        raise SettingsError("bypass_unsupported", "托管分流只支持 macOS", 422)
    # Prefer the existing CLT framework outside /Applications. The system shim
    # may select Xcode under group-writable /Applications, which must be rejected.
    # No runtime is downloaded and no host permissions are changed.
    versions = Path(
        "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions"
    )
    candidates = []
    for path in sorted(versions.glob("[0-9]*/bin/python3*")):
        if re.fullmatch(r"python3(?:\.\d+)?", path.name):
            candidates.append(path)
    candidates.append(Path(PYTHON))
    source = Path(installer.__file__).read_text()
    checked = set()
    for candidate in candidates:
        try:
            if candidate == Path(PYTHON):
                installer.protected(PYTHON)
                installer.protected("/usr/bin/xcrun")
                selected = subprocess.run(
                    ["/usr/bin/xcrun", "--find", "python3"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    env=installer.ENV,
                )
                if selected.returncode:
                    raise RuntimeError("system Python unavailable")
                candidate = Path(runtime.safe_path(selected.stdout.strip()))
            installer.protected(candidate.parent, directory=True)
            if candidate.is_symlink() and candidate.lstat().st_uid != 0:
                raise RuntimeError("unprotected runtime link")
            candidate = candidate.resolve(strict=True)
            if candidate in checked:
                continue
            checked.add(candidate)
            installer.protected(candidate)
            verify_runtime_tree(candidate)
            probe = source + "\nPYTHON = " + repr(str(candidate))
            probe += "\nruntime_preflight()\nprint(str(Path(sys.executable).resolve()))\n"
            result = subprocess.run(
                [str(candidate), "-I", "-S", "-c", probe],
                capture_output=True,
                text=True,
                timeout=30,
                env=installer.ENV,
            )
            if result.returncode != 0:
                continue
            executable = Path(runtime.safe_path(result.stdout.strip()))
            installer.protected(executable)
            if executable != candidate:
                raise RuntimeError("system runtime identity changed")
            # Pin the canonical runtime, not xcode-select's mutable launcher.
            return str(executable)
        except OSError, ValueError, RuntimeError, subprocess.SubprocessError:
            continue
    raise SettingsError(
        "bypass_runtime_untrusted",
        "未找到可用且受 root 保护的系统 Python 3.9 以上运行时（含标准库、动态库）。"
        "未安装运行时，也未放宽目录权限。",
        422,
    )


class ManagedBypass:
    def installed(self):
        if sys.platform != "darwin":
            return False
        # Even an incomplete protected installation requires an explicit repair.
        try:
            runtime.protected(runtime.ROOT, directory=True)
            return True
        except FileNotFoundError:
            return False
        except OSError, RuntimeError:
            # Report an existing unsafe installation as error, never as healthy.
            return runtime.ROOT.exists() or runtime.ROOT.is_symlink()

    def apply(self, action, config):
        python_path = preflight()
        script = authorization_script(action, config, python_path)
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-"],
                input=script,
                capture_output=True,
                text=True,
                timeout=330,
                env=installer.ENV,
            )
        except OSError, subprocess.SubprocessError:
            raise SettingsError(
                "bypass_authorization_failed", "管理员操作失败或超时；请查看当前真实状态后重试", 503
            ) from None
        if result.returncode:
            if "-128" in result.stderr:
                raise SettingsError(
                    "bypass_authorization_cancelled", "已取消管理员授权；未确认应用成功"
                )
            raise SettingsError(
                "bypass_authorization_failed",
                "管理员授权或助手操作失败；请查看当前真实状态后重试",
                503,
            )

    def read_public_status(self):
        for path in (runtime.ROOT / "helper.py", runtime.ROOT / "config.json", installer.PLIST):
            runtime.protected(path)
        value = runtime.read_json(runtime.ROOT / "status.json")
        if not isinstance(value, dict) or len(value.get("targets", [])) > runtime.MAX_ROUTES:
            raise ValueError("invalid public status")
        return value

    def job_pid(self):
        result = subprocess.run(
            ["/bin/launchctl", "print", installer.JOB],
            capture_output=True,
            text=True,
            timeout=8,
            env=installer.ENV,
        )
        if result.returncode:
            return None
        match = re.search(r"^\s*pid = ([1-9][0-9]*)\s*$", result.stdout, re.M)
        if not match:
            return None
        pid = int(match[1])
        try:
            os.kill(pid, 0)
        except PermissionError:
            pass  # root process exists; launchctl supplied its identity
        except ProcessLookupError:
            return None
        return pid

    def status(self, config):
        status = BypassStatus(installed=self.installed())
        if not status.installed:
            return status
        try:
            value = self.read_public_status()
            job_pid = self.job_pid()
            status.running = job_pid is not None
            heartbeat = value["last_sweep_at"]
            if type(heartbeat) not in (int, float) or not 0 < heartbeat < 1e12:
                raise ValueError("invalid heartbeat")
            status.last_sweep_at = heartbeat
            fresh = 0 <= time.time() - heartbeat <= max(30, config["interval_s"] * 3)
            status.synced = value["config_hash"] == runtime.config_hash(config)
            # A stopped service with saved enabled=True is never reported synced.
            if config["enabled"] and not status.running:
                status.synced = False
            errors = value["errors"]
            if not isinstance(errors, list) or not all(isinstance(e, str) for e in errors):
                raise ValueError("invalid errors")
            status.errors = errors[:32]
            routes = runtime.route_table()
            rows = {row["target"]: row for row in value["targets"]}
            for net in config["targets"] if config["enabled"] else []:
                rows.setdefault(net, {"target": net, "owned": False})
            for net, reported in sorted(rows.items()):
                if runtime.target(net) != net:
                    raise ValueError("invalid reported target")
                actual = routes.get(net)
                owned = reported["owned"] is True
                expected = {"gateway": config["gateway"], "interface": config["interface"]}
                # For disabled snapshots use the journal tuple solely to verify
                # residual ownership, never to operate on a route.
                if not config["enabled"]:
                    expected = reported
                verified = owned and runtime.matches(actual, expected) and "U" in actual["flags"]
                status.targets.append(
                    BypassTargetStatus(
                        **{
                            "target": net,
                            "gateway": actual["gateway"] if actual else None,
                            "interface": actual["interface"] if actual else None,
                            "owned": owned,
                            "verified": verified,
                        }
                    )
                )
            if status.errors:
                status.state, status.message = "error", "后台修复失败；正在等待下一周期重试。"
            elif any("conflict" in event[1] for event in value.get("events", [])):
                status.state, status.message = (
                    "degraded",
                    "存在其他路由或归属待确认，未覆盖这些路由。",
                )
            elif not status.running:
                status.state, status.message = (
                    "stopped",
                    "后台助手已停止；可显式启用以应用已保存配置。",
                )
            elif not fresh or value.get("pid") != job_pid:
                status.state, status.message = (
                    "pending",
                    "后台心跳已过期或进程未完成首次修复，尚未确认生效。",
                )
            elif not status.synced:
                status.state, status.message = "pending", "配置已保存，但后台快照尚未同步。"
            elif not config["enabled"] or value.get("enabled") is not True:
                status.synced = False
                status.state, status.message = "pending", "后台启停状态与配置不同，尚未确认生效。"
            elif not status.targets:
                status.state, status.message = (
                    "degraded",
                    "尚未发现任何目标地址，不能确认分流已生效。",
                )
            elif not all(row.verified and row.owned for row in status.targets):
                status.state, status.message = (
                    "degraded",
                    "部分目标的实际路由未通过归属及网关校验。",
                )
            else:
                status.state, status.message = "active", "后台正在运行，当前目标的实际路由已验证。"
        except OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError:
            status.synced = False
            status.state = "error"
            status.message = "无法验证后台状态或实际路由；请重新应用以修复助手。"
            status.errors = [status.message]
        return status
