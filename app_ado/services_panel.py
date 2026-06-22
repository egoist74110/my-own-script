"""本机服务面板：VPN 地址 / code-server / cloudflared 临时隧道。

设计要点（解决"关了 bot 后服务还在、重启后找不回/关不掉"的问题）：
- 进程用 detached 方式启动（start_new_session），脱离 bot 独立常驻；
- PID、启动时间、cloudflared 域名落盘到 ~/.config/my-own-script/services/<name>.json，
  bot 重启后能读回；
- 查状态不只信状态文件，还主动扫端口（code-server）/进程签名（cloudflared），
  所以即使状态文件丢了、或服务是手动起的，也能发现并显示；
- 关闭按"状态文件 PID（杀进程组）+ 端口/签名扫描"双兜底，bot 重启后照样能关；
- cloudflared 只认 quick tunnel 签名 `cloudflared tunnel --url`，绝不误伤 root 的
  `tunnel run --token` 常驻命名隧道。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

from app_ado.store import config_dir
from app_ado.vpn_ip import get_vpn_ip

CODESERVER_CONFIG = Path.home() / ".config" / "code-server" / "config.yaml"

# cloudflared quick tunnel 的命令签名；命名隧道 `tunnel run --token` 不会匹配到。
_QUICK_PATTERN = "cloudflared tunnel --url"
_DOMAIN_RE = re.compile(r"https://[a-z0-9][a-z0-9.-]*\.trycloudflare\.com")


# ---------- 通用工具 ----------

def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _bin(name: str) -> str:
    return shutil.which(name) or f"/opt/homebrew/bin/{name}"


def _state_dir() -> Path:
    d = config_dir() / "services"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(name: str) -> Path:
    return _state_dir() / f"{name}.json"


def _log_path(name: str) -> Path:
    return _state_dir() / f"{name}.log"


def _read_state(name: str) -> dict:
    p = _state_path(name)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {}


def _write_state(name: str, data: dict) -> None:
    try:
        _state_path(name).write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def _clear_state(name: str) -> None:
    try:
        _state_path(name).unlink()
    except Exception:
        pass


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _spawn_detached(argv: list[str], log_path: Path, env: dict[str, str] | None = None) -> int:
    """启动子进程并脱离 bot 常驻，返回服务 PID。

    用 `nohup ... &` 经一次性 /bin/sh 拉起：sh 退出后服务被 launchd 接管，
    既不随 bot 退出而死，也不会变成 bot 的僵尸进程（macOS 无 setsid 命令）。
    env 里的键值作为额外环境变量内联到命令前（叠加在继承环境之上）。
    """
    prog = " ".join(shlex.quote(a) for a in argv)
    prefix = ""
    if env:
        prefix = "".join(f"{k}={shlex.quote(str(v))} " for k, v in env.items())
    cmd = f"{prefix}nohup {prog} >> {shlex.quote(str(log_path))} 2>&1 < /dev/null & echo $!"
    try:
        # start_new_session：拉起的 sh 自成会话，服务进入独立进程组，
        # 这样 killpg 只杀服务子树，绝不会误伤 bot 自身（同组）。
        r = subprocess.run(
            ["/bin/sh", "-c", cmd],
            capture_output=True, text=True, timeout=10,
            start_new_session=True,
        )
        return int((r.stdout.strip().split() or ["0"])[-1])
    except Exception:
        return 0


def _signal(pid: int, sig: int, *, group: bool) -> bool:
    try:
        if group:
            os.killpg(os.getpgid(int(pid)), sig)
        else:
            os.kill(int(pid), sig)
        return True
    except Exception:
        return False


def _kill_pid(pid: int, *, group: bool) -> bool:
    """SIGTERM，等不掉再升级 SIGKILL，确保进程真的退出。返回是否动过手。

    group=True 用于本面板 start_new_session 起的进程（pid 即组长，独立进程组）；
    group=False 用于扫描发现的外部进程，只点名杀该 pid，避免误伤同组的终端等。
    """
    if not _pid_alive(pid):
        return False
    acted = _signal(pid, signal.SIGTERM, group=group)
    for _ in range(20):  # 最多等 ~4s 优雅退出（cloudflared 关闭要 1-2s）
        if not _pid_alive(pid):
            return acted
        time.sleep(0.2)
    _signal(pid, signal.SIGKILL, group=group)
    return acted


def _pids_on_port(port: int) -> list[int]:
    try:
        r = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5,
        )
        return [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    except Exception:
        return []


def _pids_by_pattern(pattern: str) -> list[int]:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5)
        return [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    except Exception:
        return []


def _lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


# ---------- code-server 配置 ----------

def _codeserver_conf() -> dict:
    out: dict = {}
    try:
        for line in CODESERVER_CONFIG.read_text("utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    except Exception:
        pass
    return out


def _codeserver_port() -> int:
    ba = _codeserver_conf().get("bind-addr", "0.0.0.0:8080")
    try:
        return int(ba.rsplit(":", 1)[1])
    except Exception:
        return 8080


def _codeserver_password() -> str | None:
    return _codeserver_conf().get("password") or None


# ---------- VPN ----------

def vpn_ip() -> str | None:
    return get_vpn_ip()


def codeserver_password() -> str | None:
    return _codeserver_password()


def cloudflared_domain() -> str | None:
    return _read_state("cloudflared").get("domain") or _scan_domain_from_log()


# ---------- code-server ----------

def codeserver_running() -> bool:
    return len(_pids_on_port(_codeserver_port())) > 0


def codeserver_start() -> tuple[bool, str]:
    if codeserver_running():
        return True, "✅ code-server 已在运行"
    try:
        pid = _spawn_detached([_bin("code-server")], _log_path("code-server"))
    except Exception as e:
        return False, f"❌ 启动失败：{e}"
    _write_state("code-server", {"pid": pid, "started_at": _now()})
    for _ in range(20):  # 等端口就绪，最多 ~10s
        if codeserver_running():
            return True, "✅ code-server 已启动"
        time.sleep(0.5)
    return True, "⏳ code-server 启动中（端口尚未就绪，可稍后刷新）"


def codeserver_stop() -> tuple[bool, str]:
    killed = False
    pid = _read_state("code-server").get("pid")
    if pid and _kill_pid(pid, group=True):
        killed = True
    for p in _pids_on_port(_codeserver_port()):
        if p != pid and _kill_pid(p, group=False):
            killed = True
    _clear_state("code-server")
    time.sleep(0.5)
    if codeserver_running():
        return False, "⚠️ 端口仍被占用，可能未完全关闭"
    return (True, "✅ code-server 已关闭") if killed else (True, "ℹ️ code-server 本来就没在运行")


def codeserver_status() -> str:
    port = _codeserver_port()
    pw = _codeserver_password() or "(未设置)"
    if not codeserver_running():
        return f"💻 code-server：🔴 未运行\n端口：{port}\n密码：{pw}"
    lines = ["💻 code-server：🟢 运行中", f"端口：{port}", f"密码：{pw}"]
    vip = get_vpn_ip()
    if vip:
        lines.append(f"PC(VPN)：http://{vip}:{port}")
    lip = _lan_ip()
    if lip and lip != vip:
        lines.append(f"局域网：http://{lip}:{port}")
    dom = _read_state("cloudflared").get("domain")
    if dom:
        lines.append(f"手机(隧道)：{dom}")
    return "\n".join(lines)


# ---------- cloudflared 临时隧道 ----------

def cloudflared_running() -> bool:
    return len(_pids_by_pattern(_QUICK_PATTERN)) > 0


def _scan_domain_from_log() -> str | None:
    try:
        txt = _log_path("cloudflared").read_text("utf-8", errors="ignore")
    except Exception:
        return None
    m = None
    for m in _DOMAIN_RE.finditer(txt):
        pass  # 取最后一次出现的域名
    return m.group(0) if m else None


def cloudflared_start() -> tuple[bool, str]:
    if cloudflared_running():
        dom = _read_state("cloudflared").get("domain") or _scan_domain_from_log()
        return True, "✅ cloudflared 已在运行" + (f"\n公网域名：{dom}" if dom else "")
    port = _codeserver_port()
    try:
        _log_path("cloudflared").write_text("", "utf-8")  # 清旧日志，确保抓到本次域名
    except Exception:
        pass
    try:
        pid = _spawn_detached(
            [_bin("cloudflared"), "tunnel", "--url", f"http://127.0.0.1:{port}"],
            _log_path("cloudflared"),
        )
    except Exception as e:
        return False, f"❌ 启动失败：{e}"
    _write_state("cloudflared", {"pid": pid, "started_at": _now(), "domain": None})
    dom = None
    for _ in range(30):  # 等域名出现，最多 ~15s
        dom = _scan_domain_from_log()
        if dom:
            break
        time.sleep(0.5)
    if dom:
        st = _read_state("cloudflared")
        st["domain"] = dom
        _write_state("cloudflared", st)
        return True, f"✅ cloudflared 已启动\n公网域名：{dom}"
    return True, "⏳ cloudflared 已启动，但暂未捕获到域名（可稍后刷新）"


def cloudflared_stop() -> tuple[bool, str]:
    killed = False
    pid = _read_state("cloudflared").get("pid")
    if pid and _kill_pid(pid, group=True):
        killed = True
    for p in _pids_by_pattern(_QUICK_PATTERN):
        if p != pid and _kill_pid(p, group=False):
            killed = True
    _clear_state("cloudflared")
    return (True, "✅ cloudflared 已关闭") if killed else (True, "ℹ️ cloudflared 本来就没在运行")


def cloudflared_status() -> str:
    if not cloudflared_running():
        return "☁️ cloudflared：🔴 未运行"
    st = _read_state("cloudflared")
    dom = st.get("domain") or _scan_domain_from_log()
    lines = ["☁️ cloudflared：🟢 运行中"]
    if dom:
        lines.append(f"公网域名：{dom}")
        pw = _codeserver_password()
        if pw:
            lines.append(f"（手机用 code-server 密码登录：{pw}）")
    elif st.get("pid"):
        lines.append("（本面板启动，域名暂未就绪，稍等几秒刷新）")
    else:
        lines.append("（该隧道不是本面板启动的，拿不到域名；点关闭再启动即可获取）")
    return "\n".join(lines)
