from __future__ import annotations

import keyring

from app_ado.store import APP_ID


def pat_key(library_id: str) -> str:
    return f"azuredevops_pat:{library_id}"


def get_pat(library_id: str) -> str | None:
    return keyring.get_password(APP_ID, pat_key(library_id))


def set_pat(library_id: str, pat: str) -> None:
    keyring.set_password(APP_ID, pat_key(library_id), pat)


def telegram_token_key() -> str:
    return "telegram_bot_token"


def get_telegram_token() -> str | None:
    return keyring.get_password(APP_ID, telegram_token_key())


def set_telegram_token(token: str) -> None:
    keyring.set_password(APP_ID, telegram_token_key(), token)
