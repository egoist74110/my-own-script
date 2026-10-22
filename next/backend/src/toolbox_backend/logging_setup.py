"""stderr-only logging with token redaction."""

import base64
import logging
import sys

_known_secrets: set[str] = set()


def register_secret(value: str) -> None:
    if value:
        _known_secrets.add(value)
        _known_secrets.add(base64.b64encode((":" + value).encode()).decode())


def contains_secret(text: str) -> bool:
    return any(value in text for value in _known_secrets)


def redact_exception(value: object) -> str:
    text = str(value)
    for secret in sorted(_known_secrets, key=len, reverse=True):
        text = text.replace(secret, "***")
    return text


class RedactingFormatter(logging.Formatter):
    def __init__(self, secrets: list[str], *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._secrets = [s for s in secrets if s]

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return redact_exception(text)


def setup_logging(secrets: list[str], level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        RedactingFormatter(secrets, "%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
