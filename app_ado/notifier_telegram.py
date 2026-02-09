from __future__ import annotations

import httpx


def send_telegram_message(*, bot_token: str, chat_id: str, text: str, reply_markup: dict | None = None, timeout_sec: float = 10.0) -> None:
    """Send Telegram message via Bot API.

    Raises RuntimeError with readable Telegram error payload.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        import json

        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=5.0), follow_redirects=False) as c:
        try:
            r = c.post(url, data=payload)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = e.response.text if e.response is not None else ""
            raise RuntimeError(f"Telegram HTTP {e.response.status_code if e.response else ''}: {body}") from e

        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram send failed: {data}")
