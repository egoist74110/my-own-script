from __future__ import annotations


def top_menu(
    *,
    show_dev: bool = False,
    show_wi: bool = False,
    show_svc: bool = False,
    show_mcp: bool = False,
) -> dict:
    rows: list[list[dict]] = [
        [{"text": "🔹 任务", "callback_data": "help_menu:tasks"}],
        [{"text": "🔸 系统操作", "callback_data": "help_menu:sys"}],
    ]
    if show_svc:
        rows.append([{"text": "🧰 服务", "callback_data": "help_menu:svc"}])
    if show_dev:
        rows.append([{"text": "🤖 Claude 会话", "callback_data": "help_menu:dev"}])
    if show_wi:
        rows.append([{"text": "📋 工单", "callback_data": "help_menu:wi"}])
    if show_mcp:
        rows.append([{"text": "⚙️ MCP 配置", "callback_data": "help_menu:mcp"}])
    return {"inline_keyboard": rows}


def mcp_menu(
    *,
    ado_running: bool,
    lark_running: bool,
    lark_logged_in: bool,
    figma_running: bool,
    figma_configured: bool,
) -> dict:
    """MCP 配置主菜单:列各 MCP 的状态,点击 toggle。"""
    ado_text = "🟢 工单 MCP 已开(点击关闭)" if ado_running else "⚪ 工单 MCP 已关(点击开启)"
    if lark_running:
        lark_text = "🟢 Lark MCP 已开(点击关闭)"
    elif not lark_logged_in:
        lark_text = "🔒 Lark MCP 未登录(请到桌面端配置)"
    else:
        lark_text = "⚪ Lark MCP 已关(点击开启)"
    if figma_running:
        figma_text = "🟢 Figma MCP 已开(点击关闭)"
    elif not figma_configured:
        figma_text = "🔒 Figma MCP 未配置(请到桌面端配置)"
    else:
        figma_text = "⚪ Figma MCP 已关(点击开启)"
    rows = [
        [{"text": ado_text, "callback_data": "mcp:ado:tg"}],
        [{"text": lark_text, "callback_data": "mcp:lark:tg"}],
    ]
    if lark_logged_in:
        rows.append([{"text": "🔑 注入 Lark 登录态到各工具(免再授权)", "callback_data": "mcp:larkinject:tg"}])
    rows.append([{"text": figma_text, "callback_data": "mcp:figma:tg"}])
    rows.append([{"text": "⬅ 返回", "callback_data": "help_menu:back"}])
    return {"inline_keyboard": rows}


def services_menu() -> dict:
    """服务面板二级菜单。"""
    return {"inline_keyboard": [
        [{"text": "🌐 VPN", "callback_data": "svc:vpn"}],
        [{"text": "💻 code-server", "callback_data": "svc:cs"}],
        [{"text": "☁️ cloudflared 隧道", "callback_data": "svc:cf"}],
        [{"text": "📱 CC Pocket", "callback_data": "svc:cp"}],
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


def ccpocket_actions_menu() -> dict:
    """CC Pocket 操作菜单：比通用菜单多一个「获取二维码」。"""
    return {"inline_keyboard": [
        [{"text": "▶️ 启动", "callback_data": "svc:cp:start"},
         {"text": "⏹ 关闭", "callback_data": "svc:cp:stop"}],
        [{"text": "📱 获取二维码", "callback_data": "svc:cp:qr"}],
        [{"text": "🔄 刷新状态", "callback_data": "svc:cp"}],
        [{"text": "⬅ 返回", "callback_data": "help_menu:svc"}],
    ]}


def service_back_menu() -> dict:
    """只读服务（如 VPN）用的返回按钮。"""
    return {"inline_keyboard": [[{"text": "⬅ 返回", "callback_data": "help_menu:svc"}]]}


def vpn_actions_menu() -> dict:
    """VPN 操作菜单：连接（自动登录）/ 刷新状态。"""
    return {"inline_keyboard": [
        [{"text": "🔌 连接（自动登录）", "callback_data": "svc:vpn:on"}],
        [{"text": "🔄 刷新状态", "callback_data": "svc:vpn"}],
        [{"text": "⬅ 返回", "callback_data": "help_menu:svc"}],
    ]}


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
