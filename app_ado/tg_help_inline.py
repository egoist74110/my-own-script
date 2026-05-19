from __future__ import annotations


def top_menu(*, show_dev: bool = False) -> dict:
    rows: list[list[dict]] = [
        [{"text": "🔹 任务", "callback_data": "help_menu:tasks"}],
        [{"text": "🔸 系统操作", "callback_data": "help_menu:sys"}],
    ]
    if show_dev:
        rows.append([{"text": "🛠 AI开发", "callback_data": "help_menu:dev"}])
    return {"inline_keyboard": rows}


def tasks_menu(tasks: list[tuple[str, str]]) -> dict:
    kb: list[list[dict]] = []
    for tid, label in tasks:
        kb.append([{"text": label, "callback_data": f"help_run:{tid}"}])
    kb.append([{"text": "⬅ 返回", "callback_data": "help_menu:back"}])
    return {"inline_keyboard": kb}


def sys_menu(*, show_rollback: bool, show_stop: bool, show_status: bool) -> dict:
    kb: list[list[dict]] = []

    row: list[dict] = []
    if show_rollback:
        row.append({"text": "回退", "callback_data": "help_sys:rollback"})
    if show_status:
        row.append({"text": "状态", "callback_data": "help_sys:status"})
    if show_stop:
        row.append({"text": "停止", "callback_data": "help_sys:stop"})
    if row:
        kb.append(row)

    kb.append([{"text": "⬅ 返回", "callback_data": "help_menu:back"}])
    return {"inline_keyboard": kb}
