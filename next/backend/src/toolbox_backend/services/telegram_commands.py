"""Telegram commands: trusted server actions, live ACL and the existing S3 executor."""

import re
import uuid
from datetime import UTC, datetime

from toolbox_backend.api.mcp_schemas import LarkActionRequest
from toolbox_backend.api.task_schemas import PreflightRequest, StartRequest
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.telegram import acl_validity, numeric

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


class TelegramDispatcher:
    def __init__(self, service, work_items):
        from toolbox_backend.services.telegram_work_items import TelegramWorkItems

        self.service = service
        self.work_items = TelegramWorkItems(self, work_items)

    def close(self):
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
                and origin.get("kind") == "telegram"
                and origin.get("chat_id") == chat
            )
        permission = group.can_rollback if operation == "rollback" else group.can_run
        return permission and task_id in group.task_ids

    async def button(self, update, label, kind, payload, *, ttl=300):
        self.service.ensure_attached()
        _, _, chat, user, _, _ = identities(update)
        token = await self.service.store.action(self.service.bot_id, chat, user, kind, payload, ttl)
        return {"text": label, "callback_data": token}

    async def panel(self, update, text, buttons=None):
        await self.service.reply(
            update, text, reply_markup={"inline_keyboard": buttons or []}, panel=True
        )

    async def tasks(self, update, *, rollback=False, page=0):
        config = await self.service.config_store.read()
        operation = "rollback" if rollback else "sync_build_release"
        tasks = [
            t
            for t in sorted(config.tasks.items, key=lambda t: (t.sort_order, t.id))
            if t.enabled
            and (
                self.allowed(config, update, operation, t.id)
                or not rollback
                and self.allowed(config, update, "rollback", t.id)
            )
        ]
        page = min(max(page, 0), max(0, (len(tasks) - 1) // 8))
        rows = [
            [
                await self.button(
                    update,
                    task.name or task.tg_command or "任务",
                    "rollback_pick" if rollback else "menu",
                    {"page": "offsets" if rollback else "task", "task_id": task.id},
                )
            ]
            for task in tasks[page * 8 : (page + 1) * 8]
        ]
        nav = []
        for label, number in (("上一页", page - 1), ("下一页", page + 1)):
            if 0 <= number * 8 < len(tasks):
                nav.append(
                    await self.button(
                        update,
                        label,
                        "menu",
                        {"page": "task_page", "number": number, "rollback": rollback},
                    )
                )
        if nav:
            rows.append(nav)
        await self.panel(
            update,
            ("请选择回滚任务" if rollback else "请选择任务") if tasks else "当前没有可执行的任务",
            rows,
        )

    async def task(self, update, task_id):
        config = await self.service.config_store.read()
        task = self.task_checked(config, update, task_id, "sync_build_release", any_mode=True)
        buttons = []
        if self.allowed(config, update, "sync_build_release", task_id):
            for label, op in (("构建发布", "sync_build_release"), ("仅发布", "deploy_only")):
                buttons.append(
                    [
                        await self.button(
                            update,
                            label,
                            "menu",
                            {"page": "preflight", "task_id": task_id, "operation": op},
                        )
                    ]
                )
        if self.allowed(config, update, "rollback", task_id):
            buttons.append(
                [
                    await self.button(
                        update, "回滚", "rollback_pick", {"page": "offsets", "task_id": task_id}
                    )
                ]
            )
        await self.panel(update, f"任务：{task.name or task.tg_command}", buttons)

    def task_checked(self, config, update, tid, operation, *, any_mode=False):
        task = next((t for t in config.tasks.items if t.id == tid), None)
        if task is None:
            raise SettingsError("not_found", "固定错误", 404)
        permitted = self.allowed(config, update, operation, tid)
        if any_mode:
            permitted = permitted or self.allowed(config, update, "rollback", tid)
        if not task.enabled or not permitted:
            raise SettingsError("validation_error", "固定错误", 422)
        return task

    async def offsets(self, update, tid):
        config = await self.service.config_store.read()
        task = self.task_checked(config, update, tid, "rollback")
        rows = [
            [
                await self.button(
                    update,
                    f"回滚偏移 {offset}",
                    "rollback_pick",
                    {
                        "page": "preflight",
                        "task_id": tid,
                        "operation": "rollback",
                        "offset": offset,
                    },
                )
            ]
            for offset in range(1, 6)
        ]
        await self.panel(update, f"{task.name}：请选择历史偏移（1..5）", rows)

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
            "sync_build_release": "构建发布",
            "deploy_only": "仅发布",
            "rollback": "回滚",
        }[op]
        text = [
            f"任务：{task.name}",
            f"操作：{operation_name}",
            f"仓库：{task.repo_name or task.repo_id or '未提供'}",
            f"分支：{task.git_flow.build_branch or '未提供'}",
        ]
        if op == "rollback":
            text.append(f"历史偏移：{offset}")
        for target in plan["targets"]:
            text.extend(
                [
                    f"目标：{target['name']}",
                    f"Build definition：{target['definition_id']} · "
                    f"Release definition：{target['release_definition_id']}",
                    "Stage：" + "、".join(map(str, target["stage_ids"])),
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
            "确认执行",
            kind,
            {
                "task_id": tid,
                "operation": op,
                "offset": offset,
                "plan_id": str(plan["plan_id"]),
            },
            ttl=ttl,
        )
        cancel = await self.button(
            update, "取消", "menu", {"page": "cancel", "confirm_token": confirm["callback_data"]}
        )
        await self.panel(update, "\n".join(text), [[confirm, cancel]])
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
        payload = action["payload"]
        if action["kind"] in {"run_confirm", "deploy_confirm", "rollback_confirm"}:
            return await self.replan(update, payload)
        await self.panel(update, "操作已过期，请重新打开菜单")
        return "expired"

    async def replan(self, update, payload):
        config = await self.service.config_store.read()
        self.task_checked(config, update, payload["task_id"], payload["operation"])
        button = await self.button(
            update,
            "重新预检",
            "menu",
            {
                "page": "preflight",
                "task_id": payload["task_id"],
                "operation": payload["operation"],
                "offset": payload.get("offset"),
            },
        )
        await self.panel(update, "计划已过期，请重新预检", [[button]])
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
        await self.panel(update, f"已开始（运行 #{result['run_id'][:8]}）")
        return "handled"

    async def stops(self, update, page=0):
        config = await self.service.config_store.read()
        runs = await self.service.runs.store.call(self.service.runs.store.active_snapshots)
        runs = [r for r in runs if self.allowed(config, update, "stop", run=r)]
        page = min(max(page, 0), max(0, (len(runs) - 1) // 8))
        buttons = []
        for run in runs[page * 8 : (page + 1) * 8]:
            if self.allowed(config, update, "stop", run=run):
                name = run["task_snapshot"].get("name", "历史任务")
                buttons.append(
                    [
                        await self.button(
                            update,
                            f"{name} · #{run['run_id'][:8]}",
                            "stop",
                            {"run_id": run["run_id"]},
                        )
                    ]
                )
        nav = []
        for label, number in (("上一页", page - 1), ("下一页", page + 1)):
            if 0 <= number * 8 < len(runs):
                nav.append(
                    await self.button(update, label, "menu", {"page": "stop", "number": number})
                )
        if nav:
            buttons.append(nav)
        await self.panel(
            update, "请选择要停止的运行" if buttons else "当前没有可停止的运行", buttons
        )

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
        await self.panel(update, text)
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
                [
                    await self.button(
                        update, "停止 Lark MCP", "mcp_lark_stop", {"action": "stop"}
                    )
                ]
            )
        else:
            buttons.append(
                [
                    await self.button(
                        update, "启动 Lark MCP", "mcp_lark_start", {"action": "start"}
                    )
                ]
            )
        buttons.append([await self.button(update, "刷新状态", "menu", {"page": "mcp"})])
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

    async def callback(self, update):
        _, callback, chat, user, _, _ = identities(update)
        token = callback.get("data")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{22}", token):
            return "ignored"
        action = await self.service.store.consume(token, self.service.bot_id, chat, user)
        if action is None:
            prior = await self.service.store.inspect_action(token, self.service.bot_id, chat, user)
            if prior is None:
                return "ignored"
            if prior["consumed_at"]:
                if prior["kind"] not in {"run_confirm", "deploy_confirm", "rollback_confirm"}:
                    return "ignored"
                if prior["result_run_id"]:
                    await self.panel(update, f"已开始（运行 #{prior['result_run_id'][:8]}）")
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
        if kind in {"run_confirm", "deploy_confirm", "rollback_confirm"}:
            return await self.confirm(update, token, action)
        if kind == "stop":
            return await self.stop(update, payload)
        if kind.startswith("wi_"):
            if role != "owner":
                return "ignored"
            return await self.work_items.callback(update, kind, payload, token)
        if kind in {"mcp_lark_start", "mcp_lark_stop"}:
            if role != "owner":
                return "ignored"
            return await self.mcp_action(update, kind, token)
        page = payload.get("page")
        if page == "tasks":
            await self.tasks(update)
        elif page == "task_page":
            await self.tasks(update, rollback=bool(payload.get("rollback")), page=payload["number"])
        elif page == "task":
            await self.task(update, payload["task_id"])
        elif page == "offsets":
            await self.offsets(update, payload["task_id"])
        elif page == "preflight":
            return await self.preflight(update, payload)
        elif page == "rollback":
            await self.tasks(update, rollback=True)
        elif page == "stop":
            await self.stops(update, payload.get("number", 0))
        elif page == "wi" and role == "owner":
            await self.work_items.projects(update)
        elif page == "mcp" and role == "owner":
            await self.mcp_panel(update)
        elif page == "status" and (role in {"owner", "legacy"} or group and group.can_status):
            await self.panel(update, await self.service.status_text(role, group, chat))
        elif page == "system" and role == "owner":
            await self.panel(update, "该功能尚未迁移到新应用")
        elif page == "cancel":
            cancelled = await self.service.store.cancel_action(
                payload.get("confirm_token"), self.service.bot_id, chat, user
            )
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
