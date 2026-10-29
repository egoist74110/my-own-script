from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app_ado.redact import redact_exception, redact_text


@dataclass(frozen=True)
class TelegramBotInfo:
    id: str
    username: str | None
    first_name: str | None


def get_me(*, bot_token: str, timeout_sec: float = 10.0) -> TelegramBotInfo:
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    err_msg: str | None = None
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=5.0), follow_redirects=False) as c:
            r = c.get(url)
            r.raise_for_status()
            data: Any = r.json()
    except httpx.HTTPError as e:
        err_msg = redact_exception(e, bot_token)
    if err_msg is not None:
        # 在 except 块外 raise 且 from None：不保留带完整 bot URL 的原异常
        raise RuntimeError(f"telegram getMe failed: {err_msg}") from None
    if not data.get("ok"):
        raise RuntimeError(redact_text(f"telegram getMe failed: {data}", bot_token))
    res = data.get("result") or {}
    return TelegramBotInfo(
        id=str(res.get("id")),
        username=str(res.get("username")) if res.get("username") else None,
        first_name=str(res.get("first_name")) if res.get("first_name") else None,
    )
