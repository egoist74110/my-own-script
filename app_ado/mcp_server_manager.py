"""ADO 工单 MCP server 子进程的全局单例管理。

PyQt UI（MCP 配置 Tab）和 TG 工单菜单共用同一份进程引用 + 状态，
避免两边各自 fork 出多个 server。
"""

from __future__ import annotations

import subprocess
import threading
from typing import Optional

from app_ado.ai_work_item_flow import (
    ado_work_items_mcp_python,
    ado_work_items_mcp_server_script,
    tool_workspace_root,
)


_lock = threading.Lock()
_process: Optional[subprocess.Popen[str]] = None


def is_ado_work_items_mcp_running() -> bool:
    with _lock:
        return _process is not None and _process.poll() is None


def start_ado_work_items_mcp() -> tuple[bool, str]:
    """启动 server 子进程并做 initialize 握手。已运行则直接返回成功。"""
    global _process
    with _lock:
        if _process is not None and _process.poll() is None:
            return True, "已在运行"
        try:
            cp = subprocess.Popen(
                [ado_work_items_mcp_python(), ado_work_items_mcp_server_script()],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(tool_workspace_root()),
            )
        except Exception as e:
            return False, f"进程启动失败：{e}"

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
            return False, f"握手失败：{e}"

        if not line:
            cp.terminate()
            return False, "server 无响应"
        if '"result"' not in line or '"serverInfo"' not in line:
            cp.terminate()
            return False, "initialize 响应不合法"

        _process = cp
        return True, "已开启"


def stop_ado_work_items_mcp() -> tuple[bool, str]:
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
            return False, f"关闭异常：{e}"
        _process = None
        return True, "已关闭"
