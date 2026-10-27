#!/usr/bin/env python3
"""Validate a build-time Tauri updater overlay config (stdlib only, offline).

Exit 0 when valid, 2 with one error per line on stderr otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PLACEHOLDER_PUBKEYS = {"REPLACE_WITH_MINISIGN_PUBLIC_KEY"}
PLACEHOLDER_ENDPOINT_MARKER = "/OWNER/REPO/"
INSECURE_KEY = "dangerousInsecureTransportProtocol"


def _find_key(node: Any, key: str, path: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{path}.{k}" if path else k
            if k == key:
                hits.append(here)
            hits.extend(_find_key(v, key, here))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            hits.extend(_find_key(v, key, f"{path}[{i}]"))
    return hits


def validate_updater_config(conf: Any, placeholders: set[str] | None = None) -> list[str]:
    """Return a list of human-readable problems (empty list means valid)."""
    if not isinstance(conf, dict):
        return ["updater config must be a JSON object"]
    errors: list[str] = []
    for hit in _find_key(conf, INSECURE_KEY):
        errors.append(f"{hit}: {INSECURE_KEY} is forbidden")
    updater = (conf.get("plugins") or {}).get("updater") if isinstance(conf.get("plugins"), dict) else None
    if not isinstance(updater, dict):
        errors.append("plugins.updater is missing or not an object")
        return errors
    endpoints = updater.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        errors.append("plugins.updater.endpoints must be a non-empty list")
    else:
        for ep in endpoints:
            if not isinstance(ep, str) or not ep.startswith("https://") or len(ep) <= len("https://"):
                errors.append(f"plugins.updater.endpoints entry must start with https://: {ep!r}")
            elif PLACEHOLDER_ENDPOINT_MARKER in ep:
                errors.append(f"plugins.updater.endpoints entry is still the example placeholder: {ep}")
    pubkey = updater.get("pubkey")
    bad = set(PLACEHOLDER_PUBKEYS) | (placeholders or set())
    if not isinstance(pubkey, str) or not pubkey.strip():
        errors.append("plugins.updater.pubkey must be a non-empty string")
    elif pubkey.strip() in bad or pubkey.strip().startswith("REPLACE_"):
        errors.append("plugins.updater.pubkey is still the example placeholder")
    return errors


def _example_placeholders() -> set[str]:
    example = Path(__file__).resolve().parent.parent / "desktop/src-tauri/tauri.updater.conf.example.json"
    try:
        data = json.loads(example.read_text(encoding="utf-8"))
        return {str(data["plugins"]["updater"]["pubkey"]).strip()}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: validate_updater_config.py <config.json>", file=sys.stderr)
        return 2
    try:
        conf = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read updater config {args[0]}: {exc}", file=sys.stderr)
        return 2
    errors = validate_updater_config(conf, _example_placeholders())
    for e in errors:
        print(f"error: updater config invalid: {e}", file=sys.stderr)
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
