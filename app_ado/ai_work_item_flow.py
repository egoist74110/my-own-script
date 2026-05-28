from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from app_ado.models import ProjectEntry


# ----------------------------------------------------------------------------
# 工单 MCP 分析提示词（点 MCP分析按钮时灌给 claude）
# ----------------------------------------------------------------------------

def build_mcp_prompt(*, project: ProjectEntry, work_item_id: int) -> str:
    """生成工单 MCP 分析提示词。

    调用方在外面已经选好仓库并 cd 进去，所以不需要再让 AI 自己确认仓库。
    """
    lines = [
        f"请通过 ADO MCP 分析工单 #{work_item_id}（项目 {project.project}）。",
        "",
        "可用工具（MCP 注册名，必须用完整前缀）：",
        "- `mcp__ado-work-items__ado_get_work_item`",
        "- `mcp__ado-work-items__ado_get_work_item_comments`",
        "- `mcp__ado-work-items__ado_evaluate_change_policy`",
        "- `mcp__ado-work-items__ado_get_attachment`（按需取附件/截图）",
        "若工具被标记为 deferred，先用 `ToolSearch` 以 `select:<完整工具名,...>` 加载 schema 再调用。",
        "不显式传 library_id / project_id 时，server 自动用本地 UI 的 active_library_id / active_project_id。",
        "",
        "执行顺序：",
        f"1. `mcp__ado-work-items__ado_get_work_item` 读详情 #{work_item_id}。",
        "2. `mcp__ado-work-items__ado_get_work_item_comments` 读评论 / updates。",
        "3. `mcp__ado-work-items__ado_evaluate_change_policy` 评估策略。",
        "4. 基于内容 + 评论 + 图片 + 策略给结论。",
        "",
        "输出要求：",
        "- 先给结论。",
        "- 再给依据。",
        "- 如果需要改代码，先说明会改哪些文件。",
        "- 不要编造未确认的信息。",
    ]
    return "\n".join(lines).strip()


# ----------------------------------------------------------------------------
# MCP server 启动命令 / 各家 CLI 接入片段（被 mcp_config_tab 和 mcp_server_manager 用）
# ----------------------------------------------------------------------------

def tool_workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


def is_frozen_build() -> bool:
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def ado_work_items_mcp_python() -> str:
    venv_python = tool_workspace_root() / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python"


def ado_work_items_mcp_server_script() -> str:
    return str(tool_workspace_root() / "app_ado" / "mcp_ado_work_items_server.py")


def ado_work_items_mcp_launch_command() -> str:
    return f"{ado_work_items_mcp_python()} {shlex.quote(ado_work_items_mcp_server_script())}"


def ado_work_items_mcp_claude_cli_command() -> str:
    py = ado_work_items_mcp_python()
    script = ado_work_items_mcp_server_script()
    return f"claude mcp add ado-work-items --scope user -- {shlex.quote(py)} {shlex.quote(script)}"


def ado_work_items_mcp_codex_toml() -> str:
    py = ado_work_items_mcp_python()
    script = ado_work_items_mcp_server_script()
    return (
        "[mcp_servers.adoWorkItems]\n"
        f'command = "{py}"\n'
        f'args = ["{script}"]\n'
    )


def ado_work_items_mcp_gemini_json_fragment() -> str:
    py = ado_work_items_mcp_python()
    script = ado_work_items_mcp_server_script()
    payload = {"ado-work-items": {"command": py, "args": [script]}}
    return json.dumps(payload, ensure_ascii=False, indent=2)
