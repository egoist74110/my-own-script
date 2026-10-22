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
    assert set(spec["paths"]) == {"/health", "/api/system/alert"}
    assert spec["info"]["version"] == __version__


def test_events_schema_has_three_events():
    schema = json.loads((CONTRACTS_DIR / "events.schema.json").read_text())
    types = {
        d["properties"]["type"]["const"]
        for d in schema["$defs"].values()
        if "type" in d.get("properties", {}) and "const" in d["properties"]["type"]
    }
    assert types == {"system.hello", "system.heartbeat", "system.alert"}
    for d in schema["$defs"].values():
        if "seq" in d.get("properties", {}):
            assert {"seq", "topic", "type", "ts", "data"} <= set(d["properties"])


def test_contracts_dir_location():
    assert CONTRACTS_DIR.name == "contracts" and CONTRACTS_DIR.parent.name == "next"


def test_version_matches_pyproject():
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text())
    assert data["project"]["version"] == __version__
