"""RFC 6238 TOTP and in-memory otpauth import parsing."""

import base64
import hashlib
import hmac
import re
import struct
from urllib.parse import parse_qs, unquote, urlsplit

MAX_IMPORT_BYTES = 1 << 20


def totp(secret: str, timestamp: int | float, *, digits: int = 6, period: int = 30) -> str:
    if digits != 6 or period != 30:
        raise ValueError("totp_unsupported")
    normalized = re.sub(r"\s+", "", secret).upper()
    try:
        key = base64.b32decode(normalized + "=" * (-len(normalized) % 8), casefold=True)
    except ValueError, base64.binascii.Error:
        raise ValueError("invalid_totp_secret") from None
    counter = int(timestamp) // period
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return f"{number:0{digits}d}"


def parse_totp_import(text: str, filter_text: str = "") -> list[dict[str, str]]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("totp_import_too_large")
    # Export formats may wrap otpauth URIs in text or JSON. Never interpret text as a path.
    uris = re.findall(r"otpauth://[^\s\"'<>]+", text, flags=re.IGNORECASE)
    if text.strip().lower().startswith("otpauth://") and not uris:
        uris = [text.strip()]
    if not uris:
        raise ValueError("totp_not_found")
    candidates = []
    unsupported = False
    for uri in uris:
        try:
            parsed = urlsplit(uri.rstrip(",}]"))
            if parsed.scheme.lower() != "otpauth" or parsed.netloc.lower() != "totp":
                continue
            values = parse_qs(parsed.query, strict_parsing=False)
            secret = values.get("secret", [""])[0].replace(" ", "").upper()
            label = unquote(parsed.path.lstrip("/"))
            issuer = values.get("issuer", [""])[0]
            if ":" in label:
                label_issuer, label = label.split(":", 1)
                issuer = issuer or label_issuer
            algorithm = values.get("algorithm", ["SHA1"])[0].upper()
            digits = values.get("digits", ["6"])[0]
            period = values.get("period", ["30"])[0]
            if algorithm != "SHA1" or digits != "6" or period != "30":
                unsupported = True
                continue
            if not secret:
                continue
            # Validate the base32 material before exposing it to the caller.
            totp(secret, 0)
            candidate = {"issuer": issuer, "label": label, "secret": secret}
            haystack = f"{issuer} {label}".casefold()
            if not filter_text or filter_text.casefold() in haystack:
                candidates.append(candidate)
        except ValueError, TypeError:
            continue
    if not candidates:
        raise ValueError("totp_unsupported" if unsupported else "totp_not_found")
    return candidates
