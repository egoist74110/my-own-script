"""Generate (or check) next/contracts/{openapi,events.schema}.json deterministically.

uv run python -m toolbox_backend.contracts          # write
uv run python -m toolbox_backend.contracts --check  # exit 1 on drift
"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from toolbox_backend.app import create_app
from toolbox_backend.domain.models import Event
from toolbox_backend.settings import Settings

# src/toolbox_backend/contracts.py -> parents[3] == next/
CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"


def _dump(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate() -> dict[str, str]:
    app = create_app(Settings(token="contract-generation", port=0))
    events = TypeAdapter(Event).json_schema(mode="serialization")
    events["title"] = "ToolboxEvent"
    return {
        "openapi.json": _dump(app.openapi()),
        "events.schema.json": _dump(events),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="toolbox_backend.contracts")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    files = generate()
    if args.check:
        drift = [
            n
            for n, text in files.items()
            if not (CONTRACTS_DIR / n).exists() or (CONTRACTS_DIR / n).read_text() != text
        ]
        if drift:
            print("contract drift: " + ", ".join(drift), file=sys.stderr)
            return 1
        return 0
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (CONTRACTS_DIR / name).write_text(text)
        print(f"wrote {CONTRACTS_DIR / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
