from __future__ import annotations


def help_keyboard(*, tasks: list[tuple[str, str]], show_rollback: bool, show_stop: bool, show_status: bool) -> dict:
    """Build inline keyboard for /help.

    tasks: [(task_id, label)]
    """
    kb: list[list[dict]] = []

    # tasks section header
    kb.append([
        {"text": "🔹 任务 🔹", "callback_data": "help_noop"},
    ])

    for tid, label in tasks:
        kb.append([
            {"text": label, "callback_data": f"help_run:{tid}"},
        ])

    # system section header
    kb.append([
        {"text": "🔸 系统操作 🔸", "callback_data": "help_noop"},
    ])

    sys_row: list[dict] = []
    if show_rollback:
        sys_row.append({"text": "回退", "callback_data": "help_sys:rollback"})
    if show_status:
        sys_row.append({"text": "状态", "callback_data": "help_sys:status"})
    if show_stop:
        sys_row.append({"text": "停止", "callback_data": "help_sys:stop"})

    if sys_row:
        # keep in one row (max 3)
        kb.append(sys_row)

    return {"inline_keyboard": kb}
