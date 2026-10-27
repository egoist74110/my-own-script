#!/usr/bin/env python3
"""Generate a Tauri v2 static update manifest (latest.json) using Python stdlib only.

Never reads private keys and never touches the network.
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def is_valid_semver(version: str) -> bool:
    return bool(SEMVER_RE.match(version))


def is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    lowered = hostname.lower()
    if lowered == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(lowered)
        return addr.is_loopback
    except ValueError:
        return False


def validate_url(url: str, *, allow_insecure: bool) -> None:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if not parsed.netloc or not parsed.hostname:
        raise ValueError(f"invalid URL (missing host): {url}")
    if scheme == "https":
        return
    if scheme == "http" and allow_insecure and is_loopback_host(parsed.hostname):
        return
    if scheme == "http" and is_loopback_host(parsed.hostname):
        raise ValueError("loopback http URL requires explicit --allow-insecure")
    raise ValueError(f"update URL must use https (got {scheme or 'empty'}): {url}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a Tauri static update manifest (latest.json)."
    )
    parser.add_argument("--version", required=True, help="Release version (strict SemVer, e.g. 1.0.0)")
    parser.add_argument("--notes-file", help="Optional path to plain-text release notes file")
    parser.add_argument(
        "--platform",
        default="darwin-aarch64",
        help="Target platform key (default: darwin-aarch64)",
    )
    parser.add_argument("--url", required=True, help="Artifact download URL (HTTPS required)")
    parser.add_argument(
        "--allow-insecure",
        action="store_true",
        help="Allow http:// only for loopback hosts (127.0.0.1 / ::1 / localhost) for local testing",
    )
    parser.add_argument("--signature-file", required=True, help="Path to .sig signature text file")
    parser.add_argument("--out", required=True, help="Output path for latest.json")

    args = parser.parse_args(argv)

    version = args.version.strip()
    if not is_valid_semver(version):
        print(f"error: invalid semver version: {args.version!r}", file=sys.stderr)
        return 1

    platform = args.platform.strip()
    if not platform:
        print("error: --platform must not be empty", file=sys.stderr)
        return 1

    try:
        validate_url(args.url.strip(), allow_insecure=args.allow_insecure)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    sig_path = Path(args.signature_file)
    if not sig_path.is_file():
        print(f"error: signature file not found: {sig_path}", file=sys.stderr)
        return 1
    signature = sig_path.read_text(encoding="utf-8").strip()
    if not signature:
        print(f"error: signature file is empty: {sig_path}", file=sys.stderr)
        return 1

    notes = ""
    if args.notes_file:
        notes_path = Path(args.notes_file)
        if not notes_path.is_file():
            print(f"error: notes file not found: {notes_path}", file=sys.stderr)
            return 1
        notes = notes_path.read_text(encoding="utf-8").rstrip("\r\n")

    pub_date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest = {
        "version": version,
        "notes": notes,
        "pub_date": pub_date,
        "platforms": {
            platform: {
                "signature": signature,
                "url": args.url.strip(),
            }
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
