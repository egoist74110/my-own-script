import json
import stat

import pytest

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.domain.settings import Config


@pytest.mark.asyncio
async def test_v2_snapshot_atomic_and_idempotent(tmp_path):
    raw = Config().model_dump(by_alias=True)
    raw.pop("ai", None)
    raw.update(schema_version=2, revision=7)
    raw["imported"]["ai"] = {"tool": {"profiles": []}, "targets": [], "mystery": 17}
    original = json.dumps(raw).encode()
    (tmp_path / "config.json").write_bytes(original)
    store = ConfigStore(tmp_path)
    migrated = await store.initialize()
    assert migrated.schema_version == 8
    assert migrated.imported.ai == {"targets": []}
    assert migrated.ai.model_extra["mystery"] == 17
    snapshots = list((tmp_path / "migrations").glob("config-v2-*.json"))
    assert len(snapshots) == 1 and snapshots[0].read_bytes() == original
    assert stat.S_IMODE(snapshots[0].stat().st_mode) == 0o600
    assert (await store.initialize()) == migrated
    assert list((tmp_path / "migrations").glob("config-v2-*.json")) == snapshots


@pytest.mark.asyncio
async def test_migration_preserves_invalid_profiles_warns_and_never_starts(tmp_path, monkeypatch):
    from uuid import uuid4

    from toolbox_backend.adapters.ai_store import AIStore
    from toolbox_backend.api.ai_schemas import SessionCreate
    from toolbox_backend.domain.errors import SettingsError
    from toolbox_backend.services.ai_sessions import AISessionService
    from toolbox_backend.services.events import EventHub

    raw = Config().model_dump(by_alias=True)
    raw.pop("ai")
    raw.update(schema_version=2, revision=3)
    bad = [
        {"id": "broken", "command": '"unterminated', "unknown": {"value": 3}},
        {"id": "dup", "name": "first", "command": "fake"},
        {"id": "dup", "name": "second", "command": "fake"},
        {"id": "control", "name": "control", "command": '"bad\nexecutable"'},
        17,
    ]
    raw["imported"]["ai"] = {
        "tool": {"profiles": bad},
        "targets": [],
        "bots": [{"ai_id": "codex", "username": "@old_user"}],
    }
    (tmp_path / "config.json").write_text(json.dumps(raw))
    config = ConfigStore(tmp_path)
    migrated = await config.initialize()
    assert len(migrated.ai.profiles) == len(bad) + 3
    assert migrated.ai.model_dump()["profiles"][0]["unknown"] == {"value": 3}
    assert migrated.ai.bots.codex.username == "@old_user"
    assert not migrated.ai.bots.codex.enabled
    ai_store = AIStore(tmp_path)
    await ai_store.initialize()
    service = AISessionService(config, ai_store, EventHub(), path_extras=[])
    attempted = []

    def resolve(command):
        attempted.append(command)
        return ["/fake-executable"]

    monkeypatch.setattr(service, "_resolve", resolve)
    try:
        view = await service.settings()
        assert view["warnings"]
        for pid in ("broken", "dup", "control"):
            with pytest.raises(SettingsError) as caught:
                await service.create(
                    SessionCreate(
                        request_id=uuid4(), kind="terminal", profile_id=pid, repo_id="unused"
                    )
                )
            assert caught.value.code == "validation_error"
        assert await ai_store.list() == []
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_v2_migration_failure_keeps_original_and_removes_partial_file(tmp_path):
    from toolbox_backend.domain.errors import SettingsError

    raw = Config().model_dump(by_alias=True)
    raw.pop("ai")
    raw.update(schema_version=2, revision=5)
    original = json.dumps(raw).encode()
    (tmp_path / "config.json").write_bytes(original)
    store = ConfigStore(tmp_path)

    def fail(stage):
        if stage == "before_replace":
            raise OSError("injected")

    store.checkpoint = fail
    with pytest.raises(SettingsError):
        await store.initialize()
    assert (tmp_path / "config.json").read_bytes() == original
    assert not list(tmp_path.glob(".config-*"))
    backups = list((tmp_path / "migrations").glob("config-v2-*.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == original


def test_legacy_ai_normalization_handles_missing_and_non_list_profiles():
    from toolbox_backend.domain.ai import normalize_ai

    blank, remaining = normalize_ai({})
    assert {p["id"] for p in blank.model_dump()["profiles"]} == {"codex", "gemini", "claude_code"}
    assert blank.defaults.claude.permission == "auto"
    assert blank.defaults.agy.mode == "sandbox"
    assert blank.analysis.codex.sandbox == "read-only"
    assert remaining == {}
    normalized, _ = normalize_ai({"tool": {"profiles": {"bad": "shape"}, "future": 42}})
    assert normalized.model_extra["legacy_profiles"] == {"bad": "shape"}
    assert normalized.model_extra["future"] == 42
