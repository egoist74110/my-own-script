"""Regressions for defects the lead found while integrating S4."""

from tests.test_s1_settings import context as context
from tests.test_s1_settings import execute
from toolbox_backend.adapters.config_store import CURRENT_SCHEMA_VERSION


async def test_settings_reports_the_stored_schema_version(context):
    _, client, *_ = context
    assert (await execute(client)).status_code == 200
    body = (await client.get("/api/settings")).json()
    assert CURRENT_SCHEMA_VERSION == 2
    assert body["schema_version"] == CURRENT_SCHEMA_VERSION


def test_expired_command_time_is_shown_in_local_timezone(monkeypatch):
    import time
    from datetime import UTC, datetime

    from toolbox_backend.services import telegram

    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    try:
        sent_at = datetime(2026, 10, 23, 7, 44, tzinfo=UTC).timestamp()
        assert telegram.local_clock(sent_at) == "15:44"
    finally:
        monkeypatch.undo()
        time.tzset()
