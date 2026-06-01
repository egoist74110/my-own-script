"""Figma MCP server 子进程的全局单例管理(对齐 app_lark.mcp_server_manager,无 OAuth)。

PyQt UI(MCP 配置 Tab)和 TG 的 MCP 菜单共用同一份进程引用 + 状态。
"""

from __future__ import annotations

import subprocess
import threading
from typing import Optional

from app_figma.figma_mcp_flow import (
    figma_mcp_python,
    figma_mcp_server_script,
    tool_workspace_root,
)
from app_figma.secrets import is_figma_configured
from app_lark.node_bootstrap import augmented_search_path


_lock = threading.Lock()
_process: Optional[subprocess.Popen[str]] = None


def _augmented_env() -> dict[str, str]:
    """子进程跑 npx 时 env 里必须能找到 node，否则会报 `env: node: No such file or directory`。"""
    import os as _os
    env = _os.environ.copy()
    env["PATH"] = augmented_search_path()
    return env


def is_figma_mcp_running() -> bool:
    with _lock:
        return _process is not None and _process.poll() is None


def start_figma_mcp() -> tuple[bool, str]:
    """启动 server 子进程并做 initialize 握手。已运行则直接返回成功。"""
    global _process
    with _lock:
        if _process is not None and _process.poll() is None:
            return True, "已在运行"
        if not is_figma_configured():
            return False, "未配置 Figma API Token"
        try:
            cp = subprocess.Popen(
                [figma_mcp_python(), figma_mcp_server_script()],
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


def stop_figma_mcp() -> tuple[bool, str]:
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
