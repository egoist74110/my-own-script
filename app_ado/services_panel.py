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
import secrets as _py_secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
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


def _spawn_detached(argv: list[str], log_path: Path, env: dict[str, str] | None = None,
                    cwd: str | None = None) -> int:
    """启动子进程并脱离 bot 常驻，返回服务 PID。

    用 `nohup ... &` 经一次性 /bin/sh 拉起：sh 退出后服务被 launchd 接管，
    既不随 bot 退出而死，也不会变成 bot 的僵尸进程（macOS 无 setsid 命令）。
    env 里的键值作为额外环境变量内联到命令前（叠加在继承环境之上）；
    cwd 作为 sh 的工作目录（子进程继承，用于让 dsh 落到指定的会话桶）。
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
            cwd=cwd,
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


def _phys_ipv4s() -> list[str]:
    """物理网卡（`en*`，排除 VPN/utun 与 lo）上的私有 IPv4 列表。"""
    ips: list[str] = []
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return ips
    in_phys = False
    for line in out.splitlines():
        if line and not line[0].isspace():
            in_phys = line.split(":", 1)[0].startswith("en")
            continue
        if in_phys:
            m = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)", line)
            if m and _is_private_ipv4(m.group(1)):
                ips.append(m.group(1))
    return ips


def _lan_ip() -> str | None:
    """适合手机直连的内网 IP。

    优先物理网卡（en*）上的 192.168.x（家 Wi-Fi，手机通常同网段）；
    其次 10.x / 172.x；最后回退「到 8.8.8.8 的默认路由 IP」（可能是 VPN 地址）。
    """
    for pref in ("192.168.", "10.", "172."):
        for ip in _phys_ipv4s():
            if ip.startswith(pref):
                return ip
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _is_private_ipv4(ip: str) -> bool:
    """是否 RFC1918 私有地址（10/8、172.16/12、192.168/16）。"""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    return False


def is_on_lan() -> bool:
    """当前是否连在局域网：任一**物理网卡**（`en*`，排除 utun/VPN 与 lo）带私有 IPv4。

    只看物理网卡而非默认路由 IP，避免 VPN（utun 的 10.254.x）被误判成局域网。
    用于 dsh「隧道开关」按钮的动态判断：局域网→开隧道，非局域网→关隧道。
    """
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False
    in_phys = False
    for line in out.splitlines():
        if line and not line[0].isspace():
            name = line.split(":", 1)[0]
            in_phys = name.startswith("en")
            continue
        if in_phys:
            m = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)", line)
            if m and _is_private_ipv4(m.group(1)):
                return True
    return False


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

def _global_cf_url() -> str:
    """全局隧道固定指向 code-server 端口。"""
    return f"http://127.0.0.1:{_codeserver_port()}"


def _global_cf_pattern() -> str:
    """全局隧道的命令签名（带具体 URL）——只认这一条，绝不误伤「指定启动」的自定义隧道。"""
    return f"{_QUICK_PATTERN} {_global_cf_url()}"


def cloudflared_running() -> bool:
    return len(_pids_by_pattern(_global_cf_pattern())) > 0


def _scan_domain_in(path: Path) -> str | None:
    try:
        txt = path.read_text("utf-8", errors="ignore")
    except Exception:
        return None
    m = None
    for m in _DOMAIN_RE.finditer(txt):
        pass  # 取最后一次出现的域名
    return m.group(0) if m else None


def _scan_domain_from_log() -> str | None:
    return _scan_domain_in(_log_path("cloudflared"))


# cloudflared 隧道传输协议偏好（持久化，survive stop——不放 state 文件，state 关闭即清）。
#   http2 = 走 TCP，穿透性好、烂网更稳（默认推荐）
#   quic  = 走 UDP，更快但 UDP 被掐时会 "failed to run the datagram handler" 断流
CF_PROTOCOLS = ("http2", "quic")
DEFAULT_CF_PROTOCOL = "http2"
_CF_PROTO_LABELS = {
    "http2": "HTTP/2（TCP·穿透好·推荐）",
    "quic": "QUIC（UDP·更快·烂网易断）",
}


def _cf_pref_path() -> Path:
    return _state_dir() / "cloudflared_pref.json"


def cloudflared_protocol() -> str:
    """当前隧道协议偏好，缺省 http2。"""
    try:
        p = json.loads(_cf_pref_path().read_text("utf-8")).get("protocol")
        if p in CF_PROTOCOLS:
            return p
    except Exception:
        pass
    return DEFAULT_CF_PROTOCOL


def set_cloudflared_protocol(proto: str) -> tuple[bool, str]:
    """切换隧道协议。运行中则重启以生效（quick tunnel 域名会变）；未运行只落盘。"""
    if proto not in CF_PROTOCOLS:
        return False, f"❌ 未知协议：{proto}"
    try:
        _cf_pref_path().write_text(
            json.dumps({"protocol": proto}, ensure_ascii=False), "utf-8"
        )
    except Exception as e:
        return False, f"❌ 协议偏好写入失败：{e}"
    label = _CF_PROTO_LABELS.get(proto, proto)
    if not cloudflared_running():
        return True, f"✅ 隧道协议已设为 {label}\n（下次启动隧道时生效）"
    # 运行中：重启使新协议生效（quick tunnel 域名会变，需同步更新 DevSpace/ChatGPT 的 URL）
    cloudflared_stop()
    cloudflared_start()
    dom = _read_state("cloudflared").get("domain") or _scan_domain_from_log()
    tail = f"\n新公网域名：{dom}" if dom else "\n（域名稍后刷新）"
    return True, f"✅ 已切到 {label} 并重启隧道{tail}"


def cloudflared_start() -> tuple[bool, str]:
    if cloudflared_running():
        dom = _read_state("cloudflared").get("domain") or _scan_domain_from_log()
        return True, "✅ cloudflared 已在运行" + (f"\n公网域名：{dom}" if dom else "")
    port = _codeserver_port()
    try:
        _log_path("cloudflared").write_text("", "utf-8")  # 清旧日志，确保抓到本次域名
    except Exception:
        pass
    proto = cloudflared_protocol()
    try:
        pid = _spawn_detached(
            # --protocol 取偏好（默认 http2）：quic 走 UDP，烂网/UDP 被掐时会出现
            # "failed to run the datagram handler" 而断流；http2 走 TCP，穿透性更好更稳。
            # 注意：--url 必须紧跟在后，保住 _QUICK_PATTERN("cloudflared tunnel --url") 进程签名。
            [_bin("cloudflared"), "tunnel", "--url", f"http://127.0.0.1:{port}", "--protocol", proto],
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
    # 只按「全局隧道」的精确签名兜底，不碰「指定启动」的自定义隧道。
    for p in _pids_by_pattern(_global_cf_pattern()):
        if p != pid and _kill_pid(p, group=False):
            killed = True
    _clear_state("cloudflared")
    return (True, "✅ cloudflared 已关闭") if killed else (True, "ℹ️ cloudflared 本来就没在运行")


def cloudflared_status() -> str:
    proto_line = f"协议：{_CF_PROTO_LABELS.get(cloudflared_protocol(), cloudflared_protocol())}"
    if not cloudflared_running():
        return f"☁️ cloudflared：🔴 未运行\n{proto_line}" + _cf_custom_status_block()
    st = _read_state("cloudflared")
    dom = st.get("domain") or _scan_domain_from_log()
    lines = ["☁️ cloudflared：🟢 运行中", proto_line]
    if dom:
        lines.append(f"公网域名：{dom}")
        pw = _codeserver_password()
        if pw:
            lines.append(f"（手机用 code-server 密码登录：{pw}）")
    elif st.get("pid"):
        lines.append("（本面板启动，域名暂未就绪，稍等几秒刷新）")
    else:
        lines.append("（该隧道不是本面板启动的，拿不到域名；点关闭再启动即可获取）")
    return "\n".join(lines) + _cf_custom_status_block()


def _cf_custom_status_block() -> str:
    """指定隧道清单（附在 cloudflared_status 末尾，方便 TG 长按复制域名）。"""
    customs = cloudflared_custom_list()
    if not customs:
        return ""
    lines = ["", "🔗 指定隧道："]
    for c in customs:
        dom = c.get("domain") or "（域名待刷新）"
        lines.append(f"· {c['url']} → {dom}")
    return "\n".join(lines)


# ---------- cloudflared 「指定启动」自定义隧道 ----------
# 与全局隧道完全独立：各自的 state / 日志 / 进程，互不启停、互不误杀。
# 一个目标 URL 一条隧道（按 URL 去重）。

def _cf_slug(url: str) -> str:
    """URL → 文件名安全的短 slug（用于各自的日志文件名）。"""
    return re.sub(r"[^a-zA-Z0-9]+", "-", url).strip("-")[:60] or "tunnel"


def _cf_custom_log(slug: str) -> Path:
    return _state_dir() / f"cloudflared_custom_{slug}.log"


def _extract_cf_url(raw: str) -> str | None:
    """从输入里抠出 URL：接受「完整命令」(含 --url X) 或「裸 URL」；必须是 http(s)://。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    toks = raw.split()
    if "--url" in toks:
        i = toks.index("--url")
        url = toks[i + 1] if i + 1 < len(toks) else ""
    else:
        url = next((t for t in toks if t.startswith(("http://", "https://"))), "")
        if not url and len(toks) == 1:
            url = toks[0]
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    return url


def _read_custom() -> dict:
    return _read_state("cloudflared_custom") or {}


def _write_custom(d: dict) -> None:
    _write_state("cloudflared_custom", d)


def cloudflared_custom_list() -> list[dict]:
    """在跑的自定义隧道列表（顺带剔除已死的条目）。元素：{url, pid, started_at, domain}。"""
    d = _read_custom()
    out: list[dict] = []
    changed = False
    for url, info in list(d.items()):
        pid = info.get("pid")
        if not _pid_alive(pid):
            del d[url]
            changed = True
            continue
        slug = info.get("slug") or _cf_slug(url)
        out.append({
            "url": url,
            "pid": pid,
            "started_at": info.get("started_at"),
            "domain": _scan_domain_in(_cf_custom_log(slug)),
        })
    if changed:
        _write_custom(d)
    return out


def cloudflared_custom_start(raw: str) -> tuple[bool, str]:
    """指定启动：输入 URL（或完整命令）起一条独立隧道，协议沿用全局偏好。必须填 URL。"""
    url = _extract_cf_url(raw)
    if not url:
        return False, "❌ 必须填写 URL（如 http://localhost:5173）"
    d = _read_custom()
    info = d.get(url)
    if info and _pid_alive(info.get("pid")):
        dom = _scan_domain_in(_cf_custom_log(info.get("slug") or _cf_slug(url)))
        return True, f"✅ 该 URL 隧道已在运行：{url}" + (f"\n域名：{dom}" if dom else "")
    slug = _cf_slug(url)
    log = _cf_custom_log(slug)
    try:
        log.write_text("", "utf-8")  # 清旧日志，确保抓到本次域名
    except Exception:
        pass
    proto = cloudflared_protocol()
    try:
        pid = _spawn_detached(
            [_bin("cloudflared"), "tunnel", "--url", url, "--protocol", proto],
            log,
        )
    except Exception as e:
        return False, f"❌ 启动失败：{e}"
    d[url] = {"pid": pid, "started_at": _now(), "slug": slug}
    _write_custom(d)
    dom = None
    for _ in range(30):  # 等域名出现，最多 ~15s
        dom = _scan_domain_in(log)
        if dom:
            break
        time.sleep(0.5)
    if dom:
        return True, f"✅ 已为 {url} 启动隧道（{proto}）\n公网域名：{dom}"
    return True, f"⏳ 已为 {url} 启动隧道，但暂未捕获到域名（可稍后刷新）"


def cloudflared_custom_stop(url: str) -> tuple[bool, str]:
    """关闭指定 URL 的自定义隧道（只杀这一条，不碰全局隧道）。"""
    d = _read_custom()
    info = d.get(url)
    killed = False
    pid = info.get("pid") if info else None
    if pid and _kill_pid(pid, group=True):
        killed = True
    # 兜底：按该 URL 的命令签名再扫一遍（pid 失效时）
    for p in _pids_by_pattern(f"{_QUICK_PATTERN} {url}"):
        if p != pid and _kill_pid(p, group=False):
            killed = True
    if url in d:
        del d[url]
        _write_custom(d)
    return (True, f"✅ 已关闭隧道：{url}") if killed else (True, f"ℹ️ 该隧道未在运行：{url}")


# ---------- dsh（DeepSeek Harness web）----------
# dsh web 本身没有密码登录：它前面起一个 Basic Auth 网关（app_ado/dsh_gateway.py），
# 隧道暴露的是**网关**端口，手机访问先过密钥（体验同 code-server 密码）。
# 密钥只进钥匙串（app_ado.secrets），首次启动自动生成。
# 启停沿用 code-server 的双兜底模式（状态文件 PID + 端口扫描），但按端口杀时
# 只认 dsh / dsh_gateway 进程签名，绝不误伤占同端口的无关进程。
# 隧道复用 cloudflared_custom_*（按 URL 一条独立隧道，不碰全局隧道）。

DSH_DEFAULT_PORT = 3080      # dsh web 默认端口
# 网关端口必须固定（Cloudflare 命名隧道路由指向 `localhost:3081`，见 DSH_TUNNEL_ROUTE_PORT）；
# 启动时尽量钉死在此端口，只有被无关进程占用才后移——后移会让隧道路由失配 → 隧道全 502。
DSH_GATEWAY_PORT = 3081
DSH_TUNNEL_ROUTE_PORT = 3081  # Cloudflare 路由里写死的网关端口（改它要同步改 CF 路由）


def _dsh_gateway_script() -> Path:
    return Path(__file__).parent / "dsh_gateway.py"


def dsh_password() -> str | None:
    from app_ado import secrets as app_secrets
    return app_secrets.get_dsh_password()


def _port_free(port: int) -> bool:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _pick_free_port(first: int) -> int | None:
    """从 first 向上扫（含自身），返回第一个空闲端口；扫 50 个仍无则 None。"""
    for p in range(first, first + 50):
        if _port_free(p):
            return p
    return None


def _wait_port_free(port: int, timeout: float = 5.0) -> bool:
    """杀完旧网关后端口可能还在收尾（1-2s），轮询等它真正释放；超时返回 False。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_free(port):
            return True
        time.sleep(0.2)
    return _port_free(port)


def _dsh_node_env() -> dict[str, str] | None:
    """dsh 是 node 脚本；nvm/homebrew 的 node 目录不一定在 GUI app 的 PATH 里，显式补上。"""
    candidates = [shutil.which("node")]
    candidates += [str(p) for p in sorted(Path.home().glob(".nvm/versions/node/*/bin/node"), reverse=True)]
    candidates += ["/opt/homebrew/bin/node", "/usr/local/bin/node"]
    for c in candidates:
        if c and os.path.exists(c):
            return {"PATH": os.path.dirname(c) + os.pathsep + os.environ.get("PATH", "")}
    return None


def _dsh_node_env_with_home() -> dict[str, str]:
    """新起 dsh 时的环境：PATH（同 _dsh_node_env）+ 显式 DSH_HOME=~/.dsh。

    显式钉住 home，避免子进程从 bot 继承到不同的 HOME/DSH_HOME 而读到空 home
    （那样模型/密钥/知识都不在）。默认 ~/.dsh 本就是 resolveDshHome 的缺省值。
    """
    env = dict(_dsh_node_env() or {})
    env["DSH_HOME"] = str(Path.home() / ".dsh")
    return env


def _dsh_project_dir() -> str:
    """新起 dsh 时用它当工作目录，让会话桶与「主 dsh」一致。

    DSH 会话按工作目录分桶（~/.dsh/sessions/<cwd 编码>/）；默认=本仓库根，
    即用户主 dsh 所在的目录，这样新起也能看到同一份会话历史。
    """
    return str(Path(__file__).resolve().parent.parent)


def _dsh_launch_argv(port: int) -> tuple[list[str], dict[str, str]] | None:
    """dsh 启动命令 + 环境。红线：只用两种官方形式，别的都不许（用户明确要求）：
      1) `dsh web ...`          —— 装好后自带，PATH 里有 dsh 时优先（最快）
      2) `npx -y @deepseek-ai/dsh web ...` —— 官方 npx 形式，GUI app PATH 受限时回退
    命令解析用「补全后的 PATH」(node 所在目录)，避免 GUI app 自身 PATH 受限漏判。
    返回 (argv, env)；两种都不可用返回 None。
    """
    env = _dsh_node_env_with_home()
    path = env.get("PATH", os.environ.get("PATH", ""))

    def _which(name: str) -> str | None:
        for d in path.split(os.pathsep):
            if not d:
                continue
            p = os.path.join(d, name)
            if os.path.exists(p) and os.access(p, os.X_OK):
                return p
        return None

    flags = ["web", "--no-open", "--host", "127.0.0.1", "--port", str(port)]
    dsh = _which("dsh")
    if dsh:
        return [dsh, *flags], env
    npx = _which("npx")
    if npx:
        return [npx, "-y", "@deepseek-ai/dsh", *flags], env
    return None


def _cmd_of(pid) -> str:
    try:
        r = subprocess.run(
            ["ps", "-p", str(int(pid)), "-o", "command="],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout
    except Exception:
        return ""


def _is_dsh_pid(pid) -> bool:
    """是否 dsh web 进程。dlx 的 .bin/dsh 是 sh shim，exec 后监听进程是
    `node .../@deepseek-ai/dsh/lib/bin.js web ...`，故认「路径含 dsh + 参数含 web」。
    ps 被环境拦截（如沙箱）时回退 pgrep 签名扫描。"""
    cmd = _cmd_of(pid)
    if cmd.strip():
        return "dsh" in cmd and " web" in (" " + cmd)
    try:
        # ps 被拦（如沙箱）时回退：与 _find_running_dsh 同用宽签名 `dsh.* web`
        # （覆盖 .bin/dsh shim 与 lib/bin.js 两种拉起方式）。
        return int(pid) in _pids_by_pattern(r"dsh.* web")
    except Exception:
        return False


def _is_dsh_gateway_pid(pid) -> bool:
    cmd = _cmd_of(pid)
    if cmd.strip():
        return "dsh_gateway" in cmd
    try:
        return int(pid) in _pids_by_pattern(r"dsh_gateway\.py")
    except Exception:
        return False


def _listen_port_of(pid) -> int | None:
    """取某 pid 的 TCP LISTEN 端口（lsof -F n，形如 n127.0.0.1:3080）；取不到返回 None。"""
    try:
        r = subprocess.run(
            ["lsof", "-nP", "-a", "-p", str(int(pid)), "-iTCP", "-sTCP:LISTEN", "-F", "n"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    for line in r.stdout.splitlines():
        if line.startswith("n"):
            tail = line[1:].rsplit(":", 1)[-1]
            if tail.isdigit():
                return int(tail)
    return None


def _is_dsh_web_port(port: int, timeout: float = 2.5) -> bool:
    """HTTP 探活：该端口的根页面是不是 dsh web。

    认 `__DSH_BOOT__` 指纹（只有 dsh web 会往注入的 shell 里放它，页面首段就有）。
    与命令行签名无关，故能识别**任意方式**拉起的 dsh web（GUI 拉起 / `dsh web` /
    npx 拉起都一样）——命令行签名会因启动方式不同而漏判，探活不会。
    """
    import urllib.request
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            head = resp.read(8192).decode("utf-8", "ignore")
        return "__DSH_BOOT__" in head
    except Exception:
        return False


def _find_running_dsh(prefer_port: int | None = None) -> tuple[int, int] | None:
    """任意端口上已有 dsh web 在监听 → 返回 (port, pid)；否则 None。

    这是「复用你那份 dsh」的关键：不局限默认端口。做法分两步——
      1) 收集候选端口：prefer_port（state 记录的端口）> 默认 3080 > `dsh.* web`
         命令行签名命中的监听端口（覆盖 `dsh web`/npx 两种官方启动）。
      2) 对候选端口做 HTTP 探活确认（认 `__DSH_BOOT__`），确认到哪个就用哪个；
         探活全失败时回退到签名命中的监听端口（优先 3080，其次 pid 最大）。
    """
    cands: list[int] = []

    def _add(p: int | None) -> None:
        if p and p not in cands:
            cands.append(p)

    _add(prefer_port)
    _add(DSH_DEFAULT_PORT)
    sig_found: list[tuple[int, int]] = []
    for raw in _pids_by_pattern(r"dsh.* web"):
        try:
            pid = int(raw)
        except Exception:
            continue
        port = _listen_port_of(pid)
        if port:
            _add(port)
            sig_found.append((port, pid))

    # 2) HTTP 探活确认（权威判据）
    for p in cands:
        if _is_dsh_web_port(p):
            pids = _pids_on_port(p)
            return p, (pids[0] if pids else -1)

    # 回退：签名命中的监听端口（探活没确认到时的兜底）
    if sig_found:
        for port, pid in sig_found:
            if prefer_port and port == prefer_port:
                return port, pid
        for port, pid in sig_found:
            if port == DSH_DEFAULT_PORT:
                return port, pid
        return max(sig_found, key=lambda t: t[1])
    return None


def dsh_running() -> bool:
    st = _read_state("dsh")
    ports = {p for p in (st.get("port"), DSH_DEFAULT_PORT) if p}
    return any(
        any(_is_dsh_pid(p) for p in _pids_on_port(port))
        for port in ports
    )


def dsh_gateway_running() -> bool:
    st = _read_state("dsh")
    return any(
        _is_dsh_gateway_pid(p)
        for p in _pids_on_port(st.get("gw_port") or DSH_GATEWAY_PORT)
    )


def dsh_tunnel_url() -> str | None:
    return _read_state("dsh").get("tunnel_url")


def dsh_domain() -> str | None:
    # 命名隧道在跑 → 固定域名：优先钥匙串里的自定义 CNAME（如 dsh.egoist88.cc.cd），
    # 没设就显示从 token 推导的 <tunnel-id>.cfargotunnel.com（两者都可用，前者好记）。
    if _dsh_named_tunnel_pids():
        from app_ado import secrets as app_secrets
        try:
            dom = app_secrets.get_dsh_tunnel_domain()
            if dom:
                return dom
        except Exception:
            pass
        return _dsh_named_tunnel_domain()
    url = dsh_tunnel_url()
    if not url:
        return None
    return next((c.get("domain") for c in cloudflared_custom_list() if c["url"] == url), None)


def _spawn_dsh_gateway(dsh_port: int, gw_port: int, key: str) -> int:
    """起（或重启）Basic Auth 网关，返回 PID。调用前应已确保 gw_port 空闲。"""
    try:
        _log_path("dsh-gateway").write_text("", "utf-8")
    except Exception:
        pass
    return _spawn_detached(
        [
            sys.executable, str(_dsh_gateway_script()),
            # 监听 0.0.0.0：同一内网的手机/设备可直连（不经 Cloudflare，WS 原生可用）；
            # 访问仍由网关的 Basic Auth key 把关，dsh 本身仍只监听 127.0.0.1。
            "--listen", f"0.0.0.0:{gw_port}",
            "--upstream", f"127.0.0.1:{dsh_port}",
            "--key", key,
        ],
        _log_path("dsh-gateway"),
    )


def _kill_dsh_gateway() -> None:
    """只杀签名是 dsh_gateway 的进程（状态 PID 杀组 + 端口扫描兜底），不碰无关进程。

    扫描「状态记录的端口 + 固定端口 3081」两处：网关必须钉在 3081（隧道路由指向它），
    状态里若是上次漂移过的端口，扫两处才能把残留实例清干净、让新实例拿回 3081。
    """
    st = _read_state("dsh")
    gw_pid = st.get("gw_pid")
    if gw_pid and _kill_pid(gw_pid, group=True):
        pass
    for port in dict.fromkeys((st.get("gw_port") or DSH_GATEWAY_PORT, DSH_GATEWAY_PORT)):
        for p in _pids_on_port(port):
            if p != gw_pid and _is_dsh_gateway_pid(p) and _kill_pid(p, group=False):
                pass


def dsh_start() -> tuple[bool, str]:
    from app_ado import secrets as app_secrets

    # 密钥：没有就自动生成存钥匙串
    key = app_secrets.get_dsh_password()
    if not key:
        key = _py_secrets.token_hex(8)  # 16 位 hex
        app_secrets.set_dsh_password(key)

    st = _read_state("dsh")
    old_tunnel_url = st.get("tunnel_url")
    port = st.get("port") or DSH_DEFAULT_PORT

    # 1) 优先复用：任意端口上已有 dsh web（你手动起的那份）→ 直接挂隧道，不新起进程。
    #    这样手机连到的就是"你那份" dsh——会话历史/模型/知识全在（会话按 cwd 分桶，
    #    复用它本身就落在正确的桶里）。
    reused = False
    running = _find_running_dsh(prefer_port=st.get("port") or DSH_DEFAULT_PORT)
    if running:
        port, _rpid = running
        reused = True
        st = {"pid": None, "started_at": st.get("started_at") or _now(), "port": port}
    else:
        # 2) 没有则在默认端口新起；端口被无关进程占就往后推。
        #    新起时钉死 DSH_HOME(~/.dsh) + 工作目录(本仓库根)，让它和主 dsh 共享同一份
        #    数据，绝不再出现"全新空 dsh"。
        if _pids_on_port(port) and not any(_is_dsh_pid(p) for p in _pids_on_port(port)):
            port = _pick_free_port(DSH_DEFAULT_PORT)
            if port is None:
                return False, f"❌ 没找到空闲端口（{DSH_DEFAULT_PORT} 起扫了 50 个都被占）"
        launch = _dsh_launch_argv(port)
        if launch is None:
            return False, "❌ 找不到可用的 dsh（补全 PATH 后既没有 `dsh` 也没有 `npx`）。请先安装 dsh 再启动。"
        argv, env = launch
        if st.get("pid") and _pid_alive(st.get("pid")):
            _kill_pid(st["pid"], group=True)
        try:
            pid = _spawn_detached(argv, _log_path("dsh"), env=env, cwd=_dsh_project_dir())
        except Exception as e:
            return False, f"❌ dsh 启动失败：{e}"
        if not pid:
            return False, f"❌ dsh 启动失败（没拿到 PID），日志：{_log_path('dsh')}"
        st = {"pid": pid, "started_at": _now(), "port": port}
        _write_state("dsh", st)
        ready = False
        for _ in range(60):  # node 启动 + profile 引导稍慢，最多等 ~30s
            if _pids_on_port(port):
                ready = True
                break
            time.sleep(0.5)
        if not ready:
            return False, f"❌ dsh 已拉起但端口 {port} 一直没就绪，看日志：{_log_path('dsh')}"

    # 3) 网关：每次启动都换新（旧的可能还指向上次的端口），先清旧、**等端口真正释放**再起。
    #    端口钉死 DSH_GATEWAY_PORT：Cloudflare 路由固定指向 localhost:3081，端口一旦漂移
    #    路由就失配（隧道全 502）。只有被无关进程占着才后移。
    _kill_dsh_gateway()
    time.sleep(0.3)
    gw_port = DSH_GATEWAY_PORT
    if not _wait_port_free(gw_port):
        gw_port = _pick_free_port(DSH_GATEWAY_PORT + 1)
        if gw_port is None:
            return False, "❌ 网关没找到空闲端口"
    gw_pid = _spawn_dsh_gateway(port, gw_port, key)
    ready = False
    for _ in range(20):  # 等网关端口就绪，最多 ~5s
        if _pids_on_port(gw_port):
            ready = True
            break
        time.sleep(0.25)
    if not ready:
        return False, f"❌ 网关启动失败，日志：{_log_path('dsh-gateway')}"
    st["gw_pid"] = gw_pid
    st["gw_port"] = gw_port
    st["tunnel_url"] = f"http://127.0.0.1:{gw_port}"
    _write_state("dsh", st)

    # 4) 隧道：优先命名隧道（钥匙串有 token → 固定域名、稳），没有才用「指定启动」快速隧道。
    #    若 URL 变了（端口被推过），旧 URL 的快速隧道顺手关掉。
    if old_tunnel_url and old_tunnel_url != st["tunnel_url"]:
        try:
            cloudflared_custom_stop(old_tunnel_url)
        except Exception:
            pass
    _nok, _tmsg = _ensure_dsh_named_tunnel()
    if not _nok:
        _, _tmsg = cloudflared_custom_start(st["tunnel_url"])

    lines = [f"✅ dsh 已启动" + ("（复用了已在运行的 dsh，历史/模型都在）" if reused else "")]
    lines.append(f"端口：{port}（网关 {gw_port}）")
    lines.append(f"密钥：{key}")
    dom = dsh_domain()
    lines.append(f"公网域名：{dom}" if dom else "（隧道域名稍后刷新）")
    return True, "\n".join(lines)


def dsh_stop() -> tuple[bool, str]:
    st = _read_state("dsh")
    port = st.get("port") or DSH_DEFAULT_PORT
    gw_port = st.get("gw_port") or DSH_GATEWAY_PORT
    # 复用来的 dsh（state.pid 为 None）本体不归面板管：只拆隧道+网关，绝不误杀
    # 用户自己那份 dsh；只有面板自己起的（pid 非空）才连同 dsh 一起关。
    owned = st.get("pid") is not None

    # 1) 隧道（按 state 记录的 URL 关；state 丢了就用默认 URL 兜底）
    url = st.get("tunnel_url") or f"http://127.0.0.1:{gw_port}"
    try:
        cloudflared_custom_stop(url)
    except Exception:
        pass

    # 2) 网关
    killed = False
    gw_pid = st.get("gw_pid")
    if gw_pid and _kill_pid(gw_pid, group=True):
        killed = True
    for p in _pids_on_port(gw_port):
        if p != gw_pid and _is_dsh_gateway_pid(p) and _kill_pid(p, group=False):
            killed = True

    # 3) dsh 本体：只在面板自己起的情况下杀（只认 dsh web 签名，误伤面 = 0）
    if owned:
        pid = st.get("pid")
        if pid and _kill_pid(pid, group=True):
            killed = True
        for p in _pids_on_port(port):
            if p != pid and _is_dsh_pid(p) and _kill_pid(p, group=False):
                killed = True

    _clear_state("dsh")
    time.sleep(0.3)
    if not owned:
        return True, "✅ 已断开 dsh 隧道/网关（复用的 dsh 本体仍在运行，未受影响）"
    if _pids_on_port(port):
        return False, "⚠️ dsh 端口仍被占用，可能未完全关闭"
    return (True, "✅ dsh 已关闭（隧道 / 网关 / dsh 全部关闭）") if killed else (True, "ℹ️ dsh 本来就没在运行")


def _dsh_tunnel_url() -> str:
    """当前 dsh 隧道应指向的网关 URL（state 优先，缺省用网关默认端口）。"""
    st = _read_state("dsh")
    return st.get("tunnel_url") or f"http://127.0.0.1:{st.get('gw_port') or DSH_GATEWAY_PORT}"


# ---------- dsh 命名隧道（Cloudflare 主控制台 Networking > Tunnels，免费计划可用、无需绑卡）----------
# token 在钥匙串（secrets.get_dsh_tunnel_token）；「隧道」按钮优先命名隧道（固定域名、
# 持久、无快速隧道的间歇 502），没有 token 才回退快速隧道（随机 trycloudflare 域名）。
# 进程识别只认「命令里带本 token」的 cloudflared，绝不误伤账号里其它项目的命名隧道。

def _dsh_tunnel_token() -> str | None:
    from app_ado import secrets as app_secrets
    try:
        return (app_secrets.get_dsh_tunnel_token() or "").strip() or None
    except Exception:
        return None


def _dsh_named_tunnel_pids() -> list[int]:
    """在跑的 dsh 命名隧道 PID（按完整 token 精确匹配；面板外手动起的也能发现）。"""
    tok = _dsh_tunnel_token()
    if not tok:
        return []
    return _pids_by_pattern(r"cloudflared tunnel run --token " + re.escape(tok))


def _dsh_named_tunnel_domain() -> str | None:
    """命名隧道公网域名：<tunnel-id>.cfargotunnel.com（tunnel ID 在 token base64 JSON 载荷的 t 字段）。"""
    tok = _dsh_tunnel_token()
    if not tok:
        return None
    try:
        import base64
        seg = tok.split(".")[1] if "." in tok else tok  # 兼容三段 JWT 与单段 base64 两种形态
        seg += "=" * (-len(seg) % 4)
        tid = json.loads(base64.urlsafe_b64decode(seg)).get("t")
        if tid:
            return f"{tid}.cfargotunnel.com"
    except Exception:
        pass
    return None


def _ensure_dsh_named_tunnel() -> tuple[bool, str]:
    """确保 dsh 命名隧道在跑（幂等）；没 token 返回失败提示（调用方回退快速隧道）。"""
    tok = _dsh_tunnel_token()
    if not tok:
        return False, "（钥匙串没有 dsh 隧道 token，回退快速隧道）"
    if _dsh_named_tunnel_pids():
        return True, "✅ dsh 命名隧道已在运行"
    try:
        _log_path("dsh-tunnel").write_text("", "utf-8")
    except Exception:
        pass
    try:
        pid = _spawn_detached(
            [_bin("cloudflared"), "tunnel", "run", "--token", tok],
            _log_path("dsh-tunnel"),
        )
    except Exception as e:
        return False, f"❌ 命名隧道启动失败：{e}"
    if not pid:
        return False, f"❌ 命名隧道启动失败（没拿到 PID），日志：{_log_path('dsh-tunnel')}"
    st = _read_state("dsh")
    st["tunnel_pid"] = pid
    _write_state("dsh", st)
    return True, f"✅ dsh 命名隧道已启动（pid {pid}）"


def dsh_tunnel_running() -> bool:
    """dsh 隧道是否在跑：命名隧道（按 token 匹配）或快速隧道（按网关 URL 匹配）。"""
    if _dsh_named_tunnel_pids():
        return True
    url = _dsh_tunnel_url()
    return any(c["url"] == url for c in cloudflared_custom_list())


def dsh_tunnel_start() -> tuple[bool, str]:
    """开 dsh 隧道：优先命名隧道（钥匙串有 token 时，固定域名、稳），否则快速隧道。
    dsh/网关没起就顺带拉起（复用 dsh_start）。只动隧道这条，不碰全局 code-server 隧道。
    """
    if not (dsh_running() and dsh_gateway_running()):
        return dsh_start()  # dsh/网关不全 → 走完整启动（复用已跑 dsh + 起网关 + 起隧道）
    ok, msg = _ensure_dsh_named_tunnel()
    if ok:
        dom = dsh_domain()
        return True, (f"✅ dsh 隧道已开启（命名隧道，固定域名）\n公网域名：{dom}" if dom else msg)
    url = _dsh_tunnel_url()
    _, msg = cloudflared_custom_start(url)  # 幂等：已在跑会返回「已在运行」
    dom = dsh_domain()
    return True, (f"✅ dsh 隧道已开启（快速隧道）\n公网域名：{dom}" if dom else msg)


def dsh_tunnel_stop() -> tuple[bool, str]:
    """关 dsh 隧道（命名隧道按 token 精确杀 + 遗留快速隧道都清；dsh/网关留着，局域网仍可直连）。"""
    for p in _dsh_named_tunnel_pids():
        _kill_pid(p, group=False)  # 可能面板外手动起的，只点名杀该 pid
    url = _dsh_tunnel_url()
    try:
        cloudflared_custom_stop(url)
    except Exception:
        pass
    if dsh_running():
        return True, "✅ dsh 隧道已关闭（dsh/网关仍在运行，局域网可直连）"
    return True, "ℹ️ dsh 隧道已关闭"


def dsh_tunnel_toggle() -> tuple[bool, str]:
    """按隧道当前状态开关 dsh 临时隧道：开着→关，关着→开（一个按钮搞定）。

    不按「是否局域网」判断——那样隧道已开着时按钮仍显示「开隧道」，自相矛盾。
    """
    if dsh_tunnel_running():
        return dsh_tunnel_stop()
    return dsh_tunnel_start()


def dsh_set_password(pw: str) -> tuple[bool, str]:
    """换密钥：写钥匙串；网关在跑就重启网关使其生效（隧道 URL 不变）。"""
    from app_ado import secrets as app_secrets

    pw = (pw or "").strip()
    if len(pw) < 6:
        return False, "❌ 密钥太短（至少 6 位）"
    app_secrets.set_dsh_password(pw)
    if not dsh_gateway_running():
        return True, "✅ 密钥已更新（下次启动生效）"
    st = _read_state("dsh")
    dsh_port = st.get("port") or DSH_DEFAULT_PORT
    # 端口钉死 DSH_GATEWAY_PORT（Cloudflare 路由固定指向 localhost:3081，见 dsh_start 注释）
    gw_port = DSH_GATEWAY_PORT
    _kill_dsh_gateway()
    time.sleep(0.3)
    if not _wait_port_free(gw_port):
        gw_port = _pick_free_port(DSH_GATEWAY_PORT + 1) or gw_port
    gw_pid = _spawn_dsh_gateway(dsh_port, gw_port, pw)
    ready = False
    for _ in range(20):
        if _pids_on_port(gw_port):
            ready = True
            break
        time.sleep(0.25)
    if not ready:
        return False, f"❌ 密钥已更新，但网关重启失败，日志：{_log_path('dsh-gateway')}"
    st["gw_pid"] = gw_pid
    st["gw_port"] = gw_port
    st["tunnel_url"] = f"http://127.0.0.1:{gw_port}"
    _write_state("dsh", st)
    return True, f"✅ 密钥已更新并重启网关（端口 {dsh_port} / 网关 {gw_port}）"


def dsh_status() -> str:
    st = _read_state("dsh")
    port = st.get("port") or DSH_DEFAULT_PORT
    gw_port = st.get("gw_port") or DSH_GATEWAY_PORT
    key = dsh_password() or "(未设置)"
    if not dsh_running():
        return f"🧠 dsh：🔴 未运行\n端口：{port}（网关 {gw_port}）\n密钥：{key}"
    lines = [
        "🧠 dsh：🟢 运行中",
        f"端口：{port}（网关 {gw_port}）",
        f"密钥：{key}",
    ]
    on_lan = is_on_lan()
    lines.append(f"网络：{'🏠 局域网' if on_lan else '📶 非局域网'}（隧道按钮据此{'开' if on_lan else '关'}）")
    lip = _lan_ip()
    if lip:
        lines.append(f"局域网直连：http://{lip}:{gw_port}")
    if dsh_tunnel_running():
        dom = dsh_domain()
        if dom:
            lines.append(f"手机(隧道)：{dom}（用上面密钥登录）")
        else:
            lines.append("手机(隧道)：（域名待刷新）")
        if _dsh_named_tunnel_pids() and gw_port != DSH_TUNNEL_ROUTE_PORT:
            lines.append(f"⚠️ 网关端口 {gw_port} 与隧道路由（localhost:{DSH_TUNNEL_ROUTE_PORT}）不一致——隧道会 502，点「启动」重拉网关")
    elif dsh_tunnel_url():
        if _dsh_tunnel_token():
            lines.append("隧道：未开启（点「开隧道」按钮，走命名隧道/固定域名）")
        else:
            lines.append("隧道：未开启（点「开隧道」按钮；钥匙串无命名隧道 token，回退快速隧道）")
    return "\n".join(lines)
