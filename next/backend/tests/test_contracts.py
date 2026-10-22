"""S0-A acceptance 6: contract drift."""

import json
import tomllib
from pathlib import Path

from toolbox_backend import __version__
from toolbox_backend.contracts import CONTRACTS_DIR, generate


def test_no_drift():
    for name, text in generate().items():
        path = CONTRACTS_DIR / name
        assert path.exists(), f"{path} missing; run python -m toolbox_backend.contracts"
        assert path.read_text() == text, f"{name} drifted; regenerate contracts"


def test_generation_is_deterministic_and_newline_terminated():
    assert generate() == generate()
    for text in generate().values():
        assert text.endswith("}\n") and not text.endswith("\n\n")
        json.loads(text)


def test_openapi_contents():
    spec = json.loads((CONTRACTS_DIR / "openapi.json").read_text())
    schemas = spec["components"]["schemas"]
    for name in ("HealthResponse", "AlertRequest", "AlertState"):
        assert name in schemas
    assert {"/health", "/api/system/alert"} <= set(spec["paths"])
    for path, method, model in (
        ("/health", "get", "HealthResponse"),
        ("/api/system/alert", "post", "AlertState"),
    ):
        assert spec["paths"][path][method]["responses"]["200"]["content"]["application/json"][
            "schema"
        ] == {
            "$ref": f"#/components/schemas/{model}",
        }
    for model, fields, required in (
        (
            "HealthResponse",
            {"status", "version", "pid", "uptime_s", "alert"},
            {"status", "version", "pid", "uptime_s", "alert"},
        ),
        ("AlertRequest", {"active", "reason"}, {"active"}),
        ("AlertState", {"active", "reason", "changed_at"}, {"active", "changed_at"}),
    ):
        assert set(schemas[model]["properties"]) == fields
        assert set(schemas[model]["required"]) == required
    assert schemas["HealthResponse"]["properties"]["status"]["const"] == "ok"
    for field, kind in (
        ("version", "string"),
        ("pid", "integer"),
        ("uptime_s", "number"),
        ("alert", "boolean"),
    ):
        assert schemas["HealthResponse"]["properties"][field]["type"] == kind
    for model in ("AlertRequest", "AlertState"):
        assert schemas[model]["properties"]["active"]["type"] == "boolean"
        assert schemas[model]["properties"]["reason"]["anyOf"] == [
            {"type": "string"},
            {"type": "null"},
        ]
    assert schemas["AlertState"]["properties"]["changed_at"]["format"] == "date-time"
    s1_methods = {
        "/api/settings": {"get"},
        "/api/settings/import/preview": {"post"},
        "/api/settings/import/execute": {"post"},
        "/api/settings/import/decline": {"post"},
        "/api/ado": {"get"},
        "/api/ado/libraries": {"post"},
        "/api/ado/libraries/{id}": {"patch", "delete"},
        "/api/ado/libraries/{id}/pat": {"put", "delete"},
        "/api/ado/libraries/{id}/test": {"post"},
        "/api/ado/libraries/{id}/remote-projects": {"get"},
        "/api/ado/projects": {"post"},
        "/api/ado/projects/{id}": {"patch", "delete"},
        "/api/ado/active": {"put"},
        "/api/credentials": {"get"},
        "/api/credentials/{account}": {"delete"},
    }
    for path, methods in s1_methods.items():
        assert methods <= set(spec["paths"][path])
    assert spec["info"]["version"] == __version__


def test_events_schema_keeps_s0_fields_and_adds_settings_changed():
    schema = json.loads((CONTRACTS_DIR / "events.schema.json").read_text())
    types = {
        d["properties"]["type"]["const"]
        for d in schema["$defs"].values()
        if "type" in d.get("properties", {}) and "const" in d["properties"]["type"]
    }
    assert {"system.hello", "system.heartbeat", "system.alert", "settings.changed"} <= types
    for d in schema["$defs"].values():
        if "seq" in d.get("properties", {}):
            assert {"seq", "topic", "type", "ts", "data"} == set(d["properties"])
            assert d["properties"]["seq"]["type"] == "integer"
            assert d["properties"]["ts"]["format"] == "date-time"
    for event, data_model, fields in (
        ("SystemHelloEvent", "HelloData", {"pid", "version", "alert"}),
        ("SystemHeartbeatEvent", "HeartbeatData", {"uptime_s"}),
        ("SystemAlertEvent", "AlertState", {"active", "reason", "changed_at"}),
        ("SettingsChangedEvent", "SettingsChangedData", {"revision"}),
    ):
        definition = schema["$defs"][event]
        assert definition["properties"]["data"]["$ref"] == f"#/$defs/{data_model}"
        assert set(schema["$defs"][data_model]["properties"]) == fields
        assert definition["properties"]["topic"]["const"] == (
            "settings" if event == "SettingsChangedEvent" else "system"
        )
    assert schema["$defs"]["HelloData"]["properties"]["pid"]["type"] == "integer"
    assert schema["$defs"]["HelloData"]["properties"]["version"]["type"] == "string"
    assert schema["$defs"]["HelloData"]["properties"]["alert"]["$ref"] == "#/$defs/AlertState"
    assert schema["$defs"]["HeartbeatData"]["properties"]["uptime_s"]["type"] == "number"
    assert schema["$defs"]["SettingsChangedData"]["properties"]["revision"]["minimum"] == 1


def test_contracts_dir_location():
    assert CONTRACTS_DIR.name == "contracts" and CONTRACTS_DIR.parent.name == "next"


def test_version_matches_pyproject():
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text())
    assert data["project"]["version"] == __version__
