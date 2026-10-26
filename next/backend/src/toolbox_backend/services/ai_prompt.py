"""Work-item analysis prompt (rewritten from the old ai_work_item_flow.build_mcp_prompt).

Never embeds work-item content: only an integer id and the configured library/project names.
The MCP server (old registration, S6 replaces it) reads the item itself.
"""

import re

CLAUDE_PREFIX = "mcp__ado-work-items__"
TOOLS = (
    ("ado_get_work_item", "读详情"),
    ("ado_get_work_item_comments", "读评论 / updates"),
    ("ado_evaluate_change_policy", "评估策略"),
    ("ado_get_attachment", "按需取附件/截图"),
)
NEW_ONLY_WARNING = "此项目是新端独有的配置，旧 MCP 可能无法解析此项目"


def one_line(value, limit=128) -> str:
    """Names come from user config: no control characters, backticks or newlines in a prompt."""
    text = re.sub(r"[\x00-\x1f\x7f`]", " ", str(value))
    return " ".join(text.split())[:limit]


def tool_prefix(cli, configured, source="legacy") -> str:
    if source == "toolbox":
        return "mcp__toolbox_ado__"
    return CLAUDE_PREFIX if cli == "claude" else configured


def is_new_only(project_id) -> bool:
    """Projects created through the new settings API use the proj:<uuid> id form."""
    return isinstance(project_id, str) and project_id.startswith("proj:")


def build_prompt(
    *, cli, work_item_id, library_name, project_name, prefix, new_only=False, source="legacy"
) -> str:
    ident = int(work_item_id)
    library, project = one_line(library_name), one_line(project_name)
    names = [f"`{prefix}{tool}`" for tool, _ in TOOLS]
    lines = [
        f"请通过 ADO MCP 分析工单 #{ident}。",
        "",
        "目标（每次调用工具都显式传入，不要依赖本地界面的当前库/项目设置）：",
        f"- library 名称：{library}（参数 library_name）",
        f"- project 名称：{project}（参数 project_name）",
    ]
    if new_only and source != "toolbox":
        lines += ["", f"警示：{NEW_ONLY_WARNING}；若工具报找不到项目，请直接说明，不要猜测。"]
    lines += ["", "可用工具（MCP 注册名，必须用完整前缀）："]
    lines += [f"- {name}" for name in names]
    if cli == "claude":
        lines.append(
            "若工具被标记为 deferred，先用 `ToolSearch` 以 "
            "`select:<完整工具名,...>` 加载 schema 再调用。"
        )
    lines += ["", "执行顺序："]
    for number, (tool, label) in enumerate(TOOLS[:3], 1):
        target = f" #{ident}" if tool == "ado_get_work_item" else ""
        lines.append(f"{number}. {names[number - 1]} {label}{target}。")
    lines += [
        "4. 基于内容 + 评论 + 图片 + 策略给结论。",
        "",
        "输出要求：",
        "- 先给结论。",
        "- 再给依据。",
        "- 如果需要改代码，先说明会改哪些文件。",
        "- 不要编造未确认的信息。",
    ]
    return "\n".join(lines)
