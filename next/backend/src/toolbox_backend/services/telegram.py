"""Telegram lifecycle owner, ACL boundary and durable notification sender."""

import asyncio
import json
import logging
import random
import re
import secrets
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from toolbox_backend.adapters.config_store import stamp
from toolbox_backend.adapters.telegram_http import TOKEN_RE, TelegramError, TelegramHTTP
from toolbox_backend.api.settings_schemas import MutationResponse
from toolbox_backend.api.telegram_schemas import TelegramStatusData
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import CredentialMeta
from toolbox_backend.domain.telegram import (
    ACLGroup,
    ACLMember,
    acl_validity,
    as_dict,
    numeric,
    username,
)
from toolbox_backend.logging_setup import contains_secret, redact_exception, register_secret

TOKEN_ACCOUNT = "telegram_bot_token"
AI_IDS = ("claude_code", "codex", "gemini")
RATE_PER_CHAT_S = 1.0
RATE_PER_BOT = (20, 60.0)
NOTIFY_STATES = {"running", "succeeded", "failed", "cancelled", "unknown", "manual_required"}


@dataclass
class HandlerScope:
    detached: bool = False


def local_clock(timestamp):
    """HH:MM in the machine's local timezone; users read it next to their own clock."""
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%H:%M")


def invalid(message="Telegram 配置无效"):
    return SettingsError("validation_error", message, 422)


def identities(update):
    callback = update.get("callback_query")
    message = (
        callback.get("message", {}) if isinstance(callback, dict) else update.get("message", {})
    )
    message = message if isinstance(message, dict) else {}
    actor = callback.get("from", {}) if isinstance(callback, dict) else message.get("from", {})
    actor = actor if isinstance(actor, dict) else {}
    chat = message.get("chat", {})
    chat = chat if isinstance(chat, dict) else {}
    chat_id, user_id = str(chat.get("id", "")), str(actor.get("id", ""))
    name = actor.get("username")
    un = "@" + name.lower() if isinstance(name, str) else None
    return message, callback, chat_id, user_id, un, chat.get("type") == "private"


class TelegramService:
    def __init__(
        self,
        settings,
        store,
        runs,
        hub,
        *,
        transport=None,
        work_items=None,
        slot="main",
        ai=None,
        mcp=None,
        services=None,
        registry=None,
        projector=None,
    ):
        self.slot = slot
        self.ai_id = slot.split(":", 1)[1] if slot != "main" else None
        self.token_account = TOKEN_ACCOUNT if self.ai_id is None else f"ai_bot_token:{self.ai_id}"
        self.credential_kind = "telegram_bot" if self.ai_id is None else "telegram_ai_bot"
        self.ai = ai
        self.mcp = mcp
        self.services = services
        self.registry = registry if registry is not None else {}
        self.projector = projector
        self.focus = {}
        self.reply_map = {}
        self._sent_chat = {}
        self._sent_bot = []
        self.rate_chat_s, (self.rate_bot_n, self.rate_bot_s) = RATE_PER_CHAT_S, RATE_PER_BOT
        self.settings = settings
        self.config_store = settings.store
        self.store = store
        self.runs = runs
        self.hub = hub
        self.transport = transport
        self.client = None
        self.task = None
        self.bot_id = None
        self.bot_username = None
        self.state = "disabled"
        self.since = stamp()
        self.last_error_category = None
        self.last_poll_at = None
        self.consecutive_failures = 0
        self._control = asyncio.Lock()
        self._bind_code = None
        self._bind_expiry = 0.0
        self._bind_failures = 0
        self._notifications = asyncio.Queue(maxsize=256)
        self._notification_task = None
        self._closing = False
        self._poll_task = None
        self._handlers = set()
        self._detached = set()
        self._handler_scopes = {}
        self._handler_context = ContextVar("telegram_handler_scope", default=None)
        self.checkpoint = lambda _: None
        self._work = None
        self._chat_locks = {}
        self._baseline_delay = None
        from toolbox_backend.services.telegram_commands import TelegramDispatcher

        if self.ai_id is None:
            self.dispatcher = TelegramDispatcher(self, work_items)
        else:
            from toolbox_backend.services.telegram_ai import AiBotDispatcher

            self.dispatcher = AiBotDispatcher(self)

    def control_of(self, config):
        if self.ai_id is None:
            return config.telegram.control
        return getattr(config.ai.bots, self.ai_id)

    def attached(self):
        scope = self._handler_context.get()
        return scope is None or not scope.detached

    def ensure_attached(self):
        if not self.attached():
            raise asyncio.CancelledError

    def status(self, state, category=None):
        from toolbox_backend.domain.models import TelegramStatusEvent

        if (self.state, self.last_error_category) == (state, category):
            return
        self.state, self.last_error_category, self.since = state, category, stamp()
        self.hub.publish(
            TelegramStatusEvent,
            TelegramStatusData(
                state=state, since=self.since, last_error_category=category, slot=self.slot
            ),
        )

    async def initialize(self):
        if self.ai_id is not None:
            # AI slots open nothing until enabled; a store fault surfaces on activation.
            try:
                config = await self.config_store.read()
                if self.control_of(config).enabled:
                    async with self._control:
                        await self._activate(config, restart=True)
            except SettingsError:
                return
            return
        await self.store.initialize(self.slot)
        if self.store.readonly_error:
            self.status("store_unavailable", "store_unavailable")
            return
        self._notification_task = asyncio.create_task(self._notification_loop())
        try:
            config = await self.config_store.read()
            if config.telegram.control.enabled:
                async with self._control:
                    await self._activate(config, restart=True)
        except SettingsError:
            # Settings/store endpoints expose their own fixed errors. No reset on startup.
            return

    async def view(self):
        config = await self.config_store.read()
        tg = config.telegram
        present = bool(await asyncio.to_thread(self.settings._get, self.token_account))
        meta = config.credentials.get(self.token_account)
        _, _, warnings = acl_validity(config)
        if self.store.readonly_error:
            warnings.append("Telegram 数据库不可用")
        if self.consecutive_failures >= 10:
            warnings.append("Telegram 连续请求失败，请检查网络与代理")
        result = dict(
            revision=config.revision,
            control=tg.control.model_dump(),
            bot=dict(
                credential=dict(present=present, source=meta.source if meta else "unknown"),
                bot_id=tg.control.bot_id,
                username=self.bot_username,
            ),
            owner=dict(
                bound=numeric(tg.owner.chat_id), chat_id=tg.owner.chat_id, source=tg.owner.source
            ),
            notify=tg.notify.model_dump(),
            poller=dict(
                state=self.state,
                since=self.since,
                last_poll_at=self.last_poll_at,
                last_error_category=self.last_error_category,
                consecutive_failures=self.consecutive_failures,
            ),
            acl=dict(
                groups=[as_dict(g) for g in tg.acl_groups],
                members=[as_dict(m) for m in tg.acl_members],
                legacy_whitelist=tg.legacy_whitelist,
            ),
            warnings=warnings,
        )
        return json.loads(redact_exception(json.dumps(result)))

    async def ai_view(self):
        config = await self.config_store.read()
        control = self.control_of(config)
        present = bool(await asyncio.to_thread(self.settings._get, self.token_account))
        meta = config.credentials.get(self.token_account)
        result = dict(
            ai_id=self.ai_id,
            slot=self.slot,
            control=dict(
                enabled=control.enabled, enabled_at=control.enabled_at, bot_id=control.bot_id
            ),
            bot=dict(
                credential=dict(present=present, source=meta.source if meta else "unknown"),
                bot_id=control.bot_id,
                username=self.bot_username or control.username,
            ),
            owner=dict(
                bound=numeric(config.telegram.owner.chat_id),
                chat_id=config.telegram.owner.chat_id,
                source=config.telegram.owner.source,
            ),
            poller=dict(
                state=self.state,
                since=self.since,
                slot=self.slot,
                last_poll_at=self.last_poll_at,
                last_error_category=self.last_error_category,
                consecutive_failures=self.consecutive_failures,
            ),
        )
        return json.loads(redact_exception(json.dumps(result)))

    def inactive(self, config):
        if self.control_of(config).enabled:
            raise SettingsError("telegram_active", "请先停用 Telegram")

    async def token(self, revision, value=None, *, legacy=False, delete=False):
        async with self._control:
            if legacy:
                config = await self.config_store.read()
                self.inactive(config)
                try:
                    value = await asyncio.to_thread(self.settings.legacy.get, self.token_account)
                except Exception:
                    raise SettingsError("credential_backend_error", "旧凭据读取失败", 502) from None
                if value:
                    register_secret(value)
                else:
                    raise SettingsError("legacy_missing", "旧 Bot 凭据不存在", 404)
            if not delete and (not isinstance(value, str) or not TOKEN_RE.fullmatch(value)):
                raise invalid("Bot Token 格式无效")
            if value:
                register_secret(value)

            def operation(tx):
                self.inactive(tx.config)
                source = "imported" if legacy else "manual"
                old = self.settings._get(self.token_account)
                if delete:

                    def pending(c):
                        c.credentials[self.token_account] = CredentialMeta(
                            kind=self.credential_kind,
                            ref=self.ai_id or self.token_account,
                            source=source,
                            updated_at=stamp(),
                            state="pending_delete",
                        )

                    tx.commit(pending)
                    self.settings._delete(self.token_account)
                    tx.commit(lambda c: c.credentials.pop(self.token_account, None))
                else:
                    self.settings._set(self.token_account, value)

                    def record(c):
                        c.credentials[self.token_account] = CredentialMeta(
                            kind=self.credential_kind,
                            ref=self.ai_id or self.token_account,
                            source=source,
                            updated_at=stamp(),
                        )

                    try:
                        tx.commit(record)
                    except BaseException:
                        if old is None:
                            self.settings._delete(self.token_account)
                        else:
                            self.settings._set(self.token_account, old)
                        raise
                return MutationResponse(revision=tx.config.revision)

            return await self.config_store.run(revision, operation)

    async def _open_client(self):
        value = await asyncio.to_thread(self.settings._get, self.token_account)
        if not value:
            raise SettingsError("no_credential", "请先录入 Bot Token")
        self.client = TelegramHTTP(value, transport=self.transport)

    def claimed_elsewhere(self, config, bot_id):
        """True when another enabled slot is registered for this bot id (single writer view)."""
        others = [("main", config.telegram.control)] + [
            (f"ai:{i}", getattr(config.ai.bots, i)) for i in AI_IDS
        ]
        return any(
            slot != self.slot and ctl.enabled and ctl.bot_id == bot_id for slot, ctl in others
        )

    async def _activate(self, config, *, restart=False, delete_webhook=False):
        await self.store.initialize(self.slot)
        if self.store.readonly_error:
            self.status("store_unavailable", "store_unavailable")
            raise SettingsError("telegram_store_unavailable", "Telegram 数据库不可用", 503)
        self.status("starting")
        enabled_committed = False
        try:
            await self._open_client()
            me = await self.client.request("getMe")
            if not isinstance(me, dict) or type(me.get("id")) is not int:
                raise TelegramError("bad_response")
            self.bot_id = str(me["id"])
            name = me.get("username")
            self.bot_username = (
                name
                if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_]{5,32}", name)
                else None
            )
            info = await self.client.request("getWebhookInfo")
            if not isinstance(info, dict):
                raise TelegramError("bad_response")
            if info.get("url") and not delete_webhook:
                self.status("webhook_set", "webhook_set")
                raise SettingsError("webhook_set", "Bot 已设置 webhook，需显式确认删除")
            if delete_webhook:
                await self.client.request("deleteWebhook", {"drop_pending_updates": False})
            bot = await self.store.bot(self.bot_id, self.bot_username, self.slot)
            if not restart:

                def enabled(c):
                    if self.claimed_elsewhere(c, self.bot_id):
                        raise SettingsError("bot_in_use", "该 Bot 已被另一个槽位使用")
                    ctl = self.control_of(c)
                    ctl.enabled = True
                    ctl.enabled_at = stamp()
                    ctl.bot_id = self.bot_id
                    if self.ai_id is not None:
                        ctl.username = self.bot_username

                config = await self.config_store.update(config.revision, enabled)
            elif self.control_of(config).bot_id != self.bot_id:
                raise SettingsError("no_credential", "Bot 身份已变化，请停用后重新启用")
            elif any(
                p.slot != self.slot and p.bot_id == self.bot_id and p.task is not None
                for p in self.registry.values()
            ):
                self.status("conflict", "bot_in_use")
                raise SettingsError("bot_in_use", "该 Bot 已被另一个槽位使用")
            if self.ai_id is not None:
                await self.store.drop_pending_ai(self.bot_id)
            enabled_committed = True
            if not bot["baseline_done"]:
                await self._baseline()
            self.task = asyncio.create_task(self._session())
            return MutationResponse(revision=config.revision)
        except TelegramError as exc:
            self._error_state(exc)
            if enabled_committed and exc.category not in {"conflict", "unauthorized"}:
                self.consecutive_failures += 1
                self._baseline_delay = self.backoff(self.consecutive_failures, exc.retry_after)
                self.task = asyncio.create_task(self._session())
            else:
                await self._cleanup()
            raise SettingsError(
                "telegram_request_failed", "Telegram 请求失败", 502, category=exc.category
            ) from None
        except BaseException as exc:
            if isinstance(exc, SettingsError) and exc.code == "telegram_store_unavailable":
                self.status("store_unavailable", "store_unavailable")
            elif self.state == "starting":
                self.status("backoff", "interrupted") if enabled_committed else self.status(
                    "disabled"
                )
            await self._cleanup()
            raise

    async def enable(self, body):
        if not body.ack_old_bot_stopped:
            raise SettingsError("ack_required", "请确认旧 Bot 已停止轮询")
        async with self._control:
            config = await self.config_store.read()
            if config.revision != body.revision:
                raise SettingsError("revision_conflict", "配置已更新", revision=config.revision)
            if self.control_of(config).enabled:
                raise SettingsError("telegram_active", "Telegram 已启用，请先停用")
            return await self._activate(config, delete_webhook=body.delete_webhook)

    async def disable(self, revision):
        async with self._control:
            config = await self.config_store.update(
                revision, lambda c: setattr(self.control_of(c), "enabled", False)
            )
            await self._stop()
            self.status("disabled")
            return MutationResponse(revision=config.revision)

    async def retry(self, revision):
        async with self._control:
            config = await self.config_store.read()
            if config.revision != revision:
                raise SettingsError("revision_conflict", "配置已更新", revision=config.revision)
            if self.state not in {"conflict", "backoff"} or not self.control_of(config).enabled:
                raise SettingsError("telegram_active", "当前状态不能重试接管")
            await self._stop()
            try:
                await self.store.initialize(self.slot)
                await self._open_client()
                self.bot_id = self.control_of(config).bot_id
                bot = await self.store.bot(self.bot_id)
                updates = await self.client.request(
                    "getUpdates",
                    {
                        "offset": bot["next_offset"] if bot["baseline_done"] else -1,
                        "timeout": 0,
                        "limit": 100,
                        "allowed_updates": ["message", "callback_query"],
                    },
                )
                if not isinstance(updates, list):
                    raise TelegramError("bad_response")
                if not bot["baseline_done"]:
                    await self._accept_baseline(updates)
                self.task = asyncio.create_task(
                    self._session(updates if bot["baseline_done"] else None)
                )
                return MutationResponse(revision=config.revision)
            except TelegramError as exc:
                self._error_state(exc)
                await self._cleanup()
                raise SettingsError(
                    "telegram_request_failed", "Telegram 请求失败", 502, category=exc.category
                ) from None
            except BaseException:
                await self._cleanup()
                raise

    def _error_state(self, exc):
        self.status(
            "conflict"
            if exc.category == "conflict"
            else "token_invalid"
            if exc.category == "unauthorized"
            else "backoff",
            exc.category,
        )

    async def _session(self, initial_updates=None):
        sender = None
        workers = []
        self._work = asyncio.Queue(maxsize=64)
        try:
            bot = await self.store.bot(self.bot_id)
            if self._baseline_delay is not None:
                delay, self._baseline_delay = self._baseline_delay, None
                await asyncio.sleep(delay)
            while not bot["baseline_done"]:
                try:
                    await self._baseline()
                    bot = await self.store.bot(self.bot_id)
                except TelegramError as exc:
                    self._error_state(exc)
                    if exc.category in {"conflict", "unauthorized"}:
                        return
                    self.consecutive_failures += 1
                    await asyncio.sleep(self.backoff(self.consecutive_failures, exc.retry_after))
            if self.ai_id is None:
                await self.recover_notifications()
            workers = [asyncio.create_task(self._worker()) for _ in range(2)]
            sender = asyncio.create_task(self._send_loop())
            if initial_updates:
                await self.process_updates(initial_updates, queued=True)
            self._poll_task = asyncio.create_task(self._poll())
            done, _ = await asyncio.wait(
                [self._poll_task, sender, *workers], return_when=asyncio.FIRST_COMPLETED
            )
            for completed in done:
                await completed
        except asyncio.CancelledError:
            raise
        except TelegramError as exc:
            self._error_state(exc)
        except Exception as exc:
            self.local_failure(exc)
        finally:
            background = [t for t in (self._poll_task, sender, *workers) if t is not None]
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            if self._handlers:
                handlers = tuple(self._handlers)
                for task in handlers:
                    task.cancel()
                _, pending = await asyncio.wait(handlers, timeout=5)
                for task in pending:
                    self._handler_scopes[task].detached = True
                    self._detached.add(task)
                if pending:
                    logging.getLogger(__name__).warning("Telegram category=detached_after_close")
            self._handlers.clear()
            self._work = None
            self._chat_locks.clear()
            await self._cleanup()

    def _handler_done(self, task):
        self._handlers.discard(task)
        self._detached.discard(task)
        self._handler_scopes.pop(task, None)
        if not task.cancelled():
            task.exception()

    async def _worker(self):
        while True:
            update = await self._work.get()
            task = asyncio.create_task(self._handle_registered(update))
            self._handlers.add(task)
            task.add_done_callback(self._handler_done)
            try:
                await asyncio.shield(task)
            finally:
                self._work.task_done()

    async def _baseline(self):
        updates = await self.client.request(
            "getUpdates",
            {
                "offset": -1,
                "timeout": 0,
                "limit": 100,
                "allowed_updates": ["message", "callback_query"],
            },
        )
        await self._accept_baseline(updates)

    async def _accept_baseline(self, updates):
        if not isinstance(updates, list):
            raise TelegramError("bad_response")
        offset = 0
        for update in updates:
            if not isinstance(update, dict) or type(update.get("update_id")) is not int:
                continue
            uid = update["update_id"]
            await self.store.register(self.bot_id, uid, "other", None, None, None)
            await self.store.finish(self.bot_id, uid, "expired", "baseline")
            offset = max(offset, uid + 1)
        await self.store.baseline(self.bot_id, offset)

    async def _poll(self):
        while True:
            try:
                bot = await self.store.bot(self.bot_id)
                self.status("polling")
                await self.store.set_state(self.bot_id, self.state)
                updates = await self.client.request(
                    "getUpdates",
                    {
                        "offset": bot["next_offset"],
                        "timeout": 25,
                        "limit": 100,
                        "allowed_updates": ["message", "callback_query"],
                    },
                )
                self.last_poll_at = stamp()
                self.consecutive_failures = 0
                await self.process_updates(updates, queued=True)
                # Mock transports may return immediately; yield and avoid a hot loop.
                await asyncio.sleep(0.01)
            except TelegramError as exc:
                self.consecutive_failures += 1
                self._error_state(exc)
                await self.store.set_state(self.bot_id, self.state)
                if exc.category in {"conflict", "unauthorized"}:
                    return
                delay = self.backoff(self.consecutive_failures, exc.retry_after)
                await asyncio.sleep(delay)
            except Exception as exc:
                self.local_failure(exc)
                raise

    def local_failure(self, exc):
        store_error = isinstance(exc, OSError) or (
            isinstance(exc, SettingsError)
            and exc.code
            in {"store_unavailable", "run_store_unavailable", "telegram_store_unavailable"}
        )
        category = "store_unavailable" if store_error else "local_failed"
        self.status("store_unavailable" if store_error else "backoff", category)
        logging.getLogger(__name__).error(
            "Telegram local operation failed category=%s type=%s", category, type(exc).__name__
        )

    @staticmethod
    def backoff(failures, retry_after=None):
        if retry_after is not None:
            return retry_after
        base = (1, 2, 5, 10, 30, 60)[min(max(failures - 1, 0), 5)]
        return min(60, base * random.uniform(0.8, 1.2))

    async def process_updates(self, updates, *, queued=False):
        if not isinstance(updates, list):
            raise TelegramError("bad_response")
        for update in updates:
            if not isinstance(update, dict) or type(update.get("update_id")) is not int:
                continue
            uid = update["update_id"]
            message, callback, chat, user, _, _ = identities(update)
            text = message.get("text", "")
            parts = text.split(maxsplit=1) if isinstance(text, str) else []
            command = parts[0].split("@")[0] if parts else ""
            # Only a white-listed command name is journaled, never text or callback data.
            command = command if re.fullmatch(r"/[a-zA-Z0-9_]{1,32}", command) else None
            kind = "callback" if isinstance(callback, dict) else "message" if message else "other"
            if not await self.store.register(
                self.bot_id,
                uid,
                kind,
                chat if numeric(chat) else None,
                user if numeric(user) else None,
                "callback" if callback else command,
            ):
                continue
            self.checkpoint("registered")
            if queued and self._work is not None:
                try:
                    self._work.put_nowait(update)
                except asyncio.QueueFull:
                    role, _ = await self.resolve_acl(update)
                    if role != "none":
                        await self.reply(update, "忙，请稍后重试")
                    await self.store.finish(self.bot_id, uid, "failed", "busy")
            else:
                await self._handle_registered(update)

    async def _handle_registered(self, update):
        task = asyncio.current_task()
        scope = HandlerScope()
        self._handler_scopes[task] = scope
        context = self._handler_context.set(scope)
        uid = update["update_id"]
        _, _, chat, _, _, _ = identities(update)
        lock, count = self._chat_locks.get(chat, (asyncio.Lock(), 0))
        self._chat_locks[chat] = (lock, count + 1)
        try:
            async with lock:
                try:
                    status = await self.handle_update(update)
                    self.ensure_attached()
                    await self.store.finish(self.bot_id, uid, status or "handled")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    if not scope.detached:
                        await self.store.finish(self.bot_id, uid, "failed", "handler_failed")
        finally:
            # A newer session may already own a different lock for this chat.
            entry = self._chat_locks.get(chat)
            if entry is not None and entry[0] is lock:
                _, count = entry
                if count == 1:
                    del self._chat_locks[chat]
                else:
                    self._chat_locks[chat] = (lock, count - 1)
            self._handler_scopes.pop(task, None)
            self._handler_context.reset(context)

    async def resolve_acl(self, update):
        _, _, chat, user, un, private = identities(update)
        if not numeric(chat) or not numeric(user):
            return "none", None
        config = await self.config_store.read()
        tg = config.telegram
        if private and numeric(tg.owner.chat_id) and chat == tg.owner.chat_id:
            return "owner", None
        if self.ai_id is not None or not tg.owner.chat_id:
            # AI slots only know the private owner; groups, members and legacy entries
            # are none: zero reply, zero side effect.
            return "none", None
        groups, members, _ = acl_validity(config)
        gids = {g.id: g for g in groups}
        for member in members:
            if member.chat_id == chat:
                return "group", gids[member.group_id]
        if private:
            for member in members:
                if member.username is None:
                    continue
                if member.user_id is not None:
                    if member.user_id == user:
                        return "group", gids[member.group_id]
                elif un and member.username.lower() == un:

                    def bind(c, member_id=member.id):
                        # Revalidate under the single writer to prevent binding stale ACL.
                        _, current, _ = acl_validity(c)
                        match = next((m for m in current if m.id == member_id), None)
                        if match is None or match.user_id not in (None, user):
                            raise SettingsError("revision_conflict", "成员已变化")
                        target = next(
                            m
                            for m in c.telegram.acl_members
                            if isinstance(m, ACLMember) and m.id == match.id
                        )
                        target.user_id = user

                    await self.config_store.update(config.revision, bind)
                    return "group", gids[member.group_id]
        for entry in tg.legacy_whitelist:
            if not (numeric(entry) or username(entry)):
                continue
            if (
                sum(isinstance(x, str) and x.lower() == entry.lower() for x in tg.legacy_whitelist)
                != 1
            ):
                continue
            if entry == chat or private and un and entry.lower() == un:
                return "legacy", None
        return "none", None

    async def handle_update(self, update):
        message, callback, chat, user, _, private = identities(update)
        text = message.get("text", "")
        text = text if isinstance(text, str) else ""
        parts = text.split(maxsplit=1)
        command = parts[0].split("@")[0] if parts else ""
        date = message.get("date")
        if self.ai_id is not None:
            role, _ = await self.resolve_acl(update)
            if role == "none":
                return "ignored"
            if isinstance(callback, dict):
                return await self.dispatcher.dispatch(update, command, role, None)
            if type(date) not in (int, float) or not 0 <= date <= 2**40:
                return "ignored"
            if time.time() - date > 300:
                await self.reply(update, f"该消息发送于 {local_clock(date)}，已过期，请重新发送")
                return "expired"
            return await self.dispatcher.message(update, command, text)
        if command.startswith("/") and (type(date) not in (int, float) or not 0 <= date <= 2**40):
            raise TelegramError("bad_response")
        if private and command == "/bind":
            config = await self.config_store.read()
            if not config.telegram.owner.chat_id:
                if time.time() - date > 300:
                    return "ignored"
                if await self._bind(update, text):
                    return "handled"
                return "ignored"
        role, group = await self.resolve_acl(update)
        if role == "none":
            return "ignored"
        if isinstance(callback, dict):
            return await self.dispatcher.dispatch(update, command, role, group)
        if command.startswith("/") and time.time() - date > 300:
            clock = local_clock(date)
            await self.reply(update, f"该指令发送于 {clock}，已过期，请重新发送")
            return "expired"
        if command in {"/help", "/start", "/menu"}:
            pages = (
                [("任务", "tasks")]
                if role == "owner" or (group and (group.can_run or group.can_rollback))
                else []
            )
            if role == "owner":
                pages += [
                    ("回滚", "rollback"),
                    ("停止", "stop"),
                    ("系统操作", "system"),
                    ("工单", "wi"),
                    ("MCP", "mcp"),
                    ("服务", "services"),
                ]
            elif group:
                if group.can_rollback:
                    pages.append(("回滚", "rollback"))
                if group.can_stop:
                    pages.append(("停止", "stop"))
            if role in {"owner", "legacy"} or group and group.can_status:
                pages.append(("状态", "status"))
            buttons = []
            for label, page in pages:
                token = await self.store.action(self.bot_id, chat, user, "menu", {"page": page})
                buttons.append([{"text": label, "callback_data": token}])
            await self.reply(
                update, "请选择菜单", reply_markup={"inline_keyboard": buttons}, panel=True
            )
        elif command == "/status":
            if role == "owner" or role == "legacy" or group and group.can_status:
                await self.reply(update, await self.status_text(role, group, chat))
            else:
                return "ignored"
        elif command in {"/vpn", "/cc", "/svc", "/service", "/cancelrollback"}:
            await self.reply(update, "该功能尚未迁移到新应用")
        else:
            result = await self.dispatcher.dispatch(update, command, role, group)
            if result is not None:
                return result
            await self.reply(update, "暂未开放")
        return "handled"

    async def status_text(self, role, group, chat):
        config = await self.config_store.read()
        visible = (
            {t.id for t in config.tasks.items}
            if role == "owner"
            else (set(group.task_ids) if group else set())
        )
        rows = await asyncio.to_thread(self.runs.store.active_snapshots)
        names = {t.id: t.name for t in config.tasks.items}
        lines = []
        for run in rows:
            origin = run.get("origin", {})
            own = origin.get("kind") == "telegram" and origin.get("chat_id") == chat
            if role == "owner" or run["task_id"] in visible or own:
                lines.append(
                    f"{names.get(run['task_id'], '历史任务')} · {run['status']}"
                    f" · #{run['run_id'][:8]}"
                )
        return "\n".join(lines) or "当前可见范围内没有活动运行"

    async def bind_code(self, revision):
        config = await self.config_store.read()
        if config.revision != revision:
            raise SettingsError("revision_conflict", "配置已更新", revision=config.revision)
        if config.telegram.owner.chat_id:
            raise SettingsError("telegram_active", "请先解绑 owner")
        self._bind_code = f"{secrets.randbelow(1000000):06d}"
        self._bind_expiry, self._bind_failures = time.monotonic() + 600, 0
        return dict(
            code=self._bind_code, expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        )

    async def _bind(self, update, text):
        _, _, chat, user, _, private = identities(update)
        if not private or not numeric(chat) or not numeric(user):
            return False
        if self._bind_code is None or time.monotonic() >= self._bind_expiry:
            self._bind_code = None
            return False
        supplied = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) == 2 else ""
        if not secrets.compare_digest(supplied.encode(), self._bind_code.encode()):
            self._bind_failures += 1
            if self._bind_failures >= 5:
                self._bind_code = None
            return False
        code = self._bind_code
        self._bind_code = None
        config = await self.config_store.read()

        def save(c):
            if c.telegram.owner.chat_id:
                raise SettingsError("revision_conflict", "owner 已绑定")
            c.telegram.owner.chat_id = chat
            c.telegram.owner.source = "bound"
            c.telegram.owner.bound_at = stamp()

        await self.config_store.update(config.revision, save)
        del code
        await self.reply(update, "owner 绑定成功")
        return True

    async def unbind(self, revision):
        self._bind_code = None

        def save(c):
            c.telegram.owner.chat_id = None
            c.telegram.owner.source = None
            c.telegram.owner.bound_at = None

        config = await self.config_store.update(revision, save)
        return MutationResponse(revision=config.revision)

    async def settings_patch(self, body):
        def save(c):
            if body.notify:
                for key, value in body.notify.model_dump(exclude_unset=True).items():
                    if value is None:
                        raise invalid()
                    setattr(c.telegram.notify, key, value)

        config = await self.config_store.update(body.revision, save)
        return MutationResponse(revision=config.revision)

    async def acl(self, kind, revision, fields=None, ident=None, delete=False):
        fields = dict(fields or {})
        patch = ident is not None
        ident = ident or ("acl_group:" if kind == "groups" else "acl_member:") + str(uuid.uuid4())

        def save(c):
            items = c.telegram.acl_groups if kind == "groups" else c.telegram.acl_members
            index = next(
                (
                    i
                    for i, x in enumerate(items)
                    if isinstance(as_dict(x), dict) and as_dict(x).get("id") == ident
                ),
                None,
            )
            if patch and index is None:
                raise SettingsError("not_found", "ACL 条目不存在", 404)
            if delete:
                del items[index]
                if kind == "groups":
                    c.telegram.acl_members = [
                        m
                        for m in c.telegram.acl_members
                        if not isinstance(as_dict(m), dict) or as_dict(m).get("group_id") != ident
                    ]
                return
            prior = as_dict(items[index]) if patch else {}
            candidate = {**prior, **fields, "id": ident}
            if kind == "groups":
                if any(candidate.get(k) is None for k in fields):
                    raise invalid()
                candidate = ACLGroup.model_validate(candidate)
                if (candidate.can_run or candidate.can_rollback) and not candidate.task_ids:
                    raise invalid("可运行或回滚的组至少需要一个任务")
                if any(t not in {t.id for t in c.tasks.items} for t in candidate.task_ids):
                    raise invalid("任务引用不存在")
            else:
                if "username" in fields:
                    candidate["user_id"] = None
                if candidate.get("username"):
                    candidate["username"] = candidate["username"].lower()
                candidate = ACLMember.model_validate(candidate)
            if patch:
                items[index] = candidate
            else:
                items.append(candidate)
            groups, members, _ = acl_validity(c)
            if ident not in {x.id for x in (groups if kind == "groups" else members)}:
                raise invalid("ACL 条目无效、重复或超限")

        try:
            config = await self.config_store.update(revision, save)
        except ValueError:
            raise invalid() from None
        return MutationResponse(revision=config.revision, id=ident)

    async def whitelist(self, body):
        config = await self.config_store.update(
            body.revision,
            lambda c: setattr(c.telegram, "legacy_whitelist", list(body.legacy_whitelist)),
        )
        return MutationResponse(revision=config.revision)

    async def reply(self, update, text, *, reply_markup=None, panel=False, chunk_size=4000):
        self.ensure_attached()
        message, callback, chat, _, _, _ = identities(update)
        mid = message.get("message_id") if panel and isinstance(callback, dict) else None
        mid = mid if type(mid) is int and mid > 0 else None
        await self.enqueue(
            chat,
            f"reply:{update['update_id']}:0",
            text,
            reply_markup=reply_markup,
            edit_message_id=mid,
            chunk_size=chunk_size,
        )

    async def enqueue(
        self,
        chat,
        key,
        text,
        *,
        kind="reply",
        bot_id=None,
        reply_markup=None,
        edit_message_id=None,
        chunk_size=4000,
    ):
        self.ensure_attached()
        category = "redacted" if contains_secret(text) else None
        safe = "内容包含敏感信息，已隐藏" if category else redact_exception(text)
        await self.store.enqueue(
            bot_id or self.bot_id,
            chat,
            key,
            safe,
            kind=kind,
            error_category=category,
            reply_markup=reply_markup if category is None else None,
            edit_message_id=edit_message_id,
            chunk_size=chunk_size,
        )

    async def test_message(self, revision):
        config = await self.config_store.read()
        if config.revision != revision:
            raise SettingsError("revision_conflict", "配置已更新", revision=config.revision)
        if not config.telegram.control.enabled:
            raise SettingsError("telegram_active", "请先启用 Telegram")
        if not numeric(config.telegram.owner.chat_id):
            raise SettingsError("owner_not_bound", "请先绑定 owner")
        await self.enqueue(
            config.telegram.owner.chat_id, "test:" + str(uuid.uuid4()), "Telegram 测试消息"
        )
        return MutationResponse(revision=config.revision)

    def on_run_event(self, event):
        if self._closing or event.get("type") != "state":
            return
        try:
            self._notifications.put_nowait(event)
        except asyncio.QueueFull:
            # Persisted events are the source of truth; recover after the burst.
            self._rescan = True

    async def _notification_loop(self):
        self._rescan = False
        while True:
            event = await self._notifications.get()
            try:
                await self.notify_event(event)
                if self._rescan:
                    self._rescan = False
                    await self.recover_notifications()
            except SettingsError:
                pass  # Durable run events remain available for next enabled-session recovery.
            finally:
                self._notifications.task_done()

    async def notify_event(self, event):
        config = await self.config_store.read()
        if not config.telegram.control.enabled or self.store._db is None:
            return
        payload = event.get("payload", {})
        status = (
            "manual_required"
            if payload.get("recovery_state") == "manual_required"
            else (payload.get("status"))
        )
        if status not in NOTIFY_STATES:
            return
        run = await self.runs.store.get(event["run_id"])
        await self.notify_run(run, status, config)

    async def notify_run(self, run, status, config=None):
        # Serialize notification admission with disable; a stale render snapshot cannot
        # admit new data after the user has transferred Bot ownership.
        async with self._control:
            config = await self.config_store.read()
            await self._notify_run(run, status, config)

    async def _notify_run(self, run, status, config):
        tg, origin = config.telegram, run.get("origin", {"kind": "ui"})
        if not tg.control.enabled:
            return
        chat = (
            origin.get("chat_id")
            if origin.get("kind") == "telegram"
            else (tg.owner.chat_id if tg.notify.ui_runs_to_owner else None)
        )
        if not numeric(chat):
            return
        snapshot = run["task_snapshot"]
        operation = {
            "sync_build_release": "构建发布",
            "deploy_only": "仅发布",
            "rollback": "回滚",
        }.get(run["operation"], "任务")
        icon = {"running": "▶️", "succeeded": "✅", "failed": "❌", "cancelled": "⏹"}.get(
            status, "⚠️"
        )
        name = re.sub(r"https?://\S+", "[链接已隐藏]", snapshot.get("name", "任务"))
        text = f"{icon} {operation} · {name} · 运行 #{run['run_id'][:8]}"
        if status in {"unknown", "manual_required"}:
            text += "\n结果需要核实"
        elif status == "failed":
            text += "\n" + {
                "git_failed": "Git 操作失败",
                "build_failed": "构建失败",
                "release_failed": "发布失败",
                "timeout": "运行超时",
                "local_failed": "本地操作失败",
            }.get(run.get("reason_code"), "任务执行失败")
        if tg.notify.include_details:
            branch = snapshot.get("git_flow", {}).get("build_branch", "")
            targets = [t for t in snapshot.get("targets", []) if t.get("enabled", True)]
            completed = sum(s.get("status") == "succeeded" for s in run.get("steps", []))
            text += f"\n分支：{branch}\n目标数：{len(targets)}\n目标：" + "、".join(
                t.get("name", "") for t in targets
            )
            text += f"\n已完成步骤：{completed}"
            # Only typed checkpoint identifiers, never logs/stderr/arbitrary remote text.
            for step in run.get("steps", []):
                checkpoint = step.get("checkpoint", {})
                if str(checkpoint.get("build_id", "")).isdigit():
                    text += f"\n构建号：{checkpoint['build_id']}"
                if str(checkpoint.get("release_id", "")).isdigit():
                    text += f"\nRelease #{checkpoint['release_id']}"
            text = re.sub(r"https?://\S+", "[链接已隐藏]", text)
            text += self._notification_links(run, config)
        await self.enqueue(
            chat,
            f"run:{run['run_id']}:{status}",
            text,
            kind="notify",
            bot_id=origin.get("bot_id") if origin.get("kind") == "telegram" else None,
        )

    @staticmethod
    def _notification_links(run, config):
        from toolbox_backend.adapters.ado_read import build_url, within

        source = run["task_snapshot"].get("source")
        if not isinstance(source, dict):
            return ""
        library = next(
            (lib for lib in config.ado.libraries if lib.id == source.get("library_id")), None
        )
        project = next((p for p in config.ado.projects if p.id == source.get("project_id")), None)
        if (
            library is None
            or project is None
            or project.library_id != library.id
            or library.base_url != source.get("base_url")
            or project.collection != source.get("collection")
            or project.project != source.get("project")
        ):
            return ""
        links = []
        for step in run.get("steps", []):
            checkpoint = step.get("checkpoint", {})
            for key, path, query in (
                ("build_id", ["_build", "results"], "?buildId="),
                ("release_id", ["_releaseProgress"], "?_a=release-pipeline-progress&releaseId="),
            ):
                ident = str(checkpoint.get(key, ""))
                if not re.fullmatch(r"[1-9][0-9]{0,9}", ident) or int(ident) > 2147483647:
                    continue
                url = (
                    build_url(library, [project.collection, project.project, *path]) + query + ident
                )
                if within(library, url) and url not in links:
                    links.append(url)
        return "".join("\n" + url for url in links)

    async def recover_notifications(self):
        config = await self.config_store.read()
        enabled_at = config.telegram.control.enabled_at
        if not config.telegram.control.enabled or not enabled_at:
            return

        def candidates():
            db = self.runs.store._require()
            rows = db.execute(
                "SELECT run_id,data_json FROM run_events WHERE type='state' "
                "AND ts>=? ORDER BY ts,run_id,seq",
                (enabled_at,),
            ).fetchall()
            return [
                (self.runs.store._get(row["run_id"]), json.loads(row["data_json"])) for row in rows
            ]

        for run, payload in await self.runs.store.call(candidates):
            status = (
                "manual_required"
                if payload.get("recovery_state") == "manual_required"
                else (payload.get("status"))
            )
            if status in NOTIFY_STATES:
                await self.notify_run(run, status, config)

    def rate_blocked(self):
        """(chats sent to within the per-chat interval, seconds until the bot budget frees)."""
        now = time.monotonic()
        self._sent_chat = {c: t for c, t in self._sent_chat.items() if now - t < self.rate_chat_s}
        self._sent_bot = [t for t in self._sent_bot if now - t < self.rate_bot_s]
        wait = 0.0
        if len(self._sent_bot) >= self.rate_bot_n:
            wait = self.rate_bot_s - (now - self._sent_bot[0])
        return tuple(self._sent_chat), wait

    async def send_once(self):
        blocked, wait = self.rate_blocked() if self.ai_id is not None else ((), 0.0)
        if wait > 0:
            return False
        row = await self.store.take(self.bot_id, blocked)
        if row is None:
            return False
        if self.ai_id is not None:
            now = time.monotonic()
            self._sent_chat[row["chat_id"]] = now
            self._sent_bot.append(now)
        try:
            payload = {"chat_id": row["chat_id"], "text": row["text"]}
            if row["reply_markup_json"]:
                payload["reply_markup"] = json.loads(row["reply_markup_json"])
            method = "sendMessage"
            if row["edit_message_id"] is not None:
                method = "editMessageText"
                payload["message_id"] = row["edit_message_id"]
            try:
                result = await self.client.request(method, payload)
            except TelegramError:
                if method != "editMessageText":
                    raise
                # A panel edit failure never retries an execution action. Only its
                # already materialized plain-text reply falls back to a new message.
                payload.pop("message_id", None)
                result = await self.client.request("sendMessage", payload)
            self.remember_message(row, result)
            await self.store.sent(row["id"], "sent")
        except TelegramError as exc:
            age = (datetime.now(UTC) - datetime.fromisoformat(row["created_at"])).total_seconds()
            retry = exc.connect_failed or exc.category == "rate_limited"
            delay = (
                exc.retry_after if exc.retry_after is not None else min(60, 2 ** row["attempts"])
            )
            if retry and row["attempts"] < 5 and age + delay <= 600:
                await self.store.sent(row["id"], "pending", exc.category, delay)
            else:
                state = (
                    "failed" if retry or exc.category in {"http_4xx", "unauthorized"} else "unknown"
                )
                await self.store.sent(row["id"], state, exc.category)
        # Cancellation during sending deliberately leaves 'sending': next initialization
        # marks unknown, so an ambiguous send is never automatically repeated.
        return True

    def remember_message(self, row, result):
        """Reply-to routing: map a sent AI message back to its session (memory, bounded)."""
        mid = result.get("message_id") if isinstance(result, dict) else None
        match = re.match(r"(?:bot:\d+:)?ai:(ais_[0-9a-f]{32}):", row["dedup_key"] or "")
        if type(mid) is int and match:
            self.reply_map[(row["chat_id"], mid)] = match.group(1)
            while len(self.reply_map) > 512:
                del self.reply_map[next(iter(self.reply_map))]

    async def _send_loop(self):
        while True:
            if not await self.send_once():
                await asyncio.sleep(0.1)

    async def _cleanup(self):
        self.dispatcher.close()
        try:
            if self.bot_id and self.store._db is not None and not self.store.readonly_error:
                try:
                    await self.store.set_state(
                        self.bot_id, "disabled" if self.state == "stopping" else self.state
                    )
                except SettingsError:
                    self.status("store_unavailable", "store_unavailable")
        finally:
            client, self.client = self.client, None
            try:
                if client:
                    await client.close()
            finally:
                self.focus.clear()
                self.reply_map.clear()
                await self.store.close(self.slot)

    async def _stop(self):
        self.status("stopping")
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        # Also covers a scheduled session cancelled before its coroutine entered try/finally.
        await self._cleanup()
        self._poll_task = None

    async def close(self):
        self._closing = True
        self._bind_code = None
        if self._notification_task:
            self._notification_task.cancel()
            await asyncio.gather(self._notification_task, return_exceptions=True)
            self._notification_task = None
        async with self._control:
            await self._stop()
            self.status("disabled")
