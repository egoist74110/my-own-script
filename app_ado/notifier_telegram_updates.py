from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import json


@dataclass(frozen=True)
class TelegramChatCandidate:
    chat_id: str
    title: str
    kind: str  # private|group|supergroup|channel|unknown
    username: str | None = None


def get_updates(*, bot_token: str, offset: int | None = None, timeout: int = 0, timeout_sec: float = 25.0) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params: dict[str, Any] = {
        "timeout": int(timeout),
        # Telegram expects JSON array string here; avoid repeated query keys.
        "allowed_updates": json.dumps(["message", "channel_post"], ensure_ascii=False),
    }
    if offset is not None:
        params["offset"] = offset
    with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=5.0), follow_redirects=False) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"telegram getUpdates failed: {data}")
    return data


def list_chat_candidates(*, bot_token: str, limit: int = 20, long_poll_sec: int = 20) -> list[TelegramChatCandidate]:
    # First do a non-blocking poll to avoid 409 conflicts when another long poll is active.
    try:
        data = get_updates(bot_token=bot_token, timeout=0)
    except httpx.HTTPStatusError as e:
        # If another getUpdates request is running, Telegram returns 409.
        if e.response is not None and e.response.status_code == 409:
            # Retry once with timeout=0 after a short wait; caller can show friendly message.
            raise
        raise

    # If empty, long poll once to reliably receive the latest message.
    if not (data.get("result") or []) and long_poll_sec > 0:
        data = get_updates(bot_token=bot_token, timeout=long_poll_sec)
    items = (data.get("result") or [])[-limit:]

    seen: set[str] = set()
    out: list[TelegramChatCandidate] = []

    def add(chat: dict[str, Any]):
        cid = chat.get("id")
        if cid is None:
            return
        cid_s = str(cid)
        if cid_s in seen:
            return
        seen.add(cid_s)
        kind = str(chat.get("type") or "unknown")
        username = chat.get("username")
        title = chat.get("title") or chat.get("first_name") or "(unknown)"
        out.append(TelegramChatCandidate(chat_id=cid_s, title=str(title), kind=kind, username=str(username) if username else None))

    for u in items:
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat:
            add(chat)

    return out
