#!/usr/bin/env python3
"""Synchronize and check project version across manifests from tauri.conf.json (stdlib only)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def _read_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"missing required file: {path}")
    return path.read_bytes()


def _extract_source_version(tauri_conf_path: Path) -> str:
    raw = _read_bytes(tauri_conf_path)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid JSON in {tauri_conf_path}: {exc}") from exc
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"missing or empty 'version' in {tauri_conf_path}")
    return version


def _find_toml_section_version(content: bytes, section: str, path: Path) -> tuple[str, int, int]:
    section_pat = re.compile(
        rb"(?m)^\[[ \t]*" + re.escape(section.encode("ascii")) + rb"[ \t]*\][ \t]*(?:#.*)?\r?\n"
    )
    m_sec = section_pat.search(content)
    if not m_sec:
        raise ValueError(f"missing [{section}] section in {path}")
    start = m_sec.end()
    next_sec = re.compile(rb"(?m)^\[[^\r\n]+\]").search(content, start)
    end = next_sec.start() if next_sec else len(content)
    ver_pat = re.compile(rb'(?m)^([ \t]*version[ \t]*=[ \t]*")([^"\r\n]+)(")')
    m_ver = ver_pat.search(content, start, end)
    if not m_ver:
        raise ValueError(f"missing version field in [{section}] of {path}")
    return m_ver.group(2).decode("utf-8"), m_ver.start(2), m_ver.end(2)


def _find_package_json_version(content: bytes, path: Path) -> tuple[str, int, int]:
    try:
        data = json.loads(content.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data.get("version"), str):
        raise ValueError(f"missing top-level string 'version' in {path}")
    ver_pat = re.compile(rb'(?m)^([ \t]*"version"[ \t]*:[ \t]*")([^"\r\n]+)(")')
    m_ver = ver_pat.search(content)
    if not m_ver:
        raise ValueError(f"could not locate top-level version field in {path}")
    return m_ver.group(2).decode("utf-8"), m_ver.start(2), m_ver.end(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="Repository root directory (defaults to two levels above this script).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Verify all versions match tauri.conf.json.")
    group.add_argument("--write", action="store_true", help="Update target files to match tauri.conf.json.")
    args = parser.parse_args(argv)

    root: Path = args.root.resolve()
    tauri_conf = root / "next/desktop/src-tauri/tauri.conf.json"
    cargo_toml = root / "next/desktop/src-tauri/Cargo.toml"
    package_json = root / "next/desktop/package.json"
    pyproject_toml = root / "next/backend/pyproject.toml"

    try:
        source_ver = _extract_source_version(tauri_conf)
        cargo_bytes = _read_bytes(cargo_toml)
        cargo_ver, cargo_s, cargo_e = _find_toml_section_version(cargo_bytes, "package", cargo_toml)
        pkg_bytes = _read_bytes(package_json)
        pkg_ver, pkg_s, pkg_e = _find_package_json_version(pkg_bytes, package_json)
        pyproj_bytes = _read_bytes(pyproject_toml)
        pyproj_ver, pyproj_s, pyproj_e = _find_toml_section_version(pyproj_bytes, "project", pyproject_toml)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    targets = [
        ("next/desktop/src-tauri/Cargo.toml", cargo_toml, cargo_bytes, cargo_ver, cargo_s, cargo_e),
        ("next/desktop/package.json", package_json, pkg_bytes, pkg_ver, pkg_s, pkg_e),
        ("next/backend/pyproject.toml", pyproject_toml, pyproj_bytes, pyproj_ver, pyproj_s, pyproj_e),
    ]

    if args.check:
        mismatches = [
            (rel, ver) for rel, _p, _b, ver, _s, _e in targets if ver != source_ver
        ]
        if mismatches:
            print(
                f"version mismatch (source next/desktop/src-tauri/tauri.conf.json = {source_ver}):",
                file=sys.stderr,
            )
            for rel, ver in mismatches:
                print(f"  {rel}: {ver} != {source_ver}", file=sys.stderr)
            return 1
        print(f"version ok: {source_ver}")
        return 0

    src_bytes = source_ver.encode("utf-8")
    for rel, path, content, ver, s, e in targets:
        if ver != source_ver:
            updated = content[:s] + src_bytes + content[e:]
            path.write_bytes(updated)
            print(f"updated {rel}: {ver} -> {source_ver}")
        else:
            print(f"unchanged {rel}: {ver}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
