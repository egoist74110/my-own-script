"""Lark MCP server 全局单例管理 + OAuth 登录托管。

为根治"多实例抢同一个会轮换的 refresh_token 导致 20038"——Lark MCP 改为
**共享 streamable HTTP 单实例**:由本 App 托管一个 lark-mcp 进程(``-m streamable
--oauth``),Claude/Codex/Antigravity 全部用同一个 URL 连接。单进程=单 token 刷新器,
不再有并发刷新竞争。App 退出时通过进程组 + atexit 回收,不留僵尸。
"""

from __future__ import annotations

import atexit
import datetime as _dt
import os as _os
import signal as _signal
import subprocess
import threading
import urllib.error
import urllib.request
from typing import Optional

from app_lark.lark_mcp_flow import tool_workspace_root
from app_lark.node_bootstrap import augmented_search_path, env_for_npx, find_npx
from app_lark.secrets import get_app_secret
from app_lark.store import (
    DEFAULT_DOMAIN,
    DEFAULT_HTTP_HOST,
    DEFAULT_OAUTH_PORT,
    DEFAULT_SCOPE,
    DEFAULT_TOOLS,
    clear_lark_login_state,
    is_logged_in,
    lark_mcp_http_url,
    load_lark_settings,
    oauth_redirect_url,
    save_lark_login_state,
)


_lock = threading.Lock()
_process: Optional[subprocess.Popen[str]] = None
_log_fh = None  # 托管 server 的日志文件句柄(随进程生命周期开/关)

# 托管 lark-mcp 的输出落盘到这里。放在 lark-mcp 自己的日志目录旁,排错时一处看全。
# 注意:lark-mcp 自身的 logger 默认 WARN 且只写它的每日文件(lark-mcp-YYYY-MM-DD.log),
# 不走 stderr——所以这个 managed 文件主要收编注入补丁的 `[lark-mcp patch]` 行 + 启动期输出;
# 完整刷新生命周期(info/debug)靠 argv 里的 `--debug` 写进 lark-mcp 每日文件。
_MANAGED_LOG = _os.path.expanduser("~/Library/Logs/lark-mcp-nodejs/managed.log")
_LOG_ROTATE_BYTES = 5 * 1024 * 1024


def lark_mcp_managed_log_path() -> str:
    """托管 server 输出的落盘路径(供 UI/TG「查看日志」与排错用)。"""
    return _MANAGED_LOG


def _open_managed_log():
    """打开(必要时先轮换)托管日志文件,返回可作 Popen stdout/stderr 的句柄;失败回退 DEVNULL。"""
    try:
        _os.makedirs(_os.path.dirname(_MANAGED_LOG), exist_ok=True)
        try:
            if _os.path.getsize(_MANAGED_LOG) > _LOG_ROTATE_BYTES:
                _os.replace(_MANAGED_LOG, _MANAGED_LOG + ".prev")  # 单文件轮换,不让无限长
        except OSError:
            pass
        return open(_MANAGED_LOG, "a", buffering=1)
    except Exception:
        return subprocess.DEVNULL


def _managed_log_tail(n: int = 8) -> str:
    """读 managed.log 末尾几行,拼成 `:...` 后缀用于启动失败提示;读不到则返回空串。"""
    try:
        with open(_MANAGED_LOG, "r", errors="replace") as fh:
            lines = fh.read().strip().splitlines()[-n:]
        tail = "\n".join(lines).strip()
        return (":\n" + tail) if tail else ""
    except Exception:
        return ""


def _close_managed_log() -> None:
    global _log_fh
    try:
        if _log_fh not in (None, subprocess.DEVNULL) and hasattr(_log_fh, "close"):
            _log_fh.close()
    except Exception:
        pass
    _log_fh = None

_login_lock = threading.Lock()
_login_process: Optional[subprocess.Popen[str]] = None
_login_cancelled: bool = False


def _augmented_env() -> dict[str, str]:
    """子进程跑 npx 时 env 里必须能找到 node，否则会报 `env: node: No such file or directory`。"""
    env = _os.environ.copy()
    env["PATH"] = augmented_search_path()
    return env


_SINGLEFLIGHT_PRELOAD = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "lark_mcp_singleflight.js")


def inject_singleflight(env: dict[str, str]) -> dict[str, str]:
    """给 lark-mcp 子进程注入 single-flight 补丁(NODE_OPTIONS=--require)。

    根治「UAT 过期后并发刷新各拿同一个会轮换的 refresh_token → 第一个轮换掉、其余拿旧值
    → 20038」。补丁在 ensureGetUserAccessToken 上收敛并发刷新为单飞。详见
    ``lark_mcp_singleflight.js``。方法名不在(上游改版)补丁会自动跳过,不影响启动。
    """
    if not _os.path.isfile(_SINGLEFLIGHT_PRELOAD):
        return env
    require_arg = f"--require {_SINGLEFLIGHT_PRELOAD}"
    prev = (env.get("NODE_OPTIONS") or "").strip()
    if _SINGLEFLIGHT_PRELOAD not in prev:
        env["NODE_OPTIONS"] = f"{prev} {require_arg}".strip() if prev else require_arg
    return env


def _kill_process_group(proc: subprocess.Popen) -> None:
    """杀掉子进程所在的整个进程组(npx→node 这种父子树一并清掉，不留僵尸)。"""
    if proc is None or proc.poll() is not None:
        return
    try:
        pgid = _os.getpgid(proc.pid)
        _os.killpg(pgid, _signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            return
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            pgid = _os.getpgid(proc.pid)
            _os.killpg(pgid, _signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


@atexit.register
def _cleanup_on_exit() -> None:
    """App 进程退出时，确保托管的 lark-mcp HTTP server 一并被回收。"""
    global _process
    if _process is not None:
        _kill_process_group(_process)
        _process = None
    _close_managed_log()


def _http_health_ok(port: int, timeout: float = 1.5) -> bool:
    """探活:GET /mcp。

    streamable 的 GET /mcp 不过鉴权中间件，直接回 405 —— 所以只要能收到**任何**
    HTTP 响应就说明 server 已起监听(连接被拒=没起)。不能用 POST initialize,因为
    ``--oauth`` 下 POST 需要 Bearer 鉴权,未授权会 401,无法作为存活判据。
    """
    req = urllib.request.Request(lark_mcp_http_url(port), method="GET")
    try:
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True  # 405/401 等 = 服务在监听
    except Exception:
        return False


# ---------------- MCP server 启停 ----------------


def is_lark_mcp_running() -> bool:
    with _lock:
        return _process is not None and _process.poll() is None


def _streamable_argv(npx: str) -> tuple[list[str], int, str] | tuple[None, str, None]:
    """组装 streamable HTTP 单实例启动参数。返回 (argv, port, secret) 或 (None, 错误原因, None)。

    App Secret **不进 argv**(否则 `ps` 任何人可见明文),由调用方放进环境变量 APP_SECRET 传
    (lark-mcp 支持)。app_id 不敏感,留在 argv 便于排错。
    """
    s = load_lark_settings()
    app_id = (s.app_id or "").strip()
    if not app_id:
        return None, "未配置 App ID", None
    secret = get_app_secret(app_id)
    if not secret:
        return None, "找不到 App Secret(请先保存配置)", None
    port = int(s.oauth_port or DEFAULT_OAUTH_PORT)
    argv = [
        npx, "-y", "@larksuiteoapi/lark-mcp", "mcp",
        "-a", app_id,
        "-d", (s.domain or DEFAULT_DOMAIN).strip(),
        "-t", (s.tools or DEFAULT_TOOLS).strip(),
        "-m", "streamable",
        "--host", DEFAULT_HTTP_HOST,
        "-p", str(port),
        "--oauth",                       # 单进程集中管 token + 刷新，根除并发刷新竞争
        "--token-mode", "user_access_token",
        "-l", (s.language or "zh").strip(),
        # 关键:**故意不传 `--scope`**。lark-mcp 0.5.1 的 provider 选择是个陷阱——
        #   传 --scope → LarkOAuth2OAuthServerProvider(authen/v1/authorize),它的 authorize() 只把
        #                **下游 MCP 客户端请求里的 scope** 转发给 Lark(我们配的 scope 仅用于"选 provider"、
        #                从不真正下发),客户端没带 offline_access → Lark 不发 refresh_token → 续期结构性失效
        #                (日志实锤 `refreshToken: false`),每次过期都被迫手动重登。
        #   不传 --scope → LarkOIDC2OAuthServerProvider(authen/v1 OIDC 流),**默认就发 refresh_token +
        #                refresh_expires_in**,自动续期才真正成立。tool 权限由飞书后台 app 配置决定,不靠此参数。
        # scope 设置/校验仍保留(用于提示后台是否已授予 docx/wiki/drive 权限),只是不再进 argv。
        # --debug:把 lark-mcp 自身 logger 从默认 WARN 调到 DEBUG,使完整刷新生命周期
        # (trying refreshToken → Successfully refreshed/expiresAt 或 20038)落进它的每日日志。日志 7 天自动清。
        "--debug",
    ]
    return argv, port, secret


def start_lark_mcp() -> tuple[bool, str]:
    """启动共享 streamable HTTP 单实例并等 /mcp 就绪。已运行则直接返回成功。"""
    global _process
    with _lock:
        if _process is not None and _process.poll() is None:
            return True, "已在运行"

        npx_path = find_npx()
        if npx_path is None:
            return False, "未找到 Node.js 运行时"
        argv, port, secret = _streamable_argv(str(npx_path))
        if argv is None:
            return False, str(port)

        # App Secret 经环境变量 APP_SECRET 传(不进 argv,避免 ps 明文泄漏)
        child_env = env_for_npx(npx_path)
        child_env["APP_SECRET"] = secret
        # 注入 single-flight 补丁:根治 UAT 过期后并发刷新自残(20038)
        inject_singleflight(child_env)

        # 输出落盘到 managed.log,而不是没人 drain 的 PIPE——后者既看不到刷新日志,
        # 还会在 pipe 缓冲(~64KB)写满时把 server 卡死。
        global _log_fh
        _log_fh = _open_managed_log()

        try:
            cp = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=_log_fh,
                stderr=subprocess.STDOUT,
                cwd=str(tool_workspace_root()),
                env=child_env,
                start_new_session=True,  # 独立进程组,停的时候连 npx→node 整棵树一起回收
            )
        except Exception as e:
            return False, f"进程启动失败:{e}"

        # 轮询等 HTTP server 起监听(最多 ~10s)
        import time as _time
        for _ in range(40):
            if cp.poll() is not None:  # 进程提前退出 = 启动失败
                return False, f"server 启动即退出{_managed_log_tail()}"
            if _http_health_ok(port):
                _process = cp
                return True, f"已开启(HTTP {lark_mcp_http_url(port)})"
            _time.sleep(0.25)

        _kill_process_group(cp)
        return False, f"server 启动超时(端口 {port} 未就绪;是否被占用?)"


def stop_lark_mcp() -> tuple[bool, str]:
    global _process
    with _lock:
        if _process is None or _process.poll() is not None:
            _process = None
            return True, "已停止"
        _kill_process_group(_process)
        _process = None
        _close_managed_log()
        return True, "已关闭"


# ---------------- OAuth 登录 ----------------


def is_lark_login_running() -> bool:
    with _login_lock:
        return _login_process is not None and _login_process.poll() is None


def is_lark_logged_in() -> bool:
    s = load_lark_settings()
    return is_logged_in(s.app_id)


LOGIN_CANCELLED_SENTINEL = "__cancelled__"


def start_lark_login(timeout_s: int = 300) -> tuple[bool, str]:
    """同步等用户在浏览器完成 OAuth。回调成功 → lark-mcp login 进程退出 → 写本地 state。

    用法:UI 端开一个 daemon thread 调这个,主线程别阻塞。
    返回:(True, "登录成功") / (False, "...") / (False, LOGIN_CANCELLED_SENTINEL) —— 用户主动取消。
    """
    global _login_process, _login_cancelled
    s = load_lark_settings()
    app_id = (s.app_id or "").strip()
    if not app_id:
        return False, "未配置 App ID"
    secret = get_app_secret(app_id)
    if not secret:
        return False, "找不到 App Secret(请先保存配置)"

    # 登录用的 OAuth 回调端口和共享 HTTP server 是同一个，二者不能同时占用；先停 server。
    # 记住登录前是否在跑：登录成功后要把它原样拉回来,否则用户「登出→登录」完会发现服务
    # 是停的(AI 工具连 3000 被拒),还得手动点「开启」,看起来就像「重登了还不行」。
    _was_running = is_lark_mcp_running()
    if _was_running:
        stop_lark_mcp()

    npx_path = find_npx()
    if npx_path is None:
        return False, "未找到 Node.js 运行时(请到 Lark MCP 卡里点\"下载内置 Node 运行时\")"
    npx = str(npx_path)

    domain = (s.domain or DEFAULT_DOMAIN).strip()
    port = int(s.oauth_port or DEFAULT_OAUTH_PORT)
    scope = (s.scope or DEFAULT_SCOPE).strip()  # 仅作登录状态元数据 / scope 校验用,不进 argv(见下)

    argv = [
        npx, "-y", "@larksuiteoapi/lark-mcp", "login",
        "-a", app_id,
        "-s", secret,
        "-d", domain,
        "-p", str(port),
        # 同 _streamable_argv:**不传 --scope**,落到 LarkOIDC2OAuthServerProvider(authen/v1 OIDC 流),
        # 默认发 refresh_token,自动续期才成立。传了 --scope 会走 v1 OAuth2 分支,易拿不到 refresh_token。
    ]

    with _login_lock:
        if _login_process is not None and _login_process.poll() is None:
            return False, f"登录子进程已在跑(浏览器应已弹出,回调端口 {port})"
        _login_cancelled = False
        try:
            _login_process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(tool_workspace_root()),
                env=env_for_npx(npx_path),
            )
        except Exception as e:
            return False, f"启动登录失败:{e}"

    try:
        out_tail: list[str] = []
        try:
            stdout, _ = _login_process.communicate(timeout=timeout_s)
            if stdout:
                out_tail = stdout.splitlines()[-20:]
        except subprocess.TimeoutExpired:
            _login_process.terminate()
            return False, f"登录超时({timeout_s}s)。浏览器没完成授权?回调 URL `{oauth_redirect_url(port)}` 是否在 Lark 后台已配?"

        if _login_cancelled:
            return False, LOGIN_CANCELLED_SENTINEL

        code = _login_process.returncode
        if code != 0:
            tail = "\n".join(out_tail).strip()
            return False, f"登录失败(exit={code})。最近输出:\n{tail or '(无)'}"

        save_lark_login_state({
            "app_id": app_id,
            "domain": domain,
            "scope": scope,
            "logged_in_at": _dt.datetime.now().isoformat(timespec="seconds"),
        })
        # 登录前停掉了共享 server,这里按原状拉回来,让重登后服务立即恢复(新 token 生效)。
        if _was_running:
            try:
                start_lark_mcp()
            except Exception:
                pass
        return True, "登录成功"
    finally:
        with _login_lock:
            _login_process = None


def cancel_lark_login() -> tuple[bool, str]:
    """中止正在跑的 OAuth 登录子进程。"""
    global _login_cancelled
    with _login_lock:
        if _login_process is None or _login_process.poll() is not None:
            return False, "登录未在进行"
        _login_cancelled = True
        try:
            _login_process.terminate()
        except Exception as e:
            return False, f"取消失败:{e}"
    return True, "已取消"


def lark_logout() -> tuple[bool, str]:
    """清本地 state + 调 lark-mcp logout 清 npm 包内部 token 缓存。"""
    s = load_lark_settings()
    app_id = (s.app_id or "").strip()
    clear_lark_login_state()

    if not app_id:
        return True, "已清空本地登录状态"

    npx_path = find_npx()
    if npx_path is None:
        return True, "已清空本地登录状态(未找到 Node 运行时,跳过 lark-mcp logout)"
    npx = str(npx_path)

    try:
        cp = subprocess.run(
            [npx, "-y", "@larksuiteoapi/lark-mcp", "logout", "-a", app_id],
            capture_output=True,
            text=True,
            timeout=60,
            env=env_for_npx(npx_path),
        )
    except Exception as e:
        return True, f"已清空本地状态;调用 lark-mcp logout 异常:{e}"

    if cp.returncode != 0:
        tail = (cp.stderr or cp.stdout or "").strip().splitlines()[-5:]
        return True, "本地状态已清;lark-mcp logout 报错(可能本来就没缓存):\n" + "\n".join(tail)
    return True, "已登出"
