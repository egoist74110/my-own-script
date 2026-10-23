"""S5-A pure AI domain and child-process boundary contracts.

These tests intentionally call only normalization helpers. They never launch a CLI,
touch Keychain, or read user configuration.
"""

from __future__ import annotations

import os

import pytest

from toolbox_backend.adapters.ai_process import child_environment
from toolbox_backend.domain.ai import config_v2_to_v3, normalize_ai, profile_argv, validate_model


def test_normalize_ai_returns_known_settings_and_preserves_unknown_fields():
    raw = {
        "profiles": [],
        "future_setting": {"nested": "preserve-me"},
    }

    normalized, remaining = normalize_ai(raw)

    assert normalized.model_dump()["future_setting"] == {"nested": "preserve-me"}
    assert remaining == {}


def test_normalize_ai_keeps_contractually_retained_fields_out_of_active_settings():
    raw = {"profiles": [], "targets": [{"name": "legacy"}], "default_policy": "manual"}

    normalized, remaining = normalize_ai(raw)

    assert normalized.profiles
    assert remaining == {"targets": [{"name": "legacy"}], "default_policy": "manual"}
    assert normalized.bots.claude_code.enabled is False
    assert normalized.bots.codex.enabled is False
    assert normalized.bots.gemini.enabled is False


def test_config_v2_to_v3_moves_ai_settings_and_preserves_legacy_remainder():
    raw = {
        "schema_version": 2,
        "imported": {"ai": {"profiles": [], "targets": [{"name": "old"}], "future": 7}},
    }

    migrated = config_v2_to_v3(raw)

    assert migrated["schema_version"] == 3
    assert migrated["ai"]["profiles"]
    assert migrated["ai"]["future"] == 7
    assert migrated["imported"]["ai"] == {"targets": [{"name": "old"}]}
    assert raw["schema_version"] == 2
    assert raw["imported"]["ai"]["future"] == 7


@pytest.mark.parametrize("value", ["claude-sonnet-4-5", "gpt-5-codex", "gemini-3.8-flash"])
def test_validate_model_accepts_plain_model_identifiers(value):
    assert validate_model(value) == value


@pytest.mark.parametrize("value", ["", "  ", "../secret", "safe\n--dangerous"])
def test_validate_model_rejects_empty_path_and_control_injection(value):
    with pytest.raises((TypeError, ValueError)):
        validate_model(value)


def test_profile_argv_parses_arguments_without_shell_interpretation():
    assert profile_argv("/fake/bin/claude --model safe-model") == [
        "/fake/bin/claude",
        "--model",
        "safe-model",
    ]


def test_profile_argv_does_not_expand_shell_syntax():
    argv = profile_argv("/fake/bin/claude '$(touch /tmp/should-not-exist)'")

    assert argv == ["/fake/bin/claude", "$(touch /tmp/should-not-exist)"]


def test_child_environment_filters_toolbox_and_secret_variables(monkeypatch):
    monkeypatch.setenv("PATH", "/isolated/fake-cli")
    monkeypatch.setenv("TOOLBOX_FAKE_SETTING", "not-for-child")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "S5A_FAKE_CLAUDE_SECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "S5A_FAKE_CODEX_SECRET")
    monkeypatch.setenv("AZURE_DEVOPS_EXT_PAT", "S5A_FAKE_ADO_PAT")

    env = child_environment(path_extras=[])

    assert env["PATH"] == "/isolated/fake-cli"
    assert "TOOLBOX_FAKE_SETTING" not in env
    assert not any("S5A_FAKE_" in value for value in env.values())


@pytest.mark.parametrize(
    "name",
    [
        "FOO_TOKEN",
        "FOO_TOKENS",
        "FOO_SECRET",
        "FOO_SECRETS",
        "FOO_PASSWORD",
        "FOO_PASSWD",
        "FOO_PAT",
        "FOO_COOKIE",
        "FOO_COOKIES",
        "API_KEY",
        "APIKEY",
        "ACCESS_KEY",
        "PRIVATE_KEY",
    ],
)
def test_child_environment_filters_sensitive_segments(monkeypatch, name):
    monkeypatch.setenv(name, f"S5A_SECRET_VALUE_{name}")

    env = child_environment(path_extras=[])

    assert name not in env
    assert f"S5A_SECRET_VALUE_{name}" not in env.values()


@pytest.mark.parametrize("name", ["PATH", "MANPATH", "INFOPATH", "FPATH"])
def test_child_environment_preserves_path_family_allowlist(monkeypatch, name):
    monkeypatch.setenv(name, f"/isolated/{name.lower()}")

    env = child_environment(path_extras=[])

    assert env[name] == f"/isolated/{name.lower()}"


def test_pty_environment_sets_terminal_without_reintroducing_secrets(monkeypatch):
    monkeypatch.setenv("TERM", "unsafe-parent-term")
    monkeypatch.setenv("GEMINI_API_KEY", "S5A_FAKE_AGY_SECRET")

    env = child_environment(pty=True, path_extras=[])

    assert env.get("TERM") in {"xterm", "xterm-256color"}
    assert "GEMINI_API_KEY" not in env
    assert os.environ["GEMINI_API_KEY"] == "S5A_FAKE_AGY_SECRET"
