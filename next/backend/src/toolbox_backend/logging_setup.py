"""stderr-only logging with token redaction."""

import logging
import sys


class RedactingFormatter(logging.Formatter):
    def __init__(self, secrets: list[str], *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._secrets = [s for s in secrets if s]

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text


def setup_logging(secrets: list[str], level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        RedactingFormatter(secrets, "%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
