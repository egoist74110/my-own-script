"""S4-A independent regressions for Telegram token redaction."""

import logging
import traceback

from toolbox_backend.logging_setup import RedactingFormatter, redact_exception, register_secret


def test_bot_api_urls_and_url_encoded_token_are_redacted():
    token = "123456789:AA_Sensitive-Telegram-Token"
    register_secret(token)
    formatter = RedactingFormatter([token], "%(message)s")

    samples = [
        f"https://api.telegram.org/bot{token}/getMe",
        "https://api.telegram.org/bot123456789%3AAA_Sensitive-Telegram-Token/sendMessage",
        "https://api.telegram.org/bot123456789%3aAA_Sensitive-Telegram-Token/sendMessage",
    ]
    for sample in samples:
        rendered = formatter.format(logging.makeLogRecord({"msg": sample, "args": ()}))
        assert token not in rendered
        assert "AA_Sensitive-Telegram-Token" not in rendered


def test_authorization_header_variants_are_redacted():
    token = "123456789:AA_Header-Secret-Token"
    register_secret(token)
    samples = [
        f"Authorization: Bearer {token}",
        f'Authorization: "Bearer {token}"',
        f"Authorization: 'Bearer {token}'",
        f"authorization: Bearer%20{token.replace(':', '%3A')}",
        f"Authorization: Bot {token}",
    ]
    for sample in samples:
        result = redact_exception(sample)
        assert token not in result
        assert "AA_Header-Secret-Token" not in result


def test_exception_cause_and_context_chain_are_redacted():
    token = "987654321:AA_Exception-Chain-Secret"
    register_secret(token)
    try:
        try:
            raise RuntimeError(f"transport failed for bot{token}")
        except RuntimeError as cause:
            raise ValueError(f"request failed: {token}") from cause
    except ValueError as exc:
        chain = "".join(traceback.format_exception(exc))

    redacted = redact_exception(chain)
    assert token not in redacted
    assert "AA_Exception-Chain-Secret" not in redacted
