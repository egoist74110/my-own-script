"""Telegram AI bots: private-owner session menu/wizard and the event projector (D11).

Everything a button does is a server-side action token (S4 ``tg_actions``) whose payload is
re-validated when it is confirmed; callback data never carries parameters. AI slots know exactly
one principal: the owner in a private chat. High-permission profiles are not offered, and a
payload carrying one is refused even though only this module can mint payloads.
"""

import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import ValidationError

from toolbox_backend.adapters.ai_store import TERMINAL
from toolbox_backend.api.ai_schemas import (
    ApprovalDecision,
    ResumeRequest,
    SendMessage,
    SessionCreate,
)
from toolbox_backend.domain.ai import AIProfile, validate_model
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.telegram import numeric
from toolbox_backend.logging_setup import redact_exception

logger = logging.getLogger(__name__)

TG_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "toolbox-next:telegram")
# The only choices Telegram can offer. Anything else (bypassPermissions, danger-full-access,
# agy auto) is desktop-only and refused here even for a hand-built payload.
TG_CLAUDE_PERMISSIONS = ("auto", "acceptEdits", "plan", "manual", "dontAsk")
TG_CODEX_SANDBOXES = ("read-only", "workspace-write")
TG_CODEX_EFFORTS = ("minimal", "low", "medium", "high")
TG_AGY_MODES = ("sandbox", "plan")
PERMISSION_LABELS = {
    "auto": "自动（默认）",
    "acceptEdits": "自动接受编辑",
    "plan": "仅规划",
    "manual": "每次审批",
    "dontAsk": "不询问（拒绝未放行）",
}
STATE_LABELS = {
    "starting": "启动中",
    "idle": "空闲",
    "busy": "运行中",
    "awaiting_approval": "等待审批",
    "closing": "关闭中",
}
ERRORS = {
    "ai_session_limit": "AI 会话数量已达上限",
    "ai_queue_full": "会话队列已满，请稍后",
    "cli_not_found": "未找到该 AI 的可执行文件",
    "repo_missing": "本地仓库不存在",
    "session_ended": "该会话已结束",
    "session_active": "会话仍在运行",
    "high_risk_ack_required": "该档位仅桌面可用",
    "validation_error": "操作无效或权限已变化",
    "ai_store_unavailable": "AI 数据库不可用",
    "not_found": "会话不存在",
    "unsupported_cli": "该 AI 配置不支持结构化会话",
    "resume_unavailable": "该会话无法续聊",
    "telegram_store_unavailable": "Telegram 数据库不可用",
    "store_unavailable": "配置数据库不可用",
    "busy": "忙，请稍后重试",
}
FAIL_CATEGORIES = {
    "timeout": "超时",
    "exit": "进程异常退出",
    "cli_error": "CLI 报告错误",
    "process_exited": "进程已退出",
    "start_failed": "无法启动",
    "internal": "内部错误",
    "interrupted": "已中断",
}
END_REASONS = {
    "user_closed": "已关闭",
    "process_exited": "进程已退出",
    "interrupted_on_exit": "应用退出",
    "backend_restart": "后端重启",
    "start_failed": "启动失败",
    "limit": "空闲超时",
}
ACTION_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
SESSION_RE = re.compile(r"^ais_[0-9a-f]{32}$")


def short(sid):
    return sid[4:12]


def identities(update):
    from toolbox_backend.services.telegram import identities as identity

    return identity(update)


def cli_of(profile):
    return profile.cli if isinstance(profile, AIProfile) else None


class AiBotDispatcher:
    """Owner-only private-chat commands, wizard and approval buttons of one AI slot."""

    def __init__(self, service):
        self.service = service
        self.ai_id = service.ai_id

    def close(self):
        pass

    # ---- helpers -------------------------------------------------------------------------

    @property
    def ai(self):
        return self.service.ai

    async def button(self, update, label, kind, payload, ttl=300):
        self.service.ensure_attached()
        _, _, chat, user, _, _ = identities(update)
        token = await self.service.store.action(self.service.bot_id, chat, user, kind, payload, ttl)
        return {"text": label, "callback_data": token}

    async def say(self, update, text, rows=None):
        markup = {"inline_keyboard": rows} if rows else None
        await self.service.reply(update, text, reply_markup=markup)

    async def profile(self):
        config = await self.service.config_store.read()
        from toolbox_backend.services.ai_sessions import find_profile

        try:
            profile = find_profile(config.ai, self.ai_id)
        except SettingsError:
            return config, None
        return config, profile

    def authorizer(self, chat):
        def authorize(config):
            owner = config.telegram.owner.chat_id
            return (
                numeric(owner)
                and owner == chat
                and self.service.control_of(config).enabled
                and self.service.attached()
                and not self.service._closing
            )

        return authorize

    async def own_session(self, sid):
        """The session row if it belongs to this AI bot's profile and is a chat session."""
        if not isinstance(sid, str) or not SESSION_RE.fullmatch(sid):
            return None
        try:
            row = await self.ai.store.get(sid)
        except SettingsError:
            return None
        if row["profile_id"] != self.ai_id or row["kind"] != "chat":
            return None
        return row

    def track(self, row, chat, user, *, origin):
        projector = self.service.projector
        if projector is not None:
            projector.bind(
                row["id"],
                self.ai_id,
                chat,
                user,
                bot_id=self.service.bot_id,
                since_seq=0 if origin else row["last_seq"],
                origin=origin,
            )

    def set_focus(self, chat, sid):
        previous = self.service.focus.get(chat)
        self.service.focus[chat] = sid
        projector = self.service.projector
        if projector is not None and previous and previous != sid:
            projector.unbind(previous, self.ai_id, chat)

    # ---- plain messages -------------------------------------------------------------------

    async def message(self, update, command, text):
        message, _, chat, user, _, _ = identities(update)
        if command in {"/start", "/help", "/menu", "/cc"}:
            await self.menu(update)
            return "handled"
        if command.startswith("/"):
            # Tasks, work items, /bind and every other command belong to the main bot.
            return "ignored"
        if not text.strip():
            return "ignored"
        sid = None
        reply = message.get("reply_to_message")
        if isinstance(reply, dict) and type(reply.get("message_id")) is int:
            sid = self.service.reply_map.get((chat, reply["message_id"]))
        sid = sid or self.service.focus.get(chat)
        if not sid:
            await self.menu(update, "尚未聚焦会话，请先选择或新建：")
            return "handled"
        try:
            return await self.prompt(update, sid, text)
        except SettingsError as exc:
            await self.say(update, ERRORS.get(exc.code, "操作失败，请稍后重试"))
            return "failed"

    async def prompt(self, update, sid, text):
        _, _, chat, user, _, _ = identities(update)
        row = await self.own_session(sid)
        if row is None or row["state"] in TERMINAL:
            self.service.focus.pop(chat, None)
            await self.menu(update, "该会话不存在或已结束，请重新选择：")
            return "handled"
        try:
            body = SendMessage(
                request_id=uuid.uuid5(TG_NAMESPACE, f"{self.service.bot_id}:{update['update_id']}"),
                text=text,
            )
        except ValidationError:
            await self.say(update, "提示词为空或超过 32 KiB")
            return "ignored"
        result = await self.ai.send(sid, body)
        self.set_focus(chat, sid)
        if row["origin_json"] and json.loads(row["origin_json"]).get("kind") != "telegram":
            self.track(row, chat, user, origin=False)
        label = (
            f"已排队（第 {result['position']} 位）" if result["status"] == "queued" else "已发送"
        )
        await self.say(
            update, f"✓ {label} · #{short(sid)}", await self.session_buttons(update, sid)
        )
        return "handled"

    async def session_buttons(self, update, sid, *, stop=True):
        row = (
            [await self.button(update, "⏹ 停止本轮", "ai_stop", {"session_id": sid})]
            if stop
            else []
        )
        row.append(await self.button(update, "🗑 结束", "ai_close", {"session_id": sid}))
        return [row]

    # ---- menu ----------------------------------------------------------------------------

    async def menu(self, update, hint=""):
        _, _, chat, _, _, _ = identities(update)
        config, profile = await self.profile()
        title = profile.name if profile is not None else "AI"
        rows_db = [
            r
            for r in await self.ai.store.list(None, 100)
            if r["profile_id"] == self.ai_id and r["kind"] == "chat" and r["state"] not in TERMINAL
        ][:8]
        repos = {r.id: r.name for r in config.ado.local_repos}
        focused = self.service.focus.get(chat)
        lines = [hint] if hint else []
        lines.append(f"{title} 会话 · 活动 {len(rows_db)} 个")
        if rows_db:
            lines.append("点选会话聚焦后，直接发送文字即可对话；回复某条输出也会发到该会话。")
        buttons = []
        for r in rows_db:
            mark = "▶ " if r["id"] == focused else ""
            label = f"{mark}#{short(r['id'])} {STATE_LABELS.get(r['state'], r['state'])}"
            label += f" · {repos.get(r['repo_id'], '已删除仓库')}"
            buttons.append(
                [
                    await self.button(update, label, "ai_focus", {"session_id": r["id"]}, 3600),
                    await self.button(update, "⏹", "ai_stop", {"session_id": r["id"]}, 3600),
                    await self.button(update, "🗑", "ai_close", {"session_id": r["id"]}, 3600),
                ]
            )
        buttons.append([await self.button(update, "➕ 新建会话", "ai_wiz", {"w": "repo", "a": {}})])
        await self.say(update, "\n".join(lines), buttons)

    # ---- callbacks -----------------------------------------------------------------------

    async def dispatch(self, update, command, role, group):
        try:
            return await self.callback(update)
        except SettingsError as exc:
            await self.say(update, ERRORS.get(exc.code, "操作失败，请稍后重试"))
            return "failed"

    async def callback(self, update):
        _, callback, chat, user, _, _ = identities(update)
        token = callback.get("data")
        if not isinstance(token, str) or not ACTION_RE.fullmatch(token):
            return "ignored"
        store, bot_id = self.service.store, self.service.bot_id
        action = await store.consume(token, bot_id, chat, user)
        if action is None:
            prior = await store.inspect_action(token, bot_id, chat, user)
            if prior is None or prior["consumed_at"]:
                return "ignored"
            await self.say(update, "操作已过期，请发送 /menu 重新打开")
            return "expired"
        role, _ = await self.service.resolve_acl(update)
        if role != "owner":
            return "ignored"
        if self.service.client and isinstance(callback.get("id"), str):
            from toolbox_backend.adapters.telegram_http import TelegramError

            with contextlib.suppress(TelegramError):
                await self.service.client.request(
                    "answerCallbackQuery", {"callback_query_id": callback["id"]}
                )
        kind, payload = action["kind"], action["payload"]
        if not isinstance(payload, dict):
            return "ignored"
        if kind == "ai_menu":
            await self.menu(update)
        elif kind == "ai_focus":
            return await self.focus(update, payload.get("session_id"))
        elif kind == "ai_prompt":
            return await self.focus(update, payload.get("session_id"), ask=True)
        elif kind == "ai_stop":
            return await self.control(update, payload.get("session_id"), "interrupt")
        elif kind == "ai_close":
            return await self.control(update, payload.get("session_id"), "close")
        elif kind == "ai_wiz":
            return await self.wizard(update, token, payload)
        elif kind == "ai_approval":
            return await self.approval(update, payload)
        else:
            return "ignored"
        return "handled"

    async def focus(self, update, sid, *, ask=False):
        _, _, chat, user, _, _ = identities(update)
        row = await self.own_session(sid)
        if row is None or row["state"] in TERMINAL:
            await self.menu(update, "该会话不存在或已结束：")
            return "handled"
        self.set_focus(chat, sid)
        if json.loads(row["origin_json"] or "{}").get("kind") != "telegram":
            self.track(row, chat, user, origin=False)
        text = f"已聚焦 #{short(sid)}，直接发送文字即可对话。"
        await self.say(update, text, await self.session_buttons(update, sid))
        return "handled"

    async def control(self, update, sid, action):
        _, _, chat, _, _, _ = identities(update)
        row = await self.own_session(sid)
        if row is None:
            await self.menu(update, "该会话不存在：")
            return "handled"
        if row["state"] in TERMINAL:
            await self.say(update, f"会话 #{short(sid)} 已结束")
            return "handled"
        await self.ai.command(sid, action)
        if action == "close":
            if self.service.focus.get(chat) == sid:
                self.service.focus.pop(chat, None)
            await self.say(update, f"🗑 已结束 #{short(sid)}")
        else:
            await self.say(update, f"⏹ 已请求停止本轮 #{short(sid)}")
        return "handled"

    # ---- approvals -----------------------------------------------------------------------

    async def approval(self, update, payload):
        _, _, chat, user, _, _ = identities(update)
        sid, aid, decision = (
            payload.get("session_id"),
            payload.get("approval_id"),
            payload.get("decision"),
        )
        # Telegram has no "always allow for this session".
        if decision not in {"allow_once", "deny"} or not isinstance(aid, str):
            return "ignored"
        if await self.own_session(sid) is None:
            return "ignored"
        by = {"kind": "telegram", "bot_id": self.service.bot_id, "chat_id": chat, "user_id": user}
        try:
            await self.ai.decide(
                sid,
                aid,
                ApprovalDecision(decision=decision),
                by=by,
                authorize=self.authorizer(chat),
            )
        except SettingsError as exc:
            text = {
                "approval_settled": "该审批已由另一端处理",
                "approval_expired": "审批已过期，已自动拒绝",
                "not_found": "审批不存在",
            }.get(exc.code, ERRORS.get(exc.code, "审批未生效"))
            await self.say(update, text)
            return "ignored" if exc.code == "validation_error" else "handled"
        await self.say(update, "✅ 已允许一次" if decision == "allow_once" else "❌ 已拒绝")
        return "handled"

    # ---- new-session wizard --------------------------------------------------------------

    async def wizard(self, update, token, payload):
        step, answers = payload.get("w"), payload.get("a")
        if not isinstance(answers, dict) or step not in {
            "repo",
            "cmode",
            "resume",
            "perm",
            "model",
            "effort",
            "sandbox",
            "mode",
            "create",
        }:
            return "ignored"
        config, profile = await self.profile()
        if profile is None or cli_of(profile) not in ("claude", "codex", "agy"):
            await self.say(update, ERRORS["unsupported_cli"])
            return "failed"
        cli = profile.cli
        repos = {r.id: r.name for r in config.ado.local_repos}
        if step != "repo" and answers.get("repo_id") not in repos:
            await self.say(update, ERRORS["repo_missing"])
            return "failed"
        if step == "repo":
            return await self.pick_repo(update, repos, cli)
        if step == "create":
            return await self.create(update, token, cli, answers, config)
        if not self.valid_answers(cli, answers):
            return "ignored"
        if step == "cmode":
            rows = [
                [await self.button(update, "全新会话", "ai_wiz", {"w": "perm", "a": answers})],
                [await self.button(update, "续聊", "ai_wiz", {"w": "resume", "a": answers})],
            ]
            await self.say(update, f"仓库：{repos[answers['repo_id']]}\n选择会话方式：", rows)
        elif step == "resume":
            found = await self.ai.resume_candidates(answers["repo_id"], "claude", "")
            rows = []
            for item in found["items"][:10]:
                rows.append(
                    [
                        await self.button(
                            update,
                            item["title"][:48],
                            "ai_wiz",
                            {"w": "perm", "a": {**answers, "resume": item["session_id"]}},
                        )
                    ]
                )
            rows.append(
                [await self.button(update, "改为全新会话", "ai_wiz", {"w": "perm", "a": answers})]
            )
            await self.say(
                update,
                "选择要续聊的 Claude 会话：" if len(rows) > 1 else "该仓库暂无可续聊的会话",
                rows,
            )
        elif step == "perm":
            rows = [
                [
                    await self.button(
                        update,
                        PERMISSION_LABELS[p],
                        "ai_wiz",
                        {"w": "create", "a": {**answers, "permission": p}},
                    )
                ]
                for p in TG_CLAUDE_PERMISSIONS
            ]
            await self.say(update, "选择权限档（高权限档仅桌面可用）：", rows)
        elif step == "model":
            models = (
                (await self.ai.agy_models())["items"]
                if cli == "agy"
                else list(getattr(config.ai.model_presets, cli))
            )
            models = [m for m in models if self.model_ok(m)][:8]
            nxt = "effort" if cli == "codex" else "mode"
            rows = [
                [
                    await self.button(
                        update, "默认模型", "ai_wiz", {"w": nxt, "a": {**answers, "model": None}}
                    )
                ]
            ]
            for model in models:
                rows.append(
                    [
                        await self.button(
                            update, model, "ai_wiz", {"w": nxt, "a": {**answers, "model": model}}
                        )
                    ]
                )
            await self.say(update, "选择模型：", rows)
        elif step == "effort":
            rows = [
                [
                    await self.button(
                        update, e, "ai_wiz", {"w": "sandbox", "a": {**answers, "effort": e}}
                    )
                ]
                for e in TG_CODEX_EFFORTS
            ]
            await self.say(update, "选择思考强度：", rows)
        elif step == "sandbox":
            rows = [
                [
                    await self.button(
                        update, s, "ai_wiz", {"w": "create", "a": {**answers, "sandbox": s}}
                    )
                ]
                for s in TG_CODEX_SANDBOXES
            ]
            await self.say(update, "选择沙箱（完全放开仅桌面可用）：", rows)
        elif step == "mode":
            rows = [
                [
                    await self.button(
                        update, m, "ai_wiz", {"w": "create", "a": {**answers, "mode": m}}
                    )
                ]
                for m in TG_AGY_MODES
            ]
            await self.say(update, "选择模式（auto 仅桌面可用）：", rows)
        return "handled"

    @staticmethod
    def model_ok(model):
        try:
            return model is None or bool(validate_model(model))
        except ValueError:
            return False

    @classmethod
    def valid_answers(cls, cli, a):
        """Defence in depth: only values the wizard itself can offer are accepted."""
        known = {"repo_id", "resume", "permission", "model", "effort", "sandbox", "mode"}
        if set(a) - known:
            return False
        if not cls.model_ok(a.get("model")):
            return False
        resume = a.get("resume")
        if resume is not None and (cli != "claude" or not isinstance(resume, str)):
            return False
        if "permission" in a and (cli != "claude" or a["permission"] not in TG_CLAUDE_PERMISSIONS):
            return False
        if "sandbox" in a and (cli != "codex" or a["sandbox"] not in TG_CODEX_SANDBOXES):
            return False
        if "effort" in a and (cli != "codex" or a["effort"] not in TG_CODEX_EFFORTS):
            return False
        return not ("mode" in a and (cli != "agy" or a["mode"] not in TG_AGY_MODES))

    async def pick_repo(self, update, repos, cli):
        if not repos:
            await self.say(update, "尚未配置本地仓库，请先在桌面端添加")
            return "handled"
        nxt = "cmode" if cli == "claude" else "model"
        rows = [
            [await self.button(update, name[:48], "ai_wiz", {"w": nxt, "a": {"repo_id": rid}})]
            for rid, name in list(repos.items())[:8]
        ]
        await self.say(update, "选择本地仓库：", rows)
        return "handled"

    async def create(self, update, token, cli, a, config):
        _, _, chat, user, _, _ = identities(update)
        if not self.valid_answers(cli, a):
            return "ignored"
        required = {"claude": "permission", "codex": "sandbox", "agy": "mode"}[cli]
        if required not in a or (cli == "codex" and "effort" not in a):
            return "ignored"
        resume = ResumeRequest(external_id=a["resume"]) if a.get("resume") else None
        try:
            body = SessionCreate(
                request_id=uuid.uuid5(TG_NAMESPACE, token),
                kind="chat",
                profile_id=self.ai_id,
                repo_id=a["repo_id"],
                model=a.get("model"),
                effort=a.get("effort"),
                permission=a[required],
                resume=resume,
                ack_high_risk=False,
            )
        except ValidationError:
            return "ignored"
        origin = {
            "kind": "telegram",
            "bot_id": self.service.bot_id,
            "chat_id": chat,
            "user_id": user,
        }
        view = await self.ai.create(body, origin=origin, authorize=self.authorizer(chat))
        row = await self.ai.store.get(view.id)
        self.set_focus(chat, view.id)
        self.track(row, chat, user, origin=True)
        text = (
            f"已创建会话 #{short(view.id)}（{view.repo.name} · {a[required]}），"
            "直接发送文字开始对话。"
        )
        await self.say(update, text, await self.session_buttons(update, view.id))
        return "handled"


# ---- projector ---------------------------------------------------------------------------


@dataclass
class Entry:
    user_id: str
    bot_id: str
    since_seq: int = 0
    origin: bool = False


@dataclass
class Batch:
    deadline: float
    items: list = field(default_factory=list)
    last_seq: int = 0


class AiTelegramProjector:
    """Session events -> outbox rows. ``offer`` is synchronous and never blocks a session."""

    IGNORED = frozenset({"thinking", "init", "notice", "turn_started", "error"})

    def __init__(self, config_store, slots, *, tool_window_s=3.0, queue_size=8192):
        self.config_store = config_store
        self.slots = slots
        self.tool_window_s = tool_window_s
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.interest = {}
        self.batches = {}
        self.dropped = 0
        self._owner = (0.0, None)
        self._task = None
        self._closed = False

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def close(self):
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self.interest.clear()
        self.batches.clear()
        while not self.queue.empty():
            self.queue.get_nowait()

    # registry (event loop only) ---------------------------------------------------------

    def bind(self, sid, ai_id, chat, user_id, *, bot_id, since_seq=0, origin=False):
        if self._closed:
            return
        entries = self.interest.setdefault(sid, {})
        if (ai_id, chat) not in entries and len(self.interest) > 256:
            self.interest.pop(next(iter(self.interest)), None)
        entries[(ai_id, chat)] = Entry(user_id, bot_id, since_seq, origin)

    def unbind(self, sid, ai_id, chat):
        entries = self.interest.get(sid)
        if entries and (ai_id, chat) in entries and not entries[(ai_id, chat)].origin:
            del entries[(ai_id, chat)]
            if not entries:
                del self.interest[sid]

    def offer(self, event):
        if (
            self._closed
            or event.get("kind") in self.IGNORED
            or event["session_id"] not in self.interest
        ):
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1

    # consumer -----------------------------------------------------------------------------

    async def _run(self):
        while True:
            timeout = None
            if self.batches:
                timeout = max(
                    0.0, min(b.deadline for b in self.batches.values()) - time.monotonic()
                )
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout)
            except TimeoutError:
                event = None
            try:
                if event is not None:
                    await self._handle(event)
                await self._flush_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A failing Telegram side must never be able to stop or slow a session.
                logger.error("ai projection failed type=%s", type(exc).__name__)

    async def _owner_chat(self):
        now = time.monotonic()
        if now >= self._owner[0]:
            try:
                config = await self.config_store.read()
                chat = config.telegram.owner.chat_id
            except SettingsError:
                chat = None
            self._owner = (now + 2.0, chat if numeric(chat) else None)
        return self._owner[1]

    def _live(self, ai_id, chat, entry, owner):
        slot = self.slots.get(ai_id)
        return (
            slot is not None
            and slot.task is not None
            and not slot._closing
            and slot.bot_id is not None
            and slot.bot_id == entry.bot_id
            and owner == chat
        )

    async def _handle(self, event):
        sid, kind, seq, payload = (
            event["session_id"],
            event["kind"],
            event["session_seq"],
            event.get("payload") or {},
        )
        entries = self.interest.get(sid)
        if not entries:
            return
        owner = await self._owner_chat()
        for (ai_id, chat), entry in tuple(entries.items()):
            if seq <= entry.since_seq or not self._live(ai_id, chat, entry, owner):
                continue
            slot = self.slots[ai_id]
            key = (sid, ai_id, chat)
            if kind == "tool_use":
                batch = self.batches.get(key)
                if batch is None:
                    batch = self.batches[key] = Batch(time.monotonic() + self.tool_window_s)
                batch.items.append(
                    (str(payload.get("tool", "tool")), str(payload.get("summary", "")))
                )
                batch.last_seq = seq
                continue
            if kind == "tool_result":
                if payload.get("is_error"):
                    await self._flush(key)
                    text = str(payload.get("text") or "工具执行失败")[:500]
                    await slot.enqueue(
                        chat,
                        f"ai:{sid}:{seq}",
                        f"⚠ 工具失败 · #{short(sid)}\n{text}",
                        kind="ai_tool",
                    )
                continue
            await self._flush(key)
            if kind == "assistant":
                text = str(payload.get("text") or "").strip()
                if text:
                    await slot.enqueue(chat, f"ai:{sid}:{seq}", text, kind="ai_text")
            elif kind in {"turn_completed", "turn_failed"}:
                await self._turn_end(slot, sid, seq, chat, entry, kind, payload)
            elif kind == "approval":
                await self._approval(slot, sid, seq, chat, entry, payload)
            elif kind == "exit":
                reason = payload.get("ended_reason")
                if reason != "user_closed":
                    label = END_REASONS.get(reason, "已结束")
                    await slot.enqueue(
                        chat,
                        f"ai:{sid}:{seq}",
                        f"🏁 会话 #{short(sid)} 已结束（{label}）",
                        kind="ai_end",
                    )
        if kind == "exit":
            self.interest.pop(sid, None)
            for key in [k for k in self.batches if k[0] == sid]:
                del self.batches[key]

    async def _turn_end(self, slot, sid, seq, chat, entry, kind, payload):
        if kind == "turn_completed":
            text = f"✓ 完成 · #{short(sid)}"
        elif payload.get("status") == "interrupted":
            text = f"⏹ 已中断 · #{short(sid)}"
        else:
            category = FAIL_CATEGORIES.get(
                payload.get("category"), str(payload.get("category") or "未知")
            )
            text = f"❌ 出错（{category}）· #{short(sid)}"
            message = str(payload.get("message") or "")[:200]
            if message:
                text += "\n" + message
        buttons = [
            [
                await self._token(
                    slot, chat, entry, "📝 发提示词", "ai_prompt", {"session_id": sid}, 3600
                ),
                await self._token(
                    slot, chat, entry, "🗑 结束", "ai_close", {"session_id": sid}, 3600
                ),
            ]
        ]
        await slot.enqueue(
            chat, f"ai:{sid}:{seq}", text, kind="ai_end", reply_markup={"inline_keyboard": buttons}
        )

    async def _approval(self, slot, sid, seq, chat, entry, payload):
        state, tool = payload.get("state"), str(payload.get("tool") or "工具")
        if state == "pending":
            try:
                left = (
                    datetime.fromisoformat(str(payload.get("expires_at"))) - datetime.now(UTC)
                ).total_seconds()
            except ValueError:
                return
            if left < 5:
                return
            ttl = int(min(left, 540))
            aid = payload.get("approval_id")
            row = [
                await self._token(
                    slot,
                    chat,
                    entry,
                    "✅ 允许一次",
                    "ai_approval",
                    {"session_id": sid, "approval_id": aid, "decision": "allow_once"},
                    ttl,
                ),
                await self._token(
                    slot,
                    chat,
                    entry,
                    "❌ 拒绝",
                    "ai_approval",
                    {"session_id": sid, "approval_id": aid, "decision": "deny"},
                    ttl,
                ),
            ]
            summary = str(payload.get("summary") or "")[:500]
            text = f"🔐 需要审批 · #{short(sid)}\n工具：{tool}\n{summary}"
            text += f"\n{int(left // 60) + 1} 分钟内未处理将自动拒绝"
            await slot.enqueue(
                chat,
                f"ai:{sid}:{seq}",
                text,
                kind="ai_approval",
                reply_markup={"inline_keyboard": [row]},
            )
        elif payload.get("auto") or payload.get("by") in {"telegram", "rule", "system"}:
            return
        elif state == "expired":
            await slot.enqueue(
                chat, f"ai:{sid}:{seq}", f"⌛ 审批已过期（{tool}），已自动拒绝", kind="ai_end"
            )
        elif state in {"allowed", "denied"}:
            word = "允许" if state == "allowed" else "拒绝"
            await slot.enqueue(
                chat, f"ai:{sid}:{seq}", f"ℹ 审批已在桌面处理：{word}（{tool}）", kind="ai_end"
            )

    async def _token(self, slot, chat, entry, label, kind, payload, ttl):
        token = await slot.store.action(slot.bot_id, chat, entry.user_id, kind, payload, ttl)
        return {"text": label, "callback_data": token}

    async def _flush(self, key):
        batch = self.batches.pop(key, None)
        if not batch or not batch.items:
            return
        sid, ai_id, chat = key
        slot = self.slots.get(ai_id)
        if slot is None or slot.task is None:
            return
        tool, summary = batch.items[0]
        text = f"🔧 {tool}: {summary}".strip()[:300]
        if len(batch.items) > 1:
            text += f" 等 {len(batch.items)} 个"
        await slot.enqueue(chat, f"ai:{sid}:{batch.last_seq}", text, kind="ai_tool")

    async def _flush_due(self):
        now = time.monotonic()
        for key in [k for k, b in self.batches.items() if b.deadline <= now]:
            try:
                await self._flush(key)
            except SettingsError:
                logger.error("ai projection flush store_unavailable")
        # Batches whose session lost interest are dropped, not leaked.
        for key in [k for k in self.batches if k[0] not in self.interest]:
            del self.batches[key]


def redacted(text):
    return redact_exception(text)
