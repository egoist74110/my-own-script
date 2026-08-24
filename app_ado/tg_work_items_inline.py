"""工单模块在 TG 上的 inline 菜单。

入口：用户点顶部菜单的"📋 工单" → 走 `wi_main_menu`。
"""

from __future__ import annotations

from typing import Iterable


BOARD_COLUMNS: list[str] = ["新建", "待开发", "开发中", "测试", "已关闭"]


def wi_main_menu(*, project_label: str, column_label: str) -> dict:
    rows: list[list[dict]] = [
        [{"text": f"📁 项目：{project_label}", "callback_data": "wi_pp"}],
        [{"text": f"📊 版块：{column_label}", "callback_data": "wi_pc"}],
        [
            {"text": "📋 列工单", "callback_data": "wi_l:1"},
            {"text": "🔄 刷新", "callback_data": "wi_rl"},
        ],
        [{"text": "⬅ 返回", "callback_data": "help_menu:back"}],
    ]
    return {"inline_keyboard": rows}


def wi_pick_project_menu(projects: Iterable[tuple[str, str]], current_id: str) -> dict:
    """projects 每条：(project_id, project_name)。"""
    kb: list[list[dict]] = []
    for pid, name in projects:
        mark = "★ " if pid == current_id else "  "
        kb.append([{"text": f"{mark}{name}", "callback_data": f"wi_psp:{pid}"}])
    kb.append([{"text": "⬅ 返回", "callback_data": "wi_main"}])
    return {"inline_keyboard": kb}


def wi_pick_column_menu(current_idx: int) -> dict:
    kb: list[list[dict]] = []
    for idx, name in enumerate(BOARD_COLUMNS):
        mark = "★ " if idx == current_idx else "  "
        kb.append([{"text": f"{mark}{name}", "callback_data": f"wi_psc:{idx}"}])
    kb.append([{"text": "⬅ 返回", "callback_data": "wi_main"}])
    return {"inline_keyboard": kb}


def wi_list_menu(
    items: Iterable[tuple[int, str, str]],
    *,
    page: int,
    total_pages: int,
) -> dict:
    """items 每条：(work_item_id, short_label, state)。"""
    kb: list[list[dict]] = []
    for wid, label, state in items:
        text = f"#{wid} {label}" + (f" [{state}]" if state else "")
        if len(text) > 60:
            text = text[:57] + "…"
        kb.append([{"text": text, "callback_data": f"wi_o:{wid}"}])

    nav: list[dict] = []
    if page > 1:
        nav.append({"text": "⬅ 上一页", "callback_data": f"wi_l:{page - 1}"})
    nav.append({"text": f"{page}/{total_pages}", "callback_data": "wi_noop"})
    if page < total_pages:
        nav.append({"text": "下一页 ➡", "callback_data": f"wi_l:{page + 1}"})
    if nav:
        kb.append(nav)

    kb.append([{"text": "⬅ 返回主菜单", "callback_data": "wi_main"}])
    return {"inline_keyboard": kb}


def wi_detail_menu(work_item_id: int, *, has_children: bool) -> dict:
    kb: list[list[dict]] = [
        [
            {"text": "👁 查看", "callback_data": f"wi_v:{work_item_id}"},
            {"text": "🔍 MCP分析", "callback_data": f"wi_m:{work_item_id}"},
            {"text": "📋 复制提示词", "callback_data": f"wi_cp:{work_item_id}"},
        ],
    ]
    if has_children:
        kb.append([{"text": "🔗 关联子单", "callback_data": f"wi_r:{work_item_id}"}])
    kb.append([{"text": "⬅ 返回列表", "callback_data": "wi_l:0"}])
    return {"inline_keyboard": kb}


def wi_pick_repo_menu(
    work_item_id: int,
    repos: Iterable[tuple[int, str, str]],
) -> dict:
    """repos 每条：(idx, repo_name, repo_path_short)。"""
    kb: list[list[dict]] = []
    for idx, name, path in repos:
        label = f"📁 {name}"
        if path:
            label += f" ({path})"
        if len(label) > 56:
            label = label[:55] + "…"
        kb.append([{"text": label, "callback_data": f"wi_mr:{work_item_id}:{idx}"}])
    kb.append([{"text": "⬅ 返回详情", "callback_data": f"wi_o:{work_item_id}"}])
    return {"inline_keyboard": kb}


def wi_pick_ai_menu(
    work_item_id: int,
    repo_idx: int,
    ais: Iterable[tuple[int, str, bool]],
) -> dict:
    """ais 每条：(ai_idx, label, supported)。supported=False 的项也会显示但点了会回错。"""
    kb: list[list[dict]] = []
    for ai_idx, label, supported in ais:
        prefix = "🤖" if supported else "🚫"
        text = f"{prefix} {label}"
        if len(text) > 56:
            text = text[:55] + "…"
        kb.append([{"text": text, "callback_data": f"wi_ma:{work_item_id}:{repo_idx}:{ai_idx}"}])
    kb.append([{"text": "⬅ 返回选仓库", "callback_data": f"wi_m:{work_item_id}"}])
    return {"inline_keyboard": kb}


def wi_related_menu(parent_id: int, children: Iterable[tuple[int, str, str]]) -> dict:
    """children 每条：(work_item_id, short_label, state)。"""
    kb: list[list[dict]] = []
    for wid, label, state in children:
        text = f"#{wid} {label}" + (f" [{state}]" if state else "")
        if len(text) > 60:
            text = text[:57] + "…"
        kb.append([{"text": text, "callback_data": f"wi_o:{wid}"}])
    kb.append([{"text": "⬅ 返回详情", "callback_data": f"wi_o:{parent_id}"}])
    return {"inline_keyboard": kb}
