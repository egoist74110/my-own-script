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
