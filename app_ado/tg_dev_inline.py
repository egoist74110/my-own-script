"""AI 开发模块在 TG 上的 inline 菜单。

入口：用户点顶部菜单的"🛠 AI开发" → 走 `dev_main_menu`。
"""

from __future__ import annotations

from typing import Iterable


_MODEL_BUTTONS: list[tuple[str, str]] = [
    ("gemini", "Gemini"),
    ("claude_code", "Claude Code"),
    ("codex", "Codex"),
]


def dev_main_menu(sessions: Iterable[tuple[str, str, str, str, bool]]) -> dict:
    """AI 开发主菜单：列现有会话 + 三个新建按钮。

    sessions 每条：(sid, model_label, repo_name, status_zh, is_focused)
    """
    kb: list[list[dict]] = []
    # 现有会话：每条一行 "  焦点★/-  #sid model repo 状态"，附 🗑 按钮
    for sid, model_label, repo_name, status_zh, is_focused in sessions:
        mark = "★" if is_focused else " "
        label = f"{mark} #{sid} · {model_label} · {repo_name} [{status_zh}]"
        kb.append([
            {"text": label, "callback_data": f"dev_focus:{sid}"},
            {"text": "🗑", "callback_data": f"dev_kill:{sid}"},
        ])

    # 新建按钮（三个一行）
    new_row: list[dict] = []
    for model_id, label in _MODEL_BUTTONS:
        new_row.append({"text": f"+ {label}", "callback_data": f"dev_new_pick_repo:{model_id}"})
    kb.append(new_row)

    kb.append([{"text": "⬅ 返回", "callback_data": "help_menu:back"}])
    return {"inline_keyboard": kb}


def dev_pick_repo_menu(model_id: str, repos: Iterable[tuple[str, str]]) -> dict:
    """选仓库菜单。repos 每条：(repo_id, repo_name)。"""
    kb: list[list[dict]] = []
    for repo_id, repo_name in repos:
        kb.append([
            {"text": repo_name, "callback_data": f"dev_do_new:{model_id}:{repo_id}"},
        ])
    kb.append([{"text": "⬅ 返回", "callback_data": "help_menu:dev"}])
    return {"inline_keyboard": kb}
