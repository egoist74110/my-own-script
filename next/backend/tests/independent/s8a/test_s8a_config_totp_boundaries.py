"""Independent S8-A config and TOTP input-boundary contracts."""

import json

import pytest
from pydantic import ValidationError

from toolbox_backend.adapters.config_store import CURRENT_SCHEMA_VERSION, ConfigStore
from toolbox_backend.adapters.vpn_totp import parse_totp_import, totp
from toolbox_backend.domain.settings import Config
from toolbox_backend.domain.vpn import VpnConfig

RFC6238_SHA1_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def test_config_v6_vpn_defaults_match_the_accepted_contract():
    config = Config()

    assert CURRENT_SCHEMA_VERSION == 8
    assert config.schema_version == 8
    assert config.vpn == VpnConfig()
    assert config.vpn.client.bundle_id == "com.safervpn.osx.smb"
    assert config.vpn.client.url_scheme == "CheckPointSASE"
    assert config.vpn.tunnel_prefix == "10.254."
    assert config.vpn.login.residency == "US Data Residency"
    assert config.vpn.login.totp_filter == "Perimeter"
    assert config.vpn.window_automation == "off"
    assert config.vpn.rung_timeout_s == 30
    assert config.vpn.login_timeout_s == 75
    assert config.vpn.max_run_s == 480
    assert config.vpn.chrome_path is None


@pytest.mark.parametrize(
    "changes",
    [
        {"tunnel_prefix": "256.254."},
        {"tunnel_prefix": "10.254.0.0/16"},
        {"login": {"residency": "Mars Data Residency"}},
        {"login": {"workspace": "workspace\nforged"}},
        {"rung_timeout_s": 4},
        {"login_timeout_s": 301},
        {"max_run_s": 1201},
        {"window_automation": "always"},
        {"client": {"url_scheme": "javascript"}},
    ],
)
def test_vpn_config_rejects_values_outside_the_contract(changes):
    with pytest.raises(ValidationError):
        VpnConfig.model_validate(changes)


@pytest.mark.asyncio
async def test_v5_migration_adds_vpn_defaults_without_changing_existing_settings(tmp_path):
    raw = Config().model_dump(mode="json", by_alias=True)
    raw.pop("vpn", None)
    raw["schema_version"] = 5
    raw["revision"] = 14
    raw["services"]["cloudflared"]["protocol"] = "http2"
    original_services = json.loads(json.dumps(raw["services"]))
    (tmp_path / "config.json").write_text(json.dumps(raw), encoding="utf-8")

    store = ConfigStore(tmp_path)
    migrated = await store.initialize()

    assert migrated.schema_version == 8
    assert migrated.revision == 15
    assert migrated.vpn == VpnConfig()
    assert migrated.services.model_dump(mode="json") == original_services
    assert await store.initialize() == migrated
    backups = list((tmp_path / "migrations").glob("config-v5-*.json"))
    assert len(backups) == 1


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
def test_totp_matches_rfc6238_sha1_six_digit_vectors(timestamp, expected):
    assert totp(RFC6238_SHA1_SECRET, timestamp) == expected


def test_totp_import_returns_every_case_insensitive_filter_match():
    text = "\n".join(
        [
            "otpauth://totp/alice%40example.test?secret=JBSWY3DPEHPK3PXP&issuer=Perimeter",
            "otpauth://totp/Harmony%3Abob?secret=KRSXG5DSNFXGOIDB&issuer=Harmony",
            "otpauth://totp/Personal?secret=MFRGGZDFMZTWQ2LK&issuer=Personal",
        ]
    )

    candidates = parse_totp_import(text, "perimeter")

    assert candidates == [
        {
            "issuer": "Perimeter",
            "label": "alice@example.test",
            "secret": "JBSWY3DPEHPK3PXP",
        }
    ]
    assert len(parse_totp_import(text, "a")) == 3


def test_totp_import_rejects_non_sha1_six_digit_thirty_second_profiles():
    for params in ("algorithm=SHA256", "digits=8", "period=60"):
        uri = f"otpauth://totp/Perimeter:alice?secret=JBSWY3DPEHPK3PXP&{params}"
        with pytest.raises(ValueError, match="totp_unsupported"):
            parse_totp_import(uri, "Perimeter")


def test_totp_import_enforces_one_mib_utf8_limit():
    text = "otpauth://totp/Perimeter:alice?secret=JBSWY3DPEHPK3PXP&issuer=Perimeter" + (
        "é" * (1 << 19)
    )

    with pytest.raises(ValueError, match="totp_import_too_large"):
        parse_totp_import(text, "Perimeter")


def test_totp_import_treats_path_like_input_as_text_and_never_reads_or_deletes_file(tmp_path):
    export_file = tmp_path / "private-export.txt"
    original = b"still here: do not read or delete"
    export_file.write_bytes(original)

    with pytest.raises(ValueError, match="totp_not_found"):
        parse_totp_import(str(export_file), "Perimeter")

    assert export_file.read_bytes() == original
