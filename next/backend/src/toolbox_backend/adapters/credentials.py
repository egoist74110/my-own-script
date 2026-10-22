"""Narrow credential ports; keyring is constructed only by the process entry point."""

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
