from __future__ import annotations

import keyring

from app_lark.store import APP_ID


def app_secret_key(app_id: str) -> str:
    return f"lark_app_secret:{app_id}"


def get_app_secret(app_id: str) -> str | None:
    if not app_id:
        return None
    return keyring.get_password(APP_ID, app_secret_key(app_id))


def set_app_secret(app_id: str, secret: str) -> None:
    keyring.set_password(APP_ID, app_secret_key(app_id), secret)


def delete_app_secret(app_id: str) -> None:
    try:
        keyring.delete_password(APP_ID, app_secret_key(app_id))
    except keyring.errors.PasswordDeleteError:
        pass
