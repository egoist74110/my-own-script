"""Telegram commands: trusted server actions, live ACL and the existing S3 executor."""

import re
import uuid
from datetime import UTC, datetime

from toolbox_backend.api.mcp_schemas import LarkActionRequest
from toolbox_backend.api.task_schemas import PreflightRequest, StartRequest
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import task_label
from toolbox_backend.domain.telegram import acl_validity, numeric
from toolbox_backend.services.telegram_menu import TelegramMenu

TG_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "toolbox-next:telegram")
LARK_STATE_LABELS = {
    "stopped": "已停止",
    "starting": "启动中",
    "running": "运行中",
    "running_degraded": "降级运行",
    "unhealthy": "不健康",
    "stopping": "停止中",
    "logging_in": "登录中",
    "failed": "失败",
}
ERRORS = {
    "tunnel_limit": "自定义隧道数量已达上限",
    "tunnel_target_forbidden": "隧道仅允许已确认的本机回环地址",
    "service_unsafe_config": "无法确认 code-server 密码认证安全，请在桌面端检查",
    "service_binary_missing": "服务程序不可用，请在桌面端配置",
    "service_port_in_use": "服务端口已被外部进程占用",
    "service_busy": "服务正在执行其他操作，请稍后重试",
    "task_active": "任务已有活动运行",
    "resource_active": "发布资源正被其他运行占用",
    "busy": "忙，请稍后重试",
    "no_credential": "尚未配置所需凭据",
    "unsupported_task": "该任务配置暂不支持执行",
    "run_store_unavailable": "运行数据库不可用",
    "telegram_store_unavailable": "Telegram 数据库不可用",
    "store_unavailable": "配置数据库不可用",
    "plan_expired": "计划已过期，请重新预检",
    "plan_changed": "任务或来源已变化，请重新预检",
    "idempotency_conflict": "请求标识冲突，请查看运行状态",
    "not_found": "任务或运行已不存在",
    "revision_conflict": "配置已变化，请重新操作",
    "validation_error": "任务不可执行或权限已变化",
    "unsafe_repository": "仓库未通过安全检查",
    "ado_request_failed": "远端请求失败，请稍后重试",
    "lark_owner_unconfirmed": "请先在桌面端确认飞书 MCP 所有权",
    "lark_not_configured": "请先配置飞书 MCP App ID 与 App Secret",
    "mcp_runtime_missing": "缺少 Node.js 或 MCP 运行组件，请先在桌面端安装",
    "mcp_port_in_use": "飞书 MCP 端口已被占用",
    "mcp_busy": "飞书 MCP 正在执行其他操作，请稍后重试",
}


def identities(update):
    from toolbox_backend.services.telegram import identities as identity

    return identity(update)


class TelegramDispatcher(TelegramMenu):
    def __init__(self, service, work_items):
        from toolbox_backend.services.telegram_work_items import TelegramWorkItems

        self.service = service
        self._service_inputs = {}
        self.work_items = TelegramWorkItems(self, work_items)

    def close(self):
        self._service_inputs.clear()
        self.work_items.close()

    @staticmethod
    def role(config, update):
        _, _, chat, user, un, private = identities(update)
        if not numeric(chat) or not numeric(user):
            return "none", None
        tg = config.telegram
        if private and chat == tg.owner.chat_id:
            return "owner", None
        if not tg.owner.chat_id:
            return "none", None
        groups, members, _ = acl_validity(config)
        by_id = {g.id: g for g in groups}
        for m in members:
            if m.chat_id == chat:
                return "group", by_id[m.group_id]
        if private:
            for m in members:
                if m.username and (
                    m.user_id == user
                    if m.user_id is not None
                    else un is not None and m.username.lower() == un
                ):
                    return "group", by_id[m.group_id]
        return "none", None

    @classmethod
    def allowed(cls, config, update, operation, task_id=None, run=None):
        role, group = cls.role(config, update)
        if role == "owner":
            return True
        if group is None:
            return False
        if operation == "stop":
            _, _, chat, _, _, _ = identities(update)
            origin = (run or {}).get("origin", {})
            return (
                group.can_stop
                and (run or {}).get("task_id") in group.task_ids
                and origin.get("kind") == "telegram"
                and origin.get("chat_id") == chat
            )
        if operation == "status":
            return group.can_status and task_id in group.task_ids
        permission = group.can_rollback if operation == "rollback" else group.can_run
        return permission and task_id in group.task_ids

    async def button(self, update, label, kind, payload, *, ttl=300):
        self.service.ensure_attached()
        _, _, chat, user, _, _ = identities(update)
        token = await self.service.store.action(self.service.bot_id, chat, user, kind, payload, ttl)
        return {"text": label, "callback_data": token}

    async def panel(self, update, text, buttons=None):
        rows = list(buttons or [])
        if not any(b["text"] == "⬅️ 返回" for row in rows for b in row):
            rows += await self.fallback_navigation(update)
        await self.service.reply(update, text, reply_markup={"inline_keyboard": rows}, panel=True)

    def task_checked(self, config, update, tid, operation, *, any_mode=False):
        task = next((t for t in config.tasks.items if t.id == tid), None)
        if task is None:
            raise SettingsError("not_found", "固定错误", 404)
        permitted = self.allowed(config, update, operation, tid)
        if any_mode:
            permitted = permitted or self.visible(config, update, tid)
        if not task.enabled or not permitted:
            raise SettingsError("validation_error", "固定错误", 422)
        return task

    async def preflight(self, update, payload):
        tid, op = payload["task_id"], payload["operation"]
        if op not in {"sync_build_release", "deploy_only", "rollback"}:
            return "ignored"
        config = await self.service.config_store.read()
        task = self.task_checked(config, update, tid, op)
        offset = payload.get("offset") if op == "rollback" else None
        if op == "rollback" and (type(offset) is not int or not 1 <= offset <= 5):
            return "ignored"
        plan = await self.service.runs.preflight(
            tid, PreflightRequest(revision=config.revision, operation=op, rollback_offset=offset)
        )
        self.service.ensure_attached()
        current = await self.service.config_store.read()
        self.task_checked(current, update, tid, op)
        operation_name = {
            "sync_build_release": "构建并发布",
            "deploy_only": "只发布",
            "rollback": "回滚",
        }[op]
        text = [
            f"任务：{task_label(config, task.id)}",
            f"操作：{operation_name}",
            f"仓库：{self.command_config(config, tid)[0].name}",
            f"分支：{task.git_flow.build_branch or '未提供'}",
        ]
        if op == "rollback":
            text.append(f"历史偏移：{offset}")
        for target in plan["targets"]:
            text.extend(
                [
                    f"目标：{target['name']}",
                    "环境："
                    + (
                        "、".join(
                            name
                            for t in task.targets
                            if t.name == target["name"]
                            for name in t.release_stage_names
                        )
                        or "未提供名称"
                    ),
                ]
            )
            if op in {"deploy_only", "rollback"}:
                text.append(
                    f"精确制品：Build #{target.get('build_id')} · "
                    f"commit {target.get('commit') or '未提供'}"
                )
            if op == "rollback":
                text.append(
                    f"Release #{target.get('release_id')} · "
                    f"创建于 {target.get('created_at') or '未提供'}"
                )
        if op == "rollback":
            text.extend(await self.rollback_details(str(plan["plan_id"])))
        text.extend("警告：" + str(w) for w in plan["warnings"])
        text.append("请确认执行；停止不会撤回已部署内容")
        ttl = max(
            0,
            min(
                300,
                (datetime.fromisoformat(plan["expires_at"]) - datetime.now(UTC)).total_seconds(),
            ),
        )
        kind = {
            "sync_build_release": "run_confirm",
            "deploy_only": "deploy_confirm",
            "rollback": "rollback_confirm",
        }[op]
        confirm = await self.button(
            update,
            "✅ 确认执行",
            kind,
            {
                "task_id": tid,
                "operation": op,
                "offset": offset,
                "plan_id": str(plan["plan_id"]),
                "context": payload.get("context", {}),
            },
            ttl=ttl,
        )
        cancel = await self.button(
            update,
            "✖️ 取消",
            "menu",
            {
                "page": "cancel",
                "task_id": tid,
                "confirm_token": confirm["callback_data"],
                "context": payload.get("context", {}),
            },
        )
        back = {
            "page": "cancel",
            "task_id": tid,
            "confirm_token": confirm["callback_data"],
            "context": payload.get("context", {}),
        }
        await self.panel(
            update, "\n".join(text), [[confirm, cancel]] + await self.navigation(update, back)
        )
        return "handled"

    async def rollback_details(self, plan_id):
        """Display-only reads of the already frozen release IDs; no public DTO change."""
        plan = self.service.runs.plans.get(plan_id)
        executor = self.service.runs.executor
        if plan is None or not hasattr(executor, "request"):
            return []
        snapshot = plan["snapshot"]
        text = []
        for target in snapshot.get("prepared", {}).get("targets", []):
            rid = target.get("release_id")
            if type(rid) is not int:
                continue
            try:
                data = await executor.request(
                    snapshot, ["release", "releases", rid], version=target["api_version"]
                )
                if data.get("id") != rid:
                    raise SettingsError("plan_changed", "固定错误")
                name = data.get("name") if isinstance(data.get("name"), str) else "名称未提供"
                envs = data.get("environments", [])
                selected = [
                    e
                    for e in envs
                    if isinstance(e, dict) and e.get("id") in target.get("environment_ids", [])
                ]
                results = [
                    e.get("status") if isinstance(e.get("status"), str) else "未提供"
                    for e in selected
                ]
                text.append(f"Release：{name} · 当前结果：{'、'.join(results) or '未提供'}")
            except SettingsError:
                raise
            except Exception:
                raise SettingsError("ado_request_failed", "固定错误", 502) from None
        return text

    async def expired(self, update, action):
        await self.panel(
            update,
            "菜单已过期，请重新 /start",
            [[await self.button(update, "🏠 主菜单", "menu", {"page": "main"})]],
        )
        return "expired"

    async def replan(self, update, payload):
        config = await self.service.config_store.read()
        self.task_checked(config, update, payload["task_id"], payload["operation"])
        button = await self.button(
            update,
            "🔄 重新预检",
            "menu",
            {
                "page": "preflight",
                "task_id": payload["task_id"],
                "operation": payload["operation"],
                "offset": payload.get("offset"),
                "context": payload.get("context", {}),
            },
        )
        rows = [[button]] + await self.navigation(
            update,
            {
                "page": "task",
                "task_id": payload["task_id"],
                "context": payload.get("context", {}),
            },
        )
        await self.panel(update, "计划已过期，请重新预检", rows)
        return "expired"

    async def confirm(self, update, token, action):
        payload = action["payload"]
        config = await self.service.config_store.read()
        self.task_checked(config, update, payload["task_id"], payload["operation"])
        _, _, chat, user, un, _ = identities(update)
        origin = {
            "kind": "telegram",
            "bot_id": self.service.bot_id,
            "chat_id": chat,
            "user_id": user,
            "username_snapshot": un,
            "action_token": token,
        }

        def authorize(c):
            return (
                self.service.attached()
                and not self.service._closing
                and (self.service._work is None or c.telegram.control.enabled)
                and self.allowed(c, update, payload["operation"], payload["task_id"])
            )

        try:
            result = await self.service.runs.start(
                payload["task_id"],
                StartRequest(
                    plan_id=payload["plan_id"],
                    request_id=uuid.uuid5(TG_NAMESPACE, token),
                    ack_old_app_idle=True,
                ),
                origin=origin,
                authorize=authorize,
            )
        except SettingsError as exc:
            if exc.code == "plan_expired":
                return await self.replan(update, payload)
            raise
        await self.service.store.action_result(token, result["run_id"])
        await self.service.reply(update, "已开始")
        return "handled"

    async def stops(self, update, page=0):
        config = await self.service.config_store.read()
        runs = await self.service.runs.store.call(self.service.runs.store.active_snapshots)
        runs = [r for r in runs if self.allowed(config, update, "stop", run=r)]
        page = min(max(page, 0), max(0, (len(runs) - 1) // 8))
        buttons = []
        for run in runs[page * 8 : (page + 1) * 8]:
            if self.allowed(config, update, "stop", run=run):
                name = task_label(
                    config, run["task_id"], run["task_snapshot"].get("name", "历史任务")
                )
                buttons.append(
                    [
                        await self.button(
                            update,
                            f"⏹ {name}",
                            "stop",
                            {"run_id": run["run_id"]},
                        )
                    ]
                )
        nav = []
        for label, number in (("⬅️ 上一页", page - 1), ("下一页 ➡️", page + 1)):
            if 0 <= number * 8 < len(runs):
                nav.append(
                    await self.button(update, label, "menu", {"page": "stop", "number": number})
                )
        if nav:
            buttons.append(nav)
        text = "请选择要停止的运行" if runs else "当前没有可停止的运行"
        buttons += await self.navigation(update, {"page": "system"})
        await self.panel(update, text, buttons)

    async def stop(self, update, payload):
        rid = payload["run_id"]
        config = await self.service.config_store.read()
        run = await self.service.runs.store.get(rid)
        if not self.allowed(config, update, "stop", run=run):
            await self.panel(update, "权限不足，不能停止此运行")
            return "ignored"
        result = await self.service.runs.cancel(
            rid, authorize=lambda c, r: self.allowed(c, update, "stop", run=r)
        )
        text = "停止不会回滚已部署内容；远端可能继续"
        if result["status"] == "unknown":
            text += "\n结果需要核实"
        back = (
            {"page": "task", "task_id": run["task_id"], "context": payload.get("context", {})}
            if payload.get("detail")
            else {"page": "stop"}
        )
        await self.panel(update, text, await self.navigation(update, back))
        return "handled"

    async def mcp_panel(self, update, *, notice: str | None = None):
        mcp = getattr(self.service, "mcp", None)
        if mcp is None:
            await self.panel(update, "MCP 服务不可用")
            return
        snap = await mcp.snapshot()
        self.service.ensure_attached()
        ado_status = "允许建单" if snap.ado.allow_create_work_item else "只读"
        figma_status = "已配置 Token" if snap.figma.token_configured else "未配置 Token"
        lark_label = LARK_STATE_LABELS.get(snap.lark.state, snap.lark.state)
        owner_label = "已确认" if snap.lark.owner_confirmed_at else "未确认"
        lines = []
        if notice:
            lines.append(notice)
        token_state = snap.lark.token_status.state
        lines.extend(
            [
                "MCP 状态",
                f"ADO：{ado_status}（stdio 按需）",
                f"Figma：{figma_status}（stdio 按需）",
                (
                    f"Lark：{lark_label} · 端口 {snap.lark.port}"
                    f" · 所有权 {owner_label} · 令牌 {token_state}"
                ),
            ]
        )
        buttons = []
        if snap.lark.state in {"running", "running_degraded", "unhealthy", "starting"}:
            buttons.append(
                [await self.button(update, "⏹ 停止 Lark MCP", "mcp_lark_stop", {"action": "stop"})]
            )
        else:
            buttons.append(
                [
                    await self.button(
                        update, "▶️ 启动 Lark MCP", "mcp_lark_start", {"action": "start"}
                    )
                ]
            )
        buttons.append([await self.button(update, "🔄 刷新状态", "menu", {"page": "mcp"})])
        buttons += await self.navigation(update, {"page": "main"}, deep=False)
        await self.panel(update, "\n".join(lines), buttons)

    async def mcp_action(self, update, kind: str, token: str):
        mcp = getattr(self.service, "mcp", None)
        if mcp is None:
            await self.panel(update, "MCP 服务不可用")
            return "handled"
        req = LarkActionRequest(request_id=uuid.uuid5(TG_NAMESPACE, token))
        if kind == "mcp_lark_start":
            snap = await mcp.start_lark(req)
            notice = (
                "Lark MCP 已启动"
                if snap.lark.state in {"running", "running_degraded"}
                else f"Lark MCP 启动失败（{snap.lark.last_error or snap.lark.state}）"
            )
            await self.mcp_panel(update, notice=notice)
        else:
            await mcp.stop_lark(req)
            await self.mcp_panel(update, notice="Lark MCP 已停止")
        return "handled"

    async def vpn_command(self, update, action):
        vpn = getattr(self.service, "vpn", None)
        if vpn is None:
            await self.panel(update, "VPN 服务不可用")
            return "handled"
        action = (action or "status").strip().lower()
        if action == "status":
            status = await vpn.snapshot()
            await self.panel(
                update,
                f"VPN：{'已连接' if status.connected else '未连接'} · {status.ip or '无地址'}",
            )
            return "handled"
        if action == "on":
            return await self.vpn_start(update, str(update.get("update_id")))
        await self.panel(update, "用法：/vpn status 或 /vpn on；断开请在客户端中操作")
        return "handled"

    async def vpn_start(self, update, token):
        vpn = getattr(self.service, "vpn", None)
        if vpn is None:
            await self.panel(update, "VPN 服务不可用")
            return "handled"
        try:
            if not vpn.telegram_login_ready():
                await self.panel(update, "请先在桌面端配置 VPN（TOTP 种子）")
                return "handled"
            await vpn.start(request_id=uuid.uuid5(TG_NAMESPACE, token))
        except SettingsError as exc:
            if not exc.code.startswith("vpn_"):
                raise
            text = {
                "vpn_busy": "VPN 正在执行其他操作，请稍后重试",
                "vpn_not_configured": "请先在桌面端配置 VPN 凭据",
                "vpn_client_missing": "VPN 客户端未安装，请先在桌面端安装",
                "vpn_mfa_required": "请在桌面端输入 VPN 验证码",
            }.get(exc.code, "VPN 操作失败，请在桌面端检查配置或稍后重试")
            await self.panel(update, text)
            return "handled"
        await self.panel(update, "已开始")
        return "handled"

    async def services_panel(self, update):
        service = getattr(self.service, "services", None)
        if service is None:
            await self.panel(update, "服务不可用")
            return
        snap = await service.snapshot()
        code, tunnel = snap.code_server, snap.cloudflared.global_
        lines = [
            f"code-server：{code.state} · 端口 {code.port or '待刷新'}",
            f"全局隧道：{tunnel.state} · {tunnel.url or '域名待刷新'}",
            f"协议：{snap.settings.cloudflared.protocol}",
            f"局域网地址：{snap.network.lan_ip or '未连接'}",
        ]
        vpn = getattr(self.service, "vpn", None)
        vpn_button = None
        if vpn is not None:
            vpn_status = await vpn.snapshot()
            lines.append(
                f"VPN：{'已连接' if vpn_status.connected else '未连接'} "
                f"· {vpn_status.ip or '无地址'}"
            )
            vpn_button = await self.button(update, "🔌 连接 VPN", "vpn_connect", {})
        else:
            lines.append("VPN 服务不可用")
        buttons = []
        for name, label, view in [
            ("code-server", "code-server", code),
            ("cloudflared", "全局隧道", tunnel),
        ]:
            action = "stop" if view.state in {"running", "unhealthy", "external"} else "start"
            title = ("⏹ 停止 " if action == "stop" else "▶️ 启动 ") + label
            kind = "svc_confirm" if name == "cloudflared" and action == "start" else "svc_action"
            buttons.append(
                [await self.button(update, title, kind, {"name": name, "action": action})]
            )
        for custom in snap.cloudflared.tunnels:
            lines.append(f"自定义隧道：{custom.state} · {custom.url or '域名待刷新'}")
            buttons.append(
                [await self.button(update, "⏹ 停止自定义隧道", "svc_delete", {"id": custom.id})]
            )
        buttons.append([await self.button(update, "➕ 新增自定义隧道", "svc_input", {})])
        if vpn_button:
            buttons.append([vpn_button])
        buttons.append([await self.button(update, "🔄 刷新状态", "menu", {"page": "services"})])
        buttons += await self.navigation(update, {"page": "main"}, deep=False)
        await self.panel(update, "\n".join(lines), buttons)

    async def services_action(self, update, kind, payload, token):
        import time

        from toolbox_backend.adapters.service_runtime import validate_tunnel_target
        from toolbox_backend.api.services_schemas import ActionRequest, TunnelCreate

        service = self.service.services
        if service is None:
            return "ignored"
        _, _, chat, user, _, _ = identities(update)
        if kind == "svc_input":
            self._service_inputs[(chat, user)] = time.monotonic() + 300
            await self.panel(update, "请输入本机回环 HTTP/HTTPS 地址与端口（5 分钟内有效）")
        elif kind == "svc_confirm":
            button = await self.button(update, "✅ 确认公开到公网", "svc_action", payload)
            await self.panel(update, "该地址将可被公网任何人访问，隧道本身无认证", [[button]])
        elif kind == "svc_create":
            validate_tunnel_target(payload["target_url"], True)
            await service.create_tunnel(
                TunnelCreate(
                    target_url=payload["target_url"],
                    ack_public=True,
                    request_id=uuid.uuid5(TG_NAMESPACE, token),
                )
            )
            await self.services_panel(update)
        elif kind == "svc_delete":
            await service.delete_tunnel(payload["id"])
            await self.services_panel(update)
        elif kind == "svc_action":
            method = service.start if payload["action"] == "start" else service.stop
            await method(
                payload["name"],
                ActionRequest(request_id=uuid.uuid5(TG_NAMESPACE, token), ack_public=True),
            )
            await self.services_panel(update)
        return "handled"

    async def system_menu(self, update, role, group):
        can_rollback = role == "owner" or bool(group and group.can_rollback)
        can_status = role in {"owner", "legacy"} or bool(group and group.can_status)
        can_stop = role == "owner" or bool(group and group.can_stop)
        if not (can_rollback or can_status or can_stop):
            return "ignored"
        rows = []
        for permitted, label, page in (
            (can_status, "📊 运行状态", "status"),
            (can_stop, "⏹ 停止运行", "stop"),
            (can_rollback, "↩️ 回滚", "rollback"),
        ):
            if permitted:
                rows.append([await self.button(update, label, "menu", {"page": page})])
        rows += await self.navigation(update, {"page": "main"}, deep=False)
        await self.panel(update, "🛠 系统操作", rows)
        return "handled"

    async def cancel_rollback(self, update):
        _, _, chat, user, _, _ = identities(update)
        cancelled = await self.service.store.cancel_rollback_actions(
            self.service.bot_id, chat, user
        )
        await self.panel(update, "已取消回滚" if cancelled else "当前没有进行中的回滚")
        return "handled"

    async def cc_command(self, update):
        config = await self.service.config_store.read()
        bot_cfg = config.ai.bots.claude_code
        slot = self.service.registry.get("ai:claude_code")
        username = (
            (slot.bot_username if slot else None)
            or bot_cfg.username
            or (bot_cfg.verified_bot.username if bot_cfg.verified_bot else None)
        )
        if bot_cfg.enabled and username:
            clean = username.lstrip("@")
            text = f"Claude 会话已迁移至 Claude Code 专属机器人：@{clean}（https://t.me/{clean}）"
        else:
            text = (
                "Claude 会话已迁移至 Claude Code 专属机器人。"
                "请在桌面端 设置 → Telegram → AI 专属机器人 启用 Claude Code 机器人。"
            )
        await self.panel(update, text)
        return "handled"

    async def callback(self, update):
        _, callback, chat, user, _, _ = identities(update)
        token = callback.get("data")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{22}", token):
            return "ignored"
        action = await self.service.store.consume(token, self.service.bot_id, chat, user)
        if action is None:
            prior = await self.service.store.inspect_action(token, self.service.bot_id, chat, user)
            if prior is None:
                return await self.expired(update, {})
            if prior["consumed_at"]:
                if prior["kind"] not in {"run_confirm", "deploy_confirm", "rollback_confirm"}:
                    return await self.expired(update, prior)
                if prior["result_run_id"]:
                    await self.panel(update, "已开始")
                else:
                    await self.panel(update, "该操作已处理，请查看状态或重新打开菜单")
                return "ignored"
            return await self.expired(update, prior)
        role, group = await self.service.resolve_acl(update)
        if role == "none":
            return "ignored"
        if self.service.client and isinstance(callback.get("id"), str):
            # Answering is best effort. A failed acknowledgement must not consume an
            # otherwise valid confirmation without handing it to the executor.
            from toolbox_backend.adapters.telegram_http import TelegramError

            try:
                await self.service.client.request(
                    "answerCallbackQuery", {"callback_query_id": callback["id"]}
                )
            except TelegramError:
                pass
        kind, payload = action["kind"], action["payload"]
        update["_tg_screen"] = (kind, payload)
        if kind in {"run_confirm", "deploy_confirm", "rollback_confirm"}:
            return await self.confirm(update, token, action)
        if kind == "stop":
            return await self.stop(update, payload)
        if kind.startswith("wi_"):
            if role != "owner":
                return "ignored"
            return await self.work_items.callback(update, kind, payload, token)
        if kind.startswith("svc_"):
            if role != "owner":
                return "ignored"
            return await self.services_action(update, kind, payload, token)
        if kind in {"mcp_lark_start", "mcp_lark_stop"}:
            if role != "owner":
                return "ignored"
            return await self.mcp_action(update, kind, token)
        if kind == "vpn_connect":
            if role != "owner":
                return "ignored"
            return await self.vpn_start(update, token)
        page = payload.get("page")
        if page == "tasks":
            await self.tasks(update)
        elif page == "task_page":
            await self.tasks(
                update,
                rollback=bool(payload.get("rollback")),
                page=payload.get("number", 0),
                config_id=payload.get("config_id"),
                config_page=payload.get("config_page", 0),
            )
        elif page == "task":
            await self.task(update, payload["task_id"], **payload.get("context", {}))
        elif page == "offsets":
            await self.offsets(update, payload["task_id"], **payload.get("context", {}))
        elif page == "preflight":
            return await self.preflight(update, payload)
        elif page == "rollback":
            await self.tasks(update, rollback=True)
        elif page == "stop":
            await self.stops(update, payload.get("number", 0))
        elif page == "wi" and role == "owner":
            await self.work_items.projects(update)
        elif page == "services" and role == "owner":
            await self.services_panel(update)
        elif page == "mcp" and role == "owner":
            await self.mcp_panel(update)
        elif page == "status" and (role in {"owner", "legacy"} or group and group.can_status):
            await self.status_panel(update, role, group, chat)
        elif page == "system":
            return await self.system_menu(update, role, group)
        elif page == "progress":
            await self.progress(update, payload)
        elif page == "main":
            await self.service.main_menu(update, role, group, chat, user)
        elif page == "cancel":
            cancelled = await self.service.store.cancel_action(
                payload.get("confirm_token"), self.service.bot_id, chat, user
            )
            if payload.get("task_id"):
                await self.task(update, payload["task_id"], **payload.get("context", {}))
            else:
                await self.panel(
                    update, "已取消本次确认" if cancelled else "确认已处理，请查看运行状态"
                )
        else:
            return "ignored"
        return "handled"

    async def dispatch(self, update, command, role, group):
        _, callback, _, _, _, _ = identities(update)
        try:
            if isinstance(callback, dict):
                return await self.callback(update)
            if command in {"/services", "/svc", "/service"}:
                if role != "owner":
                    return "ignored"
                await self.services_panel(update)
                return "handled"
            if command == "/cc":
                return await self.cc_command(update)
            if command == "/cancelrollback":
                return await self.cancel_rollback(update)
            if command == "/vpn":
                if role != "owner":
                    return "ignored"
                text = identities(update)[0].get("text", "")
                parts = text.split(maxsplit=1)
                return await self.vpn_command(update, parts[1] if len(parts) > 1 else "status")
            _, _, chat, user, _, _ = identities(update)
            if role == "owner" and (chat, user) in self._service_inputs:
                import time

                from toolbox_backend.adapters.service_runtime import validate_tunnel_target

                expires = self._service_inputs.pop((chat, user))
                if expires < time.monotonic() or command.startswith("/"):
                    return "ignored"
                target = validate_tunnel_target(update["message"].get("text", ""), True)
                button = await self.button(
                    update, "✅ 确认公开到公网", "svc_create", {"target_url": target}
                )
                await self.panel(update, "该地址将可被公网任何人访问，隧道本身无认证", [[button]])
                return "handled"
            if command in {"/run", "/rollback", "/stop"}:
                if command == "/rollback":
                    await self.tasks(update, rollback=True)
                elif command == "/stop":
                    await self.stops(update)
                else:
                    text = update["message"].get("text", "")
                    args = text.split()
                    if len(args) == 1:
                        await self.tasks(update)
                    elif len(args) == 2 and re.fullmatch(r"[a-z0-9_]{1,32}", args[1]):
                        await self.command_task(update, args[1])
                    else:
                        await self.panel(update, "用法：/run <任务指令>")
                return "handled"
            if command == "/wi":
                if role != "owner":
                    return "ignored"
                update["_tg_screen"] = ("wi_projects", {})
                await self.work_items.command(update)
                return "handled"
            if command == "/mcp":
                if role != "owner":
                    return "ignored"
                await self.mcp_panel(update)
                return "handled"
            if command.startswith("/") and re.fullmatch(r"/[a-z0-9_]{1,32}", command):
                config = await self.service.config_store.read()
                if any(t.tg_command == command[1:] for t in config.tasks.items):
                    await self.command_task(update, command[1:])
                    return "handled"
            return None
        except SettingsError as exc:
            await self.panel(update, ERRORS.get(exc.code, "操作失败，请稍后重试"))
            return "failed"

    async def command_task(self, update, command):
        config = await self.service.config_store.read()
        matches = [t for t in config.tasks.items if t.tg_command == command]
        if len(matches) != 1:
            raise SettingsError("not_found", "固定错误", 404)
        await self.task(update, matches[0].id)
