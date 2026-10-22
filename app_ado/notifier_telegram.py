from __future__ import annotations

import httpx

from app_ado.redact import redact_text


def _http_error_message(e: httpx.HTTPStatusError, bot_token: str | None) -> str:
    """状态码/方法/脱敏路径/响应体，不含 token。"""
    resp, req = e.response, e.request
    body = resp.text if resp is not None else ""
    code = resp.status_code if resp is not None else ""
    method = getattr(req, "method", "") if req is not None else ""
    path = redact_text(req.url.path, bot_token) if req is not None else ""
    return redact_text(f"Telegram HTTP {code} {method} {path}: {body}", bot_token)


def send_telegram_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str | None = None,
    timeout_sec: float = 10.0,
) -> None:
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
    if parse_mode:
        payload["parse_mode"] = parse_mode
    with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=5.0), follow_redirects=False) as c:
        r = c.post(url, data=payload)
        if r.status_code == 400 and parse_mode:
            # markdown 解析失败：退回纯文本重试一次
            payload.pop("parse_mode", None)
            r = c.post(url, data=payload)
        err_msg: str | None = None
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            err_msg = _http_error_message(e, bot_token)
        if err_msg is not None:
            # 在 except 块外 raise 且 from None：不保留带完整 URL 的原异常（__cause__/__context__ 都为空）
            raise RuntimeError(err_msg) from None

        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(redact_text(f"telegram send failed: {data}", bot_token))


def send_telegram_photo(
    *,
    bot_token: str,
    chat_id: str,
    photo: bytes,
    caption: str | None = None,
    filename: str = "qr.png",
    timeout_sec: float = 20.0,
) -> None:
    """Send a photo (raw bytes) via Telegram Bot API sendPhoto (multipart upload)."""
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    data: dict[str, str] = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
    files = {"photo": (filename, photo, "image/png")}
    with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=5.0), follow_redirects=False) as c:
        err_msg: str | None = None
        try:
            r = c.post(url, data=data, files=files)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            err_msg = _http_error_message(e, bot_token)
        if err_msg is not None:
            # 在 except 块外 raise 且 from None：不保留带完整 URL 的原异常（__cause__/__context__ 都为空）
            raise RuntimeError(err_msg) from None

        d = r.json()
        if not d.get("ok"):
            raise RuntimeError(redact_text(f"telegram sendPhoto failed: {d}", bot_token))
