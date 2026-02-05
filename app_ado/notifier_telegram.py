from __future__ import annotations

import httpx


def send_telegram_message(*, bot_token: str, chat_id: str, text: str, timeout_sec: float = 10.0) -> None:
    """Send Telegram message via Bot API.

    Raises exception on non-2xx.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=5.0), follow_redirects=False) as c:
        r = c.post(url, data=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram send failed: {data}")
