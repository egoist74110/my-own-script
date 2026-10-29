"""Independent S7-A schema upgrade and legacy snapshot requirements."""

import copy
import json

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.domain.settings import Config


async def test_v4_migration_preserves_legacy_snapshot_and_is_idempotent(tmp_path):
    raw = Config().model_dump(mode="json", by_alias=True)
    raw.pop("services")
    raw["schema_version"] = 4
    raw["revision"] = 21
    raw["imported"]["extra"] = {
        "services": {"legacy_protocol": "quic", "comment": "keep this snapshot"}
    }
    snapshot = copy.deepcopy(raw["imported"])
    original = json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
    (tmp_path / "config.json").write_bytes(original)

    store = ConfigStore(tmp_path)
    migrated = await store.initialize()
    assert migrated.schema_version == 8
    assert migrated.revision == 22
    assert migrated.services.cloudflared.protocol == "http2"
    assert migrated.services.binaries.code_server is None
    assert migrated.imported.model_dump(mode="json") == snapshot

    upgraded = store.path.read_bytes()
    assert upgraded != original
    assert await store.initialize() == migrated
    assert store.path.read_bytes() == upgraded
    backups = list((tmp_path / "migrations").glob("config-v4-*.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
