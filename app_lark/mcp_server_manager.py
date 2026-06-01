"""Lark MCP server 子进程的全局单例管理 + OAuth 登录托管(对齐 app_ado.mcp_server_manager)。"""

from __future__ import annotations

import datetime as _dt
import subprocess
import threading
from typing import Optional

from app_lark.lark_mcp_flow import (
    lark_mcp_python,
    lark_mcp_server_script,
    tool_workspace_root,
)
from app_lark.node_bootstrap import augmented_search_path, env_for_npx, find_npx
from app_lark.secrets import get_app_secret
from app_lark.store import (
    DEFAULT_DOMAIN,
    DEFAULT_OAUTH_PORT,
    DEFAULT_SCOPE,
    clear_lark_login_state,
    is_logged_in,
    load_lark_settings,
    oauth_redirect_url,
    save_lark_login_state,
)


_lock = threading.Lock()
_process: Optional[subprocess.Popen[str]] = None

_login_lock = threading.Lock()
_login_process: Optional[subprocess.Popen[str]] = None
_login_cancelled: bool = False


def _augmented_env() -> dict[str, str]:
    """子进程跑 npx 时 env 里必须能找到 node，否则会报 `env: node: No such file or directory`。"""
    import os as _os
    env = _os.environ.copy()
    env["PATH"] = augmented_search_path()
    return env


# ---------------- MCP server 启停 ----------------


def is_lark_mcp_running() -> bool:
    with _lock:
        return _process is not None and _process.poll() is None


def start_lark_mcp() -> tuple[bool, str]:
    """启动 server 子进程并做 initialize 握手。已运行则直接返回成功。"""
    global _process
    with _lock:
        if _process is not None and _process.poll() is None:
            return True, "已在运行"
        try:
            cp = subprocess.Popen(
                [lark_mcp_python(), lark_mcp_server_script()],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(tool_workspace_root()),
                env=_augmented_env(),
            )
        except Exception as e:
            return False, f"进程启动失败:{e}"

        if cp.stdin is None or cp.stdout is None:
            cp.terminate()
            return False, "进程 stdio 未就绪"

        try:
            cp.stdin.write(
                '{"jsonrpc":"2.0","id":1,"method":"initialize",'
                '"params":{"protocolVersion":"2024-11-05","capabilities":{},'
                '"clientInfo":{"name":"toolbox","version":"1.0"}}}\n'
            )
            cp.stdin.flush()
            line = cp.stdout.readline().strip()
        except Exception as e:
            cp.terminate()
            return False, f"握手失败:{e}"

        if not line:
            err_tail = ""
            try:
                if cp.stderr is not None:
                    err_tail = (cp.stderr.read() or "").strip()
            except Exception:
                pass
            cp.terminate()
            return False, f"server 无响应{(':' + err_tail) if err_tail else ''}"
        if '"result"' not in line or '"serverInfo"' not in line:
            cp.terminate()
            return False, "initialize 响应不合法"

        _process = cp
        return True, "已开启"


def stop_lark_mcp() -> tuple[bool, str]:
    global _process
    with _lock:
        if _process is None or _process.poll() is not None:
            _process = None
            return True, "已停止"
        try:
            _process.terminate()
            _process.wait(timeout=5)
        except Exception as e:
            _process = None
            return False, f"关闭异常:{e}"
        _process = None
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

    npx_path = find_npx()
    if npx_path is None:
        return False, "未找到 Node.js 运行时(请到 Lark MCP 卡里点\"下载内置 Node 运行时\")"
    npx = str(npx_path)

    domain = (s.domain or DEFAULT_DOMAIN).strip()
    port = int(s.oauth_port or DEFAULT_OAUTH_PORT)
    scope = (s.scope or DEFAULT_SCOPE).strip()

    argv = [
        npx, "-y", "@larksuiteoapi/lark-mcp", "login",
        "-a", app_id,
        "-s", secret,
        "-d", domain,
        "-p", str(port),
        "--scope", scope,
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
