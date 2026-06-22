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
        [{"text": "⬅ 返回", "callback_data": "help_menu:back"}],
    ]}


def service_actions_menu(
    key: str,
    *,
    cf_protocol: str | None = None,
    cf_customs: list[dict] | None = None,
) -> dict:
    """单个服务的启停/刷新菜单。key 取 'cs' 或 'cf'。

    cf 专属：
      - 一行协议切换（HTTP/2 ↔ QUIC）；cf_protocol 传入当前生效协议以打 ✅。
      - 「全局启停」是上面那行（其他模块依赖的那条隧道）。
      - 「➕ 指定启动」+ 每条自定义隧道一行「⏹ 关闭」；cf_customs 传 cloudflared_custom_list()，
        关闭回调按列表下标 svc:cf:cstop:<i>（URL 含特殊字符且 callback_data 限 64B，不直接塞 URL）。
    """
    rows = [
        [{"text": "▶️ 启动", "callback_data": f"svc:{key}:start"},
         {"text": "⏹ 关闭", "callback_data": f"svc:{key}:stop"}],
    ]
    if key == "cf":
        h2 = ("✅ " if cf_protocol == "http2" else "") + "HTTP/2 (稳)"
        qc = ("✅ " if cf_protocol == "quic" else "") + "QUIC (快)"
        rows.append([
            {"text": h2, "callback_data": "svc:cf:proto:http2"},
            {"text": qc, "callback_data": "svc:cf:proto:quic"},
        ])
        rows.append([{"text": "➕ 指定启动（自定义 URL）", "callback_data": "svc:cf:custom"}])
        for i, c in enumerate(cf_customs or []):
            url = c.get("url", "")
            short = url.split("://", 1)[-1]  # 去掉 scheme，更短
            dom = c.get("domain")
            label = f"⏹ {short}" + (f" → {dom.split('://',1)[-1]}" if dom else "")
            rows.append([{"text": label[:60], "callback_data": f"svc:cf:cstop:{i}"}])
    rows.append([{"text": "🔄 刷新状态", "callback_data": f"svc:{key}"}])
    rows.append([{"text": "⬅ 返回", "callback_data": "help_menu:svc"}])
    return {"inline_keyboard": rows}


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
