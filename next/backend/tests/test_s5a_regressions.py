import json

import pytest

from toolbox_backend.adapters.ai_process import child_environment
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.domain.settings import Config


def test_path_preserved_and_segmented_secret_filter(monkeypatch):
    monkeypatch.setenv("PATH", "/fake")
    monkeypatch.setenv("MANPATH", "/manual")
    monkeypatch.setenv("FOO_PAT", "fake-secret-value")
    monkeypatch.setenv("COMPASS", "safe")
    env = child_environment(path_extras=[])
    assert env["PATH"] == "/fake" and env["MANPATH"] == "/manual"
    assert "FOO_PAT" not in env and env["COMPASS"] == "safe"


@pytest.mark.asyncio
async def test_custom_migrations_cannot_remove_production_steps(tmp_path):
    raw = Config().model_dump(by_alias=True)
    raw.update(schema_version=0, revision=4)
    (tmp_path / "config.json").write_text(json.dumps(raw))
    store = ConfigStore(tmp_path)
    store.migrations = {0: lambda old: {**old, "schema_version": 1}}
    result = await store.initialize()
    assert result.schema_version == 4 and result.revision == 5


def test_migration_disables_unknown_bot_slots():
    from toolbox_backend.domain.ai import normalize_ai

    ai, _ = normalize_ai({"bots": {"future": {"enabled": True, "opaque": 3}}})
    assert ai.model_dump()["bots"]["future"]["enabled"] is False
    assert ai.model_dump()["bots"]["future"]["opaque"] == 3


@pytest.mark.asyncio
async def test_event_retention_publishes_notice_and_watermark(tmp_path):
    from toolbox_backend.adapters.ai_store import AIStore
    from toolbox_backend.adapters.config_store import stamp

    emitted = []
    store = AIStore(tmp_path, emitted.append)
    await store.initialize()
    try:
        await store.create(
            dict(
                id="s",
                kind="terminal",
                cli="other",
                profile_id="p",
                repo_id="r",
                cwd_snapshot="/fake",
                purpose="general",
                origin_json='{"kind":"ui"}',
                state="starting",
                created_at=stamp(),
                usage_json="{}",
                request_id="r",
            )
        )

        def fill():
            with store.transaction() as db:
                db.executemany(
                    "INSERT INTO ai_events VALUES(?,?,?,?,?)",
                    [("s", i, stamp(), "notice", "{}") for i in range(2, 5002)],
                )
                db.execute("UPDATE ai_sessions SET last_seq=5001")

        await store.call(fill)
        await store.transition("s", "idle")
        page = await store.events("s", 5001)
        assert emitted[-1]["session_seq"] == page["last_seq"]
        assert emitted[-1]["payload"].get("reason") == "events_trimmed"
    finally:
        await store.close()


def test_non_secret_toolbox_metadata_is_not_registered(monkeypatch):
    from toolbox_backend.logging_setup import contains_secret

    marker = "s5a-non-secret-path-unique-marker"
    monkeypatch.setenv("TOOLBOX_DATA_DIR", marker)
    child_environment(path_extras=[])
    assert not contains_secret(marker)


def test_fake_ai_gate_runs_before_socket_bind(tmp_path, monkeypatch):
    from toolbox_backend import server

    monkeypatch.setenv("TOOLBOX_DEV_FAKE_AI", "1")
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", "memory")
    attempted = []

    def bind():
        attempted.append(True)
        raise RuntimeError("must not bind")

    monkeypatch.setattr(server, "bind_socket", bind)
    assert server.main([]) == 1
    assert attempted == []


@pytest.mark.asyncio
async def test_second_pipe_creation_failure_closes_first_pipe(monkeypatch):
    import os

    from toolbox_backend.adapters.ai_process import SupervisedProcess

    original = os.pipe
    opened = []

    def pipe():
        if opened:
            raise OSError("injected fd exhaustion")
        pair = original()
        opened.extend(pair)
        return pair

    monkeypatch.setattr(os, "pipe", pipe)
    try:
        with pytest.raises(OSError):
            await SupervisedProcess.start(["/fake"], "/unused", path_extras=[])
        for fd in opened:
            with pytest.raises(OSError):
                os.fstat(fd)
    finally:
        for fd in opened:
            try:
                os.close(fd)
            except OSError:
                pass
