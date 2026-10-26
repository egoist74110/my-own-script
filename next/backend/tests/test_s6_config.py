import json

import pytest

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.domain.settings import Config


async def test_v3_upgrade_preserves_original_and_is_idempotent(tmp_path):
    raw = Config().model_dump(by_alias=True)
    raw["schema_version"] = 3
    raw.pop("mcp", None)
    raw["revision"] = 7
    raw["imported"]["lark"] = {"tools": "preset.doc.default", "oauth_port": 3456}
    original = json.dumps(raw).encode()
    (tmp_path / "config.json").write_bytes(original)
    store = ConfigStore(tmp_path)
    result = await store.initialize()
    assert result.schema_version == 4
    assert result.revision == 8
    assert result.mcp.lark.port == 3456
    assert "drive.v1.media.batchGetTmpDownloadUrl" in result.mcp.lark.tools
    assert result.ai.analysis.mcp_source == "legacy"
    assert list((tmp_path / "migrations").glob("config-v3-*"))[0].read_bytes() == original
    assert await store.initialize() == result
    assert len(list((tmp_path / "migrations").iterdir())) == 1


@pytest.mark.parametrize(
    "section,key,value,target",
    [
        ("lark", "domain", "lark", "domain"),
        ("lark", "domain", "http://open.larksuite.com", "domain"),
        ("lark", "domain", "https://private-value.invalid", "domain"),
        ("lark", "oauth_port", 0, "port"),
        ("lark", "oauth_port", 70000, "port"),
        ("lark", "tools", ",".join(["tool"] * 41), "tools"),
        ("lark", "tools", "tool,bad/tool", "tools"),
        ("lark", "tools", ["tool"], "tools"),
        ("lark", "app_id", "invalid app id", "app_id"),
        ("lark", "language", "invalid-language", "language"),
        ("lark", "scope", "x" * 4097, "scope_hint"),
        ("figma", "expiry_days", 45, "expiry_days"),
        ("figma", "token_set_at", {"invalid": "metadata"}, "token_set_at"),
    ],
)
async def test_invalid_imported_field_falls_back_without_losing_original(
    tmp_path,
    caplog,
    section,
    key,
    value,
    target,
):
    from toolbox_backend.domain.mcp import McpConfig

    raw = Config().model_dump(by_alias=True)
    raw.update(schema_version=3, revision=8)
    raw.pop("mcp")
    raw["imported"]["lark"] = {"app_id": "cli_valid", "oauth_port": 4567}
    raw["imported"][section][key] = value
    original = json.dumps(raw).encode()
    (tmp_path / "config.json").write_bytes(original)
    store = ConfigStore(tmp_path)
    migrated = await store.initialize()
    default = getattr(getattr(McpConfig(), section), target)
    assert getattr(getattr(migrated.mcp, section), target) == default
    assert migrated.imported.model_dump() == raw["imported"]
    if target != "app_id":
        assert migrated.mcp.lark.app_id == "cli_valid"
    if target != "port":
        assert migrated.mcp.lark.port == 4567
    assert f"mcp.{section}.{target}" in caplog.text
    records = [r for r in caplog.records if r.name == "toolbox_backend.domain.mcp"]
    assert len(records) == 1
    assert records[0].args == (f"mcp.{section}.{target}",)
    assert (await store.initialize()) == migrated
    assert len(list((tmp_path / "migrations").glob("config-v3-*"))) == 1
