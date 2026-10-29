"""Telegram 发布菜单：稳定分层、实时权限与返回导航。"""

from datetime import UTC, datetime

from toolbox_backend.domain.errors import SettingsError

STATUSES = {
    "queued": "排队中",
    "running": "运行中",
    "cancelling": "停止中",
    "cancelled": "已停止",
    "succeeded": "成功",
    "failed": "失败",
    "unknown": "待核实",
}
PHASES = {
    "queued": "等待执行",
    "git": "同步仓库",
    "build": "构建",
    "release": "发布",
    "rollback": "回滚",
    "git_cleanup": "清理仓库",
    "git_sync": "同步仓库",
    "git_push": "推送分支",
    "build_create": "创建构建",
    "build_wait": "等待构建",
    "build_cancel": "停止构建",
    "release_create": "创建发布",
    "release_wait": "等待发布",
    "env_deploy": "部署环境",
}


def relative_time(value):
    if not value:
        return "时间未知"
    seconds = max(0, (datetime.now(UTC) - datetime.fromisoformat(value)).total_seconds())
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds // 60)} 分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)} 小时前"
    return f"{int(seconds // 86400)} 天前"


class TelegramMenu:
    async def navigation(self, update, back, *, deep=True, kind="menu"):
        row = [await self.button(update, "⬅️ 返回", kind, back)]
        if deep:
            row.append(await self.button(update, "🏠 主菜单", "menu", {"page": "main"}))
        return [row]

    def visible(self, config, update, tid, *, rollback=False):
        if rollback:
            return self.allowed(config, update, "rollback", tid)
        role, group = self.role(config, update)
        return role == "owner" or bool(
            group
            and tid in group.task_ids
            and (group.can_run or group.can_rollback or group.can_status or group.can_stop)
        )

    @staticmethod
    def command_config(config, tid):
        for release in config.tasks.release_configs:
            for command in release.commands:
                if command.id == tid:
                    return release, command
        raise SettingsError("not_found", "命令已不存在", 404)

    async def tasks(self, update, *, rollback=False, page=0, config_id=None, config_page=0):
        config = await self.service.config_store.read()
        releases = []
        for release in sorted(config.tasks.release_configs, key=lambda r: (r.sort_order, r.id)):
            commands = [
                c
                for c in sorted(release.commands, key=lambda c: (c.sort_order, c.id))
                if c.enabled and self.visible(config, update, c.id, rollback=rollback)
            ]
            if commands:
                releases.append((release, commands))
        rows = []
        if config_id is None:
            page = min(max(page, 0), max(0, (len(releases) - 1) // 8))
            for release, commands in releases[page * 8 : (page + 1) * 8]:
                rows.append(
                    [
                        await self.button(
                            update,
                            f"📦 {release.name}（{len(commands)} 个命令）",
                            "menu",
                            {
                                "page": "task_page",
                                "config_id": release.id,
                                "rollback": rollback,
                                "config_page": page,
                                "number": 0,
                            },
                        )
                    ]
                )
            total = len(releases)
            back = {"page": "system" if rollback else "main"}
            title = "↩️ 回滚：请选择发布配置" if rollback else "🚀 发布：请选择发布配置"
            deep = rollback
        else:
            entry = next((r for r in releases if r[0].id == config_id), None)
            if entry is None:
                raise SettingsError("validation_error", "配置不可见或权限已变化", 422)
            release, commands = entry
            page = min(max(page, 0), max(0, (len(commands) - 1) // 8))
            for command in commands[page * 8 : (page + 1) * 8]:
                context = {"rollback": rollback, "config_page": config_page, "command_page": page}
                rows.append(
                    [
                        await self.button(
                            update,
                            f"▶️ {command.name}",
                            "menu",
                            {
                                "page": "offsets" if rollback else "task",
                                "task_id": command.id,
                                "context": context,
                            },
                        )
                    ]
                )
            total = len(commands)
            back = {"page": "task_page", "rollback": rollback, "number": config_page}
            title, deep = f"📦 {release.name}：请选择命令", True
        nav = []
        for label, number in (("⬅️ 上一页", page - 1), ("下一页 ➡️", page + 1)):
            if 0 <= number * 8 < total:
                nav.append(
                    await self.button(
                        update,
                        label,
                        "menu",
                        {
                            "page": "task_page",
                            "number": number,
                            "rollback": rollback,
                            "config_id": config_id,
                            "config_page": config_page,
                        },
                    )
                )
        if nav:
            rows.append(nav)
        rows += await self.navigation(update, back, deep=deep)
        await self.panel(update, title if total else "当前没有可用的发布配置", rows)

    async def task(self, update, task_id, *, rollback=False, config_page=0, command_page=0):
        config = await self.service.config_store.read()
        task = self.task_checked(config, update, task_id, "sync_build_release", any_mode=True)
        release, command = self.command_config(config, task_id)
        context = {"rollback": rollback, "config_page": config_page, "command_page": command_page}
        active, latest = await self.service.runs.store.call(self.service.runs.store.task_summaries)
        lines = [
            f"▶️ {command.name}",
            f"仓库：{release.name}",
            f"分支：{task.git_flow.build_branch or '未配置'}",
        ]
        for target in task.targets:
            environments = "、".join(target.release_stage_names) or "未提供名称"
            lines.append(f"目标：{target.name} · 环境：{environments}")
        if self.allowed(config, update, "status", task_id):
            last = latest.get(task_id)
            if last:
                status = last["status"]
                result = {
                    "succeeded": "✅ 成功",
                    "failed": "❌ 失败",
                    "cancelled": "⏹ 已停止",
                    "unknown": "❓ 待核实",
                }.get(status, "⏳ 运行中")
                when = relative_time(last["finished_at"] or last["created_at"])
                lines.append(f"上次运行：{result} · {when}")
            else:
                lines.append("上次运行：暂无记录")
        rows = []
        if task_id in active:
            run = await self.service.runs.store.get(active[task_id])
            if self.allowed(config, update, "stop", run=run):
                rows.append(
                    [
                        await self.button(
                            update,
                            "⏹ 停止这次运行",
                            "stop",
                            {
                                "run_id": run["run_id"],
                                "detail": True,
                                "context": context,
                            },
                        )
                    ]
                )
            if self.allowed(config, update, "status", task_id):
                rows.append(
                    [
                        await self.button(
                            update,
                            "📄 查看进度",
                            "menu",
                            {
                                "page": "progress",
                                "run_id": run["run_id"],
                                "context": context,
                            },
                        )
                    ]
                )
        else:
            if self.allowed(config, update, "sync_build_release", task_id):
                rows.append(
                    [
                        await self.button(
                            update,
                            label,
                            "menu",
                            {
                                "page": "preflight",
                                "task_id": task_id,
                                "operation": operation,
                                "context": context,
                            },
                        )
                        for label, operation in (
                            ("🚀 构建并发布", "sync_build_release"),
                            ("📤 只发布", "deploy_only"),
                        )
                    ]
                )
            if self.allowed(config, update, "rollback", task_id):
                rows.append(
                    [
                        await self.button(
                            update,
                            "↩️ 回滚",
                            "rollback_pick",
                            {
                                "page": "offsets",
                                "task_id": task_id,
                                "context": context,
                            },
                        )
                    ]
                )
        rows += await self.navigation(
            update,
            {
                "page": "task_page",
                "config_id": release.id,
                "rollback": rollback,
                "config_page": config_page,
                "number": command_page,
            },
        )
        await self.panel(update, "\n".join(lines), rows)

    async def offsets(self, update, tid, *, rollback=False, config_page=0, command_page=0):
        config = await self.service.config_store.read()
        self.task_checked(config, update, tid, "rollback")
        release, command = self.command_config(config, tid)
        context = {"rollback": rollback, "config_page": config_page, "command_page": command_page}
        rows = [
            [
                await self.button(
                    update,
                    f"↩️ 回滚偏移 {offset}",
                    "rollback_pick",
                    {
                        "page": "preflight",
                        "task_id": tid,
                        "operation": "rollback",
                        "offset": offset,
                        "context": context,
                    },
                )
            ]
            for offset in range(1, 6)
        ]
        back = (
            {
                "page": "task_page",
                "config_id": release.id,
                "rollback": True,
                "config_page": config_page,
                "number": command_page,
            }
            if rollback
            else {"page": "task", "task_id": tid, "context": context}
        )
        rows += await self.navigation(update, back)
        await self.panel(update, f"{command.name}：请选择历史偏移（1..5）", rows)

    async def status_panel(self, update, role, group, chat):
        await self.panel(
            update,
            await self.service.status_text(role, group, chat),
            await self.navigation(update, {"page": "system"}),
        )

    async def progress(self, update, payload):
        config = await self.service.config_store.read()
        run = await self.service.runs.store.get(payload["run_id"])
        self.task_checked(config, update, run["task_id"], "status")
        _, command = self.command_config(config, run["task_id"])
        # 仅展示持久化阶段摘要，不把原始日志或内部标识投递到聊天。
        phase = PHASES.get(run["phase"], "处理中")
        status = STATUSES.get(run["status"], "待核实")
        when = relative_time(run["updated_at"])
        text = f"📄 {command.name}\n状态：{status}\n阶段：{phase}\n更新于：{when}"
        await self.panel(
            update,
            text,
            await self.navigation(
                update,
                {
                    "page": "task",
                    "task_id": run["task_id"],
                    "context": payload.get("context", {}),
                },
            ),
        )

    async def fallback_navigation(self, update):
        kind, payload = update.get("_tg_screen", ("menu", {}))
        page = payload.get("page")
        if kind.startswith("wi_"):
            pid = payload.get("project_id")
            ident = payload.get("id")
            if kind == "wi_projects":
                return await self.navigation(update, {"page": "main"}, deep=False)
            if kind == "wi_project":
                return await self.navigation(update, {}, kind="wi_projects")
            if kind in {"wi_column", "wi_page"}:
                return await self.navigation(update, {"project_id": pid}, kind="wi_project")
            if kind == "wi_air":
                return await self.navigation(update, payload, kind="wi_ai")
            if kind in {"wi_aip", "wi_menu_cancel"}:
                return await self.navigation(update, payload, kind="wi_air")
            if kind == "wi_detail":
                if payload.get("_back"):
                    return await self.navigation(update, payload["_back"], kind="wi_related")
                state = self.work_items.state.get(identities_chat(update), {})
                if state.get("project_id") == pid:
                    return await self.navigation(update, state, kind="wi_column")
                return await self.navigation(update, {"project_id": pid}, kind="wi_project")
            if ident:
                return await self.navigation(
                    update, {"project_id": pid, "id": ident}, kind="wi_detail"
                )
            return await self.navigation(update, {"page": "wi"}, deep=False)
        if kind.startswith("svc_") or kind == "vpn_connect":
            return await self.navigation(update, {"page": "services"})
        if kind.startswith("mcp_"):
            return await self.navigation(update, {"page": "main"}, deep=False)
        if page in {"wi", "services", "mcp", "system"}:
            return await self.navigation(update, {"page": "main"}, deep=False)
        if page in {"preflight", "cancel"} and payload.get("task_id"):
            return await self.navigation(
                update,
                {
                    "page": "task",
                    "task_id": payload["task_id"],
                    "context": payload.get("context", {}),
                },
            )
        return await self.navigation(update, {"page": "main"}, deep=False)


def identities_chat(update):
    from toolbox_backend.services.telegram_commands import identities

    return identities(update)[2]
