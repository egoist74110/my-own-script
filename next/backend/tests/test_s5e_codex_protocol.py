"""Codex 0.163.0 checked wire shapes; no real CLI calls."""

import json

import pytest

from toolbox_backend.adapters.ai_cli import codex


@pytest.mark.parametrize("kind", ["error", "turn.failed"])
@pytest.mark.parametrize("nested", [True, False])
def test_codex_api_error_string_displays_inner_message(kind, nested):
    message = "Invalid value: 'bogus'. Supported values include 'max'."
    encoded = json.dumps(
        {"error": {"message": message}, "status": 400} if nested else {"message": message}
    )
    obj = {
        "type": kind,
        **({"message": encoded} if kind == "error" else {"error": {"message": encoded}}),
    }
    result = codex.parse(obj)[0]
    assert result.payload["text" if kind == "error" else "message"] == message


@pytest.mark.parametrize("message", ["plain error", "{broken", "[]", '{"error":{}}'])
def test_codex_unrecognized_error_keeps_original(message):
    assert codex.parse({"type": "error", "message": message})[0].payload["text"] == message


def test_codex_inner_message_is_clipped_after_decoding():
    encoded = json.dumps({"error": {"message": "x" * 600}})
    assert codex.parse({"type": "error", "message": encoded})[0].payload["text"] == "x" * 499 + "…"


@pytest.mark.parametrize(
    "value,expected", [(20, 20), (0, 0), (-1, 0), (True, 0), (1.5, 0), ("20", 0), (None, 0)]
)
def test_codex_checked_usage_accepts_only_nonnegative_integers(value, expected):
    payload = codex.parse(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": value,
                "cache_write_input_tokens": 0,
                "output_tokens": 5,
                "reasoning_output_tokens": value,
            },
        }
    )[0].payload
    assert payload["cached_input_tokens"] == expected
    assert payload["reasoning_output_tokens"] == expected
    assert payload["input_tokens"] == 100 and payload["output_tokens"] == 5


@pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high", "xhigh", "max"])
def test_codex_config_effort_roundtrips_without_migration(effort):
    from toolbox_backend.domain.ai import CodexDefaults

    assert CodexDefaults.model_validate({"effort": effort}).model_dump()["effort"] == effort
    assert CodexDefaults().effort == "medium"


def test_codex_config_rejects_unknown_effort():
    from pydantic import ValidationError

    from toolbox_backend.domain.ai import CodexDefaults

    with pytest.raises(ValidationError):
        CodexDefaults(effort="bogus")
