import json

import pytest

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.vpn_totp import parse_totp_import, totp
from toolbox_backend.domain.settings import Config


@pytest.mark.asyncio
async def test_v5_migration_is_snapshotted_and_idempotent(tmp_path):
    raw = Config().model_dump(by_alias=True)
    raw.pop("vpn", None)
    raw.update(schema_version=5, revision=7)
    original = json.dumps(raw).encode()
    (tmp_path / "config.json").write_bytes(original)
    store = ConfigStore(tmp_path)
    result = await store.initialize()
    assert result.schema_version == 6
    assert result.revision == 8
    assert result.vpn.window_automation == "off"
    snapshots = list((tmp_path / "migrations").glob("config-v5-*.json"))
    assert len(snapshots) == 1
    assert snapshots[0].read_bytes() == original
    assert await store.initialize() == result
    assert len(list((tmp_path / "migrations").glob("config-v5-*.json"))) == 1


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
        (20000000000, "353130"),
    ],
)
def test_rfc6238_sha1_six_digit_vectors(timestamp, expected):
    assert totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", timestamp) == expected


def test_otpauth_import_parses_candidates_in_memory():
    rows = parse_totp_import(
        "backup: otpauth://totp/Perimeter%3Aalice%40example.test?secret=JBSWY3DPEHPK3PXP&issuer=Perimeter",
        "Perimeter",
    )
    assert rows == [
        {"issuer": "Perimeter", "label": "alice@example.test", "secret": "JBSWY3DPEHPK3PXP"}
    ]
