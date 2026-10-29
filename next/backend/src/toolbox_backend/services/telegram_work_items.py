"""Owner-only S2 work items in Telegram; no remote URL bypass or raw HTML output."""

import re
import time
import uuid
from html.parser import HTMLParser

from toolbox_backend.adapters.telegram_http import TelegramError
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.services.telegram import AI_IDS
from toolbox_backend.services.telegram import identities as identities_of
from toolbox_backend.services.work_items import COLUMNS, image_type

ADO_ERRORS = {
    "no_credential": "尚未配置 ADO 凭据",
    "unauthorized": "ADO 认证失败",
    "forbidden": "无权读取此工单",
    "not_found": "工单或项目不存在",
    "timeout": "ADO 请求超时",
    "network": "ADO 网络请求失败",
    "tls": "ADO 安全连接失败",
    "redirect": "ADO 请求发生重定向，已拒绝",
    "blocked_origin": "已拒绝外部媒体",
    "bad_response": "ADO 返回格式异常",
    "too_large": "ADO 响应超过限额",
    "media_expired": "媒体已过期，请重新打开工单",
    "unsupported_media": "不支持的图片类型",
    "busy": "忙，请稍后重试",
    "store_unavailable": "配置数据库不可用",
}


class Content(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.images, self.blocked = [], [], 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"br", "p", "div", "li", "tr", "pre"}:
            self.parts.append("\n")
        if tag == "img":
            if attrs.get("data-media-id"):
                self.images.append(attrs["data-media-id"])
            else:
                self.blocked += 1
        if tag == "span" and "data-blocked-origin" in attrs:
            self.blocked += 1

    def handle_data(self, data):
        self.parts.append(data)

    @property
    def text(self):
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


class TelegramWorkItems:
    def __init__(self, dispatcher, service):
        self.dispatcher, self.service = dispatcher, service
        self.state = {}
        self.cache = {}

    def close(self):
        self.state.clear()
        self.cache.clear()

    async def owner(self, update):
        self.dispatcher.service.ensure_attached()
        config = await self.dispatcher.service.config_store.read()
        self.dispatcher.service.ensure_attached()
        if self.dispatcher.role(config, update)[0] != "owner":
            raise SettingsError("validation_error", "固定错误", 422)
        return config

    def chat(self, update):
        from toolbox_backend.services.telegram import identities

        return identities(update)[2]

    async def button(self, update, label, kind, payload):
        return await self.dispatcher.button(update, label, "wi_" + kind, payload)

    async def projects(self, update, page=0):
        update["_tg_screen"] = ("wi_projects", {})
        config = await self.owner(update)
        projects = config.ado.projects
        page = min(max(page, 0), max(0, (len(projects) - 1) // 8))
        rows = [
            [await self.button(update, "📁 " + p.project, "project", {"project_id": p.id})]
            for p in projects[page * 8 : (page + 1) * 8]
        ]
        nav = []
        for label, number in (("⬅️ 上一页", page - 1), ("下一页 ➡️", page + 1)):
            if 0 <= number * 8 < len(projects):
                nav.append(await self.button(update, label, "projects", {"page": number}))
        if nav:
            rows.append(nav)
        await self.dispatcher.panel(update, "请选择工单项目" if projects else "尚未配置项目", rows)

    async def columns(self, update, project_id):
        update["_tg_screen"] = ("wi_project", {"project_id": project_id})
        config = await self.owner(update)
        if project_id not in {p.id for p in config.ado.projects}:
            raise SettingsError("not_found", "固定错误", 404)
        self.state[self.chat(update)] = {"project_id": project_id, "column": "开发中", "page": 0}
        rows = [
            [
                await self.button(
                    update,
                    "📋 " + column,
                    "column",
                    {"project_id": project_id, "column": column, "page": 0},
                )
            ]
            for column in COLUMNS
        ]
        await self.dispatcher.panel(update, "请选择版块", rows)

    async def listing(self, update, payload):
        update["_tg_screen"] = ("wi_column", payload)
        config = await self.owner(update)
        pid, column, page = payload["project_id"], payload["column"], payload.get("page", 0)
        if column not in COLUMNS or type(page) is not int or page < 0:
            return "ignored"
        if pid not in {p.id for p in config.ado.projects}:
            raise SettingsError("not_found", "固定错误", 404)
        now = time.monotonic()
        self.cache = {k: v for k, v in self.cache.items() if v[0] > now}
        key = (pid, column, config.revision)
        if key not in self.cache:
            result = await self.service.listing(pid, column)
            self.dispatcher.service.ensure_attached()
            self.cache[key] = (time.monotonic() + 60, result)
        result = self.cache[key][1]
        await self.owner(update)
        items = result.items
        page = min(page, max(0, (len(items) - 1) // 8))
        self.state[self.chat(update)] = {"project_id": pid, "column": column, "page": page}
        rows = [
            [
                await self.button(
                    update,
                    f"📋 #{item.id} {item.title}",
                    "detail",
                    {"project_id": pid, "id": item.id},
                )
            ]
            for item in items[page * 8 : (page + 1) * 8]
        ]
        nav = []
        if page > 0:
            nav.append(
                await self.button(
                    update,
                    "⬅️ 上一页",
                    "page",
                    {"project_id": pid, "column": column, "page": page - 1},
                )
            )
        if (page + 1) * 8 < len(items):
            nav.append(
                await self.button(
                    update,
                    "下一页 ➡️",
                    "page",
                    {"project_id": pid, "column": column, "page": page + 1},
                )
            )
        if nav:
            rows.append(nav)
        rows += await self.dispatcher.navigation(update, {"project_id": pid}, kind="wi_project")
        text = f"{column} · 第 {page + 1} 页\n" + (
            "\n".join(f"#{x.id} {x.title}" for x in items[page * 8 : (page + 1) * 8]) or "暂无工单"
        )
        if result.truncated:
            text += "\n列表已达读取上限"
        await self.dispatcher.panel(update, text, rows)
        return "handled"

    async def detail(self, update, payload, *, full=False):
        update["_tg_screen"] = ("wi_full" if full else "wi_detail", payload)
        await self.owner(update)
        pid, ident = payload["project_id"], payload["id"]
        if type(ident) is not int or not 1 <= ident <= 2147483647:
            return "ignored"
        item = await self.service.detail(pid, ident)
        await self.owner(update)
        text = [
            f"#{item.id} {item.title}",
            f"状态：{item.state or '未提供'}",
            f"类型：{item.type or '未提供'}",
            f"指派：{item.assigned_to or '未指派'}",
            f"优先级：{item.priority if item.priority is not None else '未提供'}",
            f"Area：{item.area_path or '未提供'}",
            "Tags：" + "、".join(item.tags),
            item.web_url,
        ]
        if full:
            images, skipped = [], 0
            for name, field in item.html:
                if field is None:
                    continue
                if field.omitted:
                    text.append(f"{name}：正文过大，已省略")
                    continue
                parser = Content()
                parser.feed(field.html or "")
                text.append(parser.text)
                images.extend(parser.images)
                skipped += parser.blocked
            for attachment in item.attachments:
                if attachment.is_image:
                    if attachment.media_id:
                        images.append(attachment.media_id)
                    else:
                        skipped += 1
            unique = list(dict.fromkeys(images))
            accepted, total = [], 0
            for index, media_id in enumerate(unique):
                if index >= 10:
                    skipped += 1
                    continue
                try:
                    body, _, entry = await self.service.fetch_media(media_id)
                    await self.owner(update)
                    mime = image_type(body)
                    if (
                        entry.project_id != pid
                        or mime not in {"image/png", "image/jpeg", "image/gif", "image/webp"}
                        or len(body) > 5 * 1024 * 1024
                        or total + len(body) > 20 * 1024 * 1024
                    ):
                        skipped += 1
                        continue
                    total += len(body)
                    suffix = {
                        "image/png": "png",
                        "image/jpeg": "jpg",
                        "image/gif": "gif",
                        "image/webp": "webp",
                    }[mime]
                    accepted.append((f"image{index}.{suffix}", body, mime))
                except SettingsError as exc:
                    if exc.code == "validation_error":
                        raise
                    skipped += 1
            await self.owner(update)
            if accepted:
                if self.dispatcher.service.client is None:
                    text.append("图片发送结果需要核实")
                else:
                    try:
                        await self.dispatcher.service.client.upload_media(
                            self.chat(update), accepted
                        )
                    except TelegramError:
                        # No media retry after an ambiguous remote side effect.
                        text.append("图片发送失败或结果需要核实，请勿重复发送")
            if skipped:
                text.append(f"{skipped} 张图片未发送")
        rows = [
            [
                await self.button(update, "📄 全文", "full", payload),
                await self.button(update, "🔗 关联项", "related", payload),
            ],
            [
                await self.button(update, "🔍 AI 分析", "ai", payload),
                await self.button(update, "📋 复制提示词", "cp", payload),
            ],
        ]
        if full:
            rows += await self.dispatcher.fallback_navigation(update)
            await self.dispatcher.service.reply(
                update,
                "\n".join(text),
                reply_markup={"inline_keyboard": rows},
                panel=True,
                chunk_size=3900,
            )
        else:
            await self.dispatcher.panel(update, "\n".join(text), rows)
        return "handled"

    async def related(self, update, payload):
        await self.owner(update)
        pid, ident = payload["project_id"], payload["id"]
        item = await self.service.detail(pid, ident)
        await self.owner(update)
        ids = list(dict.fromkeys(([item.parent_id] if item.parent_id else []) + item.child_ids))
        page = min(max(payload.get("page", 0), 0), max(0, (len(ids) - 1) // 8))
        visible = ids[page * 8 : (page + 1) * 8]
        rows = [
            [
                await self.button(
                    update,
                    f"📋 工单 #{ident}",
                    "detail",
                    {"project_id": pid, "id": ident, "_back": payload},
                )
            ]
            for ident in visible
        ]
        nav = []
        for label, number in (("⬅️ 上一页", page - 1), ("下一页 ➡️", page + 1)):
            if 0 <= number * 8 < len(ids):
                nav.append(await self.button(update, label, "related", {**payload, "page": number}))
        if nav:
            rows.append(nav)
        lines = [f"#{item.id} 关联项 · 第 {page + 1} 页"] + [f"工单 #{ident}" for ident in visible]
        lines += [f"{link.kind}：{link.label}" for link in item.links]
        await self.dispatcher.panel(update, "\n".join(lines), rows)
        return "handled"

    async def command(self, update):
        try:
            args = update["message"].get("text", "").split()
            if len(args) == 1:
                await self.projects(update)
                return
            if (
                len(args) != 2
                or not re.fullmatch(r"[1-9][0-9]{0,9}", args[1])
                or int(args[1]) > 2147483647
            ):
                await self.dispatcher.panel(update, "用法：/wi 或 /wi <工单编号>")
                return
            state = self.state.get(self.chat(update))
            config = await self.owner(update)
            pid = state["project_id"] if state else config.ado.active_project_id
            if pid is None and len(config.ado.projects) == 1:
                pid = config.ado.projects[0].id
            if pid is None:
                await self.projects(update)
                return
            await self.detail(update, {"project_id": pid, "id": int(args[1])})
        except SettingsError as exc:
            await self.error(update, exc)

    async def error(self, update, exc):
        self.dispatcher.service.ensure_attached()
        config = await self.dispatcher.service.config_store.read()
        if self.dispatcher.role(config, update)[0] != "owner":
            return
        category = exc.extra.get("category", exc.code)
        from toolbox_backend.services.telegram_ai import ERRORS as AI_ERRORS

        fallback = AI_ERRORS.get(exc.code, "工单读取失败，请稍后重试")
        await self.dispatcher.panel(update, ADO_ERRORS.get(category, fallback))

    # ---- AI analysis and prompt copy (S5-C; main slot, owner only) ------------------------

    def ai_slot(self, profile):
        """The AI bot slot that carries this profile's output, or None (desktop only)."""
        registry = self.dispatcher.service.registry
        slot = registry.get(f"ai:{profile.id}") if profile.id in AI_IDS else None
        live = slot is not None and slot.task is not None and slot.bot_id and not slot._closing
        return slot if live else None

    async def ai_flow(self, update, kind, payload, token):
        ai = self.dispatcher.service.ai
        config = await self.owner(update)
        pid, ident = payload.get("project_id"), payload.get("id")
        if (
            ai is None
            or type(ident) is not int
            or not 1 <= ident <= 2147483647
            or pid not in {p.id for p in config.ado.projects}
        ):
            return "ignored"
        base = {"project_id": pid, "id": ident}
        repos = {r.id: r.name for r in config.ado.local_repos}
        if kind == "wi_ai":
            if not repos:
                await self.dispatcher.panel(update, "尚未配置本地仓库，请先在桌面端添加")
                return "handled"
            rows = [
                [await self.button(update, "📦 " + name[:48], "air", {**base, "repo_id": rid})]
                for rid, name in list(repos.items())[:8]
            ]
            await self.dispatcher.panel(update, f"工单 #{ident}：选择分析用的本地仓库", rows)
            return "handled"
        if kind == "wi_cp":
            return await self.copy_prompt(update, config, base, payload.get("cli"))
        rid = payload.get("repo_id")
        if rid not in repos:
            await self.dispatcher.panel(update, "本地仓库不存在")
            return "handled"
        profiles = ai.runnable_profiles(config)
        if kind == "wi_air":
            if not profiles:
                await self.dispatcher.panel(update, "没有可运行的 AI，请先在桌面端配置")
                return "handled"
            rows = []
            for profile in profiles[:8]:
                label = profile.name[:40]
                if self.ai_slot(profile) is None:
                    label += "（仅桌面可见）"
                rows.append(
                    [
                        await self.button(
                            update, label, "aip", {**base, "repo_id": rid, "profile_id": profile.id}
                        )
                    ]
                )
            await self.dispatcher.panel(update, f"工单 #{ident}：选择 AI", rows)
            return "handled"
        profile = next((p for p in profiles if p.id == payload.get("profile_id")), None)
        if profile is None:
            await self.dispatcher.panel(update, "该 AI 不可运行")
            return "handled"
        if kind == "wi_aip":
            slot = self.ai_slot(profile)
            where = (
                f"输出将发到 @{slot.bot_username or '该 AI 机器人'}"
                if slot is not None
                else "对应 AI 机器人未启用，仅可在桌面 AI 会话页查看"
            )
            confirm = await self.button(
                update, "✅ 确认分析", "aic", {**base, "repo_id": rid, "profile_id": profile.id}
            )
            cancel = await self.button(
                update,
                "✖️ 取消",
                "menu_cancel",
                {**base, "repo_id": rid, "confirm_token": confirm["callback_data"]},
            )
            await self.dispatcher.panel(
                update,
                f"将用 {profile.name} 在仓库 {repos[rid]} 以只读分析档分析工单 #{ident}\n{where}",
                [[confirm, cancel]],
            )
            return "handled"
        # wi_aic: execute. The request id derives from the single-use token.
        from toolbox_backend.api.ai_schemas import AnalysisRequest
        from toolbox_backend.services.telegram_ai import short
        from toolbox_backend.services.telegram_commands import TG_NAMESPACE

        _, _, chat, user, _, _ = identities_of(update)
        service = self.dispatcher.service

        def authorize(c):
            return (
                service.attached()
                and not service._closing
                and c.telegram.control.enabled
                and c.telegram.owner.chat_id == chat
            )

        body = AnalysisRequest(
            request_id=uuid.uuid5(TG_NAMESPACE, token),
            project_id=pid,
            repo_id=rid,
            profile_id=profile.id,
            ack_high_risk=False,
        )
        origin = {"kind": "telegram", "bot_id": service.bot_id, "chat_id": chat, "user_id": user}
        view = await ai.analyze(self.service, ident, body, origin=origin, authorize=authorize)
        slot = self.ai_slot(profile)
        if slot is not None and slot.projector is not None:
            slot.focus[chat] = view.id
            slot.projector.bind(
                view.id, profile.id, chat, user, bot_id=slot.bot_id, since_seq=0, origin=True
            )
            bot = slot.bot_username or "该 AI 机器人"
            await self.dispatcher.panel(
                update,
                f"已创建会话（#{short(view.id)}），回复将发到 @{bot}",
            )
        else:
            await self.dispatcher.panel(update, f"已在桌面 AI 会话页创建（#{short(view.id)}）")
        return "handled"

    async def copy_prompt(self, update, config, base, cli):
        ai = self.dispatcher.service.ai
        if cli not in {"claude", "codex", "agy"}:
            from toolbox_backend.services.ai_sessions import parse_profile_safe

            selected = next(
                (
                    p
                    for p in map(parse_profile_safe, config.ai.profiles)
                    if p is not None and p.id == config.ai.selected_profile_id
                ),
                None,
            )
            cli = selected.cli if selected is not None and selected.cli != "other" else "claude"
        result = await ai.prompt(self.service, base["id"], base["project_id"], cli)
        rows = [
            [
                await self.button(update, label, "cp", {**base, "cli": name})
                for label, name in (
                    ("Claude 版", "claude"),
                    ("Codex 版", "codex"),
                    ("agy 版", "agy"),
                )
                if name != cli
            ]
        ]
        rows += await self.dispatcher.navigation(update, base, kind="wi_detail")
        # 配置名称按纯文本发送，避免被解释成 Markdown。
        await self.dispatcher.service.reply(
            update,
            result["prompt"],
            reply_markup={"inline_keyboard": rows},
            panel=True,
            chunk_size=3900,
        )
        return "handled"

    async def callback(self, update, kind, payload, token=None):
        try:
            if kind == "wi_menu_cancel":
                _, _, chat, user, _, _ = identities_of(update)
                done = await self.dispatcher.service.store.cancel_action(
                    payload.get("confirm_token"), self.dispatcher.service.bot_id, chat, user
                )
                await self.dispatcher.panel(update, "已取消" if done else "确认已处理")
                return "handled"
            if kind == "wi_projects":
                await self.projects(update, payload.get("page", 0))
            elif kind == "wi_project":
                await self.columns(update, payload["project_id"])
            elif kind in {"wi_column", "wi_page"}:
                return await self.listing(update, payload)
            elif kind in {"wi_detail", "wi_full"}:
                return await self.detail(update, payload, full=kind == "wi_full")
            elif kind == "wi_related":
                return await self.related(update, payload)
            elif kind in {"wi_ai", "wi_air", "wi_aip", "wi_aic", "wi_cp"}:
                return await self.ai_flow(update, kind, payload, token)
            else:
                return "ignored"
            return "handled"
        except SettingsError as exc:
            await self.error(update, exc)
            return "failed"
