"""S4-A config migration, typed ACL, and revisioned Telegram settings contracts."""

import json
import sqlite3
import time

import httpx

from toolbox_backend.domain.settings import Config


def _v1_config(imported_telegram: dict) -> dict:
    raw = Config().model_dump(mode="json", by_alias=True)
    raw["schema_version"] = 1
    raw.pop("telegram", None)
    raw["revision"] = 4
    raw["updated_at"] = "2026-10-01T00:00:00+00:00"
    raw["imported"]["telegram"] = imported_telegram
    return raw


def _projection(response: httpx.Response) -> dict:
    value = response.json()
    result = {key: value[key] for key in ("control", "owner", "notify", "acl")}
    result["acl"]["members"] = [
        {key: item[key] for key in item if key != "id"}
        for item in result["acl"]["members"]
    ]
    return result


async def test_config_v1_migration_matches_direct_legacy_import_and_is_idempotent(
    tmp_path, telegram_app_factory
):
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "ui_settings.yaml").write_text(
        """telegram_chat_id: '5001'
telegram_control_enabled: true
telegram_notify_include_details: true
telegram_whitelist: ['5002', '@reader_1']
telegram_acl_groups:
  - id: old-ops
    name: Operators
    can_run: false
    can_stop: true
    can_status: true
    can_rollback: false
    task_ids: []
    future_rule: keep-me
telegram_acl_members:
  - group_id: old-ops
    chat_id: '5003'
    label: Operator
""",
        encoding="utf-8",
    )

    direct_dir = tmp_path / "direct-data"
    async with telegram_app_factory(tmp_path, data_dir=direct_dir) as direct:
        preview = await direct.client.post("/api/settings/import/preview")
        assert preview.status_code == 200, preview.text
        executed = await direct.client.post(
            "/api/settings/import/execute", json={"fingerprint": preview.json()["fingerprint"]}
        )
        assert executed.status_code == 200, executed.text
        direct_view = await direct.client.get("/api/telegram")
        assert direct_view.status_code == 200, direct_view.text
        direct_projection = _projection(direct_view)

    migrated_dir = tmp_path / "migrated-data"
    migrated_dir.mkdir()
    old_imported = {
        "chat_id": "5001",
        "control_enabled": True,
        "notify_include_details": True,
        "whitelist": ["5002", "@reader_1"],
        "acl_groups": [
            {
                "id": "old-ops",
                "name": "Operators",
                "can_run": False,
                "can_stop": True,
                "can_status": True,
                "can_rollback": False,
                "task_ids": [],
                "future_rule": "keep-me",
            }
        ],
        "acl_members": [{"group_id": "old-ops", "chat_id": "5003", "label": "Operator"}],
    }
    (migrated_dir / "config.json").write_text(
        json.dumps(_v1_config(old_imported)), encoding="utf-8"
    )

    async with telegram_app_factory(tmp_path, data_dir=migrated_dir) as migrated:
        first = await migrated.client.get("/api/telegram")
        assert first.status_code == 200, first.text
        assert _projection(first) == direct_projection
        config = await migrated.app.state.config_store.read()
        dumped = config.model_dump(mode="json", by_alias=True)
        assert dumped["schema_version"] == 2
        assert "telegram" not in dumped["imported"]
        assert dumped["telegram"]["control"]["enabled"] is False
        assert dumped["telegram"]["owner"]["chat_id"] == "5001"
        group = dumped["telegram"]["acl_groups"][0]
        assert group["id"] == "old-ops"
        assert group["future_rule"] == "keep-me"
        assert dumped["telegram"]["acl_members"][0]["id"].startswith("acl_member:")
        backups = list((migrated_dir / "migrations").glob("config-v1-*.json"))
        assert len(backups) == 1
        assert json.loads(backups[0].read_text(encoding="utf-8")) == _v1_config(old_imported)
        committed = (migrated_dir / "config.json").read_bytes()
        revision = dumped["revision"]

    async with telegram_app_factory(tmp_path, data_dir=migrated_dir) as restarted:
        second = await restarted.client.get("/api/telegram")
        assert second.status_code == 200, second.text
        assert (migrated_dir / "config.json").read_bytes() == committed
        assert second.json()["revision"] == revision
        assert len(list((migrated_dir / "migrations").glob("config-v1-*.json"))) == 1


async def test_acl_revision_conflict_group_cascade_and_legacy_status_only(
    tmp_path, telegram_app_factory
):
    async with telegram_app_factory(tmp_path) as ctx:
        initial = await ctx.client.get("/api/telegram")
        assert initial.status_code == 200, initial.text
        revision = initial.json()["revision"]
        created = await ctx.client.post(
            "/api/telegram/acl/groups",
            json={
                "revision": revision,
                "name": "Operators",
                "can_run": False,
                "can_stop": True,
                "can_status": True,
                "can_rollback": False,
                "task_ids": [],
            },
        )
        assert created.status_code == 200, created.text
        current = created.json()["revision"]
        group_id = created.json()["id"]
        member = await ctx.client.post(
            "/api/telegram/acl/members",
            json={
                "revision": current,
                "group_id": group_id,
                "chat_id": "5003",
                "username": None,
                "label": "operator",
            },
        )
        assert member.status_code == 200, member.text
        member_id = member.json()["id"]
        current = member.json()["revision"]

        def bind_owner(config):
            config.telegram.owner.chat_id = "5001"
            config.telegram.owner.source = "bound"

        await ctx.app.state.config_store.update(current, bind_owner)
        await ctx.app.state.telegram_store.bot("123456789", "test_bot")
        ctx.app.state.telegram_service.bot_id = "123456789"

        await ctx.app.state.telegram_service.process_updates(
            [
                {
                    "update_id": 700,
                    "message": {
                        "date": int(time.time()),
                        "chat": {"id": 5003, "type": "private"},
                        "from": {"id": 5003},
                        "text": "/status",
                    },
                }
            ]
        )
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            assert db.execute(
                "SELECT chat_id FROM tg_outbox WHERE dedup_key='reply:700:0'"
            ).fetchone() == ("5003",)

        stale = await ctx.client.patch(
            f"/api/telegram/acl/groups/{group_id}",
            json={"revision": member.json()["revision"], "can_stop": False},
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "revision_conflict"

        current = (await ctx.client.get("/api/telegram")).json()["revision"]
        removed = await ctx.client.delete(
            f"/api/telegram/acl/groups/{group_id}", params={"revision": current}
        )
        assert removed.status_code == 200, removed.text
        view = await ctx.client.get("/api/telegram")
        assert view.status_code == 200, view.text
        assert view.json()["acl"]["groups"] == []
        assert all(item["id"] != member_id for item in view.json()["acl"]["members"])

        revision = view.json()["revision"]

        def set_legacy(config):
            config.telegram.legacy_whitelist = ["5002"]
            config.telegram.owner.chat_id = "5001"
            config.telegram.owner.source = "bound"

        await ctx.app.state.config_store.update(revision, set_legacy)

        await ctx.app.state.telegram_service.process_updates(
            [
                {
                    "update_id": 901,
                    "message": {
                        "date": int(time.time()),
                        "chat": {"id": 5002, "type": "private"},
                        "from": {"id": 5002, "username": "reader_1"},
                        "text": "/status",
                    },
                }
            ]
        )
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            assert db.execute(
                "SELECT chat_id FROM tg_outbox WHERE dedup_key='reply:901:0'"
            ).fetchone() == ("5002",)
