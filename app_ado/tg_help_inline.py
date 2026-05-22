from __future__ import annotations


def top_menu(*, show_dev: bool = False, show_wi: bool = False, show_svc: bool = False) -> dict:
    rows: list[list[dict]] = [
        [{"text": "🔹 任务", "callback_data": "help_menu:tasks"}],
        [{"text": "🔸 系统操作", "callback_data": "help_menu:sys"}],
    ]
    if show_svc:
        rows.append([{"text": "🧰 服务", "callback_data": "help_menu:svc"}])
    if show_dev:
        rows.append([{"text": "🛠 AI开发", "callback_data": "help_menu:dev"}])
    if show_wi:
        rows.append([{"text": "📋 工单", "callback_data": "help_menu:wi"}])
    return {"inline_keyboard": rows}


def services_menu() -> dict:
    """服务面板二级菜单。"""
    return {"inline_keyboard": [
        [{"text": "🌐 VPN 地址", "callback_data": "svc:vpn"}],
        [{"text": "💻 code-server", "callback_data": "svc:cs"}],
        [{"text": "☁️ cloudflared 隧道", "callback_data": "svc:cf"}],
        [{"text": "⬅ 返回", "callback_data": "help_menu:back"}],
    ]}


def service_actions_menu(key: str) -> dict:
    """单个服务的启停/刷新菜单。key 取 'cs' 或 'cf'。"""
    return {"inline_keyboard": [
        [{"text": "▶️ 启动", "callback_data": f"svc:{key}:start"},
         {"text": "⏹ 关闭", "callback_data": f"svc:{key}:stop"}],
        [{"text": "🔄 刷新状态", "callback_data": f"svc:{key}"}],
        [{"text": "⬅ 返回", "callback_data": "help_menu:svc"}],
    ]}


def service_back_menu() -> dict:
    """只读服务（如 VPN）用的返回按钮。"""
    return {"inline_keyboard": [[{"text": "⬅ 返回", "callback_data": "help_menu:svc"}]]}


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
