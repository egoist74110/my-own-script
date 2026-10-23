"""stderr-only logging with token redaction."""

import base64
import json
import logging
import re
import sys
from urllib.parse import quote

_known_secrets: set[str] = set()
_BOT_URL_RE = re.compile(r"/bot\d+(?::|%3[Aa])[A-Za-z0-9_\-]+(?=/|\b|$)")
_AUTH_HEADER_RE = re.compile(
    r"""(?ix)
    (?P<k>["']?(?:proxy-)?authorization["']?\s*[:=]\s*["']?|
    ["']?x-[a-z0-9-]*(?:token|secret|key)["']?\s*[:=]\s*["']?)
    (?:[A-Za-z][A-Za-z0-9_-]*\s+(?=[^\s"',;}\]]))?
    [^\s"',;}\]]+
    """
)
_USERINFO_RE = re.compile(r"(https?://)[^/\s@]+@", re.I)


def register_secret(value: str) -> None:
    if len(value) >= 8:
        _known_secrets.add(value)
        _known_secrets.add(json.dumps(value, ensure_ascii=False)[1:-1])
        _known_secrets.add(json.dumps(value, ensure_ascii=True)[1:-1])
        _known_secrets.add(base64.b64encode((":" + value).encode()).decode())
        for safe in ("", "-_"):
            encoded = quote(value, safe=safe)
            _known_secrets.add(encoded)
            _known_secrets.add(re.sub(r"%[0-9A-F]{2}", lambda m: m[0].lower(), encoded))


def contains_secret(text: str) -> bool:
    return any(value in text for value in _known_secrets)


def redact_exception(value: object) -> str:
    parts, seen = [], set()
    current = value
    for _ in range(6):
        if id(current) in seen:
            break
        seen.add(id(current))
        try:
            parts.append(str(current))
        except Exception:
            parts.append("<unprintable>")
        if not isinstance(current, BaseException):
            break
        current = current.__cause__ or current.__context__
        if current is None:
            break
    text = " | ".join(parts)
    text = _BOT_URL_RE.sub("/bot***", text)
    text = _AUTH_HEADER_RE.sub(lambda m: m["k"] + "***", text)
    text = _USERINFO_RE.sub(r"\1***@", text)
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
    # HTTP client diagnostics include complete request paths/query strings.
    # The backend emits only its own fixed messages/origins.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
