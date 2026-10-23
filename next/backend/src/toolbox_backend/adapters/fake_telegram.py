"""In-process dev-only Bot API. It has no network listener or real credential."""

import asyncio
import json

import httpx


class FakeTelegram:
    def __init__(self):
        self.updates = []
        self.sent = []
        self.ready = asyncio.Event()
        self.next_id = 1

    def inject(self, update):
        update = dict(update)
        if type(update.get("update_id")) is not int:
            update["update_id"] = self.next_id
        self.next_id = max(self.next_id, update["update_id"] + 1)
        self.updates.append(update)
        self.ready.set()
        return update["update_id"]

    async def handle(self, request):
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content)
        if method == "getMe":
            result = {"id": 123456789, "username": "toolbox_fake_bot", "is_bot": True}
        elif method == "getWebhookInfo":
            result = {"url": ""}
        elif method == "getUpdates":
            offset = payload.get("offset", 0)
            if offset == -1:
                result = self.updates[-1:]
            else:
                self.updates = [u for u in self.updates if u["update_id"] >= offset]
                if not self.updates and payload.get("timeout"):
                    self.ready.clear()
                    with __import__("contextlib").suppress(TimeoutError):
                        await asyncio.wait_for(self.ready.wait(), timeout=payload["timeout"])
                result = self.updates[: payload.get("limit", 100)]
        elif method in {"sendMessage", "editMessageText", "answerCallbackQuery", "sendMediaGroup"}:
            self.sent.append({"method": method, "payload": payload})
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
