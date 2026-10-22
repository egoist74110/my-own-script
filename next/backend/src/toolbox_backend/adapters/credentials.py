"""Narrow credential ports; keyring is constructed only by the process entry point."""

import json
from pathlib import Path
from typing import Protocol

from toolbox_backend.logging_setup import register_secret

APP_STORE_ID = "toolbox-next"


class LegacyCredentialSource(Protocol):
    def get(self, account: str) -> str | None: ...


class CredentialStore(LegacyCredentialSource, Protocol):
    def set(self, account: str, value: str) -> None: ...
    def delete(self, account: str) -> None: ...


class MemoryCredentials:
    def __init__(self):
        self.values: dict[str, str] = {}

    def get(self, account: str) -> str | None:
        return self.values.get(account)

    def set(self, account: str, value: str) -> None:
        register_secret(value)
        self.values[account] = value

    def delete(self, account: str) -> None:
        self.values.pop(account, None)


def seed_fake_credentials(
    path: Path, *, legacy: MemoryCredentials, current: MemoryCredentials
) -> None:
    """Preload dev-only in-memory credentials from ``{"legacy": {...}, "current": {...}}``.

    Only the process entry point calls this, and only for ``--dev`` + memory credentials.
    Error messages never include file contents or values.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("TOOLBOX_DEV_FAKE_CREDENTIALS is not a readable JSON file") from None
    if not isinstance(data, dict) or not set(data) <= {"legacy", "current"}:
        raise ValueError("TOOLBOX_DEV_FAKE_CREDENTIALS must be an object with legacy/current")
    for key, target in (("legacy", legacy), ("current", current)):
        section = data.get(key, {})
        if not isinstance(section, dict) or not all(
            isinstance(account, str) and isinstance(value, str) and value
            for account, value in section.items()
        ):
            raise ValueError(f"TOOLBOX_DEV_FAKE_CREDENTIALS.{key} must map account to string")
        for account, value in section.items():
            target.set(account, value)


class KeyringLegacySource:
    def __init__(self):
        import keyring

        self._keyring = keyring

    def get(self, account: str) -> str | None:
        value = self._keyring.get_password("my-own-script", account)
        if value:
            register_secret(value)
        return value


class KeyringCredentials:
    def __init__(self):
        import keyring

        self._keyring = keyring

    def get(self, account: str) -> str | None:
        value = self._keyring.get_password(APP_STORE_ID, account)
        if value:
            register_secret(value)
        return value

    def set(self, account: str, value: str) -> None:
        register_secret(value)
        self._keyring.set_password(APP_STORE_ID, account, value)

    def delete(self, account: str) -> None:
        from keyring.errors import PasswordDeleteError

        try:
            self._keyring.delete_password(APP_STORE_ID, account)
        except PasswordDeleteError:
            # A missing entry is an idempotent delete, but permission/backend errors
            # must not be swallowed.
            if self.get(account) is not None:
                raise
