"""In-process dev-only Bot API. It has no network listener or real credential."""

import asyncio
import json
from email import policy
from email.parser import BytesParser

import httpx

MAIN_BOT_ID = 123456789


class FakeTelegram:
    """One in-process Bot API for every slot: the bot id is the numeric token prefix."""

    def __init__(self):
        self.queues = {}
        self.sent = []
        self.ready = {}
        self.next_id = 1

    @property
    def updates(self):
        return self.queues.setdefault(MAIN_BOT_ID, [])

    def inject(self, update, bot_id=MAIN_BOT_ID):
        update = dict(update)
        if type(update.get("update_id")) is not int:
            update["update_id"] = self.next_id
        self.next_id = max(self.next_id, update["update_id"] + 1)
        self.queues.setdefault(bot_id, []).append(update)
        self.ready.setdefault(bot_id, asyncio.Event()).set()
        return update["update_id"]

    async def handle(self, request):
        segment = request.url.path.rsplit("/", 2)[-2]
        try:
            bot_id = int(segment.removeprefix("bot").split(":", 1)[0])
        except ValueError:
            bot_id = MAIN_BOT_ID
        updates = self.queues.setdefault(bot_id, [])
        ready = self.ready.setdefault(bot_id, asyncio.Event())
        method = request.url.path.rsplit("/", 1)[-1]
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            envelope = BytesParser(policy=policy.default).parsebytes(
                b"Content-Type: "
                + request.headers["content-type"].encode()
                + b"\r\n\r\n"
                + request.content
            )
            payload, files = {}, []
            for part in envelope.iter_parts():
                name = part.get_param("name", header="content-disposition")
                body = part.get_payload(decode=True)
                if part.get_filename():
                    files.append({"name": name, "size": len(body), "mime": part.get_content_type()})
                else:
                    value = body.decode()
                    payload[name] = json.loads(value) if name == "media" else value
            payload["files"] = files
        else:
            payload = json.loads(request.content)
        if method == "getMe":
            name = "toolbox_fake_bot" if bot_id == MAIN_BOT_ID else f"toolbox_fake_ai_{bot_id}"
            result = {"id": bot_id, "username": name, "is_bot": True}
        elif method == "getWebhookInfo":
            result = {"url": ""}
        elif method == "getUpdates":
            offset = payload.get("offset", 0)
            if offset == -1:
                result = updates[-1:]
            else:
                updates[:] = [u for u in updates if u["update_id"] >= offset]
                if not updates and payload.get("timeout"):
                    ready.clear()
                    with __import__("contextlib").suppress(TimeoutError):
                        await asyncio.wait_for(ready.wait(), timeout=payload["timeout"])
                result = updates[: payload.get("limit", 100)]
        elif method in {
            "sendMessage",
            "editMessageText",
            "answerCallbackQuery",
            "sendMediaGroup",
            "sendPhoto",
        }:
            self.sent.append({"method": method, "payload": payload, "bot_id": str(bot_id)})
            # Diagnostic history is bounded, including injected large development sessions.
            self.sent = self.sent[-500:]
            result = {"message_id": len(self.sent)}
        elif method == "deleteWebhook":
            result = True
        else:
            return httpx.Response(400, json={"ok": False, "description": "unsupported method"})
        return httpx.Response(200, json={"ok": True, "result": result})

    @property
    def transport(self):
        return httpx.MockTransport(self.handle)
