from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class TelegramBotInfo:
    id: str
    username: str | None
    first_name: str | None


def get_me(*, bot_token: str, timeout_sec: float = 10.0) -> TelegramBotInfo:
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=5.0), follow_redirects=False) as c:
        r = c.get(url)
        r.raise_for_status()
        data: Any = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"telegram getMe failed: {data}")
    res = data.get("result") or {}
    return TelegramBotInfo(
        id=str(res.get("id")),
        username=str(res.get("username")) if res.get("username") else None,
        first_name=str(res.get("first_name")) if res.get("first_name") else None,
    )
