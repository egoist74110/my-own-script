"""Requirement tests: per-slot bot credentials (never echoed) and telegram.sqlite3 v1 -> v2."""

import sqlite3

from tests.s5c_helpers import TOKENS, open_s5c
from toolbox_backend.adapters.telegram_store import TelegramStore

SECRET_TAIL = TOKENS["claude_code"].split(":", 1)[1]


async def test_ai_token_is_stored_as_telegram_ai_bot_credential(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.put_token("claude_code")
        config = await ctx.app.state.config_store.read()
        meta = config.credentials["ai_bot_token:claude_code"]
        assert meta.kind == "telegram_ai_bot"
        assert ctx.credentials.get("ai_bot_token:claude_code") == TOKENS["claude_code"]


async def test_token_is_never_echoed_in_any_response(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        put = await ctx.client.put(
            "/api/telegram/ai-bots/claude_code/token",
            json={"revision": await ctx.revision(), "token": TOKENS["claude_code"]},
        )
        assert put.status_code == 200
        bodies = [
            put.text,
            (await ctx.client.get("/api/telegram/ai-bots")).text,
            (await ctx.client.get("/api/telegram/ai-bots/claude_code")).text,
            (await ctx.client.get("/api/telegram")).text,
        ]
        for body in bodies:
            assert SECRET_TAIL not in body
            assert TOKENS["claude_code"] not in body
        view = (await ctx.client.get("/api/telegram/ai-bots/claude_code")).json()
        assert view["bot"]["credential"]["present"] is True


async def test_import_legacy_missing_returns_404(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        response = await ctx.client.post(
            "/api/telegram/ai-bots/codex/token/import-legacy",
            json={"revision": await ctx.revision()},
        )
        assert response.status_code == 404, response.text
        assert "legacy_missing" in response.text


async def test_import_legacy_present_stores_the_ai_token(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        ctx.legacy.set("ai_bot_token:claude_code", TOKENS["claude_code"])
        response = await ctx.client.post(
            "/api/telegram/ai-bots/claude_code/token/import-legacy",
            json={"revision": await ctx.revision()},
        )
        assert response.status_code == 200, response.text
        assert ctx.credentials.get("ai_bot_token:claude_code") == TOKENS["claude_code"]
        assert SECRET_TAIL not in response.text


async def test_invalid_ai_id_is_rejected(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        response = await ctx.client.put(
            "/api/telegram/ai-bots/openai/token",
            json={"revision": await ctx.revision(), "token": TOKENS["codex"]},
        )
        assert response.status_code in {404, 422}, response.text


def _make_v1_db(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "telegram.sqlite3"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE tg_bots(bot_id TEXT PRIMARY KEY, username TEXT, next_offset INTEGER "
        "NOT NULL DEFAULT 0, baseline_done INTEGER NOT NULL DEFAULT 0, state TEXT, "
        "updated_at TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE tg_updates(bot_id TEXT, update_id INTEGER, received_at TEXT, kind TEXT, "
        "chat_id TEXT, user_id TEXT, command TEXT, status TEXT, reason TEXT, handled_at TEXT, "
        "PRIMARY KEY(bot_id,update_id))"
    )
    db.execute(
        "CREATE TABLE tg_actions(token TEXT PRIMARY KEY, bot_id TEXT, chat_id TEXT, user_id TEXT, "
        "kind TEXT, payload_json TEXT, created_at TEXT, expires_at TEXT, consumed_at TEXT, "
        "result_run_id TEXT)"
    )
    db.execute(
        "CREATE TABLE tg_outbox(id INTEGER PRIMARY KEY, bot_id TEXT, chat_id TEXT, "
        "dedup_key TEXT UNIQUE, kind TEXT, text TEXT, reply_markup_json TEXT, "
        "edit_message_id INTEGER, state TEXT, attempts INTEGER DEFAULT 0, next_attempt_at TEXT, "
        "created_at TEXT, sent_at TEXT, error_category TEXT)"
    )
    db.execute(
        "INSERT INTO tg_bots(bot_id, username, updated_at) VALUES ('123456789','old','2026-01-01')"
    )
    db.execute("PRAGMA user_version=1")
    db.commit()
    db.close()
    return path


async def test_v1_database_migrates_to_v2_with_existing_bot_on_main_slot(tmp_path):
    path = _make_v1_db(tmp_path / "data")
    store = TelegramStore(tmp_path / "data")
    await store.initialize("main")
    try:
        assert store.readonly_error is None
    finally:
        await store.close("main")
    db = sqlite3.connect(path)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        cols = [r[1] for r in db.execute("PRAGMA table_info(tg_bots)")]
        assert "slot" in cols
        assert db.execute("SELECT slot FROM tg_bots WHERE bot_id='123456789'").fetchone()[0] == "main"
    finally:
        db.close()


async def test_future_database_version_is_read_only(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    db = sqlite3.connect(data / "telegram.sqlite3")
    db.execute("PRAGMA user_version=3")
    db.commit()
    db.close()
    store = TelegramStore(data)
    await store.initialize("main")
    try:
        assert store.readonly_error
        import pytest

        from toolbox_backend.domain.errors import SettingsError

        with pytest.raises(SettingsError):
            store.require()
    finally:
        await store.close("main")
