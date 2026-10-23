"""Regressions for defects the lead found while integrating S5."""

import json
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def test_main_poller_view_keeps_s4_shape_while_status_event_carries_slot():
    # S5-C leaked the additive `slot` into PollerView, making it a required response field
    # of GET /api/telegram and breaking existing S4 clients.
    schemas = json.loads((CONTRACTS / "openapi.json").read_text())["components"]["schemas"]
    assert "slot" not in schemas["PollerView"]["properties"]
    assert "slot" in schemas["AIBotView"]["properties"]
    events = json.loads((CONTRACTS / "events.schema.json").read_text())["$defs"]
    assert "slot" in events["TelegramStatusData"]["properties"]
