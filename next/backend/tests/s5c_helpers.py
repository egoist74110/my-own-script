"""S5-C fixtures: four Telegram slots on one token-aware in-memory Bot API and fake AI CLIs."""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from tests.s5b_helpers import TOKEN, client_for, configure, use_fakes
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.settings import Settings

TOKENS = {
    "main": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
    "claude_code": "111111111:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdeg",
    "codex": "222222222:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdeh",
    "gemini": "333333333:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdei",
}
OWNER = 6001


class Bots:
    """Token-aware Bot API. ``bot_id`` is the numeric token prefix."""

    def __init__(self):
        self.requests = []
        self.queues = {}
        self.sent = {}
        self.conflict = set()
        self.hang_send = set()
        self.fail_send = set()
        self.webhook = set()
        self.get_me_override = {}
        self.next_message = 0

    def feed(self, bot_id, update):
        self.queues.setdefault(int(bot_id), []).append(update)

    def texts(self, bot_id, chat=None):
        return [
            m["payload"].get("text", "")
            for m in self.sent.get(int(bot_id), [])
            if chat is None or str(m["payload"].get("chat_id")) == str(chat)
        ]

    def last_markup(self, bot_id):
        for m in reversed(self.sent.get(int(bot_id), [])):
            markup = m["payload"].get("reply_markup")
            if markup:
                return markup
        return None

    async def __call__(self, request):
        method = request.url.path.rsplit("/", 1)[-1]
        bot_id = int(request.url.path.rsplit("/", 2)[-2].removeprefix("bot").split(":")[0])
        payload = json.loads(request.content) if request.content else {}
        self.requests.append((bot_id, method, payload))
        if method == "getMe":
            ident = self.get_me_override.get(bot_id, bot_id)
            return httpx.Response(
                200, json={"ok": True, "result": {"id": ident, "username": f"bot_{bot_id}x"}}
            )
        if method == "getWebhookInfo":
            return httpx.Response(
                200, json={"ok": True, "result": {"url": "x" if bot_id in self.webhook else ""}}
            )
        if method == "deleteWebhook":
            return httpx.Response(200, json={"ok": True, "result": True})
        if method == "getUpdates":
            if bot_id in self.conflict:
                return httpx.Response(
                    409, json={"ok": False, "error_code": 409, "description": "Conflict"}
                )
            queue = self.queues.setdefault(bot_id, [])
            offset = payload.get("offset", 0)
            if offset == -1:
                return httpx.Response(200, json={"ok": True, "result": queue[-1:]})
            queue[:] = [u for u in queue if u["update_id"] >= offset]
            if not queue:
                await asyncio.sleep(0.05)
            return httpx.Response(200, json={"ok": True, "result": list(queue)})
        if method in {"sendMessage", "editMessageText"}:
            if bot_id in self.hang_send:
                await asyncio.Event().wait()
            if bot_id in self.fail_send:
                return httpx.Response(
                    400, json={"ok": False, "error_code": 400, "description": "bad"}
                )
            self.next_message += 1
            self.sent.setdefault(bot_id, []).append(
                {"method": method, "payload": payload, "message_id": self.next_message}
            )
            return httpx.Response(
                200, json={"ok": True, "result": {"message_id": self.next_message}}
            )
        return httpx.Response(200, json={"ok": True, "result": True})


def message(ident, text, chat=OWNER, *, private=True, user=None, age=0, reply_to=None):
    result = {
        "update_id": ident,
        "message": {
            "message_id": ident,
            "date": int(time.time()) - age,
            "text": text,
            "chat": {"id": chat, "type": "private" if private else "group"},
            "from": {"id": chat if user is None else user},
        },
    }
    if reply_to is not None:
        result["message"]["reply_to_message"] = {"message_id": reply_to}
    return result


def callback(ident, data, chat=OWNER, *, private=True, user=None):
    return {
        "update_id": ident,
        "callback_query": {
            "id": f"cb{ident}",
            "from": {"id": chat if user is None else user},
            "data": data,
            "message": {
                "message_id": 1,
                "date": int(time.time()),
                "chat": {"id": chat, "type": "private" if private else "group"},
            },
        },
    }


@dataclass
class Ctx:
    app: object
    client: object
    bots: Bots
    repo: object
    log: object
    credentials: MemoryCredentials
    legacy: MemoryCredentials
    counter: list

    def slot(self, ai_id):
        return self.app.state.telegram_ai_services[ai_id]

    @property
    def main(self):
        return self.app.state.telegram_service

    def uid(self):
        self.counter[0] += 1
        return self.counter[0]

    async def revision(self):
        return (await self.app.state.config_store.read()).revision

    async def put_token(self, ai_id, token=None):
        url = (
            "/api/telegram/token"
            if ai_id == "main"
            else f"/api/telegram/ai-bots/{ai_id}/token"
        )
        response = await self.client.put(
            url, json={"revision": await self.revision(), "token": token or TOKENS[ai_id]}
        )
        assert response.status_code == 200, response.text

    async def enable(self, ai_id, *, expect=200, **extra):
        if ai_id == "main":
            url, body = "/api/telegram/control/enable", {"ack_old_bot_stopped": True}
        else:
            url = f"/api/telegram/ai-bots/{ai_id}/control/enable"
            body = {"ack_old_bot_cleared": True}
        response = await self.client.post(
            url, json={"revision": await self.revision(), **body, **extra}
        )
        assert response.status_code == expect, response.text
        return response

    async def disable(self, ai_id):
        url = (
            "/api/telegram/control/disable"
            if ai_id == "main"
            else f"/api/telegram/ai-bots/{ai_id}/control/disable"
        )
        response = await self.client.post(url, json={"revision": await self.revision()})
        assert response.status_code == 200, response.text

    async def ready(self, *ai_ids, main=False):
        ids = (["main"] if main else []) + list(ai_ids)
        for ai_id in ids:
            await self.put_token(ai_id)
            await self.enable(ai_id)
        for ai_id in ids:
            svc = self.main if ai_id == "main" else self.slot(ai_id)
            await wait(lambda svc=svc: svc.state == "polling")

    def post(self, ai_id, update):
        """Queue an update on a slot's bot (delivered by its real poller)."""
        self.bots.feed(TOKENS[ai_id].split(":")[0], update)

    def bot_id(self, ai_id):
        return TOKENS[ai_id].split(":")[0]

    def texts(self, ai_id, chat=None):
        return self.bots.texts(self.bot_id(ai_id), chat)

    async def click(self, ai_id, label, chat=OWNER):
        markup = None
        for m in reversed(self.bots.sent.get(int(self.bot_id(ai_id)), [])):
            markup = m["payload"].get("reply_markup")
            if markup and any(label in b["text"] for row in markup["inline_keyboard"] for b in row):
                break
            markup = None
        assert markup, f"no button containing {label!r}"
        button = next(
            b for row in markup["inline_keyboard"] for b in row if label in b["text"]
        )
        before = len(self.bots.sent.get(int(self.bot_id(ai_id)), []))
        self.post(ai_id, callback(self.uid(), button["callback_data"], chat))
        return before


async def wait(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if asyncio.iscoroutine(value):
            value = await value
        if value:
            return value
        await asyncio.sleep(0.03)
    raise AssertionError("condition not reached")


@asynccontextmanager
async def open_s5c(tmp_path, monkeypatch, *, owner=str(OWNER), fast_rate=True):
    import toolbox_backend.services.telegram as tgmod

    if fast_rate:
        monkeypatch.setattr(tgmod, "RATE_PER_CHAT_S", 0.0)
        monkeypatch.setattr(tgmod, "RATE_PER_BOT", (10**6, 60.0))
    log = use_fakes(monkeypatch, tmp_path)
    bots = Bots()
    credentials, legacy = MemoryCredentials(), MemoryCredentials()
    app = create_app(
        Settings(
            token=TOKEN,
            port=12345,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=credentials,
        legacy_credentials=legacy,
        telegram_transport=httpx.MockTransport(bots),
    )
    async with app.router.lifespan_context(app):
        repo = await configure(app, tmp_path)
        config = await app.state.config_store.read()

        def seed(c):
            c.telegram.owner.chat_id = owner
            c.telegram.owner.source = "bound" if owner else None

        await app.state.config_store.update(config.revision, seed)
        async with client_for(app) as client:
            yield Ctx(app, client, bots, repo, log, credentials, legacy, [1000])
