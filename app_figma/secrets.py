from __future__ import annotations

import keyring

from app_ado.store import APP_ID


FIGMA_TOKEN_KEY = "figma_api_token"


def get_figma_token() -> str | None:
    return keyring.get_password(APP_ID, FIGMA_TOKEN_KEY)


def set_figma_token(token: str) -> None:
    keyring.set_password(APP_ID, FIGMA_TOKEN_KEY, token)


def delete_figma_token() -> None:
    try:
        keyring.delete_password(APP_ID, FIGMA_TOKEN_KEY)
    except keyring.errors.PasswordDeleteError:
        pass


def is_figma_configured() -> bool:
    """是否已配置 Figma API Token(Figma 无 OAuth,有 Token 即可开 MCP)。"""
    return bool(get_figma_token())
